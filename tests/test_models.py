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
            application.models.PromptEnhancementRequest(prompt="x" * 2001)

    def test_whitespace_only_rejected(self):
        with pytest.raises(pydantic.ValidationError):
            application.models.PromptEnhancementRequest(prompt="   ")

    def test_extra_fields_rejected(self):
        with pytest.raises(pydantic.ValidationError):
            application.models.PromptEnhancementRequest(
                prompt="A cat", foo="bar"
            )


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
        "size", ["512x512", "768x768", "1024x1024"]
    )
    def test_valid_sizes(self, size):
        req = application.models.ImageGenerationRequest(prompt="x", size=size)
        assert req.size == size

    def test_invalid_size(self):
        with pytest.raises(pydantic.ValidationError):
            application.models.ImageGenerationRequest(prompt="x", size="999x999")

    def test_256x256_rejected(self):
        with pytest.raises(pydantic.ValidationError):
            application.models.ImageGenerationRequest(prompt="x", size="256x256")

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

    def test_too_long_prompt_rejected(self):
        with pytest.raises(pydantic.ValidationError):
            application.models.ImageGenerationRequest(prompt="x" * 2001)

    def test_whitespace_only_rejected(self):
        with pytest.raises(pydantic.ValidationError):
            application.models.ImageGenerationRequest(prompt="   ")

    def test_extra_fields_rejected(self):
        with pytest.raises(pydantic.ValidationError):
            application.models.ImageGenerationRequest(
                prompt="A sunset", foo="bar"
            )


class TestPromptEnhancementResponse:

    def test_instantiation(self):
        resp = application.models.PromptEnhancementResponse(
            enhanced_prompt="An enhanced cat"
        )
        assert resp.enhanced_prompt == "An enhanced cat"


class TestGeneratedImageData:

    def test_instantiation(self):
        data = application.models.GeneratedImageData(b64_json="abc123")
        assert data.b64_json == "abc123"


class TestImageGenerationResponse:

    def test_instantiation(self):
        image_data = application.models.GeneratedImageData(
            b64_json="abc123"
        )
        resp = application.models.ImageGenerationResponse(
            created=1700000000,
            data=[image_data],
        )
        assert resp.created == 1700000000
        assert len(resp.data) == 1


class TestErrorDetail:

    def test_instantiation(self):
        detail = application.models.ErrorDetail(
            code="internal_server_error",
            message="Something went wrong",
            correlation_id="abc-123",
        )
        assert detail.code == "internal_server_error"
        assert detail.message == "Something went wrong"
        assert detail.details is None
        assert detail.correlation_id == "abc-123"

    def test_with_details(self):
        detail = application.models.ErrorDetail(
            code="request_validation_failed",
            message="Invalid request",
            details="field 'prompt' is required",
            correlation_id="abc-123",
        )
        assert detail.details == "field 'prompt' is required"


class TestErrorResponse:

    def test_instantiation(self):
        err = application.models.ErrorResponse(
            error=application.models.ErrorDetail(
                code="internal_server_error",
                message="Something went wrong",
                correlation_id="abc-123",
            )
        )
        assert err.error.code == "internal_server_error"
        assert err.error.message == "Something went wrong"
        assert err.error.correlation_id == "abc-123"
