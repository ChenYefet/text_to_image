"""
Pool of independent ``StableDiffusionPipeline`` instances for concurrent
image generation.

The v5.4.0 specification (§14) mandates that when the concurrency limit is
greater than 1, the implementation must maintain a pool of ``n`` independent
pipeline instances — one per concurrency slot — to prevent shared-state
corruption.  This module provides that pool as an ``asyncio.Queue``-based
container with acquire/release semantics.

A pool of size 1 is behaviourally identical to a single instance with
acquire/release semantics.  Using the uniform pool path for all concurrency
values (including ``n = 1``) eliminates a conditional branch that would need
its own test coverage and could mask concurrency bugs that only surface when
``n > 1``.
"""

import asyncio
import contextlib
import typing

import structlog

import application.integrations.stable_diffusion_pipeline

logger = structlog.get_logger()


class StableDiffusionPipelinePool:
    """
    An ``asyncio.Queue``-based pool of independent
    ``StableDiffusionPipeline`` instances.

    Each inference operation acquires an exclusive pipeline instance from the
    pool for the duration of the inference and releases it upon completion.
    The pool size matches the configured concurrency limit so that the
    admission controller and the pool are always in agreement about how many
    concurrent operations are permitted.

    Usage::

        async with pool.acquire() as pipeline:
            result = await pipeline.generate_images(...)
    """

    def __init__(
        self,
        pipeline_instances: list[application.integrations.stable_diffusion_pipeline.StableDiffusionPipeline],
    ) -> None:
        """
        Initialise the pool with a list of ready-to-use pipeline instances.

        Args:
            pipeline_instances: A list of fully loaded and configured
                ``StableDiffusionPipeline`` instances.  The length of this
                list determines the pool size (and must match the configured
                concurrency limit).
        """
        self._queue: asyncio.Queue[application.integrations.stable_diffusion_pipeline.StableDiffusionPipeline] = (
            asyncio.Queue(maxsize=len(pipeline_instances))
        )
        for pipeline_instance in pipeline_instances:
            self._queue.put_nowait(pipeline_instance)
        self._number_of_instances = len(pipeline_instances)
        # Keep a separate reference list for health checking and shutdown.
        # The queue is the authoritative container for acquire/release, but
        # we cannot iterate over a queue without dequeuing.
        self._all_instances = list(pipeline_instances)

    @property
    def number_of_instances(self) -> int:
        """Return the total number of pipeline instances in the pool."""
        return self._number_of_instances

    @contextlib.asynccontextmanager
    async def acquire(
        self,
    ) -> typing.AsyncIterator[application.integrations.stable_diffusion_pipeline.StableDiffusionPipeline]:
        """
        Acquire an exclusive pipeline instance from the pool.

        The instance is returned to the pool when the context manager exits,
        regardless of whether the operation succeeded or raised an exception.

        Yields:
            A ``StableDiffusionPipeline`` instance that the caller has
            exclusive access to for the duration of the ``async with`` block.
        """
        pipeline_instance = await self._queue.get()
        try:
            yield pipeline_instance
        finally:
            self._queue.put_nowait(pipeline_instance)

    def check_health(self) -> bool:
        """
        Return ``True`` if at least one pipeline instance in the pool is
        loaded and available for inference.

        This method is called by the readiness probe (``GET /health/ready``)
        to determine whether the image generation backend is operational.
        It checks all instances via the reference list (not the queue,
        which would require dequeuing).
        """
        return any(instance.check_health() for instance in self._all_instances)

    async def close(self) -> None:
        """
        Close all pipeline instances in the pool and free GPU memory.

        This method drains the queue and calls ``close()`` on each instance.
        It must be called during application shutdown to release the
        substantial memory (GPU VRAM and/or CPU RAM) occupied by the loaded
        model weights.
        """
        for _ in range(self._number_of_instances):
            try:
                pipeline_instance = self._queue.get_nowait()
                await pipeline_instance.close()
            except asyncio.QueueEmpty:
                logger.warning(
                    "stable_diffusion_pipeline_pool_instance_unavailable_during_shutdown",
                )
