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
    """Create a mock ImageGenerationService that behaves like the real one."""
    service = MagicMock(
        spec=application.services.image_generation_service.ImageGenerationService,
    )
    service.generate_images = AsyncMock(return_value=["base64encodedimage"])
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


@contextlib.contextmanager
def _patched_services(mock_lm_service, mock_img_service):
    """Patch both ML service constructors for the duration of the block."""
    with (
        patch.object(
            application.services.language_model_service,
            "LanguageModelService",
            return_value=mock_lm_service,
        ),
        patch.object(
            application.services.image_generation_service.ImageGenerationService,
            "load_pipeline",
            return_value=mock_img_service,
        ),
    ):
        yield


@pytest.fixture
def mock_lm_service():
    return _build_mock_language_model_service()


@pytest.fixture
def mock_img_service():
    return _build_mock_image_generation_service()


@pytest_asyncio.fixture
async def integration_client(mock_lm_service, mock_img_service):
    """
    Create a real FastAPI app via ``create_application()`` with mocked ML
    backends, invoke the lifespan, and yield an async HTTP client.

    Patches remain active for the full lifespan because the lifespan
    closure references module-level names at runtime.
    """
    with _patched_services(mock_lm_service, mock_img_service):
        app = application.server_factory.create_application()
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                yield client


@pytest_asyncio.fixture
async def cors_client(mock_lm_service, mock_img_service):
    """
    Create a real app with CORS enabled and yield an async HTTP client.
    """
    with (
        patch("configuration.ApplicationConfiguration") as mock_config_cls,
        _patched_services(mock_lm_service, mock_img_service),
    ):
        config = mock_config_cls.return_value
        config.language_model_server_base_url = "http://localhost:8080"
        config.language_model_request_timeout_seconds = 120.0
        config.language_model_temperature = 0.7
        config.language_model_max_tokens = 512
        config.stable_diffusion_model_id = "test-model"
        config.stable_diffusion_device = "cpu"
        config.stable_diffusion_safety_checker = True
        config.stable_diffusion_inference_steps = 20
        config.stable_diffusion_guidance_scale = 7.0
        config.stable_diffusion_inference_timeout_per_unit_seconds = 60.0
        config.cors_allowed_origins = ["http://localhost:3000"]
        config.log_level = "INFO"
        config.rate_limit = "1000/minute"

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
    async def test_services_initialised_on_startup(self, mock_lm_service, mock_img_service):
        """Services must be set on app.state after lifespan startup."""
        with _patched_services(mock_lm_service, mock_img_service):
            app = application.server_factory.create_application()
            async with app.router.lifespan_context(app):
                assert app.state.language_model_service is mock_lm_service
                assert app.state.image_generation_service is mock_img_service

    @pytest.mark.asyncio
    async def test_services_closed_on_shutdown(self, mock_lm_service, mock_img_service):
        """Services must be closed when the lifespan exits."""
        with _patched_services(mock_lm_service, mock_img_service):
            app = application.server_factory.create_application()
            async with app.router.lifespan_context(app):
                pass  # startup runs

        # After exiting, shutdown should have run
        mock_lm_service.close.assert_awaited_once()
        mock_img_service.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_metrics_collector_on_app_state(self, mock_lm_service, mock_img_service):
        """The metrics collector must be set on app.state."""
        with _patched_services(mock_lm_service, mock_img_service):
            app = application.server_factory.create_application()
            async with app.router.lifespan_context(app):
                assert hasattr(app.state, "metrics_collector")
                assert app.state.metrics_collector is not None


# ─── Full Request Flows ──────────────────────────────────────────────────────


