"""
Correlation ID middleware and in-flight request tracking.

The ``CorrelationIdMiddleware`` assigns a UUID v4 correlation ID to every
incoming request, binds it to the structured log context, and injects it
as an ``X-Correlation-ID`` response header.  It also serves as the
outermost error boundary: any unhandled exception that reaches this layer
is caught and converted into a JSON HTTP 500 response with the
correlation ID, preventing stack traces from leaking to clients.

The ``InFlightRequestCounter`` provides a thread-safe atomic counter that
tracks the number of HTTP requests currently being processed.  The counter
value is read during graceful shutdown to emit the
``graceful_shutdown_initiated`` log event (specification FR40, event B-1).
"""

import threading
import uuid

import starlette.types
import structlog
import structlog.contextvars

import application.api.middleware.asgi_error_response_construction
import application.prometheus_metrics


class InFlightRequestCounter:
    """
    Thread-safe counter tracking the number of HTTP requests currently
    being processed by the service.

    This counter is incremented when a request enters the outermost
    middleware layer (``CorrelationIdMiddleware``) and decremented when
    the request completes — whether successfully or with an error.

    The primary consumer of this counter is the graceful shutdown
    sequence (specification FR40), which reads the current value to
    include it in the ``graceful_shutdown_initiated`` log event.  This
    allows operators to determine how many requests were still in
    progress when the shutdown signal was received, which is critical
    for diagnosing incomplete operations and tuning the graceful
    shutdown timeout.

    Thread safety is achieved via a ``threading.Lock`` rather than an
    ``asyncio.Lock`` because the counter may be read from synchronous
    contexts (such as signal handlers or the lifespan shutdown sequence).
    """

    def __init__(self) -> None:
        """Initialise the counter to zero with a threading lock for safety."""
        self._number_of_in_flight_requests: int = 0
        self._lock = threading.Lock()

    def increment(self) -> None:
        """Atomically increment the number of in-flight requests by one."""
        with self._lock:
            self._number_of_in_flight_requests += 1

    def decrement(self) -> None:
        """Atomically decrement the number of in-flight requests by one."""
        with self._lock:
            self._number_of_in_flight_requests -= 1

    @property
    def number_of_in_flight_requests(self) -> int:
        """Return the current number of in-flight requests."""
        return self._number_of_in_flight_requests


logger = structlog.get_logger()


def extract_content_length_from_headers(
    headers: list[tuple[bytes, bytes]],
) -> int | None:
    """
    Search an ASGI header list for the Content-Length header and return
    its integer value, or ``None`` if the header is absent or cannot be
    parsed as an integer.

    This is a module-level utility shared by both
    ``RequestLoggingMiddleware`` (which logs the declared request payload
    size) and ``RequestPayloadSizeLimitMiddleware`` (which enforces
    the maximum payload size limit).
    """
    for header_name, header_value in headers:
        if header_name.lower() == b"content-length":
            try:
                return int(header_value)
            except (ValueError, TypeError):
                return None
    return None


class CorrelationIdMiddleware:
    """
    Assign a unique correlation ID (UUID v4) to every incoming request.

    The ID is stored on ``request.state.correlation_id`` so that error
    handlers and other components can include it in response bodies.
    It is also added as an ``X-Correlation-ID`` response header.

    Implemented as a pure ASGI middleware to avoid two Starlette issues:

    1. BaseHTTPMiddleware wraps unhandled exceptions in ExceptionGroup,
       preventing catch-all exception handlers from firing.
    2. Starlette routes ``Exception`` handlers to ServerErrorMiddleware,
       which always re-raises after sending the response. By catching
       unhandled exceptions here instead, the error is fully contained
       and the client receives a proper JSON 500 response.
    """

    def __init__(
        self,
        app: starlette.types.ASGIApp,
        in_flight_request_counter: InFlightRequestCounter | None = None,
    ) -> None:
        self._asgi_application = app
        self._in_flight_request_counter = in_flight_request_counter

    async def __call__(
        self,
        scope: starlette.types.Scope,
        receive: starlette.types.Receive,
        send: starlette.types.Send,
    ) -> None:
        if scope["type"] != "http":
            await self._asgi_application(scope, receive, send)
            return

        correlation_id = str(uuid.uuid4())

        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["correlation_id"] = correlation_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        # Increment the in-flight request counter so that the graceful
        # shutdown sequence can report how many requests are still being
        # processed when the shutdown signal is received (FR40).
        if self._in_flight_request_counter is not None:
            self._in_flight_request_counter.increment()

        # Increment the Prometheus in-flight gauge for real-time
        # concurrency visibility (FR51).
        application.prometheus_metrics.gauge_of_number_of_http_requests_in_flight.inc()

        async def send_with_correlation_id(
            message: starlette.types.Message,
        ) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-correlation-id", correlation_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self._asgi_application(
                scope,
                receive,
                send_with_correlation_id,
            )
        except Exception:
            logger.exception("unexpected_exception")
            await application.api.middleware.asgi_error_response_construction.send_asgi_json_error_response(
                send=send,
                scope=scope,
                status_code=500,
                error_code="internal_server_error",
                message="An unexpected internal error occurred.",
                additional_headers=[
                    (b"x-correlation-id", correlation_id.encode()),
                ],
            )
        finally:
            # Decrement the in-flight counter now that the request has
            # completed, regardless of whether it succeeded or failed.
            if self._in_flight_request_counter is not None:
                self._in_flight_request_counter.decrement()

            # Decrement the Prometheus in-flight gauge (FR51).
            application.prometheus_metrics.gauge_of_number_of_http_requests_in_flight.dec()
