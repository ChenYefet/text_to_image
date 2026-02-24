"""
Pydantic models for request validation and response serialisation.

All request models enforce strict validation rules aligned with the v5.0.0
specification (Section 11 — Data Model and Schema Definition). All response
models use field names matching the API contract exactly.

Conditional field presence
--------------------------
Some response fields are conditionally present (omitted entirely from the
JSON payload when not applicable, rather than set to ``null``). This is
achieved using ``Optional`` defaults combined with
``response_model_exclude_unset=True`` on the FastAPI route decorator:

- ``ImageGenerationResponse.enhanced_prompt``: present only when
  ``use_enhancer`` was ``true`` in the request.
- ``ImageGenerationResponse.warnings``: present only when the content safety
  checker has flagged one or more images.
"""

import pydantic

# ──────────────────────────────────────────────────────────────────────────────
#  Request Constants
# ──────────────────────────────────────────────────────────────────────────────

MAXIMUM_PROMPT_LENGTH = 2000
MAXIMUM_IMAGES_PER_REQUEST = 4
DEFAULT_IMAGE_SIZE = "512x512"
SUPPORTED_IMAGE_SIZES = {"512x512", "768x768", "1024x1024"}

MAXIMUM_SEED_VALUE = 4_294_967_295  # Unsigned 32-bit integer maximum (2^32 - 1)

SUPPORTED_RESPONSE_FORMATS = {"base64_json"}

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
        max_length=MAXIMUM_PROMPT_LENGTH,
        pattern=r".*\S.*",
        description=(
            f"The original user-supplied prompt to be enhanced by the "
            f"language model. Must be between 1 and "
            f"{MAXIMUM_PROMPT_LENGTH} characters and contain at least one "
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
        max_length=MAXIMUM_PROMPT_LENGTH,
        pattern=r".*\S.*",
        description=(
            f"The text prompt describing the desired image. "
            f"Must be between 1 and "
            f"{MAXIMUM_PROMPT_LENGTH} characters and contain at "
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
        le=MAXIMUM_IMAGES_PER_REQUEST,
        alias="n",
        description=(
            f"The number of images to generate in a single request. "
            f"Accepts values from 1 to "
            f"{MAXIMUM_IMAGES_PER_REQUEST} inclusive."
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

    seed: int | None = pydantic.Field(
        default=None,
        ge=0,
        le=MAXIMUM_SEED_VALUE,
        description=(
            "Random seed for reproducible generation. When null or omitted, "
            "a random seed is used. The seed used is always returned in the "
            "response. Seed 0 is a valid deterministic seed with no special "
            "semantics."
        ),
    )

    response_format: str = pydantic.Field(
        default="base64_json",
        description=(
            "Format of the image data in the response. Currently only "
            "'base64_json' (base64-encoded inline) is supported. Reserved "
            "for future extension to 'url' (object-storage reference)."
        ),
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

    @pydantic.field_validator("response_format")
    @classmethod
    def validate_response_format(cls, response_format_value: str) -> str:
        """Validate that the response format is among the supported values."""
        if response_format_value not in SUPPORTED_RESPONSE_FORMATS:
            raise ValueError(
                f"The response format '{response_format_value}' is not supported. "
                f"Supported formats are: "
                f"{', '.join(sorted(SUPPORTED_RESPONSE_FORMATS))}."
            )
        return response_format_value

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

    Contains the original prompt echoed back for client-side correlation,
    the enhanced version produced by the language model, and a Unix
    timestamp indicating when the enhancement completed.
    """

    original_prompt: str = pydantic.Field(
        ...,
        description=(
            "The user-provided prompt exactly as received by the service, "
            "echoed for client-side correlation without requiring the client "
            "to maintain its own request bookkeeping."
        ),
    )

    enhanced_prompt: str = pydantic.Field(
        ...,
        description=(
            "Enhanced version of the input prompt, optimised for "
            "text-to-image generation. This value is the llama.cpp response "
            "content after leading and trailing whitespace has been stripped."
        ),
    )

    created: int = pydantic.Field(
        ...,
        description=("Unix timestamp (seconds since epoch) indicating when the prompt enhancement completed."),
    )


class GeneratedImageData(pydantic.BaseModel):
    """
    A single generated image represented as a base64-encoded string.

    The ``base64_json`` field is null when the image was filtered by the
    content safety checker (not-safe-for-work filtering).
    """

    base64_json: str | None = pydantic.Field(
        ...,
        description=(
            "The generated image encoded as a base64 PNG string using the "
            "standard base64 alphabet (RFC 4648 §4). Null if the image was "
            "filtered by the content safety checker."
        ),
    )


class ImageGenerationWarning(pydantic.BaseModel):
    """
    A warning about a specific generated image that was flagged by the
    content safety checker (not-safe-for-work filtering).
    """

    index: int = pydantic.Field(
        ...,
        ge=0,
        description=("Zero-based index into the data array of the affected image."),
    )

    reason: str = pydantic.Field(
        ...,
        description=("Machine-readable reason for the warning (for example, 'content_policy_violation')."),
    )


class ImageGenerationResponse(pydantic.BaseModel):
    """
    Response body for the POST /v1/images/generations endpoint.

    Contains a Unix timestamp, the seed used for generation, a list of
    generated images, and optional fields for the enhanced prompt and
    content safety warnings.

    Conditional field presence (managed via ``exclude_unset=True``):
    - ``enhanced_prompt``: present only when ``use_enhancer`` was ``true``.
    - ``warnings``: present only when the content safety checker flagged images.
    """

    created: int = pydantic.Field(
        ...,
        description=("Unix timestamp (seconds since epoch) indicating when image generation completed."),
    )

    seed: int = pydantic.Field(
        ...,
        description=(
            "The seed used for image generation. Echoes the request seed "
            "if provided; otherwise, the randomly generated seed."
        ),
    )

    data: list[GeneratedImageData] = pydantic.Field(
        ...,
        min_length=1,
        max_length=MAXIMUM_IMAGES_PER_REQUEST,
        description=("Array of generated images. Array length equals the request 'n' parameter."),
    )

    enhanced_prompt: str | None = pydantic.Field(
        default=None,
        description=(
            "The enhanced prompt used for image generation, present only "
            "when the request specified use_enhancer: true. Omitted entirely "
            "when use_enhancer was false or omitted."
        ),
    )

    warnings: list[ImageGenerationWarning] | None = pydantic.Field(
        default=None,
        description=(
            "Present only when the content safety checker has flagged one or "
            "more images. Lists the indices of filtered images."
        ),
    )


# ──────────────────────────────────────────────────────────────────────────────
#  Error Models
# ──────────────────────────────────────────────────────────────────────────────


class ErrorDetail(pydantic.BaseModel):
    """
    Detailed error information nested inside the error response.

    The ``details`` field can be:
    - A descriptive string (for single-cause errors such as payload_too_large)
    - An array of validation error objects (for request_validation_failed)
    - Null or omitted when no additional context is available
    """

    code: str = pydantic.Field(
        ...,
        description="A machine-readable error code in snake_case format.",
    )

    message: str = pydantic.Field(
        ...,
        description=("A human-readable error description safe for display to end users."),
    )

    details: str | list | None = pydantic.Field(
        default=None,
        description=(
            "Additional context about the error, when available. May be a "
            "descriptive string, an array of validation error objects, or null."
        ),
    )

    correlation_id: str = pydantic.Field(
        ...,
        description=("UUID v4 correlation identifier matching the X-Correlation-ID response header."),
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
