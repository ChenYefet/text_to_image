"""
Tests for application/circuit_breaker.py.

Covers all state transitions and edge cases of the circuit breaker pattern:

- CLOSED state: requests pass through, successes reset counter, failures
  accumulate, threshold reached opens the circuit.
- OPEN state: requests are rejected immediately with CircuitOpenError,
  recovery timeout transitions to HALF_OPEN.
- HALF_OPEN state: a successful probe closes the circuit, a failed probe
  reopens it.
- Property accessors for state and failure count.
- Structured log events for state transitions.
"""

import asyncio

import pytest

import application.circuit_breaker


class TestCircuitBreakerClosedState:
    """Verify behaviour when the circuit breaker is in the CLOSED state."""

    @pytest.mark.asyncio
    async def test_initial_state_is_closed(self) -> None:
        """A newly created circuit breaker starts in the CLOSED state."""
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=5,
            timeout_for_recovery_in_seconds=30.0,
            name="test",
        )

        assert breaker.state == application.circuit_breaker.CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_initial_failure_count_is_zero(self) -> None:
        """A newly created circuit breaker has zero consecutive failures."""
        breaker = application.circuit_breaker.CircuitBreaker()

        assert breaker.number_of_consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_closed_circuit_allows_requests(self) -> None:
        """When the circuit is CLOSED, ensure_circuit_is_not_open returns without raising."""
        breaker = application.circuit_breaker.CircuitBreaker(failure_threshold=5)

        # Should not raise.
        await breaker.ensure_circuit_is_not_open()

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self) -> None:
        """A successful call resets the counter of consecutive failures to zero."""
        breaker = application.circuit_breaker.CircuitBreaker(failure_threshold=5)

        await breaker.record_failure()
        await breaker.record_failure()

        assert breaker.number_of_consecutive_failures == 2

        await breaker.record_success()

        assert breaker.number_of_consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_failures_below_threshold_keep_circuit_closed(self) -> None:
        """Failures below the threshold do not open the circuit."""
        breaker = application.circuit_breaker.CircuitBreaker(failure_threshold=3)

        await breaker.record_failure()
        await breaker.record_failure()

        assert breaker.state == application.circuit_breaker.CircuitState.CLOSED
        assert breaker.number_of_consecutive_failures == 2


class TestCircuitBreakerOpening:
    """Verify the transition from CLOSED to OPEN when the failure threshold is reached."""

    @pytest.mark.asyncio
    async def test_reaching_threshold_opens_circuit(self) -> None:
        """When consecutive failures reach the threshold, the circuit opens."""
        breaker = application.circuit_breaker.CircuitBreaker(failure_threshold=3)

        await breaker.record_failure()
        await breaker.record_failure()
        await breaker.record_failure()

        assert breaker.state == application.circuit_breaker.CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_threshold_of_one_opens_on_first_failure(self) -> None:
        """A threshold of 1 opens the circuit on the very first failure."""
        breaker = application.circuit_breaker.CircuitBreaker(failure_threshold=1)

        await breaker.record_failure()

        assert breaker.state == application.circuit_breaker.CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_open_circuit_rejects_requests(self) -> None:
        """When the circuit is OPEN, ensure_circuit_is_not_open raises CircuitOpenError."""
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=1,
            timeout_for_recovery_in_seconds=60.0,
            name="test_circuit",
        )

        await breaker.record_failure()

        with pytest.raises(
            application.circuit_breaker.CircuitOpenError,
            match="test_circuit",
        ):
            await breaker.ensure_circuit_is_not_open()

    @pytest.mark.asyncio
    async def test_circuit_open_error_includes_remaining_number_of_seconds_until_recovery(self) -> None:
        """The CircuitOpenError includes the approximate remaining recovery time."""
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=1,
            timeout_for_recovery_in_seconds=60.0,
            name="test_circuit",
        )

        await breaker.record_failure()

        with pytest.raises(application.circuit_breaker.CircuitOpenError) as exception_context:
            await breaker.ensure_circuit_is_not_open()

        assert exception_context.value.remaining_number_of_seconds_until_recovery > 0
        assert exception_context.value.circuit_name == "test_circuit"


