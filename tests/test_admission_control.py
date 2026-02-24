"""
Comprehensive unit tests for the ImageGenerationAdmissionController.

The admission controller (NFR44) enforces a configurable concurrency limit
on image generation operations.  When the limit is reached, additional
requests are rejected immediately with ``ServiceBusyError`` rather than
being queued.

These tests verify:
- Successful acquisition when below the concurrency limit.
- Immediate rejection (``ServiceBusyError``) when the limit is reached.
- Correct counter management: increment on entry, decrement on exit.
- Cleanup safety: the counter is decremented even when the body of the
  context manager raises an exception.
- Concurrent acquisition up to the configured maximum.
- Property accessors for operational monitoring.
- Custom concurrency limits higher than the default of 1.
"""

import asyncio

import pytest

import application.admission_control
import application.exceptions


class TestImageGenerationAdmissionControllerInitialisation:
    """Verify that the controller initialises with correct defaults and custom values."""

    def test_default_maximum_concurrency_is_one(self) -> None:
        """The v5.0.0 specification default for maximum concurrency is 1."""
        controller = application.admission_control.ImageGenerationAdmissionController()

        assert controller.maximum_concurrency == 1

    def test_custom_maximum_concurrency_is_stored(self) -> None:
        """Operators can configure a higher concurrency limit via the constructor."""
        controller = application.admission_control.ImageGenerationAdmissionController(
            maximum_concurrency=4,
        )

        assert controller.maximum_concurrency == 4

    def test_initial_active_operation_count_is_zero(self) -> None:
        """No operations are active when the controller is first created."""
        controller = application.admission_control.ImageGenerationAdmissionController()

        assert controller.active_operation_count == 0


class TestAcquireOrRejectSuccessfulAcquisition:
    """Verify that the context manager grants admission when below the limit."""

    async def test_single_acquisition_increments_active_count(self) -> None:
        """
        When a single operation acquires admission, the active count
        increases to 1 for the duration of the context manager body.
        """
        controller = application.admission_control.ImageGenerationAdmissionController(
            maximum_concurrency=1,
        )

        async with controller.acquire_or_reject():
            assert controller.active_operation_count == 1

    async def test_active_count_returns_to_zero_after_exit(self) -> None:
        """
        After the context manager exits normally, the active count
        returns to zero — the slot is released for the next request.
        """
        controller = application.admission_control.ImageGenerationAdmissionController(
            maximum_concurrency=1,
        )

        async with controller.acquire_or_reject():
            pass  # Simulate a completed operation.

        assert controller.active_operation_count == 0

    async def test_sequential_acquisitions_succeed(self) -> None:
        """
        Multiple operations can acquire and release the same slot
        sequentially without triggering rejection.
        """
        controller = application.admission_control.ImageGenerationAdmissionController(
            maximum_concurrency=1,
        )

        for _ in range(5):
            async with controller.acquire_or_reject():
                assert controller.active_operation_count == 1
            assert controller.active_operation_count == 0

    async def test_concurrent_acquisitions_up_to_limit(self) -> None:
        """
        When the maximum concurrency is greater than 1, multiple
        operations can execute concurrently up to the configured limit.
        """
        controller = application.admission_control.ImageGenerationAdmissionController(
            maximum_concurrency=3,
        )

        # Use an event to keep all three operations active simultaneously.
        release_signal = asyncio.Event()

        async def hold_admission() -> None:
            async with controller.acquire_or_reject():
                await release_signal.wait()

        # Start three concurrent operations.
        tasks = [asyncio.create_task(hold_admission()) for _ in range(3)]

        # Give the event loop a tick to let all tasks acquire admission.
        await asyncio.sleep(0)

        assert controller.active_operation_count == 3

        # Release all operations.
        release_signal.set()
        await asyncio.gather(*tasks)

        assert controller.active_operation_count == 0


