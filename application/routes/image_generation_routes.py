"""
Route definitions for the image generation endpoint.

This module defines the POST /v1/images/generations endpoint, which
generates one or more images from a text prompt using Stable Diffusion.
When the ``use_enhancer`` flag is set to true, the prompt is first
enhanced by the language model before image generation begins.
"""

import time
import typing

import fastapi

import application.models
import application.dependencies
import application.services.language_model_service
import application.services.image_generation_service

image_generation_router = fastapi.APIRouter(
    prefix="/v1/images",
    tags=["Image Generation"],
)


@image_generation_router.post(
    "/generations",
    response_model=application.models.ImageGenerationResponse,
    summary="Generate images from a text prompt",
    description=(
        "Generates one or more images from a text prompt using Stable "
        "Diffusion. When use_enhancer is true, the prompt is first "
        "enhanced by the llama.cpp language model to improve image quality."
    ),
    status_code=200,
)
async def handle_image_generation_request(
    image_generation_request: application.models.ImageGenerationRequest,
    image_generation_service: typing.Annotated[
        application.services.image_generation_service.ImageGenerationService,
        fastapi.Depends(
            application.dependencies.get_image_generation_service,
        ),
    ],
    language_model_service: typing.Annotated[
        application.services.language_model_service.LanguageModelService,
        fastapi.Depends(
            application.dependencies.get_language_model_service,
        ),
    ],
) -> application.models.ImageGenerationResponse:
    """
    Generate images, optionally enhancing the prompt first.

    If ``use_enhancer`` is true, the original prompt is sent to the
    language model for enhancement before being forwarded to Stable
    Diffusion. The response contains one or more base64-encoded images.
    """
    prompt_for_generation = image_generation_request.prompt

    if image_generation_request.use_enhancer:
        prompt_for_generation = await language_model_service.enhance_prompt(
            original_prompt=image_generation_request.prompt,
        )

    image_width, image_height = (
        image_generation_request.parse_image_width_and_height()
    )

    base64_encoded_images = await image_generation_service.generate_images(
        prompt=prompt_for_generation,
        image_width=image_width,
        image_height=image_height,
        number_of_images=image_generation_request.number_of_images,
    )

    generated_image_data_list = [
        application.models.GeneratedImageData(
            base64_encoded_image=base64_image_string,
        )
        for base64_image_string in base64_encoded_images
    ]

    return application.models.ImageGenerationResponse(
        created_at_unix_timestamp=int(time.time()),
        data=generated_image_data_list,
    )
