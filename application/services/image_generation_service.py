"""
Service for generating images using a locally loaded Stable Diffusion pipeline.

This service uses the HuggingFace ``diffusers`` library to load a Stable
Diffusion model directly in-process. The model is downloaded automatically
from HuggingFace Hub on first run and cached locally for subsequent starts.
"""

import asyncio
import base64
import io

import diffusers
import structlog
import torch

import application.exceptions

logger = structlog.get_logger()


_BASELINE_PIXELS = 512 * 512
_CPU_TIMEOUT_MULTIPLIER = 30


class ImageGenerationService:
    """
    In-process image generation service backed by a ``diffusers``
    ``StableDiffusionPipeline``.

    Inference calls are dispatched to a thread via ``asyncio.to_thread``
    so the async event loop is never blocked. An ``asyncio.Lock`` serialises
    concurrent inference requests to avoid GPU memory contention.

    The inference timeout scales automatically with request complexity and
    device type::

        timeout = base × n_images × (w × h) / (512 × 512) [× 30 on CPU]

    so large or CPU-bound requests get proportionally more time.
    """

    DEFAULT_INFERENCE_TIMEOUT_PER_UNIT_SECONDS = 60.0

    def __init__(
        self,
        pipeline: diffusers.StableDiffusionPipeline,
        device: torch.device,
        num_inference_steps: int = 20,
        guidance_scale: float = 7.0,
        inference_timeout_per_unit_seconds: float = DEFAULT_INFERENCE_TIMEOUT_PER_UNIT_SECONDS,
    ) -> None:
        self._pipeline = pipeline
        self._device = device
        self._num_inference_steps = num_inference_steps
        self._guidance_scale = guidance_scale
        self._inference_timeout_per_unit_seconds = inference_timeout_per_unit_seconds
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
        inference_timeout_per_unit_seconds: float = DEFAULT_INFERENCE_TIMEOUT_PER_UNIT_SECONDS,
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
            inference_timeout_per_unit_seconds: Base timeout (seconds) for a
                single 512×512 image. Actual timeout scales with the number of
                images and pixel area: ``base × n_images × (w × h) / (512×512)``.
        """
        device = cls._resolve_device(device_preference)
        dtype = torch.float16 if device.type == "cuda" else torch.float32

        logger.info(
            "stable_diffusion_pipeline_loading",
            model_id=model_id,
            device=str(device),
            dtype=str(dtype),
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

        logger.info("stable_diffusion_pipeline_loaded")

        return cls(
            pipeline=pipeline,
            device=device,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            inference_timeout_per_unit_seconds=inference_timeout_per_unit_seconds,
        )

    def _compute_timeout(
        self,
        image_width: int,
        image_height: int,
        number_of_images: int,
    ) -> float:
        """
        Compute the inference timeout for a specific request.

        Scales linearly with both the number of images and the pixel area
        relative to a 512×512 baseline.  On CPU a fixed multiplier is applied
        to account for the slower inference speed::

            timeout = base × n_images × (w × h) / (512 × 512) [× CPU multiplier]
        """
        pixel_scale = (image_width * image_height) / _BASELINE_PIXELS
        timeout = self._inference_timeout_per_unit_seconds * number_of_images * pixel_scale
        if self._device.type != "cuda":
            timeout *= _CPU_TIMEOUT_MULTIPLIER
        return timeout

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
        logger.info(
            "image_generation_initiated",
            image_width=image_width,
            image_height=image_height,
            number_of_images=number_of_images,
        )

        timeout_seconds = self._compute_timeout(image_width, image_height, number_of_images)

        async with self._inference_lock:
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._run_inference,
                        prompt,
                        image_width,
                        image_height,
                        number_of_images,
                    ),
                    timeout=timeout_seconds,
                )
            except TimeoutError as timeout_error:
                logger.error(
                    "stable_diffusion_inference_timeout",
                    timeout_seconds=timeout_seconds,
                )
                raise application.exceptions.ImageGenerationServiceUnavailableError(
                    detail=(
                        f"Image generation timed out after "
                        f"{timeout_seconds}s."
                    ),
                ) from timeout_error
            except RuntimeError as runtime_error:
                logger.error(
                    "stable_diffusion_inference_failed",
                    error=str(runtime_error),
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

        logger.info(
            "image_generation_completed",
            image_count=len(base64_encoded_images),
            image_width=image_width,
            image_height=image_height,
        )

        return base64_encoded_images

    def _run_inference(
        self,
        prompt: str,
        width: int,
        height: int,
        num_images: int,
    ) -> diffusers.pipelines.stable_diffusion.StableDiffusionPipelineOutput:
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
        if not hasattr(self, "_pipeline"):
            return
        del self._pipeline
        if self._device.type == "cuda":
            torch.cuda.empty_cache()
        logger.info("stable_diffusion_pipeline_released")
