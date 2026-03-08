"""Tests for the GET /health, GET /health/ready, and GET /metrics endpoints."""

from unittest.mock import AsyncMock

import fastapi
import httpx
import pytest

import application.api.endpoints.health
import application.api.middleware.correlation_identifier


class TestHealthEndpoints:
    @pytest.mark.asyncio
    async def test_health_returns_200(self, client):
        response = await client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    @pytest.mark.asyncio
    async def test_health_has_correlation_id(self, client):
        response = await client.get("/health")

        assert "X-Correlation-ID" in response.headers

    @pytest.mark.asyncio
    async def test_health_has_cache_control_header(self, client):
        """Infrastructure endpoints must include Cache-Control: no-store, no-cache
        to prevent intermediate proxies from caching operational data."""
        response = await client.get("/health")

        assert response.headers.get("cache-control") == "no-store, no-cache"

    @pytest.mark.asyncio
    async def test_health_has_pragma_no_cache_header(self, client):
        """Infrastructure endpoints must include Pragma: no-cache for
        backward-compatible cache suppression with HTTP/1.0 intermediaries
        (§12 of the v5.8.1 specification)."""
        response = await client.get("/health")

        assert response.headers.get("pragma") == "no-cache"


class TestReadinessEndpoints:
    @pytest.mark.asyncio
    async def test_ready_when_services_healthy(
        self, client, mock_of_llama_cpp_client, mock_of_stable_diffusion_pipeline
    ):
        response = await client.get("/health/ready")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert body["checks"]["image_generation"] == "ok"
        assert body["checks"]["large_language_model"] == "ok"

    @pytest.mark.asyncio
    async def test_ready_has_correlation_id(self, client):
        response = await client.get("/health/ready")

        assert "X-Correlation-ID" in response.headers

    @pytest.mark.asyncio
    async def test_not_ready_when_services_missing(self):
        """Return 503 when services are not set on application state."""
        test_application = fastapi.FastAPI()
        test_application.add_middleware(
            application.api.middleware.correlation_identifier.CorrelationIdMiddleware,
        )
        test_application.include_router(application.api.endpoints.health.health_router)

        transport = httpx.ASGITransport(app=test_application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/health/ready")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "not_ready"
        assert body["checks"]["image_generation"] == "unavailable"
        assert body["checks"]["large_language_model"] == "unavailable"

    @pytest.mark.asyncio
    async def test_degraded_when_large_language_model_is_unavailable(
        self, client, mock_of_llama_cpp_client, mock_of_stable_diffusion_pipeline
    ):
        mock_of_llama_cpp_client.check_health = AsyncMock(return_value=False)

        response = await client.get("/health/ready")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        assert body["checks"]["large_language_model"] == "unavailable"
        assert body["checks"]["image_generation"] == "ok"

    @pytest.mark.asyncio
    async def test_not_ready_when_image_pipeline_unhealthy(self, client, mock_of_stable_diffusion_pipeline):
        mock_of_stable_diffusion_pipeline.check_health = lambda: False

        response = await client.get("/health/ready")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "not_ready"
        assert body["checks"]["image_generation"] == "unavailable"

    @pytest.mark.asyncio
    async def test_degraded_when_large_language_model_check_raises(
        self, client, mock_of_llama_cpp_client, mock_of_stable_diffusion_pipeline
    ):
        mock_of_llama_cpp_client.check_health = AsyncMock(side_effect=RuntimeError("unexpected"))

        response = await client.get("/health/ready")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        assert body["checks"]["large_language_model"] == "unavailable"
        assert body["checks"]["image_generation"] == "ok"

    @pytest.mark.asyncio
    async def test_503_response_includes_retry_after_header(self, client, mock_of_stable_diffusion_pipeline):
        """Per NFR47, HTTP 503 responses must include a Retry-After header
        populated from the retry_after_not_ready_in_seconds configuration."""
        mock_of_stable_diffusion_pipeline.check_health = lambda: False

        response = await client.get("/health/ready")

        assert response.status_code == 503
        assert "Retry-After" in response.headers
        assert response.headers["Retry-After"] == "10"

    @pytest.mark.asyncio
    async def test_degraded_response_does_not_include_retry_after_header(
        self, client, mock_of_llama_cpp_client, mock_of_stable_diffusion_pipeline
    ):
        """When the service is degraded (LLM unavailable but image generation healthy),
        no Retry-After header is sent because the HTTP status is 200."""
        mock_of_llama_cpp_client.check_health = AsyncMock(return_value=False)

        response = await client.get("/health/ready")

        assert response.status_code == 200
        assert "Retry-After" not in response.headers

    @pytest.mark.asyncio
    async def test_not_ready_when_both_backends_are_unavailable(
        self, client, mock_of_llama_cpp_client, mock_of_stable_diffusion_pipeline
    ):
        """When both backends are unavailable, return 503 with not_ready status."""
        mock_of_llama_cpp_client.check_health = AsyncMock(return_value=False)
        mock_of_stable_diffusion_pipeline.check_health = lambda: False

        response = await client.get("/health/ready")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "not_ready"
        assert body["checks"]["large_language_model"] == "unavailable"
        assert body["checks"]["image_generation"] == "unavailable"

    @pytest.mark.asyncio
    async def test_200_response_does_not_include_retry_after_header(
        self, client, mock_of_llama_cpp_client, mock_of_stable_diffusion_pipeline
    ):
        """When all backends are healthy, no Retry-After header is sent."""
        response = await client.get("/health/ready")

        assert response.status_code == 200
        assert "Retry-After" not in response.headers

    @pytest.mark.asyncio
    async def test_readiness_has_cache_control_header(self, client):
        """The readiness endpoint must include Cache-Control: no-store, no-cache."""
        response = await client.get("/health/ready")

        assert response.headers.get("cache-control") == "no-store, no-cache"

    @pytest.mark.asyncio
    async def test_readiness_has_pragma_no_cache_header(self, client):
        """The readiness endpoint must include Pragma: no-cache for
        backward-compatible cache suppression with HTTP/1.0 intermediaries
        (§12 of the v5.8.1 specification)."""
        response = await client.get("/health/ready")

        assert response.headers.get("pragma") == "no-cache"


class TestMetricsEndpoints:
    @pytest.mark.asyncio
    async def test_metrics_returns_200(self, client):
        response = await client.get("/metrics")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_metrics_contains_expected_keys(self, client):
        response = await client.get("/metrics")

        body = response.json()
        assert "collected_at" in body
        assert "service_started_at" in body
        assert "request_counts" in body
        assert "request_latencies" in body

    @pytest.mark.asyncio
    async def test_metrics_records_requests(self, client):
        await client.get("/health")
        await client.get("/health")

        response = await client.get("/metrics")
        body = response.json()

        assert body["request_counts"].get("GET /health 200", 0) >= 2

    @pytest.mark.asyncio
    async def test_metrics_has_latency_data(self, client):
        await client.get("/health")

        response = await client.get("/metrics")
        body = response.json()

        assert "GET /health" in body["request_latencies"]
        latency = body["request_latencies"]["GET /health"]
        assert latency["number_of_observations"] >= 1
        assert latency["minimum_latency_in_milliseconds"] >= 0

    @pytest.mark.asyncio
    async def test_metrics_has_cache_control_header(self, client):
        """The metrics endpoint must include Cache-Control: no-store, no-cache."""
        response = await client.get("/metrics")

        assert response.headers.get("cache-control") == "no-store, no-cache"

    @pytest.mark.asyncio
    async def test_metrics_has_pragma_no_cache_header(self, client):
        """The metrics endpoint must include Pragma: no-cache for
        backward-compatible cache suppression with HTTP/1.0 intermediaries
        (§12 of the v5.8.1 specification)."""
        response = await client.get("/metrics")

        assert response.headers.get("pragma") == "no-cache"

    @pytest.mark.asyncio
    async def test_metrics_fallback_when_collector_missing(self):
        """Return empty metrics when metrics_collector is not on application state."""
        test_application = fastapi.FastAPI()
        test_application.add_middleware(
            application.api.middleware.correlation_identifier.CorrelationIdMiddleware,
        )
        test_application.include_router(application.api.endpoints.health.health_router)

        transport = httpx.ASGITransport(app=test_application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/metrics")

        assert response.status_code == 200
        body = response.json()
        assert "collected_at" in body
        assert "service_started_at" in body
        assert body["request_counts"] == {}
        assert body["request_latencies"] == {}


class TestPrometheusMetricsEndpoint:
    @pytest.mark.asyncio
    async def test_prometheus_metrics_returns_200(self, client):
        response = await client.get("/metrics/prometheus")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_prometheus_metrics_has_correct_content_type(self, client):
        response = await client.get("/metrics/prometheus")

        assert "text/plain" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_prometheus_metrics_contains_counter_after_requests(self, client):
        await client.get("/health")

        response = await client.get("/metrics/prometheus")
        body = response.text

        assert "http_requests_received_total" in body

    @pytest.mark.asyncio
    async def test_prometheus_metrics_contains_histogram_after_requests(self, client):
        await client.get("/health")

        response = await client.get("/metrics/prometheus")
        body = response.text

        assert "http_request_duration_in_seconds" in body

    @pytest.mark.asyncio
    async def test_prometheus_metrics_has_cache_control_header(self, client):
        response = await client.get("/metrics/prometheus")

        assert response.headers.get("cache-control") == "no-store, no-cache"

    @pytest.mark.asyncio
    async def test_prometheus_metrics_has_pragma_no_cache_header(self, client):
        response = await client.get("/metrics/prometheus")

        assert response.headers.get("pragma") == "no-cache"
