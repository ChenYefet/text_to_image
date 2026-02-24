"""
Integration tests for the server factory and full request flows.

These tests exercise ``create_application()`` with mocked ML backends and
send real HTTP requests through the entire middleware → routing → dependency
injection → service → error handling → response pipeline.

The lifespan context manager is invoked manually via
``app.router.lifespan_context`` because ``httpx.ASGITransport`` does not
send ASGI lifespan events.  The service patches must remain active for the
duration of the lifespan because the lifespan closure references
module-level class names at runtime.
"""

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

import application.exceptions
import application.server_factory
import application.services.image_generation_service
import application.services.language_model_service


def _build_mock_image_generation_service():
    """
    Create a mock ImageGenerationService that returns an
    ``ImageGenerationResult`` matching the updated service interface.
    """
    mock_generation_result = application.services.image_generation_service.ImageGenerationResult(
        base64_encoded_images=["base64encodedimage"],
        content_safety_flagged_indices=[],
    )

    service = MagicMock(
        spec=application.services.image_generation_service.ImageGenerationService,
    )
    service.generate_images = AsyncMock(return_value=mock_generation_result)
    service.check_health.return_value = True
    service.close = AsyncMock()
    return service


def _build_mock_language_model_service():
    """Create a mock LanguageModelService that behaves like the real one."""
    service = MagicMock(
        spec=application.services.language_model_service.LanguageModelService,
    )
    service.enhance_prompt = AsyncMock(return_value="Enhanced prompt text")
    service.check_health = AsyncMock(return_value=True)
    service.close = AsyncMock()
    return service


def _apply_default_configuration_attributes(mock_configuration_instance):
    """
    Populate a mock configuration instance with all required attribute
    values so that ``create_application()`` does not encounter
    ``MagicMock`` objects where it expects concrete values.
    """
    mock_configuration_instance.application_host = "127.0.0.1"
    mock_configuration_instance.application_port = 8000
    mock_configuration_instance.cors_allowed_origins = []
    mock_configuration_instance.log_level = "INFO"
    mock_configuration_instance.rate_limit = "1000/minute"
    mock_configuration_instance.language_model_server_base_url = "http://localhost:8080"
    mock_configuration_instance.timeout_for_language_model_requests_in_seconds = 120.0
    mock_configuration_instance.language_model_temperature = 0.7
    mock_configuration_instance.language_model_maximum_tokens = 512
    mock_configuration_instance.language_model_system_prompt = "You are an expert at enhancing text-to-image prompts."
    mock_configuration_instance.language_model_connection_pool_size = 10
    mock_configuration_instance.language_model_maximum_response_bytes = 1_048_576
    mock_configuration_instance.stable_diffusion_model_id = "test-model"
    mock_configuration_instance.stable_diffusion_model_revision = "main"
    mock_configuration_instance.stable_diffusion_device = "cpu"
    mock_configuration_instance.stable_diffusion_safety_checker = True
    mock_configuration_instance.stable_diffusion_inference_steps = 20
    mock_configuration_instance.stable_diffusion_guidance_scale = 7.0
    mock_configuration_instance.stable_diffusion_inference_timeout_per_unit_seconds = 60.0
    mock_configuration_instance.image_generation_maximum_concurrency = 1
    mock_configuration_instance.retry_after_busy_seconds = 30
    mock_configuration_instance.retry_after_rate_limit_seconds = 60
    mock_configuration_instance.retry_after_not_ready_seconds = 10
    mock_configuration_instance.maximum_request_payload_bytes = 1_048_576
    mock_configuration_instance.timeout_for_requests_in_seconds = 300.0


@contextlib.contextmanager
def _patched_services(mock_language_model_service, mock_image_generation_service):
    """Patch both ML service constructors for the duration of the block."""
    with (
        patch.object(
            application.services.language_model_service,
            "LanguageModelService",
            return_value=mock_language_model_service,
        ),
        patch.object(
            application.services.image_generation_service.ImageGenerationService,
            "load_pipeline",
            return_value=mock_image_generation_service,
        ),
    ):
        yield


@pytest.fixture
def mock_language_model_service():
    return _build_mock_language_model_service()


@pytest.fixture
def mock_image_generation_service():
    return _build_mock_image_generation_service()


@pytest_asyncio.fixture
async def integration_client(mock_language_model_service, mock_image_generation_service):
    """
    Create a real FastAPI app via ``create_application()`` with mocked ML
    backends, invoke the lifespan, and yield an async HTTP client.

    Patches remain active for the full lifespan because the lifespan
    closure references module-level names at runtime.
    """
    with _patched_services(mock_language_model_service, mock_image_generation_service):
        app = application.server_factory.create_application()
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                yield client


@pytest_asyncio.fixture
async def cors_client(mock_language_model_service, mock_image_generation_service):
    """
    Create a real app with CORS enabled and yield an async HTTP client.
    """
    with (
        patch("configuration.ApplicationConfiguration") as mock_config_cls,
        _patched_services(mock_language_model_service, mock_image_generation_service),
    ):
        configuration_instance = mock_config_cls.return_value
        _apply_default_configuration_attributes(configuration_instance)
        configuration_instance.cors_allowed_origins = ["http://localhost:3000"]

        app = application.server_factory.create_application()
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                yield client


# ─── Server Factory ──────────────────────────────────────────────────────────


class TestServerFactory:
    @pytest.mark.asyncio
    async def test_create_application_returns_working_app(self, integration_client):
        response = await integration_client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    @pytest.mark.asyncio
    async def test_openapi_schema_available(self, integration_client):
        response = await integration_client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert schema["info"]["title"] == "Text-to-Image with Prompt Assist"

    @pytest.mark.asyncio
    async def test_services_registered_on_app_state(self, integration_client):
        response = await integration_client.get("/health/ready")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert body["checks"]["language_model"] == "ok"
        assert body["checks"]["image_generation"] == "ok"


