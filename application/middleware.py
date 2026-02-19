"""
HTTP middleware for the FastAPI application.

Provides cross-cutting concerns that apply to every request/response cycle.
"""

import json
import logging
import uuid

import starlette.types

logger = logging.getLogger(__name__)


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

        correlation_id = str(uuid.uuid4())

        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["correlation_id"] = correlation_id

        async def send_with_correlation_id(message: starlette.types.Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-correlation-id", correlation_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_correlation_id)
        except Exception:
            logger.exception("An unexpected error occurred")
            body = json.dumps({
                "error": {
                    "code": "internal_server_error",
                    "message": "An unexpected internal error occurred.",
                    "correlation_id": correlation_id,
                }
            }).encode()
            await send({
                "type": "http.response.start",
                "status": 500,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"x-correlation-id", correlation_id.encode()),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": body,
            })
