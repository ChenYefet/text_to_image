"""
Content-Type validation middleware.

The ``ContentTypeValidationMiddleware`` rejects POST requests whose
``Content-Type`` header is missing or not ``application/json`` with
HTTP 415 (``unsupported_media_type``).  GET, OPTIONS, HEAD, and other
non-body-bearing methods pass through unchecked.

This middleware enforces NFR18 (Content-Type enforcement) from the
v5.8.1 specification.

This middleware must be registered *inside* (after)
``CorrelationIdMiddleware`` so that the correlation ID is available
for inclusion in the error response body.
"""

import json

import starlette.types
import structlog

logger = structlog.get_logger()


class ContentTypeValidationMiddleware:
    """
    Reject POST requests that do not declare ``application/json`` as their
    Content-Type.

    The ``startswith`` check accommodates Content-Type values that include
    parameters such as ``application/json; charset=utf-8``.

    Non-POST HTTP methods (GET, OPTIONS, HEAD, etc.) are exempt because
    they either carry no request body or use the body for a different
    purpose (for example, CORS preflight OPTIONS requests).
    """

    # HTTP methods that are exempt from Content-Type validation because
    # they do not carry a request body that requires parsing.
    _METHODS_EXEMPT_FROM_CONTENT_TYPE_CHECK: frozenset[str] = frozenset(
        {"GET", "HEAD", "OPTIONS", "DELETE", "TRACE"},
    )

    def __init__(self, app: starlette.types.ASGIApp) -> None:
        self._asgi_application = app

    async def __call__(
        self,
        scope: starlette.types.Scope,
        receive: starlette.types.Receive,
        send: starlette.types.Send,
    ) -> None:
        if scope["type"] != "http":
            await self._asgi_application(scope, receive, send)
            return

        http_method = scope.get("method", "")

        if http_method in self._METHODS_EXEMPT_FROM_CONTENT_TYPE_CHECK:
            await self._asgi_application(scope, receive, send)
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

        await self._asgi_application(scope, receive, send)

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
                    "details": "Accepted content type: application/json.",
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
