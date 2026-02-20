"""
Pydantic models for request validation and response serialisation.

All request models enforce strict validation rules. All response models
use field names aligned with the API specification.
"""

import pydantic

# ──────────────────────────────────────────────────────────────────────────────
#  Request Constants
# ──────────────────────────────────────────────────────────────────────────────

PROMPT_MAX_LENGTH = 2000
MAX_IMAGES_PER_REQUEST = 4
DEFAULT_IMAGE_SIZE = "512x512"
SUPPORTED_IMAGE_SIZES = {"512x512", "768x768", "1024x1024"}

# ──────────────────────────────────────────────────────────────────────────────
#  Request Models
# ──────────────────────────────────────────────────────────────────────────────


class PromptEnhancementRequest(pydantic.BaseModel):
    """
    Request body for the POST /v1/prompts/enhance endpoint.

    The client supplies a raw text prompt which will be sent to the
    language model for enhancement.
    """

    prompt: str = pydantic.Field(
        ...,
        min_length=1,
        max_length=PROMPT_MAX_LENGTH,
        pattern=r".*\S.*",
        description=(
            f"The original user-supplied prompt to be enhanced by the "
            f"language model. Must be between 1 and "
            f"{PROMPT_MAX_LENGTH} characters and contain at least one "
            f"non-whitespace character."
        ),
        examples=["A cat sitting on a windowsill"],
    )

    model_config = pydantic.ConfigDict(extra="forbid")


class ImageGenerationRequest(pydantic.BaseModel):
    """
    Request body for the POST /v1/images/generations endpoint.

    The client supplies a text prompt together with generation parameters.
    When ``use_enhancer`` is true, the prompt is first enhanced by the
    language model before being forwarded to Stable Diffusion.
    """

    prompt: str = pydantic.Field(
        ...,
        min_length=1,
        max_length=PROMPT_MAX_LENGTH,
        pattern=r".*\S.*",
        description=(
            f"The text prompt describing the desired image. "
            f"Must be between 1 and "
            f"{PROMPT_MAX_LENGTH} characters and contain at "
            f"least one non-whitespace character."
        ),
        examples=["A sunset over a mountain range with vivid colours"],
    )

    use_enhancer: bool = pydantic.Field(
        default=False,
        description=(
            "When set to true, the prompt will first be enhanced by the "
            "language model before being sent to the image generation service."
        ),
    )

    number_of_images: int = pydantic.Field(
        default=1,
        ge=1,
        le=MAX_IMAGES_PER_REQUEST,
        alias="n",
        description=(
            f"The number of images to generate in a single request. "
            f"Accepts values from 1 to "
            f"{MAX_IMAGES_PER_REQUEST} inclusive."
        ),
    )

    size: str = pydantic.Field(
        default=DEFAULT_IMAGE_SIZE,
        description=(
            "The dimensions of the generated image in WIDTHxHEIGHT format. "
            f"Supported sizes: {', '.join(sorted(SUPPORTED_IMAGE_SIZES))}."
        ),
        examples=sorted(SUPPORTED_IMAGE_SIZES),
    )

    @pydantic.field_validator("size")
    @classmethod
    def validate_image_size_dimensions(cls, image_size_value: str) -> str:
        """Validate that the requested image size is among the supported dimensions."""
        if image_size_value not in SUPPORTED_IMAGE_SIZES:
            raise ValueError(
                f"The image size '{image_size_value}' is not supported. "
                f"Supported sizes are: "
                f"{', '.join(sorted(SUPPORTED_IMAGE_SIZES))}."
            )
        return image_size_value

    def parse_image_width_and_height(self) -> tuple[int, int]:
        """Parse the size string into separate width and height integer values."""
        width_string, height_string = self.size.split("x")
        return int(width_string), int(height_string)

    model_config = pydantic.ConfigDict(populate_by_name=True, extra="forbid")


# ──────────────────────────────────────────────────────────────────────────────
#  Response Models
# ──────────────────────────────────────────────────────────────────────────────


class PromptEnhancementResponse(pydantic.BaseModel):
    """
    Response body for the POST /v1/prompts/enhance endpoint.

    Contains the enhanced version of the original prompt as returned
    by the language model.
    """

    enhanced_prompt: str = pydantic.Field(
        ...,
        description="The prompt after enhancement by the language model.",
    )


class GeneratedImageData(pydantic.BaseModel):
    """
    A single generated image represented as a base64-encoded string.
    """

    b64_json: str = pydantic.Field(
        ...,
        description="The generated image encoded as a base64 string.",
    )


class ImageGenerationResponse(pydantic.BaseModel):
    """
    Response body for the POST /v1/images/generations endpoint.

    Contains a Unix timestamp and a list of generated images.
    """

    created: int = pydantic.Field(
        ...,
        description=("The Unix timestamp (in seconds) indicating when the images were generated."),
    )

    data: list[GeneratedImageData] = pydantic.Field(
        ...,
        description="A list of generated image objects.",
    )


class ErrorDetail(pydantic.BaseModel):
    """
    Detailed error information nested inside the error response.
    """

    code: str = pydantic.Field(
        ...,
        description="A machine-readable error code.",
    )

    message: str = pydantic.Field(
        ...,
        description="A human-readable message describing what went wrong.",
    )

    details: str | None = pydantic.Field(
        default=None,
        description="Additional details about the error, when available.",
    )

    correlation_id: str = pydantic.Field(
        ...,
        description="A unique identifier for this request, for tracing.",
    )


class ErrorResponse(pydantic.BaseModel):
    """
    Standardised error response returned for all error conditions.

    Every error response from this service follows this nested structure
    to ensure clients can rely on a consistent error format.
    """

    error: ErrorDetail = pydantic.Field(
        ...,
        description="An object containing error details.",
    )
