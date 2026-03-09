"""
Construction and transmission of JSON error responses at the ASGI layer.

This module provides a single shared function that middleware classes use
to send structured JSON error responses directly via the ASGI ``send``
callable.  Centralising this logic eliminates duplication across multiple
middleware modules that each independently built and sent the same
two-phase ASGI response (``http.response.start`` + ``http.response.body``).

The error response body conforms to the ``ErrorResponse`` schema defined
in the v5.10.0 specification: a top-level ``error`` object with ``code``,
``message``, ``correlation_id``, and an optional ``details`` field.
"""

import json

import starlette.types


async def send_asgi_json_error_response(
    send: starlette.types.Send,
    scope: starlette.types.Scope,
    status_code: int,
    error_code: str,
    message: str,
    details: str | None = None,
    additional_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    """
    Construct and send a JSON error response via the raw ASGI interface.

    The correlation ID is extracted from ``scope["state"]["correlation_id"]``
    (set by ``CorrelationIdMiddleware``).  If the correlation ID is not
    available — for example, because the error occurs before the scope
    state is populated — the value ``"unknown"`` is used as a fallback.

    Parameters
    ----------
    send
        The ASGI send callable for the current request.
    scope
        The ASGI scope dictionary for the current request.
    status_code
        The HTTP status code for the error response (e.g. 413, 415, 504).
    error_code
        The machine-readable error code string (e.g. ``"payload_too_large"``).
    message
        The human-readable error message.
    details
        Optional additional detail string included in the response body.
        When ``None``, the ``details`` key is omitted from the response.
    additional_headers
        Optional list of extra ASGI header tuples to include in the
        response alongside the default ``content-type`` and
        ``content-length`` headers.
    """
    state = scope.get("state", {})
    correlation_id = state.get("correlation_id", "unknown")

    error_body: dict[str, str] = {
        "code": error_code,
        "message": message,
        "correlation_id": correlation_id,
    }
    if details is not None:
        error_body["details"] = details

    response_body = json.dumps({"error": error_body}).encode()

    headers: list[tuple[bytes, bytes]] = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(response_body)).encode()),
    ]
    if additional_headers is not None:
        headers.extend(additional_headers)

    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": headers,
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": response_body,
        }
    )
