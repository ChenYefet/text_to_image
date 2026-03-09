"""
Endpoint definitions for health, readiness, and metrics endpoints.

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

import datetime
import typing

import fastapi
import prometheus_client

import application.prometheus_metrics

health_router = fastapi.APIRouter(tags=["Health"])

# The response headers applied to all infrastructure endpoint responses.
# ``Cache-Control: no-store, no-cache`` prevents caches from storing any
# part of the response and requires revalidation before reuse.
# ``Pragma: no-cache`` provides backward-compatible cache suppression for
# HTTP/1.0 intermediaries (§12 of the v5.10.0 specification mandates both).
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
                        "additionalProperties": False,
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
        "Checks that backend services (large language model server and"
        " image generation pipeline) are initialised and reachable."
        " Returns HTTP 200 with status ``degraded`` when the large"
        " language model is unavailable but image generation is healthy."
        " Returns HTTP 503 with a Retry-After header when image"
        " generation is unavailable."
    ),
    status_code=200,
    responses={
        200: {
            "description": (
                "Image generation is available. The service is either fully"
                " ready or degraded (large language model unavailable)."
            ),
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "status": {"type": "string", "enum": ["ready", "degraded"]},
                            "checks": {
                                "type": "object",
                                "properties": {
                                    "large_language_model": {"type": "string", "enum": ["ok", "unavailable"]},
                                    "image_generation": {"type": "string", "enum": ["ok"]},
                                },
                                "required": ["large_language_model", "image_generation"],
                                "additionalProperties": False,
                            },
                        },
                        "required": ["status", "checks"],
                        "additionalProperties": False,
                    },
                    "examples": {
                        "ready": {
                            "summary": "Fully ready",
                            "value": {
                                "status": "ready",
                                "checks": {"large_language_model": "ok", "image_generation": "ok"},
                            },
                        },
                        "degraded": {
                            "summary": "Degraded — large language model unavailable",
                            "value": {
                                "status": "degraded",
                                "checks": {"large_language_model": "unavailable", "image_generation": "ok"},
                            },
                        },
                    },
                },
            },
        },
        503: {
            "description": (
                "Service Unavailable — one or more backend services are"
                " unhealthy. The ``Retry-After`` header indicates how"
                " long to wait before retrying."
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
                                    "large_language_model": {
                                        "type": "string",
                                        "enum": ["ok", "unavailable"],
                                    },
                                    "image_generation": {
                                        "type": "string",
                                        "enum": ["ok", "unavailable"],
                                    },
                                },
                                "required": ["large_language_model", "image_generation"],
                                "additionalProperties": False,
                            },
                        },
                        "required": ["status", "checks"],
                        "additionalProperties": False,
                    },
                    "example": {
                        "status": "not_ready",
                        "checks": {"large_language_model": "ok", "image_generation": "unavailable"},
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
    a ``checks`` dictionary.  If image generation is unavailable, the
    overall status is ``"not_ready"`` with HTTP 503.  If only the large
    language model is unavailable, the status is ``"degraded"`` with
    HTTP 200.

    The readiness probe checks:
        - **image_generation**: Whether the Stable Diffusion pipeline
          was loaded successfully during startup (synchronous check).
        - **large_language_model**: Whether the llama.cpp server responds to
          ``GET /health`` with HTTP 200 (asynchronous network call with
          a 5-second timeout).

    When any backend is unavailable, the response includes an HTTP 503
    status code and a ``Retry-After`` header (NFR47) populated from the
    operator-configured ``retry_after_not_ready_in_seconds`` value.  This
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

    # Update the Prometheus healthy instances gauge, piggybacking on the
    # readiness probe to avoid a separate code path.
    stable_diffusion_pipeline_pool = getattr(
        request.app.state,
        "stable_diffusion_pipeline_pool",
        None,
    )
    if stable_diffusion_pipeline_pool is not None:
        application.prometheus_metrics.gauge_of_number_of_healthy_instances_in_pipeline_pool_of_stable_diffusion.set(
            stable_diffusion_pipeline_pool.count_healthy_instances(),
        )

    # ── Language model backend check ──────────────────────────────────
    #
    # The prompt enhancement service delegates to the llama.cpp client,
    # which sends an HTTP GET request to the llama.cpp server's /health
    # endpoint.  Any exception (connection refused, timeout, HTTP error)
    # is caught and treated as unhealthy to prevent a failing upstream
    # from crashing the readiness probe.
    prompt_enhancement_service = getattr(request.app.state, "prompt_enhancement_service", None)
    if prompt_enhancement_service is not None:
        try:
            large_language_model_is_healthy = await prompt_enhancement_service.check_health()
        except Exception:
            large_language_model_is_healthy = False
        checks["large_language_model"] = "ok" if large_language_model_is_healthy else "unavailable"
    else:
        checks["large_language_model"] = "unavailable"

    # ── Aggregate results ─────────────────────────────────────────────
    image_generation_is_available = checks["image_generation"] == "ok"
    large_language_model_is_available = checks["large_language_model"] == "ok"

    if image_generation_is_available and large_language_model_is_available:
        readiness_status = "ready"
        status_code = 200
    elif image_generation_is_available:
        readiness_status = "degraded"
        status_code = 200
    else:
        readiness_status = "not_ready"
        status_code = 503

    response_headers: dict[str, str] = dict(_INFRASTRUCTURE_CACHE_SUPPRESSION_HEADERS)

    if status_code == 503:
        retry_after_not_ready_in_seconds = getattr(request.app.state, "retry_after_not_ready_in_seconds", 10)
        response_headers["Retry-After"] = str(retry_after_not_ready_in_seconds)

    return fastapi.responses.JSONResponse(
        content={
            "status": readiness_status,
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
                                    "Map of 'METHOD /path STATUS_CODE' keys to the"
                                    " number of times that combination was observed."
                                ),
                                "additionalProperties": {"type": "integer"},
                            },
                            "request_latencies": {
                                "type": "object",
                                "description": (
                                    "Map of 'METHOD /path' keys to latency statistics"
                                    " (number_of_observations, minimum_latency_in_milliseconds,"
                                    " maximum_latency_in_milliseconds,"
                                    " average_latency_in_milliseconds,"
                                    " ninety_fifth_percentile_latency_in_milliseconds)."
                                ),
                                "additionalProperties": {
                                    "type": "object",
                                    "properties": {
                                        "number_of_observations": {"type": "integer"},
                                        "minimum_latency_in_milliseconds": {"type": "number"},
                                        "maximum_latency_in_milliseconds": {"type": "number"},
                                        "average_latency_in_milliseconds": {"type": "number"},
                                        "ninety_fifth_percentile_latency_in_milliseconds": {"type": "number"},
                                    },
                                    "required": [
                                        "number_of_observations",
                                        "minimum_latency_in_milliseconds",
                                        "maximum_latency_in_milliseconds",
                                        "average_latency_in_milliseconds",
                                        "ninety_fifth_percentile_latency_in_milliseconds",
                                    ],
                                    "additionalProperties": False,
                                },
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
                        "required": ["collected_at", "service_started_at", "request_counts", "request_latencies"],
                        "additionalProperties": False,
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
    v5.10.0 specification (FR38, NFR12):

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
            "collected_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "service_started_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "request_counts": {},
            "request_latencies": {},
        }
    else:
        content = metrics_collector.snapshot()

    return fastapi.responses.JSONResponse(
        content=content,
        headers=_INFRASTRUCTURE_CACHE_SUPPRESSION_HEADERS,
    )


@health_router.get(
    "/metrics/prometheus",
    summary="Prometheus metrics",
    description=(
        "Returns request count and latency metrics in Prometheus text"
        " exposition format for scraping by Prometheus-compatible monitoring systems."
    ),
    status_code=200,
    responses={
        200: {
            "description": "Prometheus text exposition format metrics.",
            "content": {
                "text/plain; version=0.0.4; charset=utf-8": {
                    "schema": {"type": "string"},
                },
            },
        },
    },
)
async def get_metrics_in_prometheus_format() -> fastapi.responses.Response:
    """
    Return request count and latency metrics in Prometheus text exposition format.

    Uses a custom ``CollectorRegistry`` that contains only the application-defined
    instruments (HTTP request counter and duration histogram), excluding the
    default Python process metrics.
    """
    metrics_output = prometheus_client.generate_latest(
        application.prometheus_metrics.registry_for_prometheus_metrics,
    )
    return fastapi.responses.Response(
        content=metrics_output,
        media_type="text/plain; version=0.0.4; charset=utf-8",
        headers=_INFRASTRUCTURE_CACHE_SUPPRESSION_HEADERS,
    )