class TestCircuitBreakerRecovery:
    """Verify the OPEN → HALF_OPEN → CLOSED recovery sequence."""

    @pytest.mark.asyncio
    async def test_recovery_timeout_transitions_to_half_open(self) -> None:
        """After the recovery timeout elapses, the circuit transitions to HALF_OPEN."""
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=1,
            timeout_for_recovery_in_seconds=0.1,
        )

        await breaker.record_failure()

        assert breaker.state == application.circuit_breaker.CircuitState.OPEN

        # Wait for the recovery timeout to elapse.
        await asyncio.sleep(0.15)

        # The next call to ensure_circuit_is_not_open should transition
        # to HALF_OPEN and allow the request through.
        await breaker.ensure_circuit_is_not_open()

        assert breaker.state == application.circuit_breaker.CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_successful_probe_closes_circuit(self) -> None:
        """A successful probe in HALF_OPEN state transitions the circuit to CLOSED."""
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=1,
            timeout_for_recovery_in_seconds=0.1,
        )

        await breaker.record_failure()
        await asyncio.sleep(0.15)
        await breaker.ensure_circuit_is_not_open()

        assert breaker.state == application.circuit_breaker.CircuitState.HALF_OPEN

        await breaker.record_success()

        assert breaker.state == application.circuit_breaker.CircuitState.CLOSED
        assert breaker.number_of_consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_failed_probe_reopens_circuit(self) -> None:
        """A failed probe in HALF_OPEN state transitions the circuit back to OPEN."""
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=1,
            timeout_for_recovery_in_seconds=0.1,
        )

        await breaker.record_failure()
        await asyncio.sleep(0.15)
        await breaker.ensure_circuit_is_not_open()

        assert breaker.state == application.circuit_breaker.CircuitState.HALF_OPEN

        await breaker.record_failure()

        assert breaker.state == application.circuit_breaker.CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_half_open_rejects_concurrent_probes(self) -> None:
        """In HALF_OPEN state, only a single probe request is permitted.
        Subsequent calls to ensure_circuit_is_not_open are rejected with
        CircuitOpenError while the first probe is in progress."""
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=1,
            timeout_for_recovery_in_seconds=0.1,
        )

        await breaker.record_failure()
        await asyncio.sleep(0.15)

        # First call transitions to HALF_OPEN and is the single probe.
        await breaker.ensure_circuit_is_not_open()

        assert breaker.state == application.circuit_breaker.CircuitState.HALF_OPEN

        # Second call in HALF_OPEN must be rejected because a probe is
        # already in progress (single-probe behaviour per spec).
        with pytest.raises(application.circuit_breaker.CircuitOpenError):
            await breaker.ensure_circuit_is_not_open()

    @pytest.mark.asyncio
    async def test_full_recovery_cycle(self) -> None:
        """
        Exercise a complete lifecycle: CLOSED → OPEN → HALF_OPEN → CLOSED.

        Verifies that after recovery, the circuit operates normally and
        can track new failures independently of the previous cycle.
        """
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=2,
            timeout_for_recovery_in_seconds=0.1,
        )

        # Phase 1: Accumulate failures to open the circuit.
        await breaker.record_failure()
        await breaker.record_failure()

        assert breaker.state == application.circuit_breaker.CircuitState.OPEN

        # Phase 2: Wait for recovery timeout.
        await asyncio.sleep(0.15)

        # Phase 3: Probe transitions to HALF_OPEN.
        await breaker.ensure_circuit_is_not_open()

        assert breaker.state == application.circuit_breaker.CircuitState.HALF_OPEN

        # Phase 4: Successful probe closes the circuit.
        await breaker.record_success()

        assert breaker.state == application.circuit_breaker.CircuitState.CLOSED
        assert breaker.number_of_consecutive_failures == 0

        # Phase 5: Verify the circuit operates normally after recovery.
        await breaker.ensure_circuit_is_not_open()

        assert breaker.state == application.circuit_breaker.CircuitState.CLOSED


class TestCircuitBreakerLogging:
    """Verify that the circuit breaker emits structured log events for state transitions."""

    @pytest.mark.asyncio
    async def test_opening_logs_warning(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """When the circuit opens, a 'circuit_breaker_opened' warning is logged."""
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=1,
            name="test_logging",
        )

        await breaker.record_failure()

        captured_output = capsys.readouterr()
        assert "circuit_breaker_opened" in captured_output.out
        assert "test_logging" in captured_output.out

    @pytest.mark.asyncio
    async def test_half_open_logs_info(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """When the circuit transitions to HALF_OPEN, an info event is logged."""
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=1,
            timeout_for_recovery_in_seconds=0.1,
            name="test_logging",
        )

        await breaker.record_failure()
        await asyncio.sleep(0.15)
        await breaker.ensure_circuit_is_not_open()

        captured_output = capsys.readouterr()
        assert "circuit_breaker_half_open" in captured_output.out

    @pytest.mark.asyncio
    async def test_closing_after_probe_logs_info(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """When a successful probe closes the circuit, an info event is logged."""
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=1,
            timeout_for_recovery_in_seconds=0.1,
            name="test_logging",
        )

        await breaker.record_failure()
        await asyncio.sleep(0.15)
        await breaker.ensure_circuit_is_not_open()
        await breaker.record_success()

        captured_output = capsys.readouterr()
        assert "circuit_breaker_closed" in captured_output.out
        assert "probe_succeeded" in captured_output.out

    @pytest.mark.asyncio
    async def test_reopening_after_failed_probe_logs_warning(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """When a failed probe reopens the circuit, a warning event is logged."""
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=1,
            timeout_for_recovery_in_seconds=0.1,
            name="test_logging",
        )

        await breaker.record_failure()
        await asyncio.sleep(0.15)
        await breaker.ensure_circuit_is_not_open()
        await breaker.record_failure()

        captured_output = capsys.readouterr()
        assert "circuit_breaker_reopened" in captured_output.out
        assert "probe_failed" in captured_output.out


