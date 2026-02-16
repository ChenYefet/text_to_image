"""
Pydantic models for request validation and response serialisation.

All request models enforce strict validation rules. All response models
use fully descriptive field names to satisfy the self-documenting
code requirement.
"""

import pydantic


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
        max_length=4096,
        description=(
            "The original user-supplied prompt to be enhanced by the "
            "language model. Must be between 1 and 4 096 characters."
        ),
        examples=["A cat sitting on a windowsill"],
    )


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
        max_length=4096,
        description=(
            "The text prompt describing the desired image. "
            "Must be between 1 and 4 096 characters."
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
        le=4,
        alias="n",
        description=(
            "The number of images to generate in a single request. "
            "Accepts values from 1 to 4 inclusive."
        ),
    )

    size: str = pydantic.Field(
        default="512x512",
        description=(
            "The dimensions of the generated image in WIDTHxHEIGHT format. "
            "Supported sizes: 256x256, 512x512, 768x768, 1024x1024."
        ),
        examples=["256x256", "512x512", "768x768", "1024x1024"],
    )

    @pydantic.field_validator("size")
    @classmethod
    def validate_image_size_dimensions(cls, image_size_value: str) -> str:
        """Validate that the requested image size is among the supported dimensions."""
        supported_image_dimensions = {
            "256x256",
            "512x512",
            "768x768",
            "1024x1024",
        }
        if image_size_value not in supported_image_dimensions:
            raise ValueError(
                f"The image size '{image_size_value}' is not supported. "
                f"Supported sizes are: "
                f"{', '.join(sorted(supported_image_dimensions))}."
            )
        return image_size_value

    def parse_image_width_and_height(self) -> tuple[int, int]:
        """Parse the size string into separate width and height integer values."""
        width_string, height_string = self.size.split("x")
        return int(width_string), int(height_string)

    model_config = pydantic.ConfigDict(populate_by_name=True)


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

    base64_encoded_image: str = pydantic.Field(
        ...,
        description="The generated image encoded as a base64 string.",
    )

    content_type: str = pydantic.Field(
        default="image/png",
        description="The MIME type of the generated image.",
    )


class ImageGenerationResponse(pydantic.BaseModel):
    """
    Response body for the POST /v1/images/generations endpoint.

    Contains a Unix timestamp and a list of generated images.
    """

    created_at_unix_timestamp: int = pydantic.Field(
        ...,
        description=(
            "The Unix timestamp (in seconds) indicating when the "
            "images were generated."
        ),
    )

    data: list[GeneratedImageData] = pydantic.Field(
        ...,
        description="A list of generated image objects.",
    )


class ErrorResponse(pydantic.BaseModel):
    """
    Standardised error response returned for all error conditions.

    Every error response from this service follows this structure to
    ensure clients can rely on a consistent error format.
    """

    error: str = pydantic.Field(
        ...,
        description="A human-readable message describing what went wrong.",
    )

    status_code: int = pydantic.Field(
        ...,
        description="The HTTP status code associated with this error.",
    )
