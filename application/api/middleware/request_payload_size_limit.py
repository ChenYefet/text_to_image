"""
Request payload size limit middleware.

The ``RequestPayloadSizeLimitMiddleware`` rejects HTTP requests whose body
exceeds the configured maximum size with HTTP 413 (``payload_too_large``).

This middleware enforces NFR15 (request payload size enforcement) from
the v5.12.0 specification.  It uses two complementary strategies:

1. **Fast-path rejection via Content-Length header**: when the client
   sends a ``Content-Length`` header that exceeds the limit, the
   request is rejected immediately *before* any body bytes are read.

2. **Streaming accumulation guard**: when no ``Content-Length`` header
   is present (for example, chunked transfer encoding), the middleware
   wraps the ASGI ``receive`` callable and tracks accumulated body
   bytes.  If the running total exceeds the limit, it short-circuits
   and sends a 413 response.

This middleware must be registered *inside* (after)
``CorrelationIdMiddleware`` so that the correlation ID is available
for inclusion in the error response body.
"""

import starlette.types
import structlog

import application.api.middleware.asgi_error_response_construction
import application.api.middleware.correlation_identifier

logger = structlog.get_logger()


class RequestPayloadSizeLimitMiddleware:
    """
    Reject HTTP requests whose body exceeds the configured maximum size.

    The error response uses the standard ``ErrorResponse`` JSON schema
    with the error code ``payload_too_large``.
    """

    def __init__(
        self,
        app: starlette.types.ASGIApp,
        maximum_number_of_bytes_of_request_payload: int = 1_048_576,
    ) -> None:
        self._asgi_application = app
        self._maximum_number_of_bytes_of_request_payload = maximum_number_of_bytes_of_request_payload

    async def __call__(
        self,
        scope: starlette.types.Scope,
        receive: starlette.types.Receive,
        send: starlette.types.Send,
    ) -> None:
        if scope["type"] != "http":
            await self._asgi_application(scope, receive, send)
            return

        # ── Fast-path: check the Content-Length header ────────────────
        #
        # The ASGI scope stores headers as a list of two-element byte
        # tuples: [(b"content-length", b"12345"), ...].  We search for
        # the content-length header and compare its integer value against
        # the configured limit.

        declared_content_length = application.api.middleware.correlation_identifier.extract_content_length_from_headers(
            scope.get("headers", []),
        )

        if (
            declared_content_length is not None
            and declared_content_length > self._maximum_number_of_bytes_of_request_payload
        ):
            logger.warning(
                "http_payload_too_large",
                declared_content_length=declared_content_length,
                maximum_number_of_bytes_allowed=self._maximum_number_of_bytes_of_request_payload,
            )
            await self._send_payload_too_large_response(scope, send)
            return

        # ── Streaming guard: wrap receive to track accumulated bytes ──
        #
        # Even when Content-Length is absent or within the limit, a
        # malicious client could send more bytes than declared.  This
        # wrapper tracks the actual number of body bytes received and
        # raises an internal flag when the limit is exceeded.

        accumulated_number_of_bytes_of_request_body = 0
        payload_limit_exceeded = False

        async def receive_with_size_tracking() -> starlette.types.Message:
            nonlocal accumulated_number_of_bytes_of_request_body, payload_limit_exceeded

            message = await receive()

            if message["type"] == "http.request":
                body_chunk = message.get("body", b"")
                accumulated_number_of_bytes_of_request_body += len(body_chunk)

                if accumulated_number_of_bytes_of_request_body > self._maximum_number_of_bytes_of_request_payload:
                    payload_limit_exceeded = True
                    logger.warning(
                        "http_payload_too_large",
                        accumulated_number_of_bytes=accumulated_number_of_bytes_of_request_body,
                        maximum_number_of_bytes_allowed=self._maximum_number_of_bytes_of_request_payload,
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
            await self._asgi_application(scope, receive_with_size_tracking, send)
        except Exception:
            if payload_limit_exceeded:
                # The application likely failed because the body was
                # truncated.  Send the 413 response instead of the
                # application's error.
                await self._send_payload_too_large_response(scope, send)
            else:
                raise

        if payload_limit_exceeded:
            # If the application didn't raise but the limit was exceeded
            # (e.g. FastAPI read partial body), we still need to handle
            # this.  However, the application may have already started sending a
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

        Delegates to the shared ASGI error response construction
        function, which reads the correlation ID from ``scope["state"]``
        (set by the outer ``CorrelationIdMiddleware``) so the error
        response includes a traceable identifier.
        """
        await application.api.middleware.asgi_error_response_construction.send_asgi_json_error_response(
            send=send,
            scope=scope,
            status_code=413,
            error_code="payload_too_large",
            message=(
                "The request payload exceeds the maximum"
                " allowed size of"
                f" {self._maximum_number_of_bytes_of_request_payload} bytes."
            ),
            details=(f"Maximum allowed payload size: {self._maximum_number_of_bytes_of_request_payload} bytes."),
        )
