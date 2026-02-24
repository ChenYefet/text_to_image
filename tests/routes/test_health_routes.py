"""Tests for the GET /health, GET /health/ready, and GET /metrics endpoints."""

from unittest.mock import AsyncMock

import fastapi
import httpx
import pytest

import application.middleware
import application.routes.health_routes


class TestHealthRoutes:
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
        (§12 of the v5.0.0 specification)."""
        response = await client.get("/health")

        assert response.headers.get("pragma") == "no-cache"


class TestReadinessRoutes:
    @pytest.mark.asyncio
    async def test_ready_when_services_healthy(
        self, client, mock_language_model_service, mock_image_generation_service
    ):
        response = await client.get("/health/ready")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert body["checks"]["image_generation"] == "ok"
        assert body["checks"]["language_model"] == "ok"

    @pytest.mark.asyncio
    async def test_ready_has_correlation_id(self, client):
        response = await client.get("/health/ready")

        assert "X-Correlation-ID" in response.headers

    @pytest.mark.asyncio
    async def test_not_ready_when_services_missing(self):
        """Return 503 when services are not set on app.state."""
        app = fastapi.FastAPI()
        app.add_middleware(
            application.middleware.CorrelationIdMiddleware,
        )
        app.include_router(application.routes.health_routes.health_router)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/health/ready")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "not_ready"
        assert body["checks"]["image_generation"] == "unavailable"
        assert body["checks"]["language_model"] == "unavailable"

    @pytest.mark.asyncio
    async def test_not_ready_when_language_model_unhealthy(self, client, mock_language_model_service):
        mock_language_model_service.check_health = AsyncMock(return_value=False)

        response = await client.get("/health/ready")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "not_ready"
        assert body["checks"]["language_model"] == "unavailable"

    @pytest.mark.asyncio
    async def test_not_ready_when_image_pipeline_unhealthy(self, client, mock_image_generation_service):
        mock_image_generation_service.check_health = lambda: False

        response = await client.get("/health/ready")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "not_ready"
        assert body["checks"]["image_generation"] == "unavailable"

    @pytest.mark.asyncio
    async def test_not_ready_when_language_model_check_raises(self, client, mock_language_model_service):
        mock_language_model_service.check_health = AsyncMock(side_effect=RuntimeError("unexpected"))

        response = await client.get("/health/ready")

        assert response.status_code == 503
        body = response.json()
        assert body["checks"]["language_model"] == "unavailable"

    @pytest.mark.asyncio
    async def test_503_response_includes_retry_after_header(self, client, mock_language_model_service):
        """Per NFR47, HTTP 503 responses must include a Retry-After header
        populated from the retry_after_not_ready_seconds configuration."""
        mock_language_model_service.check_health = AsyncMock(return_value=False)

        response = await client.get("/health/ready")

        assert response.status_code == 503
        assert "Retry-After" in response.headers
        assert response.headers["Retry-After"] == "10"

    @pytest.mark.asyncio
    async def test_200_response_does_not_include_retry_after_header(
        self, client, mock_language_model_service, mock_image_generation_service
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
        (§12 of the v5.0.0 specification)."""
        response = await client.get("/health/ready")

        assert response.headers.get("pragma") == "no-cache"


class TestMetricsRoutes:
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
        assert latency["count"] >= 1
        assert latency["minimum_milliseconds"] >= 0

    @pytest.mark.asyncio
    async def test_metrics_has_cache_control_header(self, client):
        """The metrics endpoint must include Cache-Control: no-store, no-cache."""
        response = await client.get("/metrics")

        assert response.headers.get("cache-control") == "no-store, no-cache"

    @pytest.mark.asyncio
    async def test_metrics_has_pragma_no_cache_header(self, client):
        """The metrics endpoint must include Pragma: no-cache for
        backward-compatible cache suppression with HTTP/1.0 intermediaries
        (§12 of the v5.0.0 specification)."""
        response = await client.get("/metrics")

        assert response.headers.get("pragma") == "no-cache"

    @pytest.mark.asyncio
    async def test_metrics_fallback_when_collector_missing(self):
        """Return empty metrics when metrics_collector is not on app.state."""
        app = fastapi.FastAPI()
        app.add_middleware(
            application.middleware.CorrelationIdMiddleware,
        )
        app.include_router(application.routes.health_routes.health_router)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/metrics")

        assert response.status_code == 200
        body = response.json()
        assert body == {"request_counts": {}, "request_latencies": {}}
