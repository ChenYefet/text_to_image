"""
Route definitions for the image generation endpoint.

This module defines the POST /v1/images/generations endpoint, which
generates one or more images from a text prompt using Stable Diffusion.
When the ``use_enhancer`` flag is set to true, the prompt is first
enhanced by the large language model before image generation begins.

Per the v5.2.0 specification (Section 16 — Component Failure Degradation
Matrix), when ``use_enhancer`` is true and the llama.cpp server fails,
the service returns HTTP 502 (upstream_service_unavailable). There is no
silent fallback to the original prompt.

Admission control (NFR44)
-------------------------
The image generation operation is wrapped in the
``AdmissionControllerForImageGeneration`` context manager, which limits the
number of concurrent inference operations to the operator-configured
maximum (``maximum_number_of_concurrent_operations_of_image_generation``, default 1).  When the
limit is reached, additional requests are rejected immediately with
HTTP 429 (``service_busy``) and a ``Retry-After`` header — they are
never queued.
"""

import random
import time
import typing

import fastapi
import fastapi.responses
import structlog

import application.admission_control
import application.dependencies
import application.models
import application.services.image_generation_service
import application.services.large_language_model_service

logger = structlog.get_logger()

image_generation_router = fastapi.APIRouter(
    prefix="/v1/images",
    tags=["Image Generation"],
)


