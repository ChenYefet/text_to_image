"""Tests for application/models.py — request and response Pydantic models."""

import pydantic
import pytest

import application.models


class TestPromptEnhancementRequest:

    def test_valid_prompt(self):
        req = application.models.PromptEnhancementRequest(prompt="A cat")
        assert req.prompt == "A cat"

    def test_empty_prompt_rejected(self):
        with pytest.raises(pydantic.ValidationError):
            application.models.PromptEnhancementRequest(prompt="")

    def test_too_long_prompt_rejected(self):
        with pytest.raises(pydantic.ValidationError):
            application.models.PromptEnhancementRequest(prompt="x" * 4097)


class TestImageGenerationRequest:

    def test_defaults(self):
        req = application.models.ImageGenerationRequest(prompt="A sunset")
        assert req.use_enhancer is False
        assert req.number_of_images == 1
        assert req.size == "512x512"

    def test_alias_n(self):
        req = application.models.ImageGenerationRequest.model_validate(
            {"prompt": "x", "n": 3}
        )
        assert req.number_of_images == 3

    @pytest.mark.parametrize(
        "size", ["256x256", "512x512", "768x768", "1024x1024"]
    )
    def test_valid_sizes(self, size):
        req = application.models.ImageGenerationRequest(prompt="x", size=size)
        assert req.size == size

    def test_invalid_size(self):
        with pytest.raises(pydantic.ValidationError):
            application.models.ImageGenerationRequest(prompt="x", size="999x999")

    def test_n_too_low(self):
        with pytest.raises(pydantic.ValidationError):
            application.models.ImageGenerationRequest.model_validate(
                {"prompt": "x", "n": 0}
            )

    def test_n_too_high(self):
        with pytest.raises(pydantic.ValidationError):
            application.models.ImageGenerationRequest.model_validate(
                {"prompt": "x", "n": 5}
            )

    def test_parse_image_width_and_height(self):
        req = application.models.ImageGenerationRequest(prompt="x", size="768x768")
        assert req.parse_image_width_and_height() == (768, 768)


class TestPromptEnhancementResponse:

    def test_instantiation(self):
        resp = application.models.PromptEnhancementResponse(
            enhanced_prompt="An enhanced cat"
        )
        assert resp.enhanced_prompt == "An enhanced cat"


class TestGeneratedImageData:

    def test_defaults(self):
        data = application.models.GeneratedImageData(base64_encoded_image="abc123")
        assert data.content_type == "image/png"
        assert data.base64_encoded_image == "abc123"


class TestImageGenerationResponse:

    def test_instantiation(self):
        image_data = application.models.GeneratedImageData(
            base64_encoded_image="abc123"
        )
        resp = application.models.ImageGenerationResponse(
            created_at_unix_timestamp=1700000000,
            data=[image_data],
        )
        assert resp.created_at_unix_timestamp == 1700000000
        assert len(resp.data) == 1


class TestErrorResponse:

    def test_instantiation(self):
        err = application.models.ErrorResponse(
            error="Something went wrong", status_code=500
        )
        assert err.error == "Something went wrong"
        assert err.status_code == 500