# ─── Lifespan ────────────────────────────────────────────────────────────────


class TestLifespan:
    @pytest.mark.asyncio
    async def test_services_initialised_on_startup(self, mock_language_model_service, mock_image_generation_service):
        """Services must be set on app.state after lifespan startup."""
        with _patched_services(mock_language_model_service, mock_image_generation_service):
            app = application.server_factory.create_application()
            async with app.router.lifespan_context(app):
                assert app.state.language_model_service is mock_language_model_service
                assert app.state.image_generation_service is mock_image_generation_service

    @pytest.mark.asyncio
    async def test_services_closed_on_shutdown(self, mock_language_model_service, mock_image_generation_service):
        """Services must be closed when the lifespan exits."""
        with _patched_services(mock_language_model_service, mock_image_generation_service):
            app = application.server_factory.create_application()
            async with app.router.lifespan_context(app):
                pass  # startup runs

        # After exiting, shutdown should have run
        mock_language_model_service.close.assert_awaited_once()
        mock_image_generation_service.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_metrics_collector_on_app_state(self, mock_language_model_service, mock_image_generation_service):
        """The metrics collector must be set on app.state."""
        with _patched_services(mock_language_model_service, mock_image_generation_service):
            app = application.server_factory.create_application()
            async with app.router.lifespan_context(app):
                assert hasattr(app.state, "metrics_collector")
                assert app.state.metrics_collector is not None


# ─── FR49 — Startup Model Validation (Degraded State) ────────────────────────


class TestStartupModelValidation:
    """
    Verify FR49: when the Stable Diffusion model fails to load during
    startup, the service must continue running in a degraded state rather
    than crashing.

    In the degraded state:
    - The liveness probe (GET /health) returns HTTP 200 because the
      process is alive.
    - The readiness probe (GET /health/ready) returns HTTP 503 with
      checks.image_generation reporting "unavailable".
    - Image generation requests return HTTP 502 with the
      ``model_unavailable`` error code.
    - Prompt enhancement requests (which do not require the image
      generation pipeline) continue to function normally.
    """

    @pytest_asyncio.fixture
    async def degraded_client(self, mock_language_model_service):
        """
        Create a FastAPI application where the Stable Diffusion model
        failed to load during startup, simulating the degraded state
        described in FR49.

        The ``load_pipeline`` class method is patched to raise an
        ``OSError`` (the typical exception when model files are missing
        or inaccessible), causing the lifespan to store ``None`` for the
        image generation service.
        """
        with (
            patch.object(
                application.services.language_model_service,
                "LanguageModelService",
                return_value=mock_language_model_service,
            ),
            patch.object(
                application.services.image_generation_service.ImageGenerationService,
                "load_pipeline",
                side_effect=OSError("Model file not found: /models/stable-diffusion"),
            ),
        ):
            fastapi_application = application.server_factory.create_application()
            async with fastapi_application.router.lifespan_context(
                fastapi_application,
            ):
                transport = httpx.ASGITransport(app=fastapi_application)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url="http://testserver",
                ) as http_client:
                    yield http_client

    @pytest.mark.asyncio
    async def test_liveness_probe_returns_200_in_degraded_state(
        self,
        degraded_client,
    ):
        """The liveness probe must return HTTP 200 even when the image
        generation model failed to load, because the process is alive
        and can accept diagnostic queries."""
        response = await degraded_client.get("/health")

        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_readiness_probe_returns_503_in_degraded_state(
        self,
        degraded_client,
    ):
        """The readiness probe must return HTTP 503 with
        checks.image_generation reporting 'unavailable' when the model
        failed to load during startup."""
        response = await degraded_client.get("/health/ready")

        assert response.status_code == 503
        response_body = response.json()
        assert response_body["status"] == "not_ready"
        assert response_body["checks"]["image_generation"] == "unavailable"
        assert response_body["checks"]["language_model"] == "ok"

    @pytest.mark.asyncio
    async def test_image_generation_returns_502_in_degraded_state(
        self,
        degraded_client,
    ):
        """Image generation requests must return HTTP 502 with the
        ``model_unavailable`` error code when the model failed to load."""
        response = await degraded_client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset"},
        )

        assert response.status_code == 502
        response_body = response.json()
        assert response_body["error"]["code"] == "model_unavailable"

    @pytest.mark.asyncio
    async def test_prompt_enhancement_still_works_in_degraded_state(
        self,
        degraded_client,
    ):
        """Prompt enhancement (which does not require the image generation
        pipeline) must continue to function normally in the degraded
        state, satisfying partial availability (NFR7)."""
        response = await degraded_client.post(
            "/v1/prompts/enhance",
            json={"prompt": "A cat sitting on a windowsill"},
        )

        assert response.status_code == 200
        response_body = response.json()
        assert response_body["original_prompt"] == "A cat sitting on a windowsill"
        assert response_body["enhanced_prompt"] == "Enhanced prompt text"


# ─── Full Request Flows ──────────────────────────────────────────────────────


