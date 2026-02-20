"""Shared fixtures for route integration tests."""

from unittest.mock import AsyncMock

import fastapi
import httpx
import pytest
import pytest_asyncio
import slowapi.errors

import application.dependencies
import application.error_handling
import application.metrics
import application.middleware
import application.rate_limiting
import application.routes.health_routes
import application.routes.image_generation_routes
import application.routes.prompt_enhancement_routes


@pytest.fixture
def mock_language_model_service():
    service = AsyncMock()
    service.enhance_prompt = AsyncMock(return_value="Enhanced prompt")
    return service


@pytest.fixture
def mock_image_generation_service():
    service = AsyncMock()
    service.generate_images = AsyncMock(return_value=["base64encodedimage"])
    return service


@pytest.fixture
def test_app(mock_language_model_service, mock_image_generation_service):
    app = fastapi.FastAPI()
    application.error_handling.register_error_handlers(app)

    metrics_collector = application.metrics.MetricsCollector()

    app.add_middleware(
        application.middleware.CorrelationIdMiddleware,
        metrics_collector=metrics_collector,
    )
    app.include_router(application.routes.prompt_enhancement_routes.prompt_enhancement_router)
    app.include_router(application.routes.image_generation_routes.image_generation_router)
    app.include_router(application.routes.health_routes.health_router)

    app.dependency_overrides[application.dependencies.get_language_model_service] = lambda: mock_language_model_service

    app.dependency_overrides[application.dependencies.get_image_generation_service] = lambda: (
        mock_image_generation_service
    )

    app.state.limiter = application.rate_limiting.limiter
    application.rate_limiting.configure_rate_limit("1000/minute")
    app.add_exception_handler(
        slowapi.errors.RateLimitExceeded,
        application.rate_limiting.rate_limit_exceeded_handler,
    )

    app.state.language_model_service = mock_language_model_service
    app.state.image_generation_service = mock_image_generation_service
    app.state.metrics_collector = metrics_collector

    return app


@pytest_asyncio.fixture
async def client(test_app):
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
