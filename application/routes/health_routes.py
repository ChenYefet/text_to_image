"""
Route definitions for health, readiness, and metrics endpoints.

Provides a lightweight ``GET /health`` endpoint that downstream load
balancers and orchestrators can poll to verify service availability.
A detailed ``GET /health/ready`` endpoint checks backend connectivity.
A ``GET /metrics`` endpoint exposes request count and latency metrics.
"""

import typing

import fastapi

health_router = fastapi.APIRouter(tags=["Health"])


@health_router.get(
    "/health",
    summary="Liveness check",
    description="Returns a simple healthy status when the service is running.",
    status_code=200,
)
async def health_check() -> dict:
    return {"status": "healthy"}


@health_router.get(
    "/health/ready",
    summary="Readiness check",
    description=(
        "Checks that backend services (language model server and image "
        "generation pipeline) are initialised and reachable."
    ),
    status_code=200,
)
async def readiness_check(request: fastapi.Request) -> fastapi.responses.JSONResponse:
    checks: dict[str, str] = {}

    image_service = getattr(request.app.state, "image_generation_service", None)
    if image_service is not None:
        checks["image_generation"] = "ok"
    else:
        checks["image_generation"] = "unavailable"

    lm_service = getattr(request.app.state, "language_model_service", None)
    if lm_service is not None:
        checks["language_model"] = "ok"
    else:
        checks["language_model"] = "unavailable"

    all_ok = all(v == "ok" for v in checks.values())
    status_code = 200 if all_ok else 503

    return fastapi.responses.JSONResponse(
        content={"status": "ready" if all_ok else "not_ready", "checks": checks},
        status_code=status_code,
    )


@health_router.get(
    "/metrics",
    summary="Request metrics",
    description=("Returns request count and latency metrics in JSON format for operational monitoring (NFR11)."),
    status_code=200,
)
async def metrics(request: fastapi.Request) -> dict[str, typing.Any]:
    collector = getattr(request.app.state, "metrics_collector", None)
    if collector is None:
        return {"request_counts": {}, "request_latencies": {}}
    result: dict[str, typing.Any] = collector.snapshot()
    return result
