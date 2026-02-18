"""
Route definition for the health-check endpoint.

Provides a lightweight ``GET /health`` endpoint that downstream load
balancers and orchestrators can poll to verify service availability.
"""

import fastapi

health_router = fastapi.APIRouter(tags=["Health"])


@health_router.get(
    "/health",
    summary="Health check",
    description="Returns a simple healthy status when the service is running.",
    status_code=200,
)
async def health_check() -> dict:
    return {"status": "healthy"}