class TestPromptEnhancementFlow:
    @pytest.mark.asyncio
    async def test_successful_enhancement(self, integration_client, mock_language_model_service):
        response = await integration_client.post(
            "/v1/prompts/enhance",
            json={"prompt": "A cat"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["original_prompt"] == "A cat"
        assert body["enhanced_prompt"] == "Enhanced prompt text"
        assert "created" in body
        assert isinstance(body["created"], int)
        mock_language_model_service.enhance_prompt.assert_awaited_once_with(
            original_prompt="A cat",
        )

    @pytest.mark.asyncio
    async def test_enhancement_service_unavailable(self, integration_client, mock_language_model_service):
        mock_language_model_service.enhance_prompt.side_effect = (
            application.exceptions.LanguageModelServiceUnavailableError(
                detail="llama.cpp not reachable",
            )
        )

        response = await integration_client.post(
            "/v1/prompts/enhance",
            json={"prompt": "A cat"},
        )

        assert response.status_code == 502
        body = response.json()
        assert body["error"]["code"] == "upstream_service_unavailable"
        assert "llama.cpp not reachable" in body["error"]["message"]

    @pytest.mark.asyncio
    async def test_enhancement_malformed_response(self, integration_client, mock_language_model_service):
        mock_language_model_service.enhance_prompt.side_effect = application.exceptions.PromptEnhancementError(
            detail="Unexpected response structure",
        )

        response = await integration_client.post(
            "/v1/prompts/enhance",
            json={"prompt": "A cat"},
        )

        assert response.status_code == 502
        body = response.json()
        assert body["error"]["code"] == "upstream_service_unavailable"


class TestImageGenerationFlow:
    @pytest.mark.asyncio
    async def test_successful_generation(self, integration_client, mock_image_generation_service):
        response = await integration_client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset"},
        )

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body["created"], int)
        assert body["created"] > 0
        assert "seed" in body
        assert isinstance(body["seed"], int)
        assert len(body["data"]) == 1
        assert body["data"][0]["base64_json"] == "base64encodedimage"
        mock_image_generation_service.generate_images.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generation_with_enhancer(
        self,
        integration_client,
        mock_language_model_service,
        mock_image_generation_service,
    ):
        response = await integration_client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "use_enhancer": True},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["enhanced_prompt"] == "Enhanced prompt text"
        assert "seed" in body
        mock_language_model_service.enhance_prompt.assert_awaited_once_with(
            original_prompt="A sunset",
        )
        # The enhanced prompt should be passed to image generation
        call_kwargs = mock_image_generation_service.generate_images.call_args
        assert call_kwargs.kwargs["prompt"] == "Enhanced prompt text"

    @pytest.mark.asyncio
    async def test_generation_without_enhancer_skips_lm(
        self,
        integration_client,
        mock_language_model_service,
        mock_image_generation_service,
    ):
        response = await integration_client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "use_enhancer": False},
        )

        assert response.status_code == 200
        mock_language_model_service.enhance_prompt.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_generation_custom_size_and_count(self, integration_client, mock_image_generation_service):
        three_image_result = application.services.image_generation_service.ImageGenerationResult(
            base64_encoded_images=["img1", "img2", "img3"],
            content_safety_flagged_indices=[],
        )
        mock_image_generation_service.generate_images.return_value = three_image_result

        response = await integration_client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "n": 3, "size": "1024x1024"},
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 3
        call_kwargs = mock_image_generation_service.generate_images.call_args
        assert call_kwargs.kwargs["image_width"] == 1024
        assert call_kwargs.kwargs["image_height"] == 1024
        assert call_kwargs.kwargs["number_of_images"] == 3

    @pytest.mark.asyncio
    async def test_generation_service_unavailable(self, integration_client, mock_image_generation_service):
        mock_image_generation_service.generate_images.side_effect = (
            application.exceptions.ImageGenerationServiceUnavailableError(
                detail="Pipeline not loaded",
            )
        )

        response = await integration_client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset"},
        )

        assert response.status_code == 502
        body = response.json()
        assert body["error"]["code"] == "model_unavailable"
        assert "Pipeline not loaded" in body["error"]["message"]

    @pytest.mark.asyncio
    async def test_generation_error(self, integration_client, mock_image_generation_service):
        mock_image_generation_service.generate_images.side_effect = application.exceptions.ImageGenerationError(
            detail="No images returned",
        )

        response = await integration_client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset"},
        )

        assert response.status_code == 502
        body = response.json()
        assert body["error"]["code"] == "model_unavailable"

    @pytest.mark.asyncio
    async def test_enhancer_failure_returns_502_per_specification(
        self, integration_client, mock_language_model_service, mock_image_generation_service
    ):
        """Per spec §16, when use_enhancer is true and llama.cpp fails,
        the service returns HTTP 502 — no silent fallback to the original prompt."""
        mock_language_model_service.enhance_prompt.side_effect = (
            application.exceptions.LanguageModelServiceUnavailableError(
                detail="Timeout",
            )
        )

        response = await integration_client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "use_enhancer": True},
        )

        assert response.status_code == 502
        body = response.json()
        assert body["error"]["code"] == "upstream_service_unavailable"
        # Image generation should NOT have been attempted
        mock_image_generation_service.generate_images.assert_not_awaited()


# ─── Validation Through Full Stack ───────────────────────────────────────────


