"""
Circuit breaker for upstream service communication.

Implements the circuit breaker pattern (described by Michael Nygard in
*Release It!*) to prevent the service from repeatedly waiting for the
full timeout duration when an upstream dependency is consistently
failing.  Without a circuit breaker, every request with
``use_enhancer=true`` would block for the entire
``timeout_for_language_model_requests_in_seconds`` before failing with
HTTP 502 — wasting both server resources and client patience.

State machine
-------------
The circuit breaker operates in three states::

    CLOSED  ──(failure threshold reached)──▸  OPEN
    OPEN    ──(recovery timeout elapsed)───▸  HALF_OPEN
    HALF_OPEN ──(probe succeeds)───────────▸  CLOSED
    HALF_OPEN ──(probe fails)──────────────▸  OPEN

- **CLOSED** (normal operation): requests pass through to the upstream
  service.  Each failure increments a consecutive failure counter.  When
  the counter reaches ``failure_threshold``, the circuit transitions to
  OPEN.  Any success resets the counter to zero.

- **OPEN** (fail-fast): all requests are rejected immediately with
  ``LanguageModelServiceUnavailableError`` without attempting to contact
  the upstream service.  After ``recovery_timeout_seconds`` elapse, the
  circuit transitions to HALF_OPEN.

- **HALF_OPEN** (probing): the circuit allows a single request through
  to test whether the upstream has recovered.  If the request succeeds,
  the circuit transitions back to CLOSED and the failure counter is
  reset.  If the request fails, the circuit transitions back to OPEN
  and the recovery timer restarts.

Thread safety
-------------
The circuit breaker uses an ``asyncio.Lock`` to protect state
transitions.  All state reads and writes occur within the critical
section to prevent race conditions in concurrent async environments.

Configuration
-------------
Three parameters control the circuit breaker behaviour:

- ``failure_threshold``: number of consecutive failures required to open
  the circuit (default 5).
- ``recovery_timeout_seconds``: how long the circuit remains OPEN before
  transitioning to HALF_OPEN for a probe attempt (default 30.0).
- ``name``: a human-readable identifier for the circuit, included in
  log events for operational visibility (default ``"unnamed"``)

All parameters are exposed as configuration variables with the prefix
``TEXT_TO_IMAGE_CIRCUIT_BREAKER_`` for runtime tuning without code
changes.
"""

import asyncio
import enum
import time

