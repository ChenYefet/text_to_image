"""
HTTP middleware for the FastAPI application.

Provides cross-cutting concerns that apply to every request/response cycle.
"""

import uuid

import fastapi
import starlette.middleware.base
import starlette.requests
import starlette.responses


class CorrelationIdMiddleware(starlette.middleware.base.BaseHTTPMiddleware):
    """
    Assign a unique correlation ID (UUID v4) to every incoming request.

    The ID is stored on ``request.state.correlation_id`` so that error
    handlers and other components can include it in response bodies.
    It is also added as an ``X-Correlation-ID`` response header.
    """

    async def dispatch(
        self,
        request: starlette.requests.Request,
        call_next: starlette.middleware.base.RequestResponseEndpoint,
    ) -> starlette.responses.Response:
        correlation_id = str(uuid.uuid4())
        request.state.correlation_id = correlation_id

        response = await call_next(request)

        response.headers["X-Correlation-ID"] = correlation_id
        return response
