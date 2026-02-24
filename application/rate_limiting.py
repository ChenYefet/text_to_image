"""
Rate limiting configuration for inference-heavy endpoints.

Uses slowapi (backed by the ``limits`` library) to throttle requests per
client IP address.  The rate limit is configurable via the
``TEXT_TO_IMAGE_RATE_LIMIT`` environment variable (default: ``10/minute``).

Deferred-evaluation pattern
---------------------------
The ``slowapi.Limiter.limit()`` decorator must be applied to route handler
functions at import time — before the application configuration has been
read.  However, the actual rate limit value (e.g. ``"10/minute"`` or
``"100/hour"``) is not known until the application factory reads it from
environment variables during startup.

To bridge this timing gap, the rate limit value is held in an
``InferenceRateLimitConfiguration`` instance — a callable object whose
``__call__`` method returns the currently configured rate limit string.
This callable is passed to ``slowapi.Limiter.limit()`` at import time;
slowapi invokes it on every incoming request to resolve the applicable
limit.  The actual value is set once during application startup via the
``configure()`` method, before any requests are processed.

This encapsulation replaces a bare module-level mutable variable and
``global`` statement, providing:

1. Explicit lifecycle semantics (construct → configure → read) rather
   than implicit temporal ordering of module-level mutation.
2. Elimination of the ``global`` keyword, which static analysis tools
   (ruff PLW0603) flag as a code quality concern.
3. A callable with a clear single responsibility, making the deferred-
   evaluation pattern self-documenting.

Distinction from admission control
-----------------------------------
Rate limiting and admission control are complementary but independent
mechanisms:

- **Rate limiting** (this module) restricts the *frequency* of requests
  from a *single* client IP address.  When exceeded, the client receives
  HTTP 429 with error code ``rate_limit_exceeded`` and a ``Retry-After``
  header set to ``retry_after_rate_limit_seconds``.

- **Admission control** (``admission_control.py``) limits the *total*
  number of concurrent image generation operations across *all* clients.
  When exceeded, the client receives HTTP 429 with error code
  ``service_busy`` and a ``Retry-After`` header set to
  ``retry_after_busy_seconds``.

The ``Retry-After`` values for these two mechanisms are configured
independently because they convey different operational signals: rate
limiting indicates per-client throttling (longer backoff), whilst
admission control indicates global capacity saturation (shorter backoff).

Module-level singleton note
---------------------------
The ``InferenceRateLimitConfiguration`` instance, the ``slowapi.Limiter``
instance, and the ``inference_rate_limit`` decorator are all created at
module level because slowapi's decorator-based architecture requires them
to be available when route handler modules are imported.  If multiple
FastAPI application instances are created within the same Python process
(for example, during parallel test execution), they will share these
module-level objects.  Test fixtures should call ``configure()`` and
``rate_limiter.reset()`` to reset state between tests.
"""

import fastapi
import fastapi.responses
import slowapi
import slowapi.errors
import slowapi.util

import application.models


class InferenceRateLimitConfiguration:
    """
    Encapsulates the mutable rate limit string for inference endpoints.

    This class implements the ``__call__`` protocol so that an instance
    can be passed directly to ``slowapi.Limiter.limit()`` as the dynamic
    limit callable.  On every incoming request, slowapi invokes this
    callable to determine the applicable rate limit.

    Lifecycle
    ---------
    1. **Construction** (module import time): created with a sensible
       default value (``"10/minute"``).
    2. **Configuration** (application startup): the ``configure()`` method
       is called exactly once with the operator-supplied rate limit string
       read from the ``TEXT_TO_IMAGE_RATE_LIMIT`` environment variable.
    3. **Read** (every incoming request): slowapi invokes ``__call__()``
       to retrieve the current rate limit string.

    The value is written exactly once during step 2 and read (but never
    mutated) during step 3.  This write-once-read-many pattern is safe
    for single-threaded async applications.
    """

    def __init__(self, default_rate_limit: str = "10/minute") -> None:
        """
        Initialise the configuration holder with a default rate limit.

        Args:
            default_rate_limit: The rate limit string to use until
                ``configure()`` is called.  Follows the ``limits`` library
                format: ``"count/period"`` where ``period`` is one of
                ``second``, ``minute``, ``hour``, or ``day``.
        """
        self._rate_limit_string: str = default_rate_limit

    def configure(self, rate_limit_string: str) -> None:
        """
        Set the rate limit string for inference endpoints.

        This method must be called exactly once during application startup
        (in ``server_factory.create_application()``) before any requests
        are processed.

        Args:
            rate_limit_string: A rate limit specification in the ``limits``
                library format, for example ``"10/minute"`` or
                ``"100/hour"``.
        """
        self._rate_limit_string = rate_limit_string

    def __call__(self) -> str:
        """
        Return the currently configured rate limit string.

        This method is invoked by the ``slowapi.Limiter`` on every
        incoming request to determine the applicable rate limit.

        Returns:
            The rate limit string in ``"count/period"`` format.
        """
        return self._rate_limit_string


# ──────────────────────────────────────────────────────────────────────────────
#  Module-level singleton instances
# ──────────────────────────────────────────────────────────────────────────────
#
# These objects are created at module import time and shared across all
# application instances within the same Python process.  The
# ``inference_rate_limit_configuration`` instance holds the mutable rate
# limit value; the ``rate_limiter`` is the slowapi Limiter that enforces
# it; and ``inference_rate_limit`` is the decorator applied to inference
# route handlers.

inference_rate_limit_configuration = InferenceRateLimitConfiguration()

rate_limiter = slowapi.Limiter(key_func=slowapi.util.get_remote_address)

inference_rate_limit = rate_limiter.limit(inference_rate_limit_configuration)


async def rate_limit_exceeded_handler(
    request: fastapi.Request,
    rate_limit_exceeded_exception: slowapi.errors.RateLimitExceeded,
) -> fastapi.responses.JSONResponse:
    """
    Return a structured HTTP 429 JSON response when the per-IP rate limit
    is exceeded.

    The ``Retry-After`` response header is populated from the operator-
    configured ``retry_after_rate_limit_seconds`` value stored on
    ``app.state`` during application startup.  This value is intentionally
    distinct from the admission-control ``retry_after_busy_seconds`` value
    because the two 429 variants convey different operational signals to
    the client:

    - ``rate_limit_exceeded``: the client is sending requests too
      frequently (per-IP throttling) — typically requires a longer
      backoff period.
    - ``service_busy``: the service is at GPU/CPU capacity (global
      saturation) — typically requires a shorter backoff period.
    """
    correlation_id = getattr(request.state, "correlation_id", "unknown")

    # Retrieve the dedicated rate-limit Retry-After value.  Falls back
    # to 60 seconds if the value was not set on app.state during startup
    # (defensive default for test environments).
    retry_after_seconds = getattr(request.app.state, "retry_after_rate_limit_seconds", 60)

    response = fastapi.responses.JSONResponse(
        status_code=429,
        content=application.models.ErrorResponse(
            error=application.models.ErrorDetail(
                code="rate_limit_exceeded",
                message=f"Rate limit exceeded: {rate_limit_exceeded_exception.detail}",
                correlation_id=correlation_id,
            ),
        ).model_dump(exclude_unset=True),
    )
    response.headers["Retry-After"] = str(retry_after_seconds)
    return response
