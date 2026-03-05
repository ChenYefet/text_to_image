"""
Endpoint definitions for the image generation endpoint.

This module defines the POST /v1/images/generations endpoint, which
generates one or more images from a text prompt using Stable Diffusion.
When the ``use_enhancer`` flag is set to true, the prompt is first
enhanced by the large language model before image generation begins.

Per the v5.5.0 specification (Section 16 — Component Failure Degradation
Matrix), when ``use_enhancer`` is true and the llama.cpp server fails,
the service returns HTTP 502 (upstream_service_unavailable). There is no
silent fallback to the original prompt.

Admission control (NFR44)
-------------------------
The image generation operation is wrapped in the
``AdmissionControllerForImageGeneration`` context manager, which limits the
number of concurrent inference operations to the operator-configured
maximum (``maximum_number_of_concurrent_operations_of_image_generation``, default 2).  When the
limit is reached, additional requests are rejected immediately with
HTTP 429 (``service_busy``) and a ``Retry-After`` header — they are
never queued.
"""

import typing

import fastapi
import fastapi.responses

import application.admission_control
import application.api.dependencies
import application.api.schemas.error
import application.api.schemas.image_generation
import application.contracts_shared_across_layers.image_generation
import application.services.image_generation_service

image_generation_router = fastapi.APIRouter(
    prefix="/v1/images",
    tags=["Image Generation"],
)


@image_generation_router.post(
    "/generations",
    response_model=application.contracts_shared_across_layers.image_generation.ImageGenerationResponse,
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
            "model": application.api.schemas.error.ErrorResponse,
        },
        413: {
            "description": (
                "Payload Too Large — the request body exceeds the"
                " configured maximum payload size (``payload_too_large``)."
            ),
            "model": application.api.schemas.error.ErrorResponse,
        },
        415: {
            "description": ("Unsupported Media Type — the ``Content-Type`` header is not ``application/json``."),
            "model": application.api.schemas.error.ErrorResponse,
        },
        429: {
            "description": (
                "Too Many Requests — the image generation concurrency"
                " limit is fully occupied (``service_busy``). The"
                " ``Retry-After`` header indicates how long to wait"
                " before retrying."
            ),
            "model": application.api.schemas.error.ErrorResponse,
        },
        502: {
            "description": (
                "Bad Gateway — the upstream large language model server"
                " or the Stable Diffusion pipeline encountered a failure"
                " (``upstream_service_unavailable`` or"
                " ``model_unavailable``)."
            ),
            "model": application.api.schemas.error.ErrorResponse,
        },
        504: {
            "description": (
                "Gateway Timeout — the request exceeded the configured"
                " end-to-end timeout ceiling (``request_timeout``)."
            ),
            "model": application.api.schemas.error.ErrorResponse,
        },
    },
)
async def handle_image_generation_request(
    request: fastapi.Request,
    image_generation_request: application.api.schemas.image_generation.ImageGenerationRequest,
    image_generation_service: typing.Annotated[
        application.services.image_generation_service.ImageGenerationService,
        fastapi.Depends(
            application.api.dependencies.get_image_generation_service,
        ),
    ],
    admission_controller: typing.Annotated[
        application.admission_control.AdmissionControllerForImageGeneration,
        fastapi.Depends(
            application.api.dependencies.get_admission_controller_for_image_generation,
        ),
    ],
) -> fastapi.responses.JSONResponse:
    """
    Generate images, optionally enhancing the prompt first.

    All business logic — seed resolution, prompt enhancement coordination,
    pipeline delegation, and response model construction — is handled by
    the ``ImageGenerationService``.  This endpoint handler is a thin HTTP
    adapter responsible only for admission control and HTTP response
    serialisation.

    The entire image generation operation (including optional prompt
    enhancement) is wrapped in the admission controller's context
    manager.  If the maximum number of concurrent operations has been reached, a
    ``ServiceBusyError`` is raised immediately (HTTP 429) without
    queuing the request.

    The response includes a ``Cache-Control: no-store`` header to prevent
    intermediate proxies and CDNs from caching dynamically generated
    content (§12 of the v5.5.0 specification, SHOULD-level advisory).
    """
    # Acquire admission before performing any work.  If the concurrency
    # limit has been reached, this raises ServiceBusyError immediately.
    async with admission_controller.acquire_or_reject():
        image_width, image_height = image_generation_request.parse_width_and_height_of_image()

        response_model = await image_generation_service.generate_images(
            prompt=image_generation_request.prompt,
            use_enhancer=image_generation_request.use_enhancer,
            seed=image_generation_request.seed,
            image_width=image_width,
            image_height=image_height,
            number_of_images=image_generation_request.number_of_images,
        )

    # Serialise with exclude_unset=True so that optional fields
    # (enhanced_prompt, warnings) are omitted entirely from the JSON
    # payload when they were not explicitly set on the response model.
    return fastapi.responses.JSONResponse(
        content=response_model.model_dump(exclude_unset=True),
        headers={"Cache-Control": "no-store"},
    )
