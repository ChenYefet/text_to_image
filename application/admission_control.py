"""
Concurrency-limiting admission control for image generation requests.

This module implements NFR44 from the v5.8.1 specification: a configurable
concurrency limit that immediately rejects overflow requests with HTTP 429
(``service_busy``) rather than queuing them.  Queued requests under load
would accumulate timeout debt and waste compute on operations the client
has already abandoned.

Architecture
------------
The ``AdmissionControllerForImageGeneration`` maintains an atomic counter of
currently active image generation operations, protected by a lightweight
``asyncio.Lock``.  The counter is incremented on entry and decremented
on exit (including on exception), using an async context manager to
guarantee correct cleanup.

Admission control limits the *total* number of concurrent image
generation operations across *all* clients within a single service
instance.  It protects the GPU/CPU from overcommitment.

Usage in route handlers::

    async with admission_controller.acquire_or_reject():
        result = await image_generation_service.generate_images(...)
"""

import asyncio
import collections.abc
import contextlib

import application.exceptions


class AdmissionControllerForImageGeneration:
    """
    Controls the maximum number of concurrent image generation operations
    permitted within a single service instance.

    When the number of active operations reaches ``maximum_number_of_concurrent_operations``,
    any further call to ``acquire_or_reject`` raises
    ``ServiceBusyError`` immediately — no queuing, no waiting.

    The ``acquire_or_reject`` method returns an async context manager
    that increments the active count on entry and decrements it on exit,
    ensuring correct cleanup even when the image generation operation
    raises an exception.
    """

    def __init__(self, maximum_number_of_concurrent_operations: int = 2) -> None:
        """
        Initialise the admission controller.

        Args:
            maximum_number_of_concurrent_operations: The maximum number of
                image generation operations that may execute concurrently.
                The v5.8.1 specification default is 2, optimised for GPU
                deployments where two concurrent pipeline instances occupy
                approximately 7 GB of VRAM at float16 precision.  CPU-only
                operators should reduce to 1.
        """
        self._maximum_number_of_concurrent_operations = maximum_number_of_concurrent_operations
        self._number_of_active_operations: int = 0
        self._counter_lock = asyncio.Lock()

    @contextlib.asynccontextmanager
    async def acquire_or_reject(
        self,
    ) -> collections.abc.AsyncIterator[None]:
        """
        Attempt to acquire admission for an image generation operation.

        If the number of currently active operations is below the
        configured maximum, the active count is atomically incremented
        and the caller proceeds.  When the caller exits the context
        manager (whether normally or via exception), the active count
        is decremented.

        If the maximum number of concurrent operations has already been
        reached, a ``ServiceBusyError`` is raised immediately without
        incrementing the counter.

        Yields:
            None — the context manager body executes the image
            generation operation.

        Raises:
            application.exceptions.ServiceBusyError:
                When the maximum number of concurrent operations has been reached.
        """
        async with self._counter_lock:
            if self._number_of_active_operations >= self._maximum_number_of_concurrent_operations:
                raise application.exceptions.ServiceBusyError()
            self._number_of_active_operations += 1

        try:
            yield
        finally:
            async with self._counter_lock:
                self._number_of_active_operations -= 1

    @property
    def number_of_active_operations(self) -> int:
        """Return the current number of active image generation operations."""
        return self._number_of_active_operations

    @property
    def maximum_number_of_concurrent_operations(self) -> int:
        """Return the configured maximum concurrency limit."""
        return self._maximum_number_of_concurrent_operations