class TestAcquireOrRejectRejection:
    """Verify that the controller rejects requests when the limit is reached."""

    async def test_rejection_raises_service_busy_error(self) -> None:
        """
        When the concurrency limit is reached, the next acquisition
        attempt raises ``ServiceBusyError`` immediately.
        """
        controller = application.admission_control.ImageGenerationAdmissionController(
            maximum_concurrency=1,
        )

        async with controller.acquire_or_reject():
            # The slot is occupied; the next attempt must be rejected.
            with pytest.raises(application.exceptions.ServiceBusyError):
                async with controller.acquire_or_reject():
                    pass  # pragma: no cover — should not reach here.

    async def test_rejection_does_not_increment_active_count(self) -> None:
        """
        A rejected acquisition attempt must not increment the active
        count — only successfully admitted operations occupy a slot.
        """
        controller = application.admission_control.ImageGenerationAdmissionController(
            maximum_concurrency=1,
        )

        async with controller.acquire_or_reject():
            assert controller.active_operation_count == 1

            with pytest.raises(application.exceptions.ServiceBusyError):
                async with controller.acquire_or_reject():
                    pass  # pragma: no cover

            # The count must still be 1 (from the outer context), not 2.
            assert controller.active_operation_count == 1

    async def test_rejection_at_concurrency_of_three(self) -> None:
        """
        The rejection threshold respects the configured maximum even
        when it is higher than the default of 1.
        """
        controller = application.admission_control.ImageGenerationAdmissionController(
            maximum_concurrency=3,
        )

        release_signal = asyncio.Event()

        async def hold_admission() -> None:
            async with controller.acquire_or_reject():
                await release_signal.wait()

        # Fill all three slots.
        tasks = [asyncio.create_task(hold_admission()) for _ in range(3)]
        await asyncio.sleep(0)

        assert controller.active_operation_count == 3

        # The fourth attempt must be rejected.
        with pytest.raises(application.exceptions.ServiceBusyError):
            async with controller.acquire_or_reject():
                pass  # pragma: no cover

        # Clean up: release the held operations.
        release_signal.set()
        await asyncio.gather(*tasks)

    async def test_slot_available_after_rejection_and_release(self) -> None:
        """
        After a rejection, once the occupying operation completes and
        releases its slot, the next acquisition attempt succeeds.
        """
        controller = application.admission_control.ImageGenerationAdmissionController(
            maximum_concurrency=1,
        )

        async with controller.acquire_or_reject():
            # Reject while the slot is occupied.
            with pytest.raises(application.exceptions.ServiceBusyError):
                async with controller.acquire_or_reject():
                    pass  # pragma: no cover

        # The slot is now free; this must succeed.
        async with controller.acquire_or_reject():
            assert controller.active_operation_count == 1


class TestAcquireOrRejectExceptionSafety:
    """Verify that the counter is decremented even when the body raises."""

    async def test_counter_decremented_on_exception_in_body(self) -> None:
        """
        If the image generation operation raises an exception inside the
        context manager, the active count must still be decremented so
        the slot is freed for subsequent requests.
        """
        controller = application.admission_control.ImageGenerationAdmissionController(
            maximum_concurrency=1,
        )

        with pytest.raises(RuntimeError, match="simulated inference failure"):
            async with controller.acquire_or_reject():
                assert controller.active_operation_count == 1
                raise RuntimeError("simulated inference failure")

        # The slot must be freed despite the exception.
        assert controller.active_operation_count == 0

    async def test_subsequent_acquisition_succeeds_after_exception(self) -> None:
        """
        After an exception releases the slot, a new operation can
        successfully acquire admission.
        """
        controller = application.admission_control.ImageGenerationAdmissionController(
            maximum_concurrency=1,
        )

        with pytest.raises(ValueError):
            async with controller.acquire_or_reject():
                raise ValueError("simulated error")

        # The next acquisition must succeed.
        async with controller.acquire_or_reject():
            assert controller.active_operation_count == 1


class TestAdmissionControllerProperties:
    """Verify the read-only property accessors used for operational monitoring."""

    def test_active_operation_count_property_returns_integer(self) -> None:
        """The active_operation_count property returns an integer."""
        controller = application.admission_control.ImageGenerationAdmissionController()

        assert isinstance(controller.active_operation_count, int)

    def test_maximum_concurrency_property_returns_configured_value(self) -> None:
        """The maximum_concurrency property returns the value set at construction."""
        controller = application.admission_control.ImageGenerationAdmissionController(
            maximum_concurrency=8,
        )

        assert controller.maximum_concurrency == 8
