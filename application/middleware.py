"""
HTTP middleware for the FastAPI application.

Provides cross-cutting concerns that apply to every request/response cycle.
"""

import json
import time
import uuid

import starlette.types
import structlog
import structlog.contextvars

import application.metrics

logger = structlog.get_logger()


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
    ) -> None:
        self.app = app
        self._metrics = metrics_collector

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

        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["correlation_id"] = correlation_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        logger.info("http_request_received", method=method, path=path)

        async def send_with_correlation_id(message: starlette.types.Message) -> None:
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = message.get("status", 0)
                headers = list(message.get("headers", []))
                headers.append((b"x-correlation-id", correlation_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_correlation_id)
        except Exception:
            response_status = 500
            logger.exception("unexpected_exception")
            body = json.dumps(
                {
                    "error": {
                        "code": "internal_server_error",
                        "message": "An unexpected internal error occurred.",
                        "correlation_id": correlation_id,
                    }
                }
            ).encode()
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
                    "body": body,
                }
            )
        finally:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "http_request_completed",
                method=method,
                path=path,
                status=response_status,
                duration_ms=round(duration_ms, 1),
            )
            if self._metrics is not None:
                self._metrics.record_request(
                    method=method,
                    path=path,
                    status=response_status,
                    duration_ms=round(duration_ms, 1),
                )
