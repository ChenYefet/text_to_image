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
        mock_language_model_service.enhance_prompt.assert_awaited_once_with(
            original_prompt="A cat sitting on a windowsill"
        )

    @pytest.mark.asyncio
    async def test_empty_body(self, client):
        response = await client.post(
            "/v1/prompts/enhance",
            json={},
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_empty_prompt(self, client):
        response = await client.post(
            "/v1/prompts/enhance",
            json={"prompt": ""},
        )

        assert response.status_code == 400

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
        assert "Server down" in response.json()["error"]

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

        assert response.status_code == 500
        assert "Malformed response" in response.json()["error"]