class TestValidationFlow:
    @pytest.mark.asyncio
    async def test_invalid_json_returns_400(self, integration_client):
        response = await integration_client.post(
            "/v1/prompts/enhance",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "invalid_request_json"

    @pytest.mark.asyncio
    async def test_missing_prompt_returns_400(self, integration_client):
        response = await integration_client.post(
            "/v1/images/generations",
            json={},
        )

        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "request_validation_failed"

    @pytest.mark.asyncio
    async def test_whitespace_prompt_returns_400(self, integration_client):
        response = await integration_client.post(
            "/v1/prompts/enhance",
            json={"prompt": "   "},
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_extra_fields_rejected(self, integration_client):
        response = await integration_client.post(
            "/v1/prompts/enhance",
            json={"prompt": "Hello", "extra": "field"},
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_image_size_rejected(self, integration_client):
        response = await integration_client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "size": "256x256"},
        )

        assert response.status_code == 400


# ─── Correlation ID Propagation ──────────────────────────────────────────────


class TestCorrelationIdPropagation:
    @pytest.mark.asyncio
    async def test_success_response_has_correlation_id(self, integration_client):
        response = await integration_client.get("/health")
        assert "x-correlation-id" in response.headers
        correlation_id = response.headers["x-correlation-id"]
        # UUID v4 format
        assert len(correlation_id) == 36
        assert correlation_id.count("-") == 4

    @pytest.mark.asyncio
    async def test_error_response_has_correlation_id(self, integration_client):
        response = await integration_client.post(
            "/v1/prompts/enhance",
            json={},
        )

        assert response.status_code == 400
        assert "x-correlation-id" in response.headers
        body = response.json()
        # Correlation ID in body matches header
        assert body["error"]["correlation_id"] == response.headers["x-correlation-id"]

    @pytest.mark.asyncio
    async def test_502_error_has_correlation_id(self, integration_client, mock_language_model_service):
        mock_language_model_service.enhance_prompt.side_effect = (
            application.exceptions.LanguageModelServiceUnavailableError(
                detail="Not reachable",
            )
        )

        response = await integration_client.post(
            "/v1/prompts/enhance",
            json={"prompt": "A cat"},
        )

        assert response.status_code == 502
        assert "x-correlation-id" in response.headers
        body = response.json()
        assert body["error"]["correlation_id"] == response.headers["x-correlation-id"]

    @pytest.mark.asyncio
    async def test_each_request_gets_unique_correlation_id(self, integration_client):
        response1 = await integration_client.get("/health")
        response2 = await integration_client.get("/health")

        id1 = response1.headers["x-correlation-id"]
        id2 = response2.headers["x-correlation-id"]
        assert id1 != id2

    @pytest.mark.asyncio
    async def test_unhandled_exception_returns_json_500_with_correlation_id(
        self,
        integration_client,
        mock_image_generation_service,
    ):
        mock_image_generation_service.generate_images.side_effect = ValueError(
            "totally unexpected",
        )

        response = await integration_client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset"},
        )

        assert response.status_code == 500
        assert "x-correlation-id" in response.headers
        body = response.json()
        assert body["error"]["code"] == "internal_server_error"
        assert body["error"]["correlation_id"] == response.headers["x-correlation-id"]


# ─── Metrics Through Full Stack ──────────────────────────────────────────────


class TestMetricsFlow:
    @pytest.mark.asyncio
    async def test_metrics_recorded_for_requests(self, integration_client):
        # Make a few requests
        await integration_client.get("/health")
        await integration_client.get("/health")

        response = await integration_client.get("/metrics")
        assert response.status_code == 200
        body = response.json()

        assert "request_counts" in body
        assert "request_latencies" in body

        # At least the /health requests should appear
        counts = body["request_counts"]
        assert counts.get("GET /health 200", 0) >= 2

    @pytest.mark.asyncio
    async def test_metrics_include_latency_data(self, integration_client):
        await integration_client.get("/health")

        response = await integration_client.get("/metrics")
        body = response.json()

        latencies = body["request_latencies"]
        assert "GET /health" in latencies
        health_latency = latencies["GET /health"]
        assert health_latency["count"] >= 1
        assert health_latency["minimum_milliseconds"] >= 0
        assert health_latency["maximum_milliseconds"] >= health_latency["minimum_milliseconds"]

    @pytest.mark.asyncio
    async def test_error_requests_tracked_in_metrics(self, integration_client):
        await integration_client.post(
            "/v1/prompts/enhance",
            json={},
        )

        response = await integration_client.get("/metrics")
        body = response.json()
        counts = body["request_counts"]
        assert counts.get("POST /v1/prompts/enhance 400", 0) >= 1


# ─── CORS ────────────────────────────────────────────────────────────────────


