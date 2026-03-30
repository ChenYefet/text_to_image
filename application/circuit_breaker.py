"""
Circuit breaker for upstream service communication.

Implements the circuit breaker pattern (described by Michael Nygard in
*Release It!*) to prevent the service from repeatedly waiting for the
full timeout duration when an upstream dependency is consistently
failing.  Without a circuit breaker, every request with
``use_enhancer=true`` would block for the entire
``timeout_for_requests_to_large_language_model_in_seconds`` before failing with
HTTP 502 — wasting both server resources and client patience.

State machine
-------------
The circuit breaker operates in three states::

    CLOSED  ──(consecutive failure count reached)──▸  OPEN
    OPEN    ──(recovery timeout elapsed)───▸  HALF_OPEN
    HALF_OPEN ──(probe succeeds)───────────▸  CLOSED
    HALF_OPEN ──(probe fails)──────────────▸  OPEN

- **CLOSED** (normal operation): requests pass through to the upstream
  service.  Each failure increments a counter of consecutive failures.  When
  the counter reaches ``number_of_consecutive_failures_to_open_circuit_breaker``, the circuit transitions to
  OPEN.  Any success resets the counter to zero.

- **OPEN** (fail-fast): all requests are rejected immediately with
  ``LargeLanguageModelServiceUnavailableError`` without attempting to contact
  the upstream service.  After ``timeout_for_recovery_in_seconds`` elapse, the
  circuit transitions to HALF_OPEN.

- **HALF_OPEN** (probing): the circuit allows a single request through
  to test whether the upstream has recovered.  If the request succeeds,
  the circuit transitions back to CLOSED and the counter of consecutive
  failures is reset.  If the request fails, the circuit transitions
  back to OPEN and the recovery timer restarts.

Thread safety
-------------
The circuit breaker uses an ``asyncio.Lock`` to protect state
transitions.  All state reads and writes occur within the critical
section to prevent race conditions in concurrent async environments.

Configuration
-------------
Three parameters control the circuit breaker behaviour:

- ``number_of_consecutive_failures_to_open_circuit_breaker``: number of consecutive failures required to open
  the circuit (default 5).
- ``timeout_for_recovery_in_seconds``: how long the circuit remains OPEN before
  transitioning to HALF_OPEN for a probe attempt (default 30.0).
- ``name``: a human-readable identifier for the circuit, included in
  log events for operational visibility (default ``"unnamed"``)

All parameters are exposed as configuration variables with the prefix
``TEXT_TO_IMAGE_`` for runtime tuning without code changes.
"""

import asyncio
import enum
import time

import structlog

from application.prometheus_metrics import state_of_circuit_breaker

logger = structlog.get_logger()