class TestCircuitBreakerTimingEdgeCases:
    """Verify edge cases around the recovery timeout boundary."""

    @pytest.mark.asyncio
    async def test_request_just_before_recovery_timeout_is_rejected(self) -> None:
        """A request sent just before the recovery timeout expires is still rejected."""
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=1,
            timeout_for_recovery_in_seconds=10.0,
        )

        await breaker.record_failure()

        # The recovery timeout is 10 seconds; we have not waited at all.
        with pytest.raises(application.circuit_breaker.CircuitOpenError):
            await breaker.ensure_circuit_is_not_open()

    @pytest.mark.asyncio
    async def test_success_in_closed_state_does_not_change_state(self) -> None:
        """Recording success in CLOSED state keeps the circuit CLOSED."""
        breaker = application.circuit_breaker.CircuitBreaker(failure_threshold=5)

        await breaker.record_success()

        assert breaker.state == application.circuit_breaker.CircuitState.CLOSED
        assert breaker.number_of_consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_additional_failures_in_open_state_do_not_change_state(self) -> None:
        """Recording additional failures while the circuit is OPEN keeps it OPEN."""
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=1,
            timeout_for_recovery_in_seconds=60.0,
        )

        await breaker.record_failure()

        assert breaker.state == application.circuit_breaker.CircuitState.OPEN

        await breaker.record_failure()
        await breaker.record_failure()

        assert breaker.state == application.circuit_breaker.CircuitState.OPEN
        assert breaker.number_of_consecutive_failures == 3


class TestCircuitBreakerConcurrentAccess:
    """Verify that the circuit breaker handles concurrent state mutations safely."""

    @pytest.mark.asyncio
    async def test_concurrent_failures_do_not_corrupt_counter(self) -> None:
        """
        When multiple coroutines record failures concurrently, the final
        failure count must equal the total number of recorded failures.
        The asyncio.Lock inside the circuit breaker prevents lost updates.
        """
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=100,
            timeout_for_recovery_in_seconds=60.0,
        )

        number_of_concurrent_tasks = 20

        async def record_one_failure() -> None:
            await breaker.record_failure()

        await asyncio.gather(*[record_one_failure() for _ in range(number_of_concurrent_tasks)])

        assert breaker.number_of_consecutive_failures == number_of_concurrent_tasks

    @pytest.mark.asyncio
    async def test_concurrent_success_and_failure_do_not_deadlock(self) -> None:
        """
        Interleaving record_success and record_failure calls concurrently
        must not deadlock the circuit breaker's internal lock.
        """
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=100,
            timeout_for_recovery_in_seconds=60.0,
        )

        async def alternate_success_and_failure(index: int) -> None:
            if index % 2 == 0:
                await breaker.record_failure()
            else:
                await breaker.record_success()

        await asyncio.gather(*[alternate_success_and_failure(i) for i in range(20)])

        # The circuit should be in a valid state (not deadlocked).
        # The exact counter value depends on scheduling order, but the
        # state must be one of the three valid states.
        assert breaker.state in {
            application.circuit_breaker.CircuitState.CLOSED,
            application.circuit_breaker.CircuitState.OPEN,
            application.circuit_breaker.CircuitState.HALF_OPEN,
        }


class TestCircuitOpenError:
    """Verify the CircuitOpenError exception attributes and message."""

    def test_error_message_includes_circuit_name(self) -> None:
        """The error message includes the circuit breaker's name."""
        error = application.circuit_breaker.CircuitOpenError(
            circuit_name="large_language_model",
            remaining_number_of_seconds_until_recovery=15.5,
        )

        assert "large_language_model" in str(error)

    def test_error_attributes_are_accessible(self) -> None:
        """The circuit_name and remaining_number_of_seconds_until_recovery attributes are accessible."""
        error = application.circuit_breaker.CircuitOpenError(
            circuit_name="test_circuit",
            remaining_number_of_seconds_until_recovery=42.0,
        )

        assert error.circuit_name == "test_circuit"
        assert error.remaining_number_of_seconds_until_recovery == 42.0