class TestCorsMiddleware:
    @pytest.mark.asyncio
    async def test_cors_preflight_allowed_origin(self, cors_client):
        response = await cors_client.options(
            "/v1/prompts/enhance",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"

    @pytest.mark.asyncio
    async def test_cors_preflight_disallowed_origin(self, cors_client):
        response = await cors_client.options(
            "/v1/prompts/enhance",
            headers={
                "Origin": "http://evil.com",
                "Access-Control-Request-Method": "POST",
            },
        )

        # Disallowed origin should not get CORS headers
        assert "access-control-allow-origin" not in response.headers

    @pytest.mark.asyncio
    async def test_cors_not_added_when_origins_empty(self, integration_client):
        response = await integration_client.options(
            "/v1/prompts/enhance",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )

        # Default config has empty cors_allowed_origins, so no CORS headers
        assert "access-control-allow-origin" not in response.headers


# ─── Concurrency ─────────────────────────────────────────────────────────────


class TestConcurrency:
    @pytest.mark.asyncio
    async def test_parallel_requests_get_distinct_correlation_ids(self, integration_client):
        """Concurrent requests must each receive a unique correlation ID."""
        import asyncio

        responses = await asyncio.gather(
            integration_client.get("/health"),
            integration_client.get("/health"),
            integration_client.get("/health"),
            integration_client.get("/health"),
            integration_client.get("/health"),
        )

        correlation_ids = [r.headers["x-correlation-id"] for r in responses]
        assert len(set(correlation_ids)) == 5


# ─── Rate Limiting ──────────────────────────────────────────────────────────


class TestRateLimiting:
    @pytest.mark.asyncio
    async def test_rate_limit_returns_429(self, mock_language_model_service, mock_image_generation_service):
        """Exceeding the rate limit must return a 429 JSON response."""
        import application.rate_limiting

        with (
            patch("configuration.ApplicationConfiguration") as mock_config_cls,
            _patched_services(mock_language_model_service, mock_image_generation_service),
        ):
            configuration_instance = mock_config_cls.return_value
            _apply_default_configuration_attributes(configuration_instance)
            configuration_instance.rate_limit = "2/minute"

            application.rate_limiting.rate_limiter.reset()

            app = application.server_factory.create_application()
            async with app.router.lifespan_context(app):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                    # First two requests should succeed
                    r1 = await client.post("/v1/prompts/enhance", json={"prompt": "A cat"})
                    assert r1.status_code == 200

                    r2 = await client.post("/v1/prompts/enhance", json={"prompt": "A dog"})
                    assert r2.status_code == 200

                    # Third request should be rate limited
                    r3 = await client.post("/v1/prompts/enhance", json={"prompt": "A bird"})
                    assert r3.status_code == 429
                    body = r3.json()
                    assert body["error"]["code"] == "rate_limit_exceeded"
                    assert "x-correlation-id" in r3.headers
                    # NFR47: Retry-After header must be present on 429 responses
                    assert "Retry-After" in r3.headers
                    assert r3.headers["Retry-After"] == "60"


# ─── HTTP 405 Method Not Allowed with Allow Header (NFR22) ──────────────────


class TestMethodNotAllowedWithAllowHeader:
    """
    Verify that HTTP 405 responses include a structured JSON error body
    with the error code ``method_not_allowed`` and an ``Allow`` header
    listing the permitted methods for the endpoint, as required by
    NFR22 and RFC 9110 §15.5.6.
    """

    @pytest.mark.asyncio
    async def test_get_on_post_endpoint_returns_405_with_allow_post(
        self,
        integration_client,
    ):
        """GET on POST /v1/prompts/enhance returns 405 with Allow: POST."""
        response = await integration_client.get("/v1/prompts/enhance")

        assert response.status_code == 405
        body = response.json()
        assert body["error"]["code"] == "method_not_allowed"
        assert response.headers.get("allow") == "POST"

    @pytest.mark.asyncio
    async def test_delete_on_image_generation_returns_405_with_allow_post(
        self,
        integration_client,
    ):
        """DELETE on POST /v1/images/generations returns 405 with Allow: POST."""
        response = await integration_client.delete("/v1/images/generations")

        assert response.status_code == 405
        body = response.json()
        assert body["error"]["code"] == "method_not_allowed"
        assert response.headers.get("allow") == "POST"

    @pytest.mark.asyncio
    async def test_post_on_health_returns_405_with_allow_get_head(
        self,
        integration_client,
    ):
        """POST on GET /health returns 405 with Allow: GET, HEAD."""
        response = await integration_client.post(
            "/health",
            json={},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 405
        body = response.json()
        assert body["error"]["code"] == "method_not_allowed"
        assert response.headers.get("allow") == "GET, HEAD"

    @pytest.mark.asyncio
    async def test_delete_on_metrics_returns_405_with_allow_get_head(
        self,
        integration_client,
    ):
        """DELETE on GET /metrics returns 405 with Allow: GET, HEAD."""
        response = await integration_client.delete("/metrics")

        assert response.status_code == 405
        body = response.json()
        assert body["error"]["code"] == "method_not_allowed"
        assert response.headers.get("allow") == "GET, HEAD"

    @pytest.mark.asyncio
    async def test_405_response_has_correlation_id(
        self,
        integration_client,
    ):
        """HTTP 405 error responses include a correlation ID."""
        response = await integration_client.get("/v1/prompts/enhance")

        assert response.status_code == 405
        body = response.json()
        assert "correlation_id" in body["error"]
        assert body["error"]["correlation_id"] != "unknown"


# ─── HTTP 404 Not Found ─────────────────────────────────────────────────────


class TestNotFoundFullStackIntegration:
    """
    Verify that requests to undefined endpoints receive a structured JSON
    error response with HTTP 404 and the error code ``not_found``, rather
    than Starlette's default plain-text or HTML response.
    """

    @pytest.mark.asyncio
    async def test_undefined_endpoint_returns_404_with_structured_json_error(
        self,
        integration_client,
    ):
        """A GET request to a non-existent path returns HTTP 404 with the
        ``not_found`` error code and a correlation ID for traceability."""
        response = await integration_client.get("/v1/nonexistent/path")

        assert response.status_code == 404
        response_body = response.json()
        assert response_body["error"]["code"] == "not_found"
        assert "x-correlation-id" in response.headers
        assert response_body["error"]["correlation_id"] == response.headers["x-correlation-id"]


# ─── Readiness Check Returning 503 (NFR47) ───────────────────────────────────


class TestReadinessCheckReturning503FullStackIntegration:
    """
    Full-stack integration tests verifying that the readiness endpoint
    (``GET /health/ready``) returns HTTP 503 (Service Unavailable) with
    a ``Retry-After`` header and the correct response body structure
    when one or more backend services are unhealthy.

    These tests modify the mock service health checks *after* the
    application has been created and the lifespan has started, simulating
    a runtime scenario where a backend becomes unavailable during
    operation (for example, the llama.cpp server crashes or the Stable
    Diffusion pipeline encounters a fatal error).

    The ``Retry-After`` header is required by NFR47 of the v5.0.0
    specification to enable orchestrators and monitoring tools to
    implement intelligent back-off when the service reports not-ready.
    """

    @pytest.mark.asyncio
    async def test_readiness_returns_503_when_image_generation_service_unhealthy(
        self,
        integration_client,
        mock_image_generation_service,
    ):
        """When the image generation service reports unhealthy, the
        readiness endpoint returns HTTP 503 with ``status: not_ready``,
        the ``image_generation`` check marked as ``unavailable``, a
        ``Retry-After`` header, and ``Cache-Control: no-store, no-cache``
        to prevent intermediate proxies from caching stale health data."""
        mock_image_generation_service.check_health.return_value = False

        response = await integration_client.get("/health/ready")

        assert response.status_code == 503
        response_body = response.json()
        assert response_body["status"] == "not_ready"
        assert response_body["checks"]["image_generation"] == "unavailable"
        assert response_body["checks"]["language_model"] == "ok"

        # NFR47: Retry-After header must be present on 503 responses.
        assert "Retry-After" in response.headers
        assert response.headers["Retry-After"] == "10"

        # Infrastructure endpoints must include Cache-Control to prevent
        # caching of operational data by intermediate proxies.
        assert response.headers.get("cache-control") == "no-store, no-cache"

        # Correlation ID must be present for traceability.
        assert "x-correlation-id" in response.headers

    @pytest.mark.asyncio
    async def test_readiness_returns_503_when_language_model_service_unhealthy(
        self,
        integration_client,
        mock_language_model_service,
    ):
        """When the language model service reports unhealthy, the
        readiness endpoint returns HTTP 503 with the ``language_model``
        check marked as ``unavailable`` and a ``Retry-After`` header."""
        mock_language_model_service.check_health.return_value = False

        response = await integration_client.get("/health/ready")

        assert response.status_code == 503
        response_body = response.json()
        assert response_body["status"] == "not_ready"
        assert response_body["checks"]["language_model"] == "unavailable"
        assert response_body["checks"]["image_generation"] == "ok"
        assert "Retry-After" in response.headers

    @pytest.mark.asyncio
    async def test_readiness_returns_503_when_both_services_unhealthy(
        self,
        integration_client,
        mock_language_model_service,
        mock_image_generation_service,
    ):
        """When both backend services are unhealthy simultaneously, the
        readiness endpoint returns HTTP 503 with both checks marked as
        ``unavailable``.  This simulates a complete backend outage."""
        mock_language_model_service.check_health.return_value = False
        mock_image_generation_service.check_health.return_value = False

        response = await integration_client.get("/health/ready")

        assert response.status_code == 503
        response_body = response.json()
        assert response_body["status"] == "not_ready"
        assert response_body["checks"]["language_model"] == "unavailable"
        assert response_body["checks"]["image_generation"] == "unavailable"
        assert "Retry-After" in response.headers


# ─── Middleware-Enforced Error Scenarios (413, 415, 504) ─────────────────────


class TestPayloadTooLargeFullStackIntegration:
    """
    Full-stack integration tests verifying that the
    ``RequestPayloadSizeLimitMiddleware`` correctly rejects oversized
    request payloads with HTTP 413 (Payload Too Large) when the request
    traverses the complete middleware → routing → error handling pipeline.

    These tests complement the unit-level middleware tests in
    ``test_middleware.py`` by confirming that the middleware integrates
    correctly with the correlation ID middleware, the structured error
    response format, and the metrics collector within a fully assembled
    application instance created via ``create_application()``.

    A deliberately small payload limit (100 bytes) is configured so that
    a normal-length JSON request body exceeds the threshold without
    requiring large memory allocations in the test process.
    """

    @pytest.mark.asyncio
    async def test_oversized_payload_returns_413_with_payload_too_large_error_code(
        self,
        mock_language_model_service,
        mock_image_generation_service,
    ):
        """An HTTP POST whose body exceeds the configured maximum payload
        size is rejected with HTTP 413 and a structured JSON error body
        containing the ``payload_too_large`` error code.

        The correlation ID must appear in both the ``X-Correlation-ID``
        response header and the ``error.correlation_id`` field of the
        JSON body, confirming end-to-end traceability across the full
        middleware stack."""
        with (
            patch("configuration.ApplicationConfiguration") as mock_configuration_class,
            _patched_services(mock_language_model_service, mock_image_generation_service),
        ):
            configuration_instance = mock_configuration_class.return_value
            _apply_default_configuration_attributes(configuration_instance)
            # Set a deliberately small payload limit so that a normal-length
            # JSON request body exceeds the threshold.
            configuration_instance.maximum_request_payload_bytes = 100

            fastapi_application = application.server_factory.create_application()
            async with fastapi_application.router.lifespan_context(
                fastapi_application,
            ):
                transport = httpx.ASGITransport(app=fastapi_application)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url="http://testserver",
                ) as http_client:
                    # Construct a JSON body that exceeds the 100-byte limit.
                    oversized_json_body = '{"prompt": "' + "A" * 200 + '"}'

                    response = await http_client.post(
                        "/v1/prompts/enhance",
                        content=oversized_json_body.encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )

                    assert response.status_code == 413
                    response_body = response.json()
                    assert response_body["error"]["code"] == "payload_too_large"
                    assert "x-correlation-id" in response.headers
                    assert response_body["error"]["correlation_id"] == response.headers["x-correlation-id"]

    @pytest.mark.asyncio
    async def test_service_layer_not_invoked_when_payload_rejected(
        self,
        mock_language_model_service,
        mock_image_generation_service,
    ):
        """When the payload size limit middleware rejects a request, the
        service layer must not be invoked — the rejection occurs before
        the request body reaches the application layer."""
        with (
            patch("configuration.ApplicationConfiguration") as mock_configuration_class,
            _patched_services(mock_language_model_service, mock_image_generation_service),
        ):
            configuration_instance = mock_configuration_class.return_value
            _apply_default_configuration_attributes(configuration_instance)
            configuration_instance.maximum_request_payload_bytes = 100

            fastapi_application = application.server_factory.create_application()
            async with fastapi_application.router.lifespan_context(
                fastapi_application,
            ):
                transport = httpx.ASGITransport(app=fastapi_application)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url="http://testserver",
                ) as http_client:
                    oversized_json_body = '{"prompt": "' + "A" * 200 + '"}'

                    await http_client.post(
                        "/v1/prompts/enhance",
                        content=oversized_json_body.encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )

                    # The language model service must not have been called.
                    mock_language_model_service.enhance_prompt.assert_not_awaited()