class CircuitState(enum.Enum):
    """
    The three possible states of a circuit breaker.

    - ``CLOSED``: normal operation; requests pass through to the upstream.
    - ``OPEN``: fail-fast; requests are rejected immediately.
    - ``HALF_OPEN``: probing; one request is allowed through to test recovery.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """
    A circuit breaker that tracks consecutive upstream failures and
    transitions between CLOSED, OPEN, and HALF_OPEN states to prevent
    repeated timeout-duration waits against a consistently failing
    upstream service.

    Usage::

        circuit_breaker = CircuitBreaker(
            number_of_consecutive_failures_to_open_circuit_breaker=5,
            timeout_for_recovery_in_seconds=30.0,
            name="large_language_model",
        )

        # Before making an upstream call:
        circuit_breaker.ensure_circuit_is_not_open()

        # After a successful upstream call:
        circuit_breaker.record_success()

        # After a failed upstream call:
        circuit_breaker.record_failure()

    The ``ensure_circuit_is_not_open`` method raises
    ``CircuitOpenError`` when the circuit is in the OPEN state and the
    recovery timeout has not yet elapsed, enabling the caller to
    fail-fast without waiting for the upstream timeout.
    """

    def __init__(
        self,
        number_of_consecutive_failures_to_open_circuit_breaker: int = 5,
        timeout_for_recovery_in_seconds: float = 30.0,
        name: str = "unnamed",
    ) -> None:
        """
        Initialise the circuit breaker.

        Args:
            number_of_consecutive_failures_to_open_circuit_breaker: The number of consecutive upstream
                failures required to transition the circuit from CLOSED
                to OPEN.  A value of 1 opens the circuit on the very
                first failure.  A higher value tolerates transient
                errors before triggering fail-fast behaviour.
            timeout_for_recovery_in_seconds: The duration in seconds that the
                circuit remains in the OPEN state before transitioning
                to HALF_OPEN for a probe attempt.  During this period,
                all requests are rejected immediately.
            name: A human-readable identifier for this circuit breaker
                instance, included in structured log events for
                operational visibility and disambiguation when multiple
                circuit breakers are active.
        """
        self._number_of_consecutive_failures_to_open_circuit_breaker = (
            number_of_consecutive_failures_to_open_circuit_breaker
        )
        self._timeout_for_recovery_in_seconds = timeout_for_recovery_in_seconds
        self._name = name

        self._state = CircuitState.CLOSED
        self._number_of_consecutive_failures: int = 0
        self._timestamp_of_last_failure: float = 0.0
        self._probe_in_progress: bool = False
        self._lock_for_state_transitions = asyncio.Lock()

        state_of_circuit_breaker.labels(
            circuit_name=self._name,
        ).state(self._state.value)

    @property
    def state(self) -> CircuitState:
        """Return the current state of the circuit breaker."""
        return self._state

    @property
    def number_of_consecutive_failures(self) -> int:
        """Return the current number of consecutive failures."""
        return self._number_of_consecutive_failures

    async def ensure_circuit_is_not_open(self) -> None:
        """
        Check the circuit breaker state and either allow the request
        to proceed or raise ``CircuitOpenError`` to fail fast.

        State transitions that occur within this method:

        - If the circuit is CLOSED, the method returns immediately
          (the request may proceed).
        - If the circuit is OPEN and the recovery timeout has elapsed,
          the circuit transitions to HALF_OPEN, marks a probe as in
          progress, and the method returns (the request is the probe).
        - If the circuit is OPEN and the recovery timeout has not yet
          elapsed, ``CircuitOpenError`` is raised (fail-fast).
        - If the circuit is HALF_OPEN and a probe is already in
          progress, ``CircuitOpenError`` is raised (only one probe
          request is permitted at a time per the specification).

        Raises:
            CircuitOpenError: When the circuit is OPEN and the recovery
                timeout has not elapsed, or when the circuit is
                HALF_OPEN and a probe is already in progress.
        """
        async with self._lock_for_state_transitions:
            if self._state == CircuitState.CLOSED:
                return

            if self._state == CircuitState.HALF_OPEN:
                # Only one probe request is permitted in the HALF_OPEN
                # state.  If a probe is already in progress, reject
                # this request with the same fail-fast behaviour as
                # the OPEN state.
                raise CircuitOpenError(
                    circuit_name=self._name,
                    remaining_number_of_seconds_until_recovery=0.0,
                )

            # The circuit is OPEN.  Check whether the recovery timeout
            # has elapsed since the last failure.
            elapsed_number_of_seconds_since_last_failure = time.monotonic() - self._timestamp_of_last_failure

            if elapsed_number_of_seconds_since_last_failure >= self._timeout_for_recovery_in_seconds:
                # The recovery timeout has elapsed.  Transition to
                # HALF_OPEN to allow a single probe request through.
                self._state = CircuitState.HALF_OPEN
                self._probe_in_progress = True
                state_of_circuit_breaker.labels(
                    circuit_name=self._name,
                ).state(self._state.value)
                logger.info(
                    "circuit_breaker_half_open",
                    circuit_name=self._name,
                    elapsed_number_of_seconds=round(elapsed_number_of_seconds_since_last_failure, 1),
                )
                return

            # The recovery timeout has not elapsed.  Reject the request.
            remaining_number_of_seconds = (
                self._timeout_for_recovery_in_seconds - elapsed_number_of_seconds_since_last_failure
            )
            raise CircuitOpenError(
                circuit_name=self._name,
                remaining_number_of_seconds_until_recovery=remaining_number_of_seconds,
            )

    async def record_success(self) -> None:
        """
        Record a successful upstream call.

        If the circuit is in the HALF_OPEN state (a probe succeeded),
        this transitions the circuit back to CLOSED.  In all states,
        the counter of consecutive failures is reset to zero and the
        probe-in-progress flag is cleared.
        """
        async with self._lock_for_state_transitions:
            previous_state = self._state

            self._number_of_consecutive_failures = 0
            self._state = CircuitState.CLOSED
            self._probe_in_progress = False
            state_of_circuit_breaker.labels(
                circuit_name=self._name,
            ).state(self._state.value)

            if previous_state == CircuitState.HALF_OPEN:
                logger.info(
                    "circuit_breaker_closed",
                    circuit_name=self._name,
                    reason="probe_succeeded",
                )

    async def record_failure(self) -> None:
        """
        Record a failed upstream call.

        Increments the counter of consecutive failures.  If the counter
        reaches the configured threshold and the circuit is currently
        CLOSED, the circuit transitions to OPEN.  If the circuit is
        HALF_OPEN (a probe failed), it transitions back to OPEN and
        the probe-in-progress flag is cleared.
        """
        async with self._lock_for_state_transitions:
            self._number_of_consecutive_failures += 1
            self._timestamp_of_last_failure = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                # The probe failed.  Transition back to OPEN and
                # restart the recovery timer.
                self._state = CircuitState.OPEN
                self._probe_in_progress = False
                state_of_circuit_breaker.labels(
                    circuit_name=self._name,
                ).state(self._state.value)
                logger.warning(
                    "circuit_breaker_reopened",
                    circuit_name=self._name,
                    reason="probe_failed",
                    number_of_consecutive_failures=self._number_of_consecutive_failures,
                )
                return

            if (
                self._state == CircuitState.CLOSED
                and self._number_of_consecutive_failures >= self._number_of_consecutive_failures_to_open_circuit_breaker
            ):
                self._state = CircuitState.OPEN
                state_of_circuit_breaker.labels(
                    circuit_name=self._name,
                ).state(self._state.value)
                logger.warning(
                    "circuit_breaker_opened",
                    circuit_name=self._name,
                    number_of_consecutive_failures=self._number_of_consecutive_failures,
                    timeout_for_recovery_in_seconds=self._timeout_for_recovery_in_seconds,
                )


class CircuitOpenError(Exception):
    """
    Raised when the circuit breaker is in the OPEN state and the
    recovery timeout has not yet elapsed.

    This exception signals that the upstream service has been
    consistently failing and the circuit breaker is preventing further
    requests from waiting for the full timeout duration.

    Attributes:
        circuit_name: The human-readable name of the circuit breaker
            that rejected the request.
        remaining_number_of_seconds_until_recovery: Approximate number of seconds
            remaining until the circuit transitions to HALF_OPEN and
            allows a probe request.
    """

    def __init__(
        self,
        circuit_name: str,
        remaining_number_of_seconds_until_recovery: float,
    ) -> None:
        self.circuit_name = circuit_name
        self.remaining_number_of_seconds_until_recovery = remaining_number_of_seconds_until_recovery
        super().__init__(
            f"Circuit breaker '{circuit_name}' is open."
            " The upstream service has been consistently failing."
            f" Recovery probe in {remaining_number_of_seconds_until_recovery:.1f}"
            " seconds."
        )
