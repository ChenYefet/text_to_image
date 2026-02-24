"""Tests for application/models.py — request and response Pydantic models."""

import pydantic
import pytest

import application.models


class TestPromptEnhancementRequest:
    def test_valid_prompt(self) -> None:
        request = application.models.PromptEnhancementRequest(prompt="A cat")
        assert request.prompt == "A cat"

    def test_empty_prompt_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            application.models.PromptEnhancementRequest(prompt="")

    def test_too_long_prompt_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            application.models.PromptEnhancementRequest(prompt="x" * 2001)

    def test_whitespace_only_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            application.models.PromptEnhancementRequest(prompt="   ")

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            application.models.PromptEnhancementRequest(prompt="A cat", foo="bar")


class TestImageGenerationRequest:
    def test_defaults(self) -> None:
        request = application.models.ImageGenerationRequest(prompt="A sunset")
        assert request.use_enhancer is False
        assert request.number_of_images == 1
        assert request.size == "512x512"
        assert request.seed is None
        assert request.response_format == "base64_json"

    def test_alias_n(self) -> None:
        request = application.models.ImageGenerationRequest.model_validate({"prompt": "x", "n": 3})
        assert request.number_of_images == 3

    @pytest.mark.parametrize("size", ["512x512", "768x768", "1024x1024"])
    def test_valid_sizes(self, size: str) -> None:
        request = application.models.ImageGenerationRequest(prompt="x", size=size)
        assert request.size == size

    def test_invalid_size(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            application.models.ImageGenerationRequest(prompt="x", size="999x999")

    def test_256x256_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            application.models.ImageGenerationRequest(prompt="x", size="256x256")

    def test_n_too_low(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            application.models.ImageGenerationRequest.model_validate({"prompt": "x", "n": 0})

    def test_n_too_high(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            application.models.ImageGenerationRequest.model_validate({"prompt": "x", "n": 5})

    def test_parse_image_width_and_height(self) -> None:
        request = application.models.ImageGenerationRequest(prompt="x", size="768x768")
        assert request.parse_image_width_and_height() == (768, 768)

    def test_too_long_prompt_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            application.models.ImageGenerationRequest(prompt="x" * 2001)

    def test_whitespace_only_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            application.models.ImageGenerationRequest(prompt="   ")

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            application.models.ImageGenerationRequest(prompt="A sunset", foo="bar")

    # ── Seed field validation ──

    def test_seed_null_accepted(self) -> None:
        request = application.models.ImageGenerationRequest(prompt="A sunset", seed=None)
        assert request.seed is None

    def test_seed_zero_accepted(self) -> None:
        request = application.models.ImageGenerationRequest(prompt="A sunset", seed=0)
        assert request.seed == 0

    def test_seed_maximum_accepted(self) -> None:
        request = application.models.ImageGenerationRequest(
            prompt="A sunset",
            seed=application.models.MAXIMUM_SEED_VALUE,
        )
        assert request.seed == application.models.MAXIMUM_SEED_VALUE

    def test_seed_above_maximum_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            application.models.ImageGenerationRequest(
                prompt="A sunset",
                seed=application.models.MAXIMUM_SEED_VALUE + 1,
            )

    def test_seed_negative_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            application.models.ImageGenerationRequest(prompt="A sunset", seed=-1)

    # ── Response format field validation ──

    def test_response_format_base64_json_accepted(self) -> None:
        request = application.models.ImageGenerationRequest(
            prompt="A sunset",
            response_format="base64_json",
        )
        assert request.response_format == "base64_json"

    def test_response_format_url_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            application.models.ImageGenerationRequest(
                prompt="A sunset",
                response_format="url",
            )

    def test_response_format_invalid_value_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            application.models.ImageGenerationRequest(
                prompt="A sunset",
                response_format="png",
            )


class TestPromptEnhancementResponse:
    def test_instantiation(self) -> None:
        response = application.models.PromptEnhancementResponse(
            original_prompt="A cat",
            enhanced_prompt="An enhanced cat",
            created=1740268800,
        )
        assert response.original_prompt == "A cat"
        assert response.enhanced_prompt == "An enhanced cat"
        assert response.created == 1740268800

    def test_all_fields_required(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            application.models.PromptEnhancementResponse(enhanced_prompt="An enhanced cat")  # type: ignore[call-arg]

    def test_original_prompt_echoed_exactly(self) -> None:
        """The original prompt includes any leading/trailing whitespace."""
        prompt_with_spaces = "  A cat with spaces  "
        response = application.models.PromptEnhancementResponse(
            original_prompt=prompt_with_spaces,
            enhanced_prompt="Enhanced cat",
            created=1740268800,
        )
        assert response.original_prompt == prompt_with_spaces


class TestGeneratedImageData:
    def test_instantiation(self) -> None:
        data = application.models.GeneratedImageData(base64_json="abc123")
        assert data.base64_json == "abc123"

    def test_null_base64_json_for_filtered_image(self) -> None:
        data = application.models.GeneratedImageData(base64_json=None)
        assert data.base64_json is None


class TestImageGenerationWarning:
    def test_instantiation(self) -> None:
        warning = application.models.ImageGenerationWarning(
            index=0,
            reason="content_policy_violation",
        )
        assert warning.index == 0
        assert warning.reason == "content_policy_violation"

    def test_negative_index_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            application.models.ImageGenerationWarning(index=-1, reason="test")


class TestImageGenerationResponse:
    def test_instantiation_with_required_fields(self) -> None:
        image_data = application.models.GeneratedImageData(base64_json="abc123")
        response = application.models.ImageGenerationResponse(
            created=1700000000,
            seed=42,
            data=[image_data],
        )
        assert response.created == 1700000000
        assert response.seed == 42
        assert len(response.data) == 1

    def test_enhanced_prompt_defaults_to_none(self) -> None:
        image_data = application.models.GeneratedImageData(base64_json="abc123")
        response = application.models.ImageGenerationResponse(
            created=1700000000,
            seed=42,
            data=[image_data],
        )
        assert response.enhanced_prompt is None

    def test_enhanced_prompt_included_when_set(self) -> None:
        image_data = application.models.GeneratedImageData(base64_json="abc123")
        response = application.models.ImageGenerationResponse(
            created=1700000000,
            seed=42,
            data=[image_data],
            enhanced_prompt="A detailed sunset prompt",
        )
        assert response.enhanced_prompt == "A detailed sunset prompt"

    def test_warnings_defaults_to_none(self) -> None:
        image_data = application.models.GeneratedImageData(base64_json="abc123")
        response = application.models.ImageGenerationResponse(
            created=1700000000,
            seed=42,
            data=[image_data],
        )
        assert response.warnings is None

    def test_warnings_included_when_set(self) -> None:
        image_data = application.models.GeneratedImageData(base64_json=None)
        warning = application.models.ImageGenerationWarning(
            index=0,
            reason="content_policy_violation",
        )
        response = application.models.ImageGenerationResponse(
            created=1700000000,
            seed=42,
            data=[image_data],
            warnings=[warning],
        )
        assert response.warnings is not None
        assert len(response.warnings) == 1
        assert response.warnings[0].reason == "content_policy_violation"

    def test_exclude_unset_omits_optional_fields(self) -> None:
        """When enhanced_prompt and warnings are not set, they should be
        excluded from the serialised dict when using exclude_unset=True."""
        image_data = application.models.GeneratedImageData(base64_json="abc123")
        response = application.models.ImageGenerationResponse(
            created=1700000000,
            seed=42,
            data=[image_data],
        )
        serialised = response.model_dump(exclude_unset=True)
        assert "enhanced_prompt" not in serialised
        assert "warnings" not in serialised

    def test_exclude_unset_includes_set_optional_fields(self) -> None:
        """When enhanced_prompt is explicitly set, it should appear in the
        serialised dict even with exclude_unset=True."""
        image_data = application.models.GeneratedImageData(base64_json="abc123")
        response = application.models.ImageGenerationResponse(
            created=1700000000,
            seed=42,
            data=[image_data],
            enhanced_prompt="An enhanced sunset",
        )
        serialised = response.model_dump(exclude_unset=True)
        assert "enhanced_prompt" in serialised
        assert serialised["enhanced_prompt"] == "An enhanced sunset"

    def test_empty_data_list_rejected(self) -> None:
        """The data array must contain at least one element (minItems: 1
        per §11 of the v5.0.0 specification)."""
        with pytest.raises(pydantic.ValidationError):
            application.models.ImageGenerationResponse(
                created=1700000000,
                seed=42,
                data=[],
            )

    def test_data_list_exceeding_maximum_rejected(self) -> None:
        """The data array must not exceed four elements (maxItems: 4
        per §11 of the v5.0.0 specification)."""
        five_images = [application.models.GeneratedImageData(base64_json="abc") for _ in range(5)]
        with pytest.raises(pydantic.ValidationError):
            application.models.ImageGenerationResponse(
                created=1700000000,
                seed=42,
                data=five_images,
            )

    def test_data_list_at_maximum_accepted(self) -> None:
        """Exactly four images (the maximum) must be accepted."""
        four_images = [application.models.GeneratedImageData(base64_json="abc") for _ in range(4)]
        response = application.models.ImageGenerationResponse(
            created=1700000000,
            seed=42,
            data=four_images,
        )
        assert len(response.data) == 4

    def test_seed_is_required(self) -> None:
        image_data = application.models.GeneratedImageData(base64_json="abc123")
        with pytest.raises(pydantic.ValidationError):
            application.models.ImageGenerationResponse(
                created=1700000000,
                data=[image_data],
            )  # type: ignore[call-arg]


class TestErrorDetail:
    def test_instantiation(self) -> None:
        detail = application.models.ErrorDetail(
            code="internal_server_error",
            message="Something went wrong",
            correlation_id="abc-123",
        )
        assert detail.code == "internal_server_error"
        assert detail.message == "Something went wrong"
        assert detail.details is None
        assert detail.correlation_id == "abc-123"

    def test_with_string_details(self) -> None:
        detail = application.models.ErrorDetail(
            code="request_validation_failed",
            message="Invalid request",
            details="field 'prompt' is required",
            correlation_id="abc-123",
        )
        assert detail.details == "field 'prompt' is required"

    def test_with_list_details(self) -> None:
        validation_errors = [
            {"loc": ["body", "prompt"], "msg": "Field required", "type": "missing"},
        ]
        detail = application.models.ErrorDetail(
            code="request_validation_failed",
            message="Request body failed schema validation.",
            details=validation_errors,
            correlation_id="abc-123",
        )
        assert isinstance(detail.details, list)
        assert len(detail.details) == 1


class TestErrorResponse:
    def test_instantiation(self) -> None:
        error_response = application.models.ErrorResponse(
            error=application.models.ErrorDetail(
                code="internal_server_error",
                message="Something went wrong",
                correlation_id="abc-123",
            )
        )
        assert error_response.error.code == "internal_server_error"
        assert error_response.error.message == "Something went wrong"
        assert error_response.error.correlation_id == "abc-123"