class TestUnsupportedMediaTypeFullStackIntegration:
    """
    Full-stack integration tests verifying that the
    ``ContentTypeValidationMiddleware`` correctly rejects POST requests
    with a non-``application/json`` Content-Type header with HTTP 415
    (Unsupported Media Type) when the request traverses the complete
    middleware → routing → error handling pipeline.

    These tests use the standard ``integration_client`` fixture because
    the Content-Type check does not depend on custom configuration — the
    middleware is always active for POST requests.
    """

    @pytest.mark.asyncio
    async def test_post_with_non_json_content_type_returns_415_with_structured_error(
        self,
        integration_client,
    ):
        """An HTTP POST with ``Content-Type: text/plain`` is rejected with
        HTTP 415 and the ``unsupported_media_type`` error code.

        The correlation ID must appear in both the response header and the
        error body for end-to-end traceability."""
        response = await integration_client.post(
            "/v1/prompts/enhance",
            content=b'{"prompt": "A cat"}',
            headers={"Content-Type": "text/plain"},
        )

        assert response.status_code == 415
        response_body = response.json()
        assert response_body["error"]["code"] == "unsupported_media_type"
        assert "x-correlation-id" in response.headers
        assert response_body["error"]["correlation_id"] == response.headers["x-correlation-id"]

    @pytest.mark.asyncio
    async def test_post_with_missing_content_type_returns_415(
        self,
        integration_client,
    ):
        """An HTTP POST with an empty Content-Type header is rejected
        with HTTP 415 because the middleware treats an absent or empty
        Content-Type as invalid for POST requests."""
        response = await integration_client.post(
            "/v1/prompts/enhance",
            content=b'{"prompt": "A cat"}',
            headers={"Content-Type": ""},
        )

        assert response.status_code == 415
        response_body = response.json()
        assert response_body["error"]["code"] == "unsupported_media_type"

    @pytest.mark.asyncio
    async def test_get_requests_bypass_content_type_validation(
        self,
        integration_client,
    ):
        """GET requests are exempt from Content-Type validation.  The
        liveness endpoint must return HTTP 200 regardless of whether
        a Content-Type header is present or not."""
        response = await integration_client.get("/health")

        assert response.status_code == 200
        assert response.json()["status"] == "healthy"


