"""
Route definitions for health, readiness, and metrics endpoints.

Provides three infrastructure endpoints for operational monitoring:

- ``GET /health`` — A lightweight liveness probe that returns HTTP 200
  whenever the service process is running.  Used by load balancers and
  orchestrators to detect process crashes.

- ``GET /health/ready`` — A detailed readiness probe that checks the
  initialisation status of both backend services (llama.cpp language
  model server and Stable Diffusion image generation pipeline).  Returns
  HTTP 200 when all backends are healthy, or HTTP 503 with a
  ``Retry-After`` header when any backend is unavailable.

- ``GET /metrics`` — Exposes request count and latency metrics in JSON
  format for operational monitoring dashboards.

Cache suppression policy
-----------------------
All infrastructure endpoints include ``Cache-Control: no-store, no-cache``
and ``Pragma: no-cache`` response headers to prevent intermediate proxies
and CDNs from caching operational data.  The ``Pragma: no-cache`` directive
provides backward-compatible cache suppression for HTTP/1.0 intermediaries.
Health status, readiness, and metrics change on every poll; stale cached
values would mislead orchestrators and monitoring dashboards.
"""

import typing

import fastapi

health_router = fastapi.APIRouter(tags=["Health"])

# The response headers applied to all infrastructure endpoint responses.
# ``Cache-Control: no-store, no-cache`` prevents caches from storing any
# part of the response and requires revalidation before reuse.
# ``Pragma: no-cache`` provides backward-compatible cache suppression for
# HTTP/1.0 intermediaries (§12 of the v5.0.0 specification mandates both).
# Together they ensure that every request receives fresh operational data.
_INFRASTRUCTURE_CACHE_SUPPRESSION_HEADERS: dict[str, str] = {
    "Cache-Control": "no-store, no-cache",
    "Pragma": "no-cache",
}


@health_router.get(
    "/health",
    summary="Liveness check",
    description="Returns a simple healthy status when the service is running.",
    status_code=200,
    responses={
        200: {
            "description": "The service process is running and accepting requests.",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "status": {
                                "type": "string",
                                "enum": ["healthy"],
                                "description": "Always ``healthy`` when the process is alive.",
                            },
                        },
                        "required": ["status"],
                    },
                    "example": {"status": "healthy"},
                },
            },
        },
    },
)
async def health_check() -> fastapi.responses.JSONResponse:
    """
    Return a simple healthy status when the service process is running.

    This endpoint does not check backend connectivity — that is the
    responsibility of the readiness endpoint (``GET /health/ready``).
    Load balancers should use this endpoint for liveness probing only.
    """
    return fastapi.responses.JSONResponse(
        content={"status": "healthy"},
        headers=_INFRASTRUCTURE_CACHE_SUPPRESSION_HEADERS,
    )


