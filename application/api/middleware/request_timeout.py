"""
Request timeout middleware.

The ``RequestTimeoutMiddleware`` enforces the operator-configured
end-to-end request timeout (``request_timeout_in_seconds``, default
300 s).  Requests exceeding this ceiling are aborted with HTTP 504
(``request_timeout``).  This middleware implements NFR48 from the v5.4.0
specification.

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

import asyncio
import json
import time

import starlette.types
import structlog

logger = structlog.get_logger()


class RequestTimeoutMiddleware:
    """
    Enforce an end-to-end request timeout on every HTTP request.

    When the timeout is exceeded, the request processing is cancelled
    and the client receives an HTTP 504 (Gateway Timeout) response with
    the structured error code ``request_timeout``.
    """

    def __init__(
        self,
        app: starlette.types.ASGIApp,
        request_timeout_in_seconds: float = 300.0,
    ) -> None:
        self._asgi_application = app
        self._request_timeout_in_seconds = request_timeout_in_seconds

    async def __call__(
        self,
        scope: starlette.types.Scope,
        receive: starlette.types.Receive,
        send: starlette.types.Send,
    ) -> None:
        if scope["type"] != "http":
            await self._asgi_application(scope, receive, send)
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

        start_time_of_timeout_measurement = time.monotonic()

        try:
            await asyncio.wait_for(
                self._asgi_application(scope, receive, send_with_header_tracking),
                timeout=self._request_timeout_in_seconds,
            )
        except TimeoutError:
            elapsed_number_of_seconds = round(
                time.monotonic() - start_time_of_timeout_measurement,
                3,
            )
            logger.error(
                "request_timeout_exceeded",
                timeout_in_seconds=self._request_timeout_in_seconds,
                elapsed_number_of_seconds=elapsed_number_of_seconds,
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

    async def _send_request_timeout_response(
        self,
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
                    "details": (f"Timeout duration: {self._request_timeout_in_seconds} seconds."),
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
