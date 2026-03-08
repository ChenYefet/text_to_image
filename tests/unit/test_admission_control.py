"""
Comprehensive unit tests for the AdmissionControllerForImageGeneration.

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


class TestAdmissionControllerForImageGenerationInitialisation:
    """Verify that the controller initialises with correct defaults and custom values."""

    def test_default_maximum_number_of_concurrent_operations_is_two(self) -> None:
        """The v5.8.0 specification default for maximum number of concurrent operations is 2."""
        controller = application.admission_control.AdmissionControllerForImageGeneration()

        assert controller.maximum_number_of_concurrent_operations == 2

    def test_custom_maximum_number_of_concurrent_operations_is_stored(self) -> None:
        """Operators can configure a higher concurrency limit via the constructor."""
        controller = application.admission_control.AdmissionControllerForImageGeneration(
            maximum_number_of_concurrent_operations=4,
        )

        assert controller.maximum_number_of_concurrent_operations == 4

    def test_initial_number_of_active_operations_is_zero(self) -> None:
        """No operations are active when the controller is first created."""
        controller = application.admission_control.AdmissionControllerForImageGeneration()

        assert controller.number_of_active_operations == 0


class TestAcquireOrRejectSuccessfulAcquisition:
    """Verify that the context manager grants admission when below the limit."""

    async def test_single_acquisition_increments_active_count(self) -> None:
        """
        When a single operation acquires admission, the active count
        increases to 1 for the duration of the context manager body.
        """
        controller = application.admission_control.AdmissionControllerForImageGeneration(
            maximum_number_of_concurrent_operations=1,
        )

        async with controller.acquire_or_reject():
            assert controller.number_of_active_operations == 1

    async def test_active_count_returns_to_zero_after_exit(self) -> None:
        """
        After the context manager exits normally, the active count
        returns to zero — the slot is released for the next request.
        """
        controller = application.admission_control.AdmissionControllerForImageGeneration(
            maximum_number_of_concurrent_operations=1,
        )

        async with controller.acquire_or_reject():
            pass  # Simulate a completed operation.

        assert controller.number_of_active_operations == 0

    async def test_sequential_acquisitions_succeed(self) -> None:
        """
        Multiple operations can acquire and release the same slot
        sequentially without triggering rejection.
        """
        controller = application.admission_control.AdmissionControllerForImageGeneration(
            maximum_number_of_concurrent_operations=1,
        )

        for _ in range(5):
            async with controller.acquire_or_reject():
                assert controller.number_of_active_operations == 1
            assert controller.number_of_active_operations == 0

    async def test_concurrent_acquisitions_up_to_limit(self) -> None:
        """
        When the maximum number of concurrent operations is greater than 1, multiple
        operations can execute concurrently up to the configured limit.
        """
        controller = application.admission_control.AdmissionControllerForImageGeneration(
            maximum_number_of_concurrent_operations=3,
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

        assert controller.number_of_active_operations == 3

        # Release all operations.
        release_signal.set()
        await asyncio.gather(*tasks)

        assert controller.number_of_active_operations == 0


class TestAcquireOrRejectRejection:
    """Verify that the controller rejects requests when the limit is reached."""

    async def test_rejection_raises_service_busy_error(self) -> None:
        """
        When the concurrency limit is reached, the next acquisition
        attempt raises ``ServiceBusyError`` immediately.
        """
        controller = application.admission_control.AdmissionControllerForImageGeneration(
            maximum_number_of_concurrent_operations=1,
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
        controller = application.admission_control.AdmissionControllerForImageGeneration(
            maximum_number_of_concurrent_operations=1,
        )

        async with controller.acquire_or_reject():
            assert controller.number_of_active_operations == 1

            with pytest.raises(application.exceptions.ServiceBusyError):
                async with controller.acquire_or_reject():
                    pass  # pragma: no cover

            # The count must still be 1 (from the outer context), not 2.
            assert controller.number_of_active_operations == 1

    async def test_rejection_at_concurrency_of_three(self) -> None:
        """
        The rejection threshold respects the configured maximum even
        when it is higher than the default of 1.
        """
        controller = application.admission_control.AdmissionControllerForImageGeneration(
            maximum_number_of_concurrent_operations=3,
        )

        release_signal = asyncio.Event()

        async def hold_admission() -> None:
            async with controller.acquire_or_reject():
                await release_signal.wait()

        # Fill all three slots.
        tasks = [asyncio.create_task(hold_admission()) for _ in range(3)]
        await asyncio.sleep(0)

        assert controller.number_of_active_operations == 3

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
        controller = application.admission_control.AdmissionControllerForImageGeneration(
            maximum_number_of_concurrent_operations=1,
        )

        async with controller.acquire_or_reject():
            # Reject while the slot is occupied.
            with pytest.raises(application.exceptions.ServiceBusyError):
                async with controller.acquire_or_reject():
                    pass  # pragma: no cover

        # The slot is now free; this must succeed.
        async with controller.acquire_or_reject():
            assert controller.number_of_active_operations == 1


class TestAcquireOrRejectExceptionSafety:
    """Verify that the counter is decremented even when the body raises."""

    async def test_counter_decremented_on_exception_in_body(self) -> None:
        """
        If the image generation operation raises an exception inside the
        context manager, the active count must still be decremented so
        the slot is freed for subsequent requests.
        """
        controller = application.admission_control.AdmissionControllerForImageGeneration(
            maximum_number_of_concurrent_operations=1,
        )

        with pytest.raises(RuntimeError, match="simulated inference failure"):
            async with controller.acquire_or_reject():
                assert controller.number_of_active_operations == 1
                raise RuntimeError("simulated inference failure")

        # The slot must be freed despite the exception.
        assert controller.number_of_active_operations == 0

    async def test_subsequent_acquisition_succeeds_after_exception(self) -> None:
        """
        After an exception releases the slot, a new operation can
        successfully acquire admission.
        """
        controller = application.admission_control.AdmissionControllerForImageGeneration(
            maximum_number_of_concurrent_operations=1,
        )

        with pytest.raises(ValueError):
            async with controller.acquire_or_reject():
                raise ValueError("simulated error")

        # The next acquisition must succeed.
        async with controller.acquire_or_reject():
            assert controller.number_of_active_operations == 1


class TestAdmissionControllerCounterIntegrity:
    """Verify that the active operations counter maintains integrity under edge cases."""

    async def test_counter_never_goes_below_zero(self) -> None:
        """
        After a normal acquire-release cycle, the counter must be exactly
        zero.  Multiple sequential acquire-release cycles must not cause
        the counter to drift below zero through accumulation errors.
        """
        controller = application.admission_control.AdmissionControllerForImageGeneration(
            maximum_number_of_concurrent_operations=1,
        )

        for _ in range(10):
            async with controller.acquire_or_reject():
                assert controller.number_of_active_operations == 1
            assert controller.number_of_active_operations == 0

        # Final invariant: exactly zero.
        assert controller.number_of_active_operations == 0

    async def test_counter_correct_after_mixed_successes_and_exceptions(self) -> None:
        """
        Alternating between successful operations and operations that raise
        exceptions must leave the counter at exactly zero after all operations
        complete.
        """
        controller = application.admission_control.AdmissionControllerForImageGeneration(
            maximum_number_of_concurrent_operations=1,
        )

        for iteration in range(6):
            if iteration % 2 == 0:
                async with controller.acquire_or_reject():
                    pass
            else:
                with pytest.raises(ValueError):
                    async with controller.acquire_or_reject():
                        raise ValueError("simulated failure")

        assert controller.number_of_active_operations == 0


class TestAdmissionControllerProperties:
    """Verify the read-only property accessors used for operational monitoring."""

    def test_number_of_active_operations_property_returns_integer(self) -> None:
        """The number_of_active_operations property returns an integer."""
        controller = application.admission_control.AdmissionControllerForImageGeneration()

        assert isinstance(controller.number_of_active_operations, int)

    def test_maximum_number_of_concurrent_operations_property_returns_configured_value(self) -> None:
        """The maximum_number_of_concurrent_operations property returns the value set at construction."""
        controller = application.admission_control.AdmissionControllerForImageGeneration(
            maximum_number_of_concurrent_operations=8,
        )

        assert controller.maximum_number_of_concurrent_operations == 8
