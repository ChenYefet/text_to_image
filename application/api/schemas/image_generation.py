"""
Pydantic schemas for the image generation endpoint.

These schemas define the request body for POST /v1/images/generations,
aligned with the v5.2.6 specification (Section 11 — Data Model and Schema
Definition).

The response models (``ImageGenerationResponse``, ``GeneratedImageData``,
``ImageGenerationWarning``) and shared constants (``MAXIMUM_SEED_VALUE``,
``MAXIMUM_NUMBER_OF_IMAGES_PER_REQUEST``) live in
``application.contracts_shared_across_layers.image_generation`` so that both
the API layer and the service layer can depend on them without creating a
reverse dependency.

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

import typing

import pydantic

from application.api.schemas.prompt_enhancement import (
    MAXIMUM_NUMBER_OF_CHARACTERS_IN_PROMPT,
)
from application.contracts_shared_across_layers.image_generation import (
    MAXIMUM_NUMBER_OF_IMAGES_PER_REQUEST,
    MAXIMUM_SEED_VALUE,
)

# ──────────────────────────────────────────────────────────────────────────────
#  Request Constants
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_IMAGE_SIZE: typing.Literal["512x512"] = "512x512"
SUPPORTED_IMAGE_SIZES = {"512x512", "768x768", "1024x1024"}

SUPPORTED_RESPONSE_FORMATS = {"base64_json"}

# ──────────────────────────────────────────────────────────────────────────────
#  Request Model
# ──────────────────────────────────────────────────────────────────────────────


class ImageGenerationRequest(pydantic.BaseModel):
    """
    Request body for the POST /v1/images/generations endpoint.

    The client supplies a text prompt together with generation parameters.
    When ``use_enhancer`` is true, the prompt is first enhanced by the
    large language model before being forwarded to Stable Diffusion.
    """

    prompt: str = pydantic.Field(
        ...,
        min_length=1,
        max_length=MAXIMUM_NUMBER_OF_CHARACTERS_IN_PROMPT,
        pattern=r".*\S.*",
        description=(
            "The text prompt describing the desired image. Must be between 1"
            f" and {MAXIMUM_NUMBER_OF_CHARACTERS_IN_PROMPT} characters and contain at least one"
            " non-whitespace character."
        ),
        examples=["A sunset over a mountain range with vivid colours"],
    )

    use_enhancer: bool = pydantic.Field(
        default=False,
        description=(
            "When set to true, the prompt will first be enhanced by the large"
            " language model before being sent to the image generation service."
        ),
    )

    number_of_images: int = pydantic.Field(
        default=1,
        ge=1,
        le=MAXIMUM_NUMBER_OF_IMAGES_PER_REQUEST,
        alias="n",
        description=(
            "The number of images to generate in a single request."
            f" Accepts values from 1 to {MAXIMUM_NUMBER_OF_IMAGES_PER_REQUEST} inclusive."
        ),
    )

    size: typing.Literal["512x512", "768x768", "1024x1024"] = pydantic.Field(
        default=DEFAULT_IMAGE_SIZE,
        description=(
            "The dimensions of the generated image in WIDTHxHEIGHT format."
            f" Supported sizes: {', '.join(sorted(SUPPORTED_IMAGE_SIZES))}."
        ),
        examples=sorted(SUPPORTED_IMAGE_SIZES),
    )

    seed: int | None = pydantic.Field(
        default=None,
        ge=0,
        le=MAXIMUM_SEED_VALUE,
        description=(
            "Random seed for reproducible generation. When null or omitted,"
            " a random seed is used. The seed used is always returned in the"
            " response. Seed 0 is a valid deterministic seed with no special"
            " semantics."
        ),
    )

    response_format: typing.Literal["base64_json"] = pydantic.Field(
        default="base64_json",
        description=(
            "Format of the image data in the response. Currently only"
            " 'base64_json' (base64-encoded inline) is supported. Reserved"
            " for future extension to 'url' (object-storage reference)."
        ),
    )

    def parse_width_and_height_of_image(self) -> tuple[int, int]:
        """Parse the size string into separate width and height integer values."""
        width_string, height_string = self.size.split("x")
        return int(width_string), int(height_string)

    model_config = pydantic.ConfigDict(populate_by_name=True, extra="forbid")
