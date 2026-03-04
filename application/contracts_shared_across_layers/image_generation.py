"""
Shared data contracts for image generation used by both the API layer and the
service layer.

These Pydantic models and constants were extracted from the API schemas module
to eliminate a reverse dependency: the service layer previously imported
from the API layer, violating the specification's unidirectional dependency
rule (§13 — Dependencies flow strictly from left to right).

Both the API endpoint (which uses ``ImageGenerationResponse`` as its
``response_model``) and the service layer (which constructs response
instances) import from this shared module.
"""

import pydantic

# ──────────────────────────────────────────────────────────────────────────────
#  Shared Constants
# ──────────────────────────────────────────────────────────────────────────────

MAXIMUM_NUMBER_OF_IMAGES_PER_REQUEST = 4

MAXIMUM_SEED_VALUE = 4_294_967_295  # Unsigned 32-bit integer maximum (2^32 - 1)


# ──────────────────────────────────────────────────────────────────────────────
#  Response Models
# ──────────────────────────────────────────────────────────────────────────────


class GeneratedImageData(pydantic.BaseModel):
    """
    A single generated image represented as a base64-encoded string.

    The ``base64_json`` field is null when the image was filtered by the
    content safety checker (not-safe-for-work filtering).
    """

    base64_json: str | None = pydantic.Field(
        ...,
        description=(
            "The generated image encoded as a base64 PNG string using the"
            " standard base64 alphabet (RFC 4648 \u00a74). Null if the image was"
            " filtered by the content safety checker."
        ),
    )

    model_config = pydantic.ConfigDict(extra="forbid")


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

    model_config = pydantic.ConfigDict(extra="forbid")


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
        ge=0,
        description=(
            "The seed used for image generation. Echoes the request seed if"
            " provided; otherwise, the randomly generated seed."
        ),
    )

    data: list[GeneratedImageData] = pydantic.Field(
        ...,
        min_length=1,
        max_length=MAXIMUM_NUMBER_OF_IMAGES_PER_REQUEST,
        description=("Array of generated images. Array length equals the request 'n' parameter."),
    )

    enhanced_prompt: str | None = pydantic.Field(
        default=None,
        min_length=1,
        description=(
            "The enhanced prompt used for image generation, present only when"
            " the request specified use_enhancer: true. Omitted entirely when"
            " use_enhancer was false or omitted."
        ),
    )

    warnings: list[ImageGenerationWarning] | None = pydantic.Field(
        default=None,
        description=(
            "Present only when the content safety checker has flagged one or"
            " more images. Lists the indices of filtered images."
        ),
    )

    model_config = pydantic.ConfigDict(extra="forbid")
