"""
Route definitions for the prompt enhancement endpoint.

This module defines the POST /v1/prompts/enhance endpoint, which accepts
a raw text prompt and returns an enhanced version optimised for
high-quality image generation.
"""

import typing

import fastapi

import application.dependencies
import application.models
import application.services.language_model_service

prompt_enhancement_router = fastapi.APIRouter(
    prefix="/v1/prompts",
    tags=["Prompt Enhancement"],
)


@prompt_enhancement_router.post(
    "/enhance",
    response_model=application.models.PromptEnhancementResponse,
    summary="Enhance a text prompt using the language model",
    description=(
        "Accepts a raw text prompt and returns an enhanced version "
        "optimised for high-quality image generation. The enhancement "
        "is performed by the llama.cpp language model running in "
        "OpenAI-compatible mode."
    ),
    status_code=200,
)
async def handle_prompt_enhancement_request(
    prompt_enhancement_request: application.models.PromptEnhancementRequest,
    language_model_service: typing.Annotated[
        application.services.language_model_service.LanguageModelService,
        fastapi.Depends(
            application.dependencies.get_language_model_service,
        ),
    ],
) -> application.models.PromptEnhancementResponse:
    """
    Enhance the provided prompt by forwarding it to the language model.

    The language model receives the original prompt together with a system
    instruction that guides it to add descriptive details about lighting,
    composition, style, and colour palette.
    """
    enhanced_prompt_text = await language_model_service.enhance_prompt(
        original_prompt=prompt_enhancement_request.prompt,
    )

    return application.models.PromptEnhancementResponse(
        enhanced_prompt=enhanced_prompt_text,
    )