class TestPromptEnhancementFlow:
    @pytest.mark.asyncio
    async def test_successful_enhancement(self, integration_client, mock_lm_service):
        response = await integration_client.post(
            "/v1/prompts/enhance",
            json={"prompt": "A cat"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["enhanced_prompt"] == "Enhanced prompt text"
        mock_lm_service.enhance_prompt.assert_awaited_once_with(
            original_prompt="A cat",
        )

    @pytest.mark.asyncio
    async def test_enhancement_service_unavailable(self, integration_client, mock_lm_service):
        mock_lm_service.enhance_prompt.side_effect = application.exceptions.LanguageModelServiceUnavailableError(
            detail="llama.cpp not reachable",
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
    async def test_enhancement_malformed_response(self, integration_client, mock_lm_service):
        mock_lm_service.enhance_prompt.side_effect = application.exceptions.PromptEnhancementError(
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
    async def test_successful_generation(self, integration_client, mock_img_service):
        response = await integration_client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset"},
        )

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body["created"], int)
        assert body["created"] > 0
        assert len(body["data"]) == 1
        assert body["data"][0]["b64_json"] == "base64encodedimage"
        mock_img_service.generate_images.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generation_with_enhancer(self, integration_client, mock_lm_service, mock_img_service):
        response = await integration_client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "use_enhancer": True},
        )

        assert response.status_code == 200
        mock_lm_service.enhance_prompt.assert_awaited_once_with(
            original_prompt="A sunset",
        )
        # The enhanced prompt should be passed to image generation
        call_kwargs = mock_img_service.generate_images.call_args
        assert call_kwargs.kwargs["prompt"] == "Enhanced prompt text"

    @pytest.mark.asyncio
    async def test_generation_without_enhancer_skips_lm(self, integration_client, mock_lm_service, mock_img_service):
        response = await integration_client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "use_enhancer": False},
        )

        assert response.status_code == 200
        mock_lm_service.enhance_prompt.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_generation_custom_size_and_count(self, integration_client, mock_img_service):
        mock_img_service.generate_images.return_value = [
            "img1",
            "img2",
            "img3",
        ]

        response = await integration_client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "n": 3, "size": "1024x1024"},
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 3
        call_kwargs = mock_img_service.generate_images.call_args
        assert call_kwargs.kwargs["image_width"] == 1024
        assert call_kwargs.kwargs["image_height"] == 1024
        assert call_kwargs.kwargs["number_of_images"] == 3

    @pytest.mark.asyncio
    async def test_generation_service_unavailable(self, integration_client, mock_img_service):
        mock_img_service.generate_images.side_effect = application.exceptions.ImageGenerationServiceUnavailableError(
            detail="Pipeline not loaded",
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
    async def test_generation_error(self, integration_client, mock_img_service):
        mock_img_service.generate_images.side_effect = application.exceptions.ImageGenerationError(
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
    async def test_enhancer_failure_falls_back_to_original_prompt(
        self, integration_client, mock_lm_service, mock_img_service
    ):
        """When the enhancer fails during image generation, the original prompt is used."""
        mock_lm_service.enhance_prompt.side_effect = application.exceptions.LanguageModelServiceUnavailableError(
            detail="Timeout",
        )

        response = await integration_client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "use_enhancer": True},
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 1
        # The original prompt should have been used for generation
        call_kwargs = mock_img_service.generate_images.call_args
        assert call_kwargs.kwargs["prompt"] == "A sunset"


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
    async def test_502_error_has_correlation_id(self, integration_client, mock_lm_service):
        mock_lm_service.enhance_prompt.side_effect = application.exceptions.LanguageModelServiceUnavailableError(
            detail="Not reachable",
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
    async def test_unhandled_exception_returns_json_500_with_correlation_id(self, integration_client, mock_img_service):
        mock_img_service.generate_images.side_effect = ValueError(
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
        assert health_latency["min_ms"] >= 0
        assert health_latency["max_ms"] >= health_latency["min_ms"]

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
    async def test_rate_limit_returns_429(self, mock_lm_service, mock_img_service):
        """Exceeding the rate limit must return a 429 JSON response."""
        import application.rate_limiting

        with (
            patch("configuration.ApplicationConfiguration") as mock_config_cls,
            _patched_services(mock_lm_service, mock_img_service),
        ):
            config = mock_config_cls.return_value
            config.language_model_server_base_url = "http://localhost:8080"
            config.language_model_request_timeout_seconds = 120.0
            config.language_model_temperature = 0.7
            config.language_model_max_tokens = 512
            config.stable_diffusion_model_id = "test-model"
            config.stable_diffusion_device = "cpu"
            config.stable_diffusion_safety_checker = True
            config.stable_diffusion_inference_steps = 20
            config.stable_diffusion_guidance_scale = 7.0
            config.stable_diffusion_inference_timeout_per_unit_seconds = 60.0
            config.cors_allowed_origins = []
            config.log_level = "INFO"
            config.rate_limit = "2/minute"

            application.rate_limiting.limiter.reset()

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
