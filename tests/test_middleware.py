"""Tests for application/middleware.py — CorrelationIdMiddleware."""

import uuid

import fastapi
import httpx
import pytest
import pytest_asyncio

import application.middleware


def _create_test_app():
    """Create a minimal FastAPI app with the correlation ID middleware."""
    app = fastapi.FastAPI()
    app.add_middleware(application.middleware.CorrelationIdMiddleware)

    @app.get("/test")
    async def test_endpoint(request: fastapi.Request):
        return {"correlation_id": request.state.correlation_id}

    @app.get("/error")
    async def error_endpoint():
        raise RuntimeError("something broke")

    return app


@pytest_asyncio.fixture
async def client():
    app = _create_test_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


class TestCorrelationIdMiddleware:
    @pytest.mark.asyncio
    async def test_header_present(self, client):
        response = await client.get("/test")
        assert "X-Correlation-ID" in response.headers

    @pytest.mark.asyncio
    async def test_valid_uuid(self, client):
        response = await client.get("/test")
        correlation_id = response.headers["X-Correlation-ID"]
        # Should not raise
        parsed = uuid.UUID(correlation_id, version=4)
        assert str(parsed) == correlation_id

    @pytest.mark.asyncio
    async def test_matches_request_state(self, client):
        response = await client.get("/test")
        header_id = response.headers["X-Correlation-ID"]
        body_id = response.json()["correlation_id"]
        assert header_id == body_id

    @pytest.mark.asyncio
    async def test_unique_per_request(self, client):
        response1 = await client.get("/test")
        response2 = await client.get("/test")
        id1 = response1.headers["X-Correlation-ID"]
        id2 = response2.headers["X-Correlation-ID"]
        assert id1 != id2

    @pytest.mark.asyncio
    async def test_unhandled_exception_returns_json_500(self, client):
        response = await client.get("/error")

        assert response.status_code == 500
        body = response.json()
        assert body["error"]["code"] == "internal_server_error"
        assert "X-Correlation-ID" in response.headers

    @pytest.mark.asyncio
    async def test_non_http_scope_passed_through(self):
        """Non-HTTP scopes (e.g. websocket, lifespan) bypass the middleware."""
        inner_called = False

        async def inner_app(scope, receive, send):
            nonlocal inner_called
            inner_called = True

        middleware = application.middleware.CorrelationIdMiddleware(inner_app)
        await middleware({"type": "lifespan"}, None, None)
        assert inner_called
