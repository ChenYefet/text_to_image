"""
Route definitions for the prompt enhancement endpoint.

This module defines the POST /v1/prompts/enhance endpoint, which accepts
a raw text prompt and returns an enhanced version optimised for
high-quality image generation.

The response includes a ``Cache-Control: no-store`` header to prevent
intermediate proxies and CDNs from caching dynamically generated content
(§12 of the v5.0.0 specification, SHOULD-level advisory).
"""

import time
import typing

import fastapi
import fastapi.responses

import application.dependencies
import application.models
import application.rate_limiting
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
    responses={
        400: {
            "description": (
                "Bad Request — the request body contains invalid JSON "
                "(``invalid_request_json``) or fails schema validation "
                "(``request_validation_failed``)."
            ),
            "model": application.models.ErrorResponse,
        },
        413: {
            "description": (
                "Payload Too Large — the request body exceeds the "
                "configured maximum payload size "
                "(``payload_too_large``)."
            ),
            "model": application.models.ErrorResponse,
        },
        415: {
            "description": ("Unsupported Media Type — the ``Content-Type`` header is not ``application/json``."),
            "model": application.models.ErrorResponse,
        },
        429: {
            "description": (
                "Too Many Requests — the per-IP rate limit has been "
                "exceeded (``rate_limit_exceeded``). The ``Retry-After`` "
                "header indicates how long to wait before retrying."
            ),
            "model": application.models.ErrorResponse,
        },
        502: {
            "description": (
                "Bad Gateway — the llama.cpp language model server is "
                "unreachable or returned an error "
                "(``upstream_service_unavailable``)."
            ),
            "model": application.models.ErrorResponse,
        },
        504: {
            "description": (
                "Gateway Timeout — the request exceeded the configured "
                "end-to-end timeout ceiling (``request_timeout``)."
            ),
            "model": application.models.ErrorResponse,
        },
    },
)
@application.rate_limiting.inference_rate_limit
async def handle_prompt_enhancement_request(
    request: fastapi.Request,
    prompt_enhancement_request: application.models.PromptEnhancementRequest,
    language_model_service: typing.Annotated[
        application.services.language_model_service.LanguageModelService,
        fastapi.Depends(
            application.dependencies.get_language_model_service,
        ),
    ],
) -> fastapi.responses.JSONResponse:
    """
    Enhance the provided prompt by forwarding it to the language model.

    The language model receives the original prompt together with a system
    instruction that guides it to add descriptive details about lighting,
    composition, style, and colour palette.

    The response echoes the original prompt for client-side correlation
    and includes a Unix timestamp indicating when enhancement completed.

    The response includes a ``Cache-Control: no-store`` header to prevent
    intermediate proxies and CDNs from caching dynamically generated
    content (§12 of the v5.0.0 specification, SHOULD-level advisory).
    """
    enhanced_prompt_text = await language_model_service.enhance_prompt(
        original_prompt=prompt_enhancement_request.prompt,
    )

    response_model = application.models.PromptEnhancementResponse(
        original_prompt=prompt_enhancement_request.prompt,
        enhanced_prompt=enhanced_prompt_text,
        created=int(time.time()),
    )

    return fastapi.responses.JSONResponse(
        content=response_model.model_dump(),
        headers={"Cache-Control": "no-store"},
    )
