"""
Service for generating images using a locally loaded Stable Diffusion pipeline.

This service uses the HuggingFace ``diffusers`` library to load a Stable
Diffusion model directly in-process. The model is downloaded automatically
from HuggingFace Hub on first run and cached locally for subsequent starts.
"""

import asyncio
import base64
import io
import logging

import diffusers
import torch

import application.exceptions

logger = logging.getLogger(__name__)


class ImageGenerationService:
    """
    In-process image generation service backed by a ``diffusers``
    ``StableDiffusionPipeline``.

    Inference calls are dispatched to a thread via ``asyncio.to_thread``
    so the async event loop is never blocked. An ``asyncio.Lock`` serialises
    concurrent inference requests to avoid GPU memory contention.
    """

    def __init__(
        self,
        pipeline: diffusers.StableDiffusionPipeline,
        device: torch.device,
        num_inference_steps: int = 20,
        guidance_scale: float = 7.0,
    ) -> None:
        self._pipeline = pipeline
        self._device = device
        self._num_inference_steps = num_inference_steps
        self._guidance_scale = guidance_scale
        self._inference_lock = asyncio.Lock()

    @staticmethod
    def _resolve_device(device_preference: str) -> torch.device:
        """
        Map a device preference string to a concrete ``torch.device``.

        ``"auto"`` selects CUDA when available, otherwise falls back to CPU.
        """
        if device_preference == "auto":
            if torch.cuda.is_available():
                return torch.device("cuda")
            return torch.device("cpu")
        return torch.device(device_preference)

    @classmethod
    def load_pipeline(
        cls,
        model_id: str,
        device_preference: str = "auto",
        enable_safety_checker: bool = True,
        num_inference_steps: int = 20,
        guidance_scale: float = 7.0,
    ) -> "ImageGenerationService":
        """
        Download (or load from cache) a Stable Diffusion model and return
        a ready-to-use ``ImageGenerationService``.

        Args:
            model_id: A HuggingFace model ID or a local filesystem path.
            device_preference: ``"auto"``, ``"cpu"``, or ``"cuda"``.
            enable_safety_checker: When False, disables the NSFW safety checker.
            num_inference_steps: Number of denoising steps per image.
            guidance_scale: Classifier-free guidance scale.
        """
        device = cls._resolve_device(device_preference)
        dtype = torch.float16 if device.type == "cuda" else torch.float32

        logger.info(
            "Loading Stable Diffusion pipeline '%s' on %s (dtype=%s) ...",
            model_id,
            device,
            dtype,
        )

        pipeline_kwargs: dict = {
            "torch_dtype": dtype,
        }
        if not enable_safety_checker:
            pipeline_kwargs["safety_checker"] = None

        pipeline = diffusers.StableDiffusionPipeline.from_pretrained(
            model_id,
            **pipeline_kwargs,
        )
        pipeline = pipeline.to(device)
        pipeline.enable_attention_slicing()

        logger.info("Stable Diffusion pipeline loaded successfully.")

        return cls(
            pipeline=pipeline,
            device=device,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
        )

    async def generate_images(
        self,
        prompt: str,
        image_width: int,
        image_height: int,
        number_of_images: int,
    ) -> list[str]:
        """
        Generate images from a text prompt using the loaded pipeline.

        Returns:
            A list of base64-encoded PNG strings, one per generated image.

        Raises:
            ImageGenerationServiceUnavailableError:
                When the pipeline is not loaded or an unexpected runtime
                error occurs during inference.
            ImageGenerationError:
                When the pipeline produces no images.
        """
        async with self._inference_lock:
            try:
                result = await asyncio.to_thread(
                    self._run_inference,
                    prompt,
                    image_width,
                    image_height,
                    number_of_images,
                )
            except RuntimeError as runtime_error:
                logger.error(
                    "Stable Diffusion inference failed: %s",
                    runtime_error,
                )
                raise application.exceptions.ImageGenerationServiceUnavailableError(
                    detail="Image generation failed during inference.",
                ) from runtime_error

        pil_images = result.images

        if not pil_images:
            raise application.exceptions.ImageGenerationError(
                detail="The Stable Diffusion pipeline returned no images.",
            )

        base64_encoded_images: list[str] = []
        for pil_image in pil_images:
            buffer = io.BytesIO()
            pil_image.save(buffer, format="PNG")
            encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
            base64_encoded_images.append(encoded)

        return base64_encoded_images

    def _run_inference(
        self,
        prompt: str,
        width: int,
        height: int,
        num_images: int,
    ):
        """Synchronous pipeline call, intended to be run via ``to_thread``."""
        return self._pipeline(
            prompt=prompt,
            width=width,
            height=height,
            num_images_per_prompt=num_images,
            num_inference_steps=self._num_inference_steps,
            guidance_scale=self._guidance_scale,
        )

    async def close(self) -> None:
        """Delete the pipeline and free GPU memory if applicable."""
        del self._pipeline
        if self._device.type == "cuda":
            torch.cuda.empty_cache()
        logger.info("Stable Diffusion pipeline released.")
