"""Shared fixtures for route integration tests."""

from unittest.mock import AsyncMock

import fastapi
import httpx
import pytest
import pytest_asyncio
import slowapi.errors

import application.admission_control
import application.dependencies
import application.error_handling
import application.metrics
import application.middleware
import application.rate_limiting
import application.routes.health_routes
import application.routes.image_generation_routes
import application.routes.prompt_enhancement_routes
import application.services.image_generation_service


@pytest.fixture
def mock_language_model_service():
    service = AsyncMock()
    service.enhance_prompt = AsyncMock(return_value="Enhanced prompt")
    service.check_health = AsyncMock(return_value=True)
    return service


@pytest.fixture
def mock_image_generation_service():
    """
    Create a mock image generation service that returns an
    ``ImageGenerationResult`` matching the updated service interface.
    """
    mock_generation_result = application.services.image_generation_service.ImageGenerationResult(
        base64_encoded_images=["base64encodedimage"],
        content_safety_flagged_indices=[],
    )

    service = AsyncMock()
    service.generate_images = AsyncMock(return_value=mock_generation_result)
    service.check_health = lambda: True
    return service


@pytest.fixture
def image_generation_admission_controller():
    """
    Admission controller with a generous concurrency limit so that
    route-level tests are not blocked by admission control unless they
    explicitly test that behaviour.
    """
    return application.admission_control.ImageGenerationAdmissionController(
        maximum_concurrency=100,
    )


@pytest.fixture
def test_app(
    mock_language_model_service,
    mock_image_generation_service,
    image_generation_admission_controller,
):
    app = fastapi.FastAPI()
    application.error_handling.register_error_handlers(app)

    metrics_collector = application.metrics.MetricsCollector()

    app.add_middleware(
        application.middleware.RequestPayloadSizeLimitMiddleware,
        maximum_request_payload_bytes=1_048_576,
    )

    app.add_middleware(
        application.middleware.ContentTypeValidationMiddleware,
    )

    app.add_middleware(
        application.middleware.RequestTimeoutMiddleware,
        request_timeout_seconds=300.0,
    )

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

    app.dependency_overrides[application.dependencies.get_image_generation_admission_controller] = lambda: (
        image_generation_admission_controller
    )

    app.state.limiter = application.rate_limiting.rate_limiter
    application.rate_limiting.inference_rate_limit_configuration.configure("1000/minute")
    app.add_exception_handler(
        slowapi.errors.RateLimitExceeded,
        application.rate_limiting.rate_limit_exceeded_handler,
    )

    app.state.language_model_service = mock_language_model_service
    app.state.image_generation_service = mock_image_generation_service
    app.state.image_generation_admission_controller = image_generation_admission_controller
    app.state.metrics_collector = metrics_collector
    app.state.retry_after_busy_seconds = 30
    app.state.retry_after_rate_limit_seconds = 60
    app.state.retry_after_not_ready_seconds = 10

    return app


@pytest_asyncio.fixture
async def client(test_app):
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
