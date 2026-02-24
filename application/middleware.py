"""
HTTP middleware for the FastAPI application.

Provides cross-cutting concerns that apply to every request/response cycle:

- **CorrelationIdMiddleware** (outermost): assigns a UUID v4 correlation ID
  to every request and attaches it to both the response header and the
  structured log context.  Also serves as the catch-all error boundary for
  unhandled exceptions (HTTP 500).

- **RequestTimeoutMiddleware**: enforces the operator-configured end-to-end
  request timeout (``request_timeout_seconds``, default 300 s).  Requests
  exceeding this ceiling are aborted with HTTP 504 (request_timeout).
  This middleware implements NFR48 from the v5.0.0 specification.

- **ContentTypeValidationMiddleware**: rejects POST requests whose
  ``Content-Type`` header is missing or not ``application/json`` with
  HTTP 415 (http_unsupported_media_type).  GET, OPTIONS, and HEAD requests
  pass through unchecked.

- **RequestPayloadSizeLimitMiddleware**: rejects request bodies that exceed
  the operator-configured maximum (``maximum_request_payload_bytes``,
  default 1 MB) with HTTP 413 (http_payload_too_large) before the full body
  reaches the application layer.

In-flight request tracking
--------------------------
The ``InFlightRequestCounter`` provides a thread-safe atomic counter that
tracks the number of HTTP requests currently being processed.  It is
incremented when a request enters the ``CorrelationIdMiddleware`` and
decremented when the request completes (whether successfully or with an
error).  The counter value is read during graceful shutdown to emit the
``graceful_shutdown_initiated`` log event with the number of requests
still in progress (specification FR40, event B-1).

Middleware registration order
-----------------------------
ASGI middleware executes in reverse registration order (last registered =
outermost).  The resulting execution order is::

    Request → CorrelationId → RequestTimeout → ContentType → PayloadSizeLimit → CORS → App

CorrelationIdMiddleware is outermost so that every request — including
those rejected by inner middleware — receives a traceable correlation
ID.  RequestTimeoutMiddleware is second so that the entire request
processing pipeline (including validation and inference) is bounded by
the end-to-end timeout.  ContentTypeValidationMiddleware rejects
malformed requests before the body is read.
RequestPayloadSizeLimitMiddleware then guards against oversized payloads.
"""

import asyncio
import json
import threading
import time
import uuid

import starlette.types
import structlog
import structlog.contextvars

import application.metrics


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
        self._count: int = 0
        self._lock = threading.Lock()

    def increment(self) -> None:
        """Atomically increment the in-flight request count by one."""
        with self._lock:
            self._count += 1

    def decrement(self) -> None:
        """Atomically decrement the in-flight request count by one."""
        with self._lock:
            self._count -= 1

    @property
    def count(self) -> int:
        """Return the current number of in-flight requests."""
        return self._count


logger = structlog.get_logger()


