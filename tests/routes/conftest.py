"""Shared fixtures for route integration tests."""

from unittest.mock import AsyncMock

import fastapi
import httpx
import pytest
import pytest_asyncio

import application.admission_control
import application.api.dependencies
import application.api.endpoints.health
import application.api.endpoints.image_generation
import application.api.endpoints.prompt_enhancement
import application.api.error_handlers
import application.api.middleware.content_type_validation
import application.api.middleware.correlation_identifier
import application.api.middleware.request_logging
import application.api.middleware.request_payload_size_limit
import application.api.middleware.request_timeout
import application.integrations.stable_diffusion_pipeline
import application.metrics
import application.services.image_generation_service
import application.services.prompt_enhancement_service


@pytest.fixture
def mock_of_llama_cpp_client():
    service = AsyncMock()
    service.enhance_prompt = AsyncMock(return_value="Enhanced prompt")
    service.check_health = AsyncMock(return_value=True)
    return service


@pytest.fixture
def mock_of_stable_diffusion_pipeline():
    """
    Create a mock Stable Diffusion pipeline that returns an
    ``ImageGenerationResult`` matching the pipeline interface.
    """
    mock_generation_result = application.integrations.stable_diffusion_pipeline.ImageGenerationResult(
        base64_encoded_images=["base64encodedimage"],
        indices_flagged_by_content_safety_checker=[],
    )

    service = AsyncMock()
    service.generate_images = AsyncMock(return_value=mock_generation_result)
    service.check_health = lambda: True
    return service


@pytest.fixture
def prompt_enhancement_service(mock_of_llama_cpp_client):
    """
    Create a real PromptEnhancementService wrapping the mock LlamaCppClient.

    This allows route-level integration tests to exercise the full
    service-to-integration path while keeping the external client mocked.
    """
    return application.services.prompt_enhancement_service.PromptEnhancementService(
        llama_cpp_client=mock_of_llama_cpp_client,
    )


@pytest.fixture
def image_generation_service(
    mock_of_stable_diffusion_pipeline,
    prompt_enhancement_service,
):
    """
    Create a real ImageGenerationService wrapping the mock pipeline and
    the real PromptEnhancementService (which itself wraps a mock client).

    This allows route-level integration tests to exercise the full
    endpoint-to-service-to-integration path while keeping external
    dependencies mocked.
    """
    return application.services.image_generation_service.ImageGenerationService(
        stable_diffusion_pipeline=mock_of_stable_diffusion_pipeline,
        prompt_enhancement_service=prompt_enhancement_service,
    )


@pytest.fixture
def admission_controller_for_image_generation():
    """
    Admission controller with a generous concurrency limit so that
    route-level tests are not blocked by admission control unless they
    explicitly test that behaviour.
    """
    return application.admission_control.AdmissionControllerForImageGeneration(
        maximum_number_of_concurrent_operations=100,
    )


@pytest.fixture
def test_application(
    prompt_enhancement_service,
    image_generation_service,
    admission_controller_for_image_generation,
):
    test_application = fastapi.FastAPI()
    application.api.error_handlers.register_error_handlers(test_application)

    metrics_collector = application.metrics.MetricsCollector()

    test_application.add_middleware(
        application.api.middleware.request_payload_size_limit.RequestPayloadSizeLimitMiddleware,
        maximum_number_of_bytes_of_request_payload=1_048_576,
    )

    test_application.add_middleware(
        application.api.middleware.content_type_validation.ContentTypeValidationMiddleware,
    )

    test_application.add_middleware(
        application.api.middleware.request_timeout.RequestTimeoutMiddleware,
        request_timeout_in_seconds=300.0,
    )

    test_application.add_middleware(
        application.api.middleware.request_logging.RequestLoggingMiddleware,
        metrics_collector=metrics_collector,
    )

    test_application.add_middleware(
        application.api.middleware.correlation_identifier.CorrelationIdMiddleware,
    )
    test_application.include_router(application.api.endpoints.prompt_enhancement.prompt_enhancement_router)
    test_application.include_router(application.api.endpoints.image_generation.image_generation_router)
    test_application.include_router(application.api.endpoints.health.health_router)

    test_application.dependency_overrides[application.api.dependencies.get_prompt_enhancement_service] = lambda: (
        prompt_enhancement_service
    )

    test_application.dependency_overrides[application.api.dependencies.get_image_generation_service] = lambda: (
        image_generation_service
    )

    test_application.dependency_overrides[
        application.api.dependencies.get_admission_controller_for_image_generation
    ] = lambda: admission_controller_for_image_generation

    test_application.state.prompt_enhancement_service = prompt_enhancement_service
    test_application.state.image_generation_service = image_generation_service
    test_application.state.admission_controller_for_image_generation = admission_controller_for_image_generation
    test_application.state.metrics_collector = metrics_collector
    test_application.state.retry_after_busy_in_seconds = 30
    test_application.state.retry_after_not_ready_in_seconds = 10

    return test_application


@pytest_asyncio.fixture
async def client(test_application):
    transport = httpx.ASGITransport(app=test_application)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_test_client:
        yield async_test_client
