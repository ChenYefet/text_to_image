"""
Rate limiting configuration for inference-heavy endpoints.

Uses slowapi (backed by limits) to throttle requests per client IP.
The rate limit is configurable via the ``TEXT_TO_IMAGE_RATE_LIMIT``
environment variable (default: ``10/minute``).

The configured limit is stored on ``app.state.rate_limit`` and read
at request time via a dynamic callable so that the decorator can be
applied at import time while the actual limit value is deferred to
application startup.
"""

import fastapi
import fastapi.responses
import slowapi
import slowapi.errors
import slowapi.util

import application.models

# Module-level rate limit string. Updated by server_factory on startup.
_configured_rate_limit = "10/minute"


def _dynamic_limit() -> str:
    """Return the currently configured rate limit string."""
    return _configured_rate_limit


limiter = slowapi.Limiter(key_func=slowapi.util.get_remote_address)

inference_rate_limit = limiter.limit(_dynamic_limit)


def configure_rate_limit(rate_limit: str) -> None:
    """Set the rate limit string (called during application startup)."""
    global _configured_rate_limit  # noqa: PLW0603
    _configured_rate_limit = rate_limit


async def rate_limit_exceeded_handler(
    request: fastapi.Request,
    exc: slowapi.errors.RateLimitExceeded,
) -> fastapi.responses.JSONResponse:
    """Return a 429 JSON response consistent with the API error format."""
    correlation_id = getattr(request.state, "correlation_id", "unknown")
    return fastapi.responses.JSONResponse(
        status_code=429,
        content=application.models.ErrorResponse(
            error=application.models.ErrorDetail(
                code="rate_limit_exceeded",
                message=f"Rate limit exceeded: {exc.detail}",
                correlation_id=correlation_id,
            ),
        ).model_dump(),
    )
