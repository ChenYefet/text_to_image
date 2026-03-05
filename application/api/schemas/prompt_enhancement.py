"""
Pydantic schemas for the prompt enhancement endpoint.

These schemas define the request and response bodies for
POST /v1/prompts/enhance, aligned with the v5.2.6 specification
(Section 11 — Data Model and Schema Definition).
"""

import pydantic

MAXIMUM_NUMBER_OF_CHARACTERS_IN_PROMPT = 2000


class PromptEnhancementRequest(pydantic.BaseModel):
    """
    Request body for the POST /v1/prompts/enhance endpoint.

    The client supplies a raw text prompt which will be sent to the
    large language model for enhancement.
    """

    prompt: str = pydantic.Field(
        ...,
        min_length=1,
        max_length=MAXIMUM_NUMBER_OF_CHARACTERS_IN_PROMPT,
        pattern=r".*\S.*",
        description=(
            f"The original user-supplied prompt to be enhanced by the large language model."
            f" Must be between 1 and {MAXIMUM_NUMBER_OF_CHARACTERS_IN_PROMPT} characters and contain at"
            " least one non-whitespace character."
        ),
        examples=["A cat sitting on a windowsill"],
    )

    model_config = pydantic.ConfigDict(extra="forbid")


class PromptEnhancementResponse(pydantic.BaseModel):
    """
    Response body for the POST /v1/prompts/enhance endpoint.

    Contains the original prompt echoed back for client-side correlation,
    the enhanced version produced by the large language model, and a Unix
    timestamp indicating when the enhancement completed.
    """

    original_prompt: str = pydantic.Field(
        ...,
        min_length=1,
        description=(
            "The user-provided prompt exactly as received by the service,"
            " echoed for client-side correlation without requiring the client"
            " to maintain its own request bookkeeping."
        ),
    )

    enhanced_prompt: str = pydantic.Field(
        ...,
        min_length=1,
        description=(
            "Enhanced version of the input prompt, optimised for"
            " text-to-image generation. This value is the llama.cpp response"
            " content after leading and trailing whitespace has been stripped."
        ),
    )

    created: int = pydantic.Field(
        ...,
        description=("Unix timestamp (seconds since epoch) indicating when the prompt enhancement completed."),
    )

    model_config = pydantic.ConfigDict(extra="forbid")