def extract_content_length_from_headers(
    headers: list[tuple[bytes, bytes]],
) -> int | None:
    """
    Search an ASGI header list for the Content-Length header and return
    its integer value, or ``None`` if the header is absent or cannot be
    parsed as an integer.

    This is a module-level utility shared by both
    ``CorrelationIdMiddleware`` (which logs the declared request payload
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
        metrics_collector: application.metrics.MetricsCollector | None = None,
        in_flight_request_counter: InFlightRequestCounter | None = None,
    ) -> None:
        self.app = app
        self._metrics_collector = metrics_collector
        self._in_flight_request_counter = in_flight_request_counter

    async def __call__(
        self,
        scope: starlette.types.Scope,
        receive: starlette.types.Receive,
        send: starlette.types.Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        correlation_id = str(uuid.uuid4())
        method = scope.get("method", "")
        path = scope.get("path", "")
        start_time = time.monotonic()
        response_status = 0
        response_payload_bytes = 0

        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["correlation_id"] = correlation_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        # Extract the declared request payload size from the Content-Length
        # header (if present) for inclusion in the http_request_received
        # log event, as recommended by the v5.0.0 specification's 31-event
        # logging taxonomy.
        request_payload_bytes = extract_content_length_from_headers(
            scope.get("headers", []),
        )

        logger.info(
            "http_request_received",
            method=method,
            path=path,
            request_payload_bytes=request_payload_bytes,
        )

        # Increment the in-flight request counter so that the graceful
        # shutdown sequence can report how many requests are still being
        # processed when the shutdown signal is received (FR40).
        if self._in_flight_request_counter is not None:
            self._in_flight_request_counter.increment()

        async def send_with_correlation_id_and_size_tracking(
            message: starlette.types.Message,
        ) -> None:
            nonlocal response_status, response_payload_bytes
            if message["type"] == "http.response.start":
                response_status = message.get("status", 0)
                headers = list(message.get("headers", []))
                headers.append((b"x-correlation-id", correlation_id.encode()))
                message["headers"] = headers
            elif message["type"] == "http.response.body":
                # Accumulate the response body size for inclusion in the
                # http_request_completed log event.  Streaming responses
                # may send multiple body chunks; we track the total.
                body_chunk = message.get("body", b"")
                response_payload_bytes += len(body_chunk)
            await send(message)

        try:
            await self.app(
                scope,
                receive,
                send_with_correlation_id_and_size_tracking,
            )
        except Exception:
            response_status = 500
            logger.exception("unexpected_exception")
            error_response_body = json.dumps(
                {
                    "error": {
                        "code": "internal_server_error",
                        "message": "An unexpected internal error occurred.",
                        "correlation_id": correlation_id,
                    }
                }
            ).encode()
            response_payload_bytes = len(error_response_body)
            await send(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"x-correlation-id", correlation_id.encode()),
                    ],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": error_response_body,
                }
            )
        finally:
            # Decrement the in-flight counter now that the request has
            # completed, regardless of whether it succeeded or failed.
            if self._in_flight_request_counter is not None:
                self._in_flight_request_counter.decrement()

            duration_milliseconds = (time.monotonic() - start_time) * 1000
            logger.info(
                "http_request_completed",
                method=method,
                path=path,
                status=response_status,
                duration_milliseconds=round(duration_milliseconds, 1),
                response_payload_bytes=response_payload_bytes,
            )
            if self._metrics_collector is not None:
                self._metrics_collector.record_request(
                    method=method,
                    path=path,
                    status=response_status,
                    duration_milliseconds=round(duration_milliseconds, 1),
                )



class RequestTimeoutMiddleware:
    """
    Enforce an end-to-end request timeout on every HTTP request.

    This middleware implements NFR48 from the v5.0.0 specification: a
    configurable maximum duration for any single HTTP request.  When the
    timeout is exceeded, the request processing is cancelled and the client
    receives an HTTP 504 (Gateway Timeout) response with the structured
    error code ``request_timeout``.

    The timeout encompasses the entire request lifecycle — including body
    parsing, validation, prompt enhancement, image generation inference,
    and response serialisation.  It is the outermost timing boundary and
    operates independently of component-level timeouts (such as the
    per-image inference timeout or the llama.cpp request timeout).

    This middleware must be registered *inside* (after)
    ``CorrelationIdMiddleware`` so that timeout responses include the
    correlation ID for traceability.

    Implementation note
    -------------------
    The middleware tracks whether the inner application has already started
    sending HTTP response headers.  If a timeout occurs *after* headers
    have been sent to the client, the middleware cannot retroactively
    replace the response with a 504; in that case, it logs the timeout
    but allows the partial response to complete.  This scenario is
    extremely unlikely in practice — the application layer finishes
    composing the full response before sending any bytes to the client.
    """

    def __init__(
        self,
        app: starlette.types.ASGIApp,
        request_timeout_seconds: float = 300.0,
    ) -> None:
        self.app = app
        self._request_timeout_seconds = request_timeout_seconds

    async def __call__(
        self,
        scope: starlette.types.Scope,
        receive: starlette.types.Receive,
        send: starlette.types.Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Track whether the inner application has already started sending
        # response headers.  Once headers are sent, the HTTP response
        # status code is committed and cannot be replaced with a 504.
        response_headers_already_sent = False

        async def send_with_header_tracking(
            message: starlette.types.Message,
        ) -> None:
            nonlocal response_headers_already_sent
            if message["type"] == "http.response.start":
                response_headers_already_sent = True
            await send(message)

        try:
            await asyncio.wait_for(
                self.app(scope, receive, send_with_header_tracking),
                timeout=self._request_timeout_seconds,
            )
        except TimeoutError:
            logger.error(
                "request_timeout_exceeded",
                timeout_seconds=self._request_timeout_seconds,
                path=scope.get("path", ""),
                method=scope.get("method", ""),
            )

            if response_headers_already_sent:
                # The inner application has already started sending
                # response headers to the client.  We cannot replace
                # the response with a 504 at this point.  Log the
                # timeout for operational visibility and allow the
                # partial response to complete.
                logger.warning(
                    "request_timeout_after_headers_sent",
                    path=scope.get("path", ""),
                )
                return

            await self._send_request_timeout_response(scope, send)

    @staticmethod
    async def _send_request_timeout_response(
        scope: starlette.types.Scope,
        send: starlette.types.Send,
    ) -> None:
        """
        Send an HTTP 504 (Gateway Timeout) JSON response.

        Reads the correlation ID from ``scope["state"]`` (set by the
        outer ``CorrelationIdMiddleware``) so the error response
        includes a traceable identifier.
        """
        state = scope.get("state", {})
        correlation_id = state.get("correlation_id", "unknown")

        response_body = json.dumps(
            {
                "error": {
                    "code": "request_timeout",
                    "message": ("The request exceeded the maximum allowed processing time and was aborted."),
                    "correlation_id": correlation_id,
                }
            }
        ).encode()

        await send(
            {
                "type": "http.response.start",
                "status": 504,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(response_body)).encode()),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": response_body,
            }
        )


class ContentTypeValidationMiddleware:
    """
    Reject POST requests that do not declare ``application/json`` as their
    Content-Type.

    This middleware enforces NFR18 (Content-Type enforcement) from the
    v5.0.0 specification.  It inspects the ``Content-Type`` header on
    every POST request and returns HTTP 415 (Unsupported Media Type)
    when the header is:

    - Absent entirely, or
    - Present but does not start with ``application/json``.

    The ``startswith`` check accommodates Content-Type values that include
    parameters such as ``application/json; charset=utf-8``.

    Non-POST HTTP methods (GET, OPTIONS, HEAD, etc.) are exempt because
    they either carry no request body or use the body for a different
    purpose (for example, CORS preflight OPTIONS requests).

    This middleware must be registered *inside* (after)
    ``CorrelationIdMiddleware`` so that the correlation ID is available
    for inclusion in the error response body.
    """

    # HTTP methods that are exempt from Content-Type validation because
    # they do not carry a request body that requires parsing.
    _METHODS_EXEMPT_FROM_CONTENT_TYPE_CHECK: frozenset[str] = frozenset(
        {"GET", "HEAD", "OPTIONS", "DELETE", "TRACE"},
    )

    def __init__(self, app: starlette.types.ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: starlette.types.Scope,
        receive: starlette.types.Receive,
        send: starlette.types.Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        http_method = scope.get("method", "")

        if http_method in self._METHODS_EXEMPT_FROM_CONTENT_TYPE_CHECK:
            await self.app(scope, receive, send)
            return

        # ── Extract and validate the Content-Type header ──────────────
        #
        # The ASGI scope stores headers as a list of two-element byte
        # tuples.  We search for the content-type header and verify it
        # starts with "application/json".

        content_type_value = self._extract_content_type_from_headers(
            scope.get("headers", []),
        )

        if content_type_value is None or not content_type_value.startswith("application/json"):
            logger.warning(
                "http_unsupported_media_type",
                received_content_type=content_type_value,
                expected_content_type="application/json",
            )
            await self._send_unsupported_media_type_response(scope, send)
            return

        await self.app(scope, receive, send)

    @staticmethod
    def _extract_content_type_from_headers(
        headers: list[tuple[bytes, bytes]],
    ) -> str | None:
        """
        Search the ASGI header list for the Content-Type header and
        return its decoded string value, or ``None`` if the header is
        absent.
        """
        for header_name, header_value in headers:
            if header_name.lower() == b"content-type":
                return header_value.decode("latin-1").strip().lower()
        return None

    @staticmethod
    async def _send_unsupported_media_type_response(
        scope: starlette.types.Scope,
        send: starlette.types.Send,
    ) -> None:
        """
        Send an HTTP 415 (Unsupported Media Type) JSON response.

        Reads the correlation ID from ``scope["state"]`` (set by the
        outer ``CorrelationIdMiddleware``) so the error response
        includes a traceable identifier.
        """
        state = scope.get("state", {})
        correlation_id = state.get("correlation_id", "unknown")

        response_body = json.dumps(
            {
                "error": {
                    "code": "unsupported_media_type",
                    "message": (
                        "The Content-Type header must be 'application/json'. This API only accepts JSON request bodies."
                    ),
                    "correlation_id": correlation_id,
                }
            }
        ).encode()

        await send(
            {
                "type": "http.response.start",
                "status": 415,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(response_body)).encode()),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": response_body,
            }
        )


class RequestPayloadSizeLimitMiddleware:
    """
    Reject HTTP requests whose body exceeds the configured maximum size.

    This middleware enforces NFR15 (request payload size enforcement) from
    the v5.0.0 specification.  It uses two complementary strategies:

    1. **Fast-path rejection via Content-Length header**: when the client
       sends a ``Content-Length`` header that exceeds the limit, the
       request is rejected immediately *before* any body bytes are read.

    2. **Streaming accumulation guard**: when no ``Content-Length`` header
       is present (for example, chunked transfer encoding), the middleware
       wraps the ASGI ``receive`` callable and tracks accumulated body
       bytes.  If the running total exceeds the limit, it short-circuits
       and sends a 413 response.

    The error response uses the standard ``ErrorResponse`` JSON schema
    with the error code ``payload_too_large``.

    This middleware must be registered *inside* (after)
    ``CorrelationIdMiddleware`` so that the correlation ID is available
    for inclusion in the error response body.
    """

    def __init__(
        self,
        app: starlette.types.ASGIApp,
        maximum_request_payload_bytes: int = 1_048_576,
    ) -> None:
        self.app = app
        self._maximum_request_payload_bytes = maximum_request_payload_bytes

    async def __call__(
        self,
        scope: starlette.types.Scope,
        receive: starlette.types.Receive,
        send: starlette.types.Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # ── Fast-path: check the Content-Length header ────────────────
        #
        # The ASGI scope stores headers as a list of two-element byte
        # tuples: [(b"content-length", b"12345"), ...].  We search for
        # the content-length header and compare its integer value against
        # the configured limit.

        declared_content_length = extract_content_length_from_headers(
            scope.get("headers", []),
        )

        if declared_content_length is not None and declared_content_length > self._maximum_request_payload_bytes:
            logger.warning(
                "http_payload_too_large",
                declared_content_length=declared_content_length,
                maximum_allowed_bytes=self._maximum_request_payload_bytes,
            )
            await self._send_payload_too_large_response(scope, send)
            return

        # ── Streaming guard: wrap receive to track accumulated bytes ──
        #
        # Even when Content-Length is absent or within the limit, a
        # malicious client could send more bytes than declared.  This
        # wrapper tracks the actual number of body bytes received and
        # raises an internal flag when the limit is exceeded.

        accumulated_body_bytes = 0
        payload_limit_exceeded = False

        async def receive_with_size_tracking() -> starlette.types.Message:
            nonlocal accumulated_body_bytes, payload_limit_exceeded

            message = await receive()

            if message["type"] == "http.request":
                body_chunk = message.get("body", b"")
                accumulated_body_bytes += len(body_chunk)

                if accumulated_body_bytes > self._maximum_request_payload_bytes:
                    payload_limit_exceeded = True
                    logger.warning(
                        "http_payload_too_large",
                        accumulated_bytes=accumulated_body_bytes,
                        maximum_allowed_bytes=self._maximum_request_payload_bytes,
                    )
                    # Return an empty body to prevent further processing.
                    # The response will be sent by the exception path below.
                    return {
                        "type": "http.request",
                        "body": b"",
                        "more_body": False,
                    }

            return message

        try:
            await self.app(scope, receive_with_size_tracking, send)
        except Exception:
            if payload_limit_exceeded:
                # The application likely failed because the body was
                # truncated.  Send the 413 response instead of the
                # application's error.
                await self._send_payload_too_large_response(scope, send)
            else:
                raise

        if payload_limit_exceeded:
            # If the app didn't raise but the limit was exceeded (e.g.
            # FastAPI read partial body), we still need to handle this.
            # However, the app may have already started sending a
            # response, so we cannot send another one.  The truncated
            # body should cause a validation error at the application
            # layer, which is an acceptable degraded behaviour.
            pass

    async def _send_payload_too_large_response(
        self,
        scope: starlette.types.Scope,
        send: starlette.types.Send,
    ) -> None:
        """
        Send an HTTP 413 (Payload Too Large) JSON response.

        Reads the correlation ID from ``scope["state"]`` (set by the
        outer ``CorrelationIdMiddleware``) so the error response
        includes a traceable identifier.
        """
        state = scope.get("state", {})
        correlation_id = state.get("correlation_id", "unknown")

        response_body = json.dumps(
            {
                "error": {
                    "code": "payload_too_large",
                    "message": (
                        f"The request payload exceeds the maximum allowed "
                        f"size of {self._maximum_request_payload_bytes} bytes."
                    ),
                    "correlation_id": correlation_id,
                }
            }
        ).encode()

        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(response_body)).encode()),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": response_body,
            }
        )