@health_router.get(
    "/health/ready",
    summary="Readiness check",
    description=(
        "Checks that backend services (language model server and image "
        "generation pipeline) are initialised and reachable. Returns "
        "HTTP 503 with a Retry-After header when any backend is unavailable."
    ),
    status_code=200,
    responses={
        200: {
            "description": "All backend services are healthy and ready to accept requests.",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "status": {"type": "string", "enum": ["ready"]},
                            "checks": {
                                "type": "object",
                                "properties": {
                                    "language_model": {"type": "string", "enum": ["ok"]},
                                    "image_generation": {"type": "string", "enum": ["ok"]},
                                },
                                "required": ["language_model", "image_generation"],
                            },
                        },
                        "required": ["status", "checks"],
                    },
                    "example": {
                        "status": "ready",
                        "checks": {"language_model": "ok", "image_generation": "ok"},
                    },
                },
            },
        },
        503: {
            "description": (
                "Service Unavailable — one or more backend services are "
                "unhealthy. The ``Retry-After`` header indicates how long "
                "to wait before retrying."
            ),
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "status": {"type": "string", "enum": ["not_ready"]},
                            "checks": {
                                "type": "object",
                                "properties": {
                                    "language_model": {
                                        "type": "string",
                                        "enum": ["ok", "unavailable"],
                                    },
                                    "image_generation": {
                                        "type": "string",
                                        "enum": ["ok", "unavailable"],
                                    },
                                },
                                "required": ["language_model", "image_generation"],
                            },
                        },
                        "required": ["status", "checks"],
                    },
                    "example": {
                        "status": "not_ready",
                        "checks": {"language_model": "ok", "image_generation": "unavailable"},
                    },
                },
            },
            "headers": {
                "Retry-After": {
                    "description": ("Number of seconds the client should wait before retrying the readiness check."),
                    "schema": {"type": "integer"},
                },
            },
        },
    },
)
async def readiness_check(request: fastapi.Request) -> fastapi.responses.JSONResponse:
    """
    Check the initialisation status of all backend services.

    Queries each backend independently and aggregates the results into
    a ``checks`` dictionary.  If any backend reports as unavailable, the
    overall status is ``"not_ready"`` with HTTP 503.

    The readiness probe checks:
        - **image_generation**: Whether the Stable Diffusion pipeline
          was loaded successfully during startup (synchronous check).
        - **language_model**: Whether the llama.cpp server responds to
          ``GET /health`` with HTTP 200 (asynchronous network call with
          a 5-second timeout).

    When any backend is unavailable, the response includes an HTTP 503
    status code and a ``Retry-After`` header (NFR47) populated from the
    operator-configured ``retry_after_not_ready_seconds`` value.  This
    header tells orchestrators and clients how long to wait before
    retrying the readiness check.
    """
    checks: dict[str, str] = {}

    # ── Image generation backend check ────────────────────────────────
    #
    # The image generation service may be ``None`` if the Stable Diffusion
    # model failed to load during startup (FR49 degraded state).  In that
    # case, the check reports "unavailable".
    image_generation_service = getattr(request.app.state, "image_generation_service", None)
    if image_generation_service is not None and image_generation_service.check_health():
        checks["image_generation"] = "ok"
    else:
        checks["image_generation"] = "unavailable"

    # ── Language model backend check ──────────────────────────────────
    #
    # The language model service sends an HTTP GET request to the
    # llama.cpp server's /health endpoint.  Any exception (connection
    # refused, timeout, HTTP error) is caught and treated as unhealthy
    # to prevent a failing upstream from crashing the readiness probe.
    language_model_service = getattr(request.app.state, "language_model_service", None)
    if language_model_service is not None:
        try:
            language_model_is_healthy = await language_model_service.check_health()
        except Exception:
            language_model_is_healthy = False
        checks["language_model"] = "ok" if language_model_is_healthy else "unavailable"
    else:
        checks["language_model"] = "unavailable"

    # ── Aggregate results ─────────────────────────────────────────────
    all_backends_are_healthy = all(check_status == "ok" for check_status in checks.values())
    status_code = 200 if all_backends_are_healthy else 503

    response_headers: dict[str, str] = dict(_INFRASTRUCTURE_CACHE_SUPPRESSION_HEADERS)

    if not all_backends_are_healthy:
        retry_after_not_ready_seconds = getattr(request.app.state, "retry_after_not_ready_seconds", 10)
        response_headers["Retry-After"] = str(retry_after_not_ready_seconds)

    return fastapi.responses.JSONResponse(
        content={
            "status": "ready" if all_backends_are_healthy else "not_ready",
            "checks": checks,
        },
        status_code=status_code,
        headers=response_headers,
    )


@health_router.get(
    "/metrics",
    summary="Request metrics",
    description=("Returns request count and latency metrics in JSON format for operational monitoring (NFR11)."),
    status_code=200,
    responses={
        200: {
            "description": "A point-in-time snapshot of request count and latency metrics.",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "request_counts": {
                                "type": "object",
                                "description": (
                                    "Map of 'METHOD /path STATUS_CODE' keys to "
                                    "the number of times that combination was observed."
                                ),
                                "additionalProperties": {"type": "integer"},
                            },
                            "request_latencies": {
                                "type": "object",
                                "description": (
                                    "Map of 'METHOD /path' keys to latency statistics (count, minimum_milliseconds, maximum_milliseconds, average_milliseconds, ninety_fifth_percentile_milliseconds)."
                                ),
                                "additionalProperties": {"type": "object"},
                            },
                            "collected_at": {
                                "type": "string",
                                "format": "date-time",
                                "description": "ISO 8601 UTC timestamp of when the snapshot was generated.",
                            },
                            "service_started_at": {
                                "type": "string",
                                "format": "date-time",
                                "description": "ISO 8601 UTC timestamp of when the service process started.",
                            },
                        },
                        "required": ["request_counts", "request_latencies"],
                    },
                },
            },
        },
    },
)
async def get_metrics(request: fastapi.Request) -> fastapi.responses.JSONResponse:
    """
    Return a point-in-time snapshot of request count and latency metrics.

    The response includes two temporal metadata fields required by the
    v5.0.0 specification (FR38, NFR12):

    - ``collected_at``: ISO 8601 UTC timestamp of when the snapshot was
      generated.
    - ``service_started_at``: ISO 8601 UTC timestamp of when the service
      process started.

    When the metrics collector is not available (which should not happen
    in normal operation), a minimal fallback response with empty counts
    and latencies is returned.
    """
    metrics_collector = getattr(request.app.state, "metrics_collector", None)
    if metrics_collector is None:
        content: dict[str, typing.Any] = {
            "request_counts": {},
            "request_latencies": {},
        }
    else:
        content = metrics_collector.snapshot()

    return fastapi.responses.JSONResponse(
        content=content,
        headers=_INFRASTRUCTURE_CACHE_SUPPRESSION_HEADERS,
    )
