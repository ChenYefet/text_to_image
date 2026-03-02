"""
Service-layer orchestrator for image generation.

This service wraps the ``StableDiffusionPipeline`` integration and
coordinates with the ``PromptEnhancementService`` when prompt enhancement
is requested.  It absorbs the orchestration logic that was previously
embedded in the image generation endpoint handler: seed resolution,
prompt enhancement coordination, pipeline delegation, and response
model construction.

The API endpoint handler becomes a thin HTTP adapter that delegates
all business logic to this service.
"""

import random
import time
import typing

import structlog

import application.api.schemas.image_generation
import application.integrations.stable_diffusion_pipeline
import application.services.prompt_enhancement_service

logger = structlog.get_logger()


class ImageGenerationService:
    """
    Orchestrate image generation with optional prompt enhancement.

    This service coordinates between the ``StableDiffusionPipeline`` (for
    image generation) and the ``PromptEnhancementService`` (for optional
    prompt enhancement before generation).  It serves as the single entry
    point for the image generation endpoint, encapsulating all business
    logic so that the endpoint handler remains a thin HTTP adapter.

    Admission control is not handled by this service — it remains in the
    endpoint handler, which wraps the service call in the admission
    controller's context manager.
    """

    def __init__(
        self,
        stable_diffusion_pipeline: application.integrations.stable_diffusion_pipeline.StableDiffusionPipeline,
        prompt_enhancement_service: application.services.prompt_enhancement_service.PromptEnhancementService,
    ) -> None:
        """
        Initialise the image generation service.

        Args:
            stable_diffusion_pipeline: The Stable Diffusion pipeline
                instance used for image generation.
            prompt_enhancement_service: The prompt enhancement service
                used when ``use_enhancer`` is ``True``.
        """
        self._stable_diffusion_pipeline = stable_diffusion_pipeline
        self._prompt_enhancement_service = prompt_enhancement_service

    async def generate_images(
        self,
        prompt: str,
        use_enhancer: bool,
        seed: int | None,
        image_width: int,
        image_height: int,
        number_of_images: int,
    ) -> application.api.schemas.image_generation.ImageGenerationResponse:
        """
        Generate images from a text prompt, optionally enhancing the prompt first.

        If ``use_enhancer`` is ``True``, the original prompt is sent to the
        prompt enhancement service before being forwarded to Stable
        Diffusion.  Per the specification (Section 16), if enhancement
        fails, the exception propagates to the error handler which maps
        it to HTTP 502 — there is no silent fallback.

        The seed is resolved here: if the caller provides ``None``, a
        random seed is generated.  Seed 0 is a valid deterministic seed
        with no special semantics.

        Args:
            prompt: The text prompt describing the desired image.
            use_enhancer: Whether to enhance the prompt before generation.
            seed: The seed for reproducible generation, or ``None`` for
                a randomly generated seed.
            image_width: Width of the generated image in pixels.
            image_height: Height of the generated image in pixels.
            number_of_images: Number of images to generate in one batch.

        Returns:
            An ``ImageGenerationResponse`` containing the generated images,
            the seed used, and optionally the enhanced prompt and content
            safety warnings.

        Raises:
            LargeLanguageModelServiceUnavailableError:
                When prompt enhancement is requested but the llama.cpp
                server is unreachable or returns an error.
            ImageGenerationServiceUnavailableError:
                When the Stable Diffusion pipeline fails during inference.
            ImageGenerationError:
                When the pipeline produces no images.
        """
        prompt_for_generation = prompt
        enhanced_prompt_for_response: str | None = None

        if use_enhancer:
            enhanced_prompt_text = await self._prompt_enhancement_service.enhance_prompt(
                original_prompt=prompt,
            )
            prompt_for_generation = enhanced_prompt_text
            enhanced_prompt_for_response = enhanced_prompt_text

            # FR33 — Log the enhanced prompt text at INFO level so that
            # the enhancement result can be recovered from logs if the
            # subsequent image generation step fails.
            logger.info(
                "enhanced_prompt_for_generation",
                original_prompt=prompt,
                enhanced_prompt=enhanced_prompt_text,
            )

        # Resolve the seed: use the client-provided seed or generate a random one.
        # Seed 0 is a valid deterministic seed with no special semantics.
        seed_for_generation: int = (
            seed if seed is not None else random.randint(0, application.api.schemas.image_generation.MAXIMUM_SEED_VALUE)
        )

        generation_result = await self._stable_diffusion_pipeline.generate_images(
            prompt=prompt_for_generation,
            image_width=image_width,
            image_height=image_height,
            number_of_images=number_of_images,
            seed=seed_for_generation,
        )

        list_of_generated_image_data = [
            application.api.schemas.image_generation.GeneratedImageData(
                base64_json=base64_image_string,
            )
            for base64_image_string in generation_result.base64_encoded_images
        ]

        # Build the response with required fields.  Optional fields
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
                application.api.schemas.image_generation.ImageGenerationWarning(
                    index=flagged_index,
                    reason="content_policy_violation",
                )
                for flagged_index in generation_result.indices_flagged_by_content_safety_checker
            ]

        return application.api.schemas.image_generation.ImageGenerationResponse(
            **keyword_arguments_for_response,
        )

    def check_health(self) -> bool:
        """
        Check whether the Stable Diffusion pipeline is loaded and available.

        Delegates to ``StableDiffusionPipeline.check_health()``.

        Returns:
            ``True`` if the pipeline is loaded and ready for inference,
            ``False`` otherwise.
        """
        return self._stable_diffusion_pipeline.check_health()

    async def close(self) -> None:
        """
        Release the Stable Diffusion pipeline and free GPU memory.

        Delegates to ``StableDiffusionPipeline.close()``.
        """
        await self._stable_diffusion_pipeline.close()