class TestRequestTimeoutFullStackIntegration:
    """
    Full-stack integration tests verifying that the
    ``RequestTimeoutMiddleware`` correctly aborts requests exceeding the
    configured end-to-end timeout ceiling with HTTP 504 (Gateway Timeout)
    and the structured error code ``request_timeout`` (NFR48).

    These tests use a deliberately short timeout (50 milliseconds) and a
    mock language model service that blocks for 10 seconds, ensuring the
    timeout fires deterministically.  The ``asyncio.wait_for`` mechanism
    cancels the blocked coroutine promptly, so the test completes in
    approximately 50 ms rather than 10 seconds.
    """

    @pytest.mark.asyncio
    async def test_request_exceeding_timeout_returns_504_with_request_timeout_error_code(
        self,
        mock_language_model_service,
        mock_image_generation_service,
    ):
        """A request whose processing time exceeds the configured
        end-to-end timeout ceiling receives HTTP 504 with the
        ``request_timeout`` error code and a correlation ID.

        The mock language model service is configured to block for 10
        seconds, but the timeout is set to 50 milliseconds, ensuring
        the timeout fires before the service completes."""

        async def simulate_slow_prompt_enhancement(original_prompt):
            """Block for far longer than the configured timeout to
            deterministically trigger the timeout middleware."""
            await asyncio.sleep(10.0)
            return "This response will never be sent"

        mock_language_model_service.enhance_prompt = AsyncMock(
            side_effect=simulate_slow_prompt_enhancement,
        )

        with (
            patch("configuration.ApplicationConfiguration") as mock_configuration_class,
            _patched_services(mock_language_model_service, mock_image_generation_service),
        ):
            configuration_instance = mock_configuration_class.return_value
            _apply_default_configuration_attributes(configuration_instance)
            # Set a deliberately short timeout (50 ms) so the test
            # completes quickly whilst still exceeding the timeout.
            configuration_instance.timeout_for_requests_in_seconds = 0.05

            fastapi_application = application.server_factory.create_application()
            async with fastapi_application.router.lifespan_context(
                fastapi_application,
            ):
                transport = httpx.ASGITransport(app=fastapi_application)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url="http://testserver",
                ) as http_client:
                    response = await http_client.post(
                        "/v1/prompts/enhance",
                        json={"prompt": "A cat sitting on a windowsill"},
                    )

                    assert response.status_code == 504
                    response_body = response.json()
                    assert response_body["error"]["code"] == "request_timeout"
                    assert "x-correlation-id" in response.headers
                    assert response_body["error"]["correlation_id"] == response.headers["x-correlation-id"]


# ─── Admission Control Rejection (429 service_busy) ─────────────────────────


