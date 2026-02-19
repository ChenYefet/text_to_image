"""Tests for the POST /v1/prompts/enhance endpoint."""

import pytest

import application.exceptions


class TestPromptEnhancementRoutes:

    @pytest.mark.asyncio
    async def test_success(self, client, mock_language_model_service):
        response = await client.post(
            "/v1/prompts/enhance",
            json={"prompt": "A cat sitting on a windowsill"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["enhanced_prompt"] == "Enhanced prompt"
        assert "X-Correlation-ID" in response.headers
        mock_language_model_service.enhance_prompt.assert_awaited_once_with(
            original_prompt="A cat sitting on a windowsill"
        )

    @pytest.mark.asyncio
    async def test_invalid_json(self, client):
        response = await client.post(
            "/v1/prompts/enhance",
            content=b"{not valid json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "invalid_request_json"
        assert "X-Correlation-ID" in response.headers

    @pytest.mark.asyncio
    async def test_empty_body(self, client):
        response = await client.post(
            "/v1/prompts/enhance",
            json={},
        )

        assert response.status_code == 400
        assert "X-Correlation-ID" in response.headers
        body = response.json()
        assert "code" in body["error"]
        assert "message" in body["error"]

    @pytest.mark.asyncio
    async def test_empty_prompt(self, client):
        response = await client.post(
            "/v1/prompts/enhance",
            json={"prompt": ""},
        )

        assert response.status_code == 400
        assert "X-Correlation-ID" in response.headers

    @pytest.mark.asyncio
    async def test_whitespace_only_prompt(self, client):
        response = await client.post(
            "/v1/prompts/enhance",
            json={"prompt": "   "},
        )

        assert response.status_code == 400
        assert "X-Correlation-ID" in response.headers

    @pytest.mark.asyncio
    async def test_extra_fields_rejected(self, client):
        response = await client.post(
            "/v1/prompts/enhance",
            json={"prompt": "A cat", "foo": "bar"},
        )

        assert response.status_code == 400
        assert "X-Correlation-ID" in response.headers

    @pytest.mark.asyncio
    async def test_service_unavailable(
        self, client, mock_language_model_service
    ):
        mock_language_model_service.enhance_prompt.side_effect = (
            application.exceptions.LanguageModelServiceUnavailableError(
                detail="Server down"
            )
        )

        response = await client.post(
            "/v1/prompts/enhance",
            json={"prompt": "A cat"},
        )

        assert response.status_code == 502
        assert "X-Correlation-ID" in response.headers
        body = response.json()
        assert body["error"]["code"] == "upstream_service_unavailable"
        assert "Server down" in body["error"]["message"]

    @pytest.mark.asyncio
    async def test_enhancement_error(
        self, client, mock_language_model_service
    ):
        mock_language_model_service.enhance_prompt.side_effect = (
            application.exceptions.PromptEnhancementError(
                detail="Malformed response"
            )
        )

        response = await client.post(
            "/v1/prompts/enhance",
            json={"prompt": "A cat"},
        )

        assert response.status_code == 502
        assert "X-Correlation-ID" in response.headers
        body = response.json()
        assert body["error"]["code"] == "upstream_service_unavailable"
        assert "Malformed response" in body["error"]["message"]
