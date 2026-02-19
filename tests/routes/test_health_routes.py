"""Tests for the GET /health, GET /health/ready, and GET /metrics endpoints."""

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


class TestReadinessRoutes:

    @pytest.mark.asyncio
    async def test_ready_when_services_available(
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
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            response = await client.get("/health/ready")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "not_ready"
        assert body["checks"]["image_generation"] == "unavailable"
        assert body["checks"]["language_model"] == "unavailable"


class TestMetricsRoutes:

    @pytest.mark.asyncio
    async def test_metrics_returns_200(self, client):
        response = await client.get("/metrics")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_metrics_contains_expected_keys(self, client):
        response = await client.get("/metrics")

        body = response.json()
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
        assert latency["min_ms"] >= 0

    @pytest.mark.asyncio
    async def test_metrics_fallback_when_collector_missing(self):
        """Return empty metrics when metrics_collector is not on app.state."""
        app = fastapi.FastAPI()
        app.add_middleware(
            application.middleware.CorrelationIdMiddleware,
        )
        app.include_router(application.routes.health_routes.health_router)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            response = await client.get("/metrics")

        assert response.status_code == 200
        body = response.json()
        assert body == {"request_counts": {}, "request_latencies": {}}