class TestAdmissionControlRejectionFullStackIntegration:
    """
    Full-stack integration tests verifying that the semaphore-based
    admission controller (NFR44) correctly rejects overflow image
    generation requests with HTTP 429 and the error code ``service_busy``
    when the maximum concurrency limit has been reached.

    These tests are distinct from the IP-based rate limiting tests
    (``TestRateLimiting``): admission control limits the *total* number of
    concurrent image generation operations across all clients, whilst rate
    limiting restricts the request *frequency* from a single IP address.

    The test strategy uses two synchronisation primitives:

    1. ``generation_entered_event``: signalled by the mock image generation
       service when it enters the (blocking) generate_images call.  This
       ensures the first request has acquired the admission slot before the
       second request is sent.

    2. ``generation_release_event``: signalled by the test to unblock the
       first request after the second request has been verified as rejected.
       This ensures clean shutdown without leaked asyncio tasks.
    """

    @pytest.mark.asyncio
    async def test_concurrent_generation_beyond_limit_returns_429_service_busy(
        self,
        mock_language_model_service,
        mock_image_generation_service,
    ):
        """When the admission control semaphore is fully occupied by an
        active image generation operation, a second concurrent request
        receives HTTP 429 with the ``service_busy`` error code, a
        ``Retry-After`` header, and a correlation ID.

        After the first operation completes and releases its admission
        slot, the service returns to normal operation."""
        generation_entered_event = asyncio.Event()
        generation_release_event = asyncio.Event()

        mock_generation_result = application.services.image_generation_service.ImageGenerationResult(
            base64_encoded_images=["base64encodedimage"],
            content_safety_flagged_indices=[],
        )

        async def blocking_generate_images(**kwargs):
            """Simulate a long-running image generation operation that
            signals its entry and then blocks until explicitly released
            by the test harness."""
            generation_entered_event.set()
            await generation_release_event.wait()
            return mock_generation_result

        mock_image_generation_service.generate_images = AsyncMock(
            side_effect=blocking_generate_images,
        )

        with (
            patch("configuration.ApplicationConfiguration") as mock_configuration_class,
            _patched_services(mock_language_model_service, mock_image_generation_service),
        ):
            configuration_instance = mock_configuration_class.return_value
            _apply_default_configuration_attributes(configuration_instance)
            # Set concurrency to 1 so that a single active operation
            # fully occupies the admission controller.
            configuration_instance.image_generation_maximum_concurrency = 1

            fastapi_application = application.server_factory.create_application()
            async with fastapi_application.router.lifespan_context(
                fastapi_application,
            ):
                transport = httpx.ASGITransport(app=fastapi_application)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url="http://testserver",
                ) as http_client:
                    # Start the first request, which will block inside
                    # the admission controller until explicitly released.
                    first_request_task = asyncio.create_task(
                        http_client.post(
                            "/v1/images/generations",
                            json={"prompt": "First image request"},
                        ),
                    )

                    # Wait for the first request to actually enter the
                    # image generation service, confirming that it has
                    # acquired the admission slot.
                    await asyncio.wait_for(
                        generation_entered_event.wait(),
                        timeout=5.0,
                    )

                    # The admission slot is now occupied.  A second
                    # concurrent request must be rejected immediately
                    # with HTTP 429 (service_busy).
                    second_response = await http_client.post(
                        "/v1/images/generations",
                        json={"prompt": "Second image request"},
                    )

                    assert second_response.status_code == 429
                    second_response_body = second_response.json()
                    assert second_response_body["error"]["code"] == "service_busy"

                    # NFR47: the 429 response must include a Retry-After
                    # header to enable intelligent client back-off.
                    assert "Retry-After" in second_response.headers
                    assert second_response.headers["Retry-After"] == "30"

                    # Correlation ID must be present for traceability.
                    assert "x-correlation-id" in second_response.headers
                    assert (
                        second_response_body["error"]["correlation_id"] == second_response.headers["x-correlation-id"]
                    )

                    # Release the first request so it completes normally.
                    generation_release_event.set()
                    first_response = await first_request_task
                    assert first_response.status_code == 200

    @pytest.mark.asyncio
    async def test_service_busy_error_code_is_distinct_from_rate_limit_exceeded(
        self,
        mock_language_model_service,
        mock_image_generation_service,
    ):
        """The admission control rejection error code (``service_busy``)
        must be distinct from the IP-based rate limiting error code
        (``rate_limit_exceeded``).  Both produce HTTP 429 but represent
        fundamentally different rejection reasons:

        - ``service_busy``: the GPU/CPU inference pipeline is at maximum
          concurrency across all clients.
        - ``rate_limit_exceeded``: a single IP address has exceeded the
          configured request frequency threshold.

        This test verifies the distinction by triggering admission
        control rejection and confirming the error code."""
        generation_entered_event = asyncio.Event()
        generation_release_event = asyncio.Event()

        mock_generation_result = application.services.image_generation_service.ImageGenerationResult(
            base64_encoded_images=["base64encodedimage"],
            content_safety_flagged_indices=[],
        )

        async def blocking_generate_images(**kwargs):
            generation_entered_event.set()
            await generation_release_event.wait()
            return mock_generation_result

        mock_image_generation_service.generate_images = AsyncMock(
            side_effect=blocking_generate_images,
        )

        with (
            patch("configuration.ApplicationConfiguration") as mock_configuration_class,
            _patched_services(mock_language_model_service, mock_image_generation_service),
        ):
            configuration_instance = mock_configuration_class.return_value
            _apply_default_configuration_attributes(configuration_instance)
            configuration_instance.image_generation_maximum_concurrency = 1

            fastapi_application = application.server_factory.create_application()
            async with fastapi_application.router.lifespan_context(
                fastapi_application,
            ):
                transport = httpx.ASGITransport(app=fastapi_application)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url="http://testserver",
                ) as http_client:
                    first_request_task = asyncio.create_task(
                        http_client.post(
                            "/v1/images/generations",
                            json={"prompt": "Blocking request"},
                        ),
                    )

                    await asyncio.wait_for(
                        generation_entered_event.wait(),
                        timeout=5.0,
                    )

                    rejected_response = await http_client.post(
                        "/v1/images/generations",
                        json={"prompt": "Rejected request"},
                    )

                    # The error code must be "service_busy", NOT
                    # "rate_limit_exceeded".
                    rejected_response_body = rejected_response.json()
                    assert rejected_response_body["error"]["code"] == "service_busy"
                    assert rejected_response_body["error"]["code"] != "rate_limit_exceeded"

                    generation_release_event.set()
                    await first_request_task
