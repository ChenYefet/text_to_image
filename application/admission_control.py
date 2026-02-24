"""
Semaphore-based admission control for image generation requests.

This module implements NFR44 from the v5.0.0 specification: a configurable
concurrency limit that immediately rejects overflow requests with HTTP 429
(``service_busy``) rather than queuing them.  Queued requests under load
would accumulate timeout debt and waste compute on operations the client
has already abandoned.

Architecture
------------
The ``ImageGenerationAdmissionController`` maintains an atomic counter of
currently active image generation operations, protected by a lightweight
``asyncio.Lock``.  The counter is incremented on entry and decremented
on exit (including on exception), using an async context manager to
guarantee correct cleanup.

This mechanism is distinct from IP-based rate limiting (``slowapi``):

- **Admission control** limits the *total* number of concurrent image
  generation operations across *all* clients within a single service
  instance.  It protects the GPU/CPU from overcommitment.

- **Rate limiting** limits the *frequency* of requests from a *single*
  client IP address.  It prevents any one client from monopolising the
  service.

Both mechanisms can be active simultaneously.

Usage in route handlers::

    async with admission_controller.acquire_or_reject():
        result = await image_generation_service.generate_images(...)
"""

import asyncio
import collections.abc
import contextlib

import application.exceptions


class ImageGenerationAdmissionController:
    """
    Controls the maximum number of concurrent image generation operations
    permitted within a single service instance.

    When the number of active operations reaches ``maximum_concurrency``,
    any further call to ``acquire_or_reject`` raises
    ``ServiceBusyError`` immediately — no queuing, no waiting.

    The ``acquire_or_reject`` method returns an async context manager
    that increments the active count on entry and decrements it on exit,
    ensuring correct cleanup even when the image generation operation
    raises an exception.
    """

    def __init__(self, maximum_concurrency: int = 1) -> None:
        """
        Initialise the admission controller.

        Args:
            maximum_concurrency: The maximum number of image generation
                operations that may execute concurrently.  The v5.0.0
                specification default is 1, which serialises inference
                to prevent GPU memory contention on single-GPU hosts.
        """
        self._maximum_concurrency = maximum_concurrency
        self._active_operation_count: int = 0
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

        If the maximum concurrency has already been reached, a
        ``ServiceBusyError`` is raised immediately without incrementing
        the counter.

        Yields:
            None — the context manager body executes the image
            generation operation.

        Raises:
            application.exceptions.ServiceBusyError:
                When the maximum concurrency limit has been reached.
        """
        async with self._counter_lock:
            if self._active_operation_count >= self._maximum_concurrency:
                raise application.exceptions.ServiceBusyError()
            self._active_operation_count += 1

        try:
            yield
        finally:
            async with self._counter_lock:
                self._active_operation_count -= 1

    @property
    def active_operation_count(self) -> int:
        """Return the current number of active image generation operations."""
        return self._active_operation_count

    @property
    def maximum_concurrency(self) -> int:
        """Return the configured maximum concurrency limit."""
        return self._maximum_concurrency