@image_generation_router.post(
    "/generations",
    response_model=application.models.ImageGenerationResponse,
    response_model_exclude_unset=True,
    summary="Generate images from a text prompt",
    description=(
        "Generates one or more images from a text prompt using Stable Diffusion."
        " When use_enhancer is true, the prompt is first enhanced by the"
        " llama.cpp large language model to improve image quality."
    ),
    status_code=200,
    responses={
        200: {
            "description": (
                "Images were generated successfully. The response contains"
                " the seed used, an array of base64-encoded PNG images,"
                " and optionally the enhanced prompt and content safety"
                " warnings."
            ),
        },
        400: {
            "description": (
                "Bad Request — the request body contains invalid JSON"
                " (``invalid_request_json``) or fails schema validation"
                " (``request_validation_failed``)."
            ),
            "model": application.models.ErrorResponse,
        },
        413: {
            "description": (
                "Payload Too Large — the request body exceeds the"
                " configured maximum payload size (``payload_too_large``)."
            ),
            "model": application.models.ErrorResponse,
        },
        415: {
            "description": ("Unsupported Media Type — the ``Content-Type`` header is not ``application/json``."),
            "model": application.models.ErrorResponse,
        },
        429: {
            "description": (
                "Too Many Requests — the image generation concurrency"
                " limit is fully occupied (``service_busy``). The"
                " ``Retry-After`` header indicates how long to wait"
                " before retrying."
            ),
            "model": application.models.ErrorResponse,
        },
        502: {
            "description": (
                "Bad Gateway — the upstream large language model server"
                " or the Stable Diffusion pipeline encountered a failure"
                " (``upstream_service_unavailable`` or"
                " ``model_unavailable``)."
            ),
            "model": application.models.ErrorResponse,
        },
        504: {
            "description": (
                "Gateway Timeout — the request exceeded the configured"
                " end-to-end timeout ceiling (``request_timeout``)."
            ),
            "model": application.models.ErrorResponse,
        },
    },
)
async def handle_image_generation_request(
    request: fastapi.Request,
    image_generation_request: application.models.ImageGenerationRequest,
    image_generation_service: typing.Annotated[
        application.services.image_generation_service.ImageGenerationService,
        fastapi.Depends(
            application.dependencies.get_image_generation_service,
        ),
    ],
    large_language_model_service: typing.Annotated[
        application.services.large_language_model_service.LargeLanguageModelService,
        fastapi.Depends(
            application.dependencies.get_large_language_model_service,
        ),
    ],
    admission_controller: typing.Annotated[
        application.admission_control.AdmissionControllerForImageGeneration,
        fastapi.Depends(
            application.dependencies.get_admission_controller_for_image_generation,
        ),
    ],
) -> fastapi.responses.JSONResponse:
    """
    Generate images, optionally enhancing the prompt first.

    If ``use_enhancer`` is true, the original prompt is sent to the
    large language model for enhancement before being forwarded to Stable
    Diffusion. Per the specification, if enhancement fails, the request
    fails with HTTP 502 — there is no silent fallback.

    The entire image generation operation (including optional prompt
    enhancement) is wrapped in the admission controller's context
    manager.  If the maximum number of concurrent operations has been reached, a
    ``ServiceBusyError`` is raised immediately (HTTP 429) without
    queuing the request.

    The response always includes the ``seed`` used for generation (either
    the client-provided seed or a randomly generated one). When
    ``use_enhancer`` was true, the ``enhanced_prompt`` field is included
    in the response.

    The response includes a ``Cache-Control: no-store`` header to prevent
    intermediate proxies and CDNs from caching dynamically generated
    content (§12 of the v5.2.0 specification, SHOULD-level advisory).
    """
    # Acquire admission before performing any work.  If the concurrency
    # limit has been reached, this raises ServiceBusyError immediately.
    async with admission_controller.acquire_or_reject():
        prompt_for_generation = image_generation_request.prompt
        enhanced_prompt_for_response: str | None = None

        if image_generation_request.use_enhancer:
            # Per spec §16: if enhancement fails, let the exception propagate
            # to the error handler which maps it to HTTP 502.
            enhanced_prompt_text = await large_language_model_service.enhance_prompt(
                original_prompt=image_generation_request.prompt,
            )
            prompt_for_generation = enhanced_prompt_text
            enhanced_prompt_for_response = enhanced_prompt_text

            # FR33 — Log the enhanced prompt text at INFO level so that
            # the enhancement result can be recovered from logs if the
            # subsequent image generation step fails.  Without this log
            # event, a successful 10–30 second prompt enhancement would
            # be irrecoverable when the generation raises an exception.
            logger.info(
                "enhanced_prompt_for_generation",
                original_prompt=image_generation_request.prompt,
                enhanced_prompt=enhanced_prompt_text,
            )

        # Resolve the seed: use the client-provided seed or generate a random one.
        # Seed 0 is a valid deterministic seed with no special semantics.
        seed_for_generation: int = (
            image_generation_request.seed
            if image_generation_request.seed is not None
            else random.randint(0, application.models.MAXIMUM_SEED_VALUE)
        )

        image_width, image_height = image_generation_request.parse_width_and_height_of_image()

        generation_result = await image_generation_service.generate_images(
            prompt=prompt_for_generation,
            image_width=image_width,
            image_height=image_height,
            number_of_images=image_generation_request.number_of_images,
            seed=seed_for_generation,
        )

    list_of_generated_image_data = [
        application.models.GeneratedImageData(
            base64_json=base64_image_string,
        )
        for base64_image_string in generation_result.base64_encoded_images
    ]

    # Build the response with required fields. Optional fields
    # (enhanced_prompt, warnings) are only set when applicable;
    # response_model_exclude_unset=True on the route decorator ensures
    # they are omitted from the JSON payload when not set.
    keyword_arguments_for_response: dict[str, typing.Any] = {
        "created": int(time.time()),
        "seed": seed_for_generation,
        "data": list_of_generated_image_data,
    }

    if enhanced_prompt_for_response is not None:
        keyword_arguments_for_response["enhanced_prompt"] = enhanced_prompt_for_response

    # Include content safety warnings only when the safety checker has flagged
    # one or more images, per FR45.
    if generation_result.indices_flagged_by_content_safety_checker:
        keyword_arguments_for_response["warnings"] = [
            application.models.ImageGenerationWarning(
                index=flagged_index,
                reason="content_policy_violation",
            )
            for flagged_index in generation_result.indices_flagged_by_content_safety_checker
        ]

    response_model = application.models.ImageGenerationResponse(**keyword_arguments_for_response)

    # Serialise with exclude_unset=True so that optional fields
    # (enhanced_prompt, warnings) are omitted entirely from the JSON
    # payload when they were not explicitly set on the response model.
    return fastapi.responses.JSONResponse(
        content=response_model.model_dump(exclude_unset=True),
        headers={"Cache-Control": "no-store"},
    )
