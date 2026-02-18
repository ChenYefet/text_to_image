"""Tests for the POST /v1/images/generations endpoint."""

import pytest

import application.exceptions


class TestImageGenerationRoutes:

    @pytest.mark.asyncio
    async def test_success(self, client, mock_image_generation_service):
        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset"},
        )

        assert response.status_code == 200
        body = response.json()
        assert "created_at_unix_timestamp" in body
        assert len(body["data"]) == 1
        assert body["data"][0]["base64_encoded_image"] == "base64encodedimage"
        assert body["data"][0]["content_type"] == "image/png"

    @pytest.mark.asyncio
    async def test_with_enhancer(
        self,
        client,
        mock_language_model_service,
        mock_image_generation_service,
    ):
        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "use_enhancer": True},
        )

        assert response.status_code == 200
        mock_language_model_service.enhance_prompt.assert_awaited_once()
        mock_image_generation_service.generate_images.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_without_enhancer(
        self,
        client,
        mock_language_model_service,
        mock_image_generation_service,
    ):
        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "use_enhancer": False},
        )

        assert response.status_code == 200
        mock_language_model_service.enhance_prompt.assert_not_awaited()
        mock_image_generation_service.generate_images.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalid_size(self, client):
        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "size": "999x999"},
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_n(self, client):
        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "n": 0},
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_missing_prompt(self, client):
        response = await client.post(
            "/v1/images/generations",
            json={},
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_service_unavailable(
        self, client, mock_image_generation_service
    ):
        mock_image_generation_service.generate_images.side_effect = (
            application.exceptions.ImageGenerationServiceUnavailableError(
                detail="Pipeline not loaded"
            )
        )

        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset"},
        )

        assert response.status_code == 502
        assert "Pipeline not loaded" in response.json()["error"]

    @pytest.mark.asyncio
    async def test_generation_error(
        self, client, mock_image_generation_service
    ):
        mock_image_generation_service.generate_images.side_effect = (
            application.exceptions.ImageGenerationError(
                detail="No images returned"
            )
        )

        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset"},
        )

        assert response.status_code == 500
        assert "No images returned" in response.json()["error"]
