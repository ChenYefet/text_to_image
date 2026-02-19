"""Tests for the GET /health and GET /health/ready endpoints."""

import pytest


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