import structlog

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
            failure_threshold=5,
            recovery_timeout_seconds=30.0,
            name="language_model",
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
        failure_threshold: int = 5,
        recovery_timeout_seconds: float = 30.0,
        name: str = "unnamed",
    ) -> None:
        """
        Initialise the circuit breaker.

        Args:
            failure_threshold: The number of consecutive upstream
                failures required to transition the circuit from CLOSED
                to OPEN.  A value of 1 opens the circuit on the very
                first failure.  A higher value tolerates transient
                errors before triggering fail-fast behaviour.
            recovery_timeout_seconds: The duration in seconds that the
                circuit remains in the OPEN state before transitioning
                to HALF_OPEN for a probe attempt.  During this period,
                all requests are rejected immediately.
            name: A human-readable identifier for this circuit breaker
                instance, included in structured log events for
                operational visibility and disambiguation when multiple
                circuit breakers are active.
        """
        self._failure_threshold = failure_threshold
        self._recovery_timeout_seconds = recovery_timeout_seconds
        self._name = name

        self._state = CircuitState.CLOSED
        self._consecutive_failure_count: int = 0
        self._last_failure_timestamp: float = 0.0
        self._state_transition_lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Return the current state of the circuit breaker."""
        return self._state

    @property
    def consecutive_failure_count(self) -> int:
        """Return the current count of consecutive failures."""
        return self._consecutive_failure_count

    async def ensure_circuit_is_not_open(self) -> None:
        """
        Check the circuit breaker state and either allow the request
        to proceed or raise ``CircuitOpenError`` to fail fast.

        State transitions that occur within this method:

        - If the circuit is CLOSED, the method returns immediately
          (the request may proceed).
        - If the circuit is OPEN and the recovery timeout has elapsed,
          the circuit transitions to HALF_OPEN and the method returns
          (the request is a probe attempt).
        - If the circuit is OPEN and the recovery timeout has not yet
          elapsed, ``CircuitOpenError`` is raised (fail-fast).
        - If the circuit is HALF_OPEN, the method returns immediately
          (another probe is already in progress; allowing concurrent
          probes avoids head-of-line blocking at the cost of a small
          number of additional upstream requests during recovery).

        Raises:
            CircuitOpenError: When the circuit is OPEN and the recovery
                timeout has not elapsed.
        """
        async with self._state_transition_lock:
            if self._state == CircuitState.CLOSED:
                return

            if self._state == CircuitState.HALF_OPEN:
                # A probe is already in progress.  Allow this request
                # through as well to avoid unnecessary blocking.
                return

            # The circuit is OPEN.  Check whether the recovery timeout
            # has elapsed since the last failure.
            elapsed_seconds_since_last_failure = time.monotonic() - self._last_failure_timestamp

            if elapsed_seconds_since_last_failure >= self._recovery_timeout_seconds:
                # The recovery timeout has elapsed.  Transition to
                # HALF_OPEN to allow a probe request through.
                self._state = CircuitState.HALF_OPEN
                logger.info(
                    "circuit_breaker_half_open",
                    circuit_name=self._name,
                    elapsed_seconds=round(elapsed_seconds_since_last_failure, 1),
                )
                return

            # The recovery timeout has not elapsed.  Reject the request.
            remaining_seconds = self._recovery_timeout_seconds - elapsed_seconds_since_last_failure
            raise CircuitOpenError(
                circuit_name=self._name,
                remaining_seconds_until_recovery=remaining_seconds,
            )

    async def record_success(self) -> None:
        """
        Record a successful upstream call.

        If the circuit is in the HALF_OPEN state (a probe succeeded),
        this transitions the circuit back to CLOSED.  In all states,
        the consecutive failure counter is reset to zero.
        """
        async with self._state_transition_lock:
            previous_state = self._state

            self._consecutive_failure_count = 0
            self._state = CircuitState.CLOSED

            if previous_state == CircuitState.HALF_OPEN:
                logger.info(
                    "circuit_breaker_closed",
                    circuit_name=self._name,
                    reason="probe_succeeded",
                )

    async def record_failure(self) -> None:
        """
        Record a failed upstream call.

        Increments the consecutive failure counter.  If the counter
        reaches the configured threshold and the circuit is currently
        CLOSED, the circuit transitions to OPEN.  If the circuit is
        HALF_OPEN (a probe failed), it transitions back to OPEN.
        """
        async with self._state_transition_lock:
            self._consecutive_failure_count += 1
            self._last_failure_timestamp = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                # The probe failed.  Transition back to OPEN and
                # restart the recovery timer.
                self._state = CircuitState.OPEN
                logger.warning(
                    "circuit_breaker_reopened",
                    circuit_name=self._name,
                    reason="probe_failed",
                    consecutive_failures=self._consecutive_failure_count,
                )
                return

            if self._state == CircuitState.CLOSED and self._consecutive_failure_count >= self._failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    "circuit_breaker_opened",
                    circuit_name=self._name,
                    consecutive_failures=self._consecutive_failure_count,
                    recovery_timeout_seconds=self._recovery_timeout_seconds,
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
        remaining_seconds_until_recovery: Approximate number of seconds
            remaining until the circuit transitions to HALF_OPEN and
            allows a probe request.
    """

    def __init__(
        self,
        circuit_name: str,
        remaining_seconds_until_recovery: float,
    ) -> None:
        self.circuit_name = circuit_name
        self.remaining_seconds_until_recovery = remaining_seconds_until_recovery
        super().__init__(
            f"Circuit breaker '{circuit_name}' is open. "
            f"The upstream service has been consistently failing. "
            f"Recovery probe in {remaining_seconds_until_recovery:.1f} seconds."
        )
