"""Tests for application/services/language_model_service.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import application.exceptions
import application.services.language_model_service


def _make_service(base_url="http://localhost:8080", timeout=30.0):
    return application.services.language_model_service.LanguageModelService(
        language_model_server_base_url=base_url,
        request_timeout_seconds=timeout,
    )


def _mock_json_response(content_text, status_code=200):
    """Create a mock httpx.Response with the standard chat-completion shape."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = {
        "choices": [{"message": {"content": content_text}}]
    }
    response.raise_for_status = MagicMock()
    return response


class TestEnhancePrompt:

    @pytest.mark.asyncio
    async def test_success(self):
        service = _make_service()
        mock_response = _mock_json_response("Enhanced prompt text")
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(return_value=mock_response)

        result = await service.enhance_prompt("A cat")

        assert result == "Enhanced prompt text"
        service.http_client.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_strips_whitespace(self):
        service = _make_service()
        mock_response = _mock_json_response("  Enhanced with spaces  ")
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(return_value=mock_response)

        result = await service.enhance_prompt("A cat")

        assert result == "Enhanced with spaces"

    @pytest.mark.asyncio
    async def test_connection_error(self):
        service = _make_service()
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        with pytest.raises(
            application.exceptions.LanguageModelServiceUnavailableError
        ):
            await service.enhance_prompt("A cat")

    @pytest.mark.asyncio
    async def test_http_status_error(self):
        service = _make_service()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Server error",
                request=MagicMock(),
                response=mock_response,
            )
        )

        with pytest.raises(
            application.exceptions.LanguageModelServiceUnavailableError
        ):
            await service.enhance_prompt("A cat")

    @pytest.mark.asyncio
    async def test_timeout(self):
        service = _make_service()
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(
            side_effect=httpx.TimeoutException("Timed out")
        )

        with pytest.raises(
            application.exceptions.LanguageModelServiceUnavailableError
        ):
            await service.enhance_prompt("A cat")

    @pytest.mark.asyncio
    async def test_malformed_response(self):
        service = _make_service()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"unexpected": "structure"}
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(application.exceptions.PromptEnhancementError):
            await service.enhance_prompt("A cat")

    @pytest.mark.asyncio
    async def test_empty_content(self):
        service = _make_service()
        mock_response = _mock_json_response("")
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(application.exceptions.PromptEnhancementError):
            await service.enhance_prompt("A cat")


class TestClose:

    @pytest.mark.asyncio
    async def test_close_calls_aclose(self):
        service = _make_service()
        service.http_client = AsyncMock()

        await service.close()

        service.http_client.aclose.assert_awaited_once()
