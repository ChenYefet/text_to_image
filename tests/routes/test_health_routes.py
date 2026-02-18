"""Tests for the GET /health endpoint."""

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
