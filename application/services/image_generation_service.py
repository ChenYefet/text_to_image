"""
Service for generating images using a locally loaded Stable Diffusion pipeline.

This service uses the HuggingFace ``diffusers`` library to load a Stable
Diffusion model directly in-process.  The model is downloaded automatically
from HuggingFace Hub on first run and cached locally for subsequent starts.

Memory management
-----------------
After each inference call (whether successful or failed), the service
explicitly invokes ``gc.collect()`` and, on CUDA devices,
``torch.cuda.empty_cache()`` to release intermediate tensors that
PyTorch's allocator would otherwise retain.  Without this cleanup, the
process resident set size grows monotonically and triggers the OS
out-of-memory killer after 3–5 inference cycles on 8 GB RAM.

Content safety checker (not-safe-for-work filtering)
-----------------------------------------------------
When the safety checker is enabled, the pipeline returns a boolean list
``nsfw_content_detected`` (a library-defined attribute from the
``diffusers`` package) alongside generated images.  This service
inspects that list and replaces flagged images with ``None`` in the
returned data, allowing the route handler to populate the ``warnings``
array in the response.

Startup warmup
--------------
The very first inference call after model loading is typically slower than
subsequent calls because PyTorch performs one-time optimisations (kernel
selection, memory allocation patterns, JIT compilation) during the first
forward pass.  To prevent this latency penalty from affecting the first
real user request, the service offers a ``run_startup_warmup`` method
that performs a minimal dummy inference (1 step, 64×64, 1 image) during
the application startup sequence.  The output is discarded, but PyTorch's
one-time setup work is completed and amortised into the startup time.

If the warmup is not performed (or fails), the service falls back to the
original behaviour: tracking first-inference state and emitting a
``first_warmup_of_inference_of_stable_diffusion`` log event (specification
Section 18, event B-4) with the warmup latency in milliseconds so that
operators can distinguish genuine performance regressions from expected
first-call overhead.
"""

import asyncio
import base64
import gc
import io
import time

import diffusers
import psutil
import structlog
import torch

import application.exceptions

logger = structlog.get_logger()


# The baseline pixel count used as the denominator in the timeout scaling
# formula.  A single 512×512 image represents 1.0× the base timeout.
# Larger images scale proportionally (e.g. 1024×1024 = 4.0× base).
_BASELINE_PIXEL_COUNT = 512 * 512

# On CPU hardware, inference is approximately 30× slower than on GPU.
# This multiplier is applied to the computed timeout when the inference
# device is not a CUDA GPU, ensuring that CPU-bound generation requests
# receive a proportionally longer timeout window.
_CPU_TIMEOUT_MULTIPLIER = 30


class ImageGenerationService:
    """
    In-process image generation service backed by a ``diffusers``
    ``StableDiffusionPipeline``.

    Inference calls are dispatched to a background thread via
    ``asyncio.to_thread`` so the async event loop is never blocked by
    the synchronous PyTorch forward pass.

    Concurrency control is handled externally by the
    ``ImageGenerationAdmissionController`` (see ``admission_control.py``),
    which rejects overflow requests with HTTP 429 before they reach this
    service.  This service therefore does not maintain its own lock or
    semaphore.

    The inference timeout scales automatically with request complexity and
    device type::

        timeout = base × number_of_images × (width × height) / (512 × 512) [× 30 on CPU]

    so large or CPU-bound requests get proportionally more time.
    """

    DEFAULT_INFERENCE_TIMEOUT_PER_UNIT_SECONDS = 60.0

    def __init__(
        self,
        pipeline: diffusers.StableDiffusionPipeline,
        device: torch.device,
        number_of_inference_steps: int = 20,
        guidance_scale: float = 7.0,
        inference_timeout_per_unit_seconds: float = DEFAULT_INFERENCE_TIMEOUT_PER_UNIT_SECONDS,
    ) -> None:
        """
        Initialise the image generation service.

        This constructor is not intended to be called directly.  Use the
        ``load_pipeline`` class method to create an instance with a fully
        loaded and configured Stable Diffusion pipeline.

        Args:
            pipeline: A loaded ``StableDiffusionPipeline`` instance ready
                for inference.
            device: The ``torch.device`` that the pipeline has been moved
                to (e.g. ``torch.device("cuda")`` or ``torch.device("cpu")``).
            number_of_inference_steps: Number of denoising steps per image.
                More steps generally produce higher quality output at the
                cost of increased latency.
            guidance_scale: Classifier-free guidance scale.  Higher values
                follow the prompt more closely; lower values are more
                creative.
            inference_timeout_per_unit_seconds: Base timeout (seconds) for
                generating a single 512×512 image.  The actual timeout
                scales with the number of images and pixel area.
        """
        self._pipeline = pipeline
        self._device = device
        self._number_of_inference_steps = number_of_inference_steps
        self._guidance_scale = guidance_scale
        self._inference_timeout_per_unit_seconds = inference_timeout_per_unit_seconds

        # Track whether the first inference has been completed, so we can
        # emit the ``first_warmup_of_inference_of_stable_diffusion`` log event
        # with the warmup latency on the first call to ``generate_images``.
        self._first_inference_completed: bool = False

    @staticmethod
    def _resolve_device(device_preference: str) -> torch.device:
        """
        Map a device preference string to a concrete ``torch.device``.

        Args:
            device_preference: One of ``"auto"``, ``"cpu"``, or ``"cuda"``.
                When ``"auto"`` is specified, CUDA is selected if a
                compatible GPU is available; otherwise CPU is used.

        Returns:
            A ``torch.device`` instance representing the resolved device.
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
        model_revision: str = "main",
        device_preference: str = "auto",
        enable_safety_checker: bool = True,
        number_of_inference_steps: int = 20,
        guidance_scale: float = 7.0,
        inference_timeout_per_unit_seconds: float = DEFAULT_INFERENCE_TIMEOUT_PER_UNIT_SECONDS,
    ) -> "ImageGenerationService":
        """
        Download (or load from cache) a Stable Diffusion model and return
        a ready-to-use ``ImageGenerationService``.

        This class method handles the entire model loading lifecycle:
        device resolution, dtype selection, model download, pipeline
        construction, and memory optimisation (attention slicing).

        On successful loading, emits a ``model_validation_at_startup_passed``
        log event at INFO level as required by the v5.0.0 specification
        (Section 18, event B-5).

        Args:
            model_id: A HuggingFace model ID (e.g.
                ``"stable-diffusion-v1-5/stable-diffusion-v1-5"``) or a
                local filesystem path to a pre-downloaded model.
            model_revision: The HuggingFace model revision identifier — a
                specific commit hash or branch name.  Pinning to a commit
                hash ensures identical model weights across all deployments.
                The default ``"main"`` tracks the latest published revision.
            device_preference: ``"auto"``, ``"cpu"``, or ``"cuda"``.
            enable_safety_checker: When ``False``, disables the content safety
                checker.  Generated images will not be filtered.
            number_of_inference_steps: Number of denoising steps per image.
            guidance_scale: Classifier-free guidance scale.
            inference_timeout_per_unit_seconds: Base timeout (seconds) for a
                single 512×512 image.  Actual timeout scales with the number
                of images and pixel area:
                ``base × number_of_images × (w × h) / (512 × 512)``.
        """
        device = cls._resolve_device(device_preference)
        dtype = torch.float16 if device.type == "cuda" else torch.float32

        logger.info(
            "stable_diffusion_pipeline_loading",
            model_id=model_id,
            model_revision=model_revision,
            device=str(device),
            dtype=str(dtype),
        )

        pipeline_keyword_arguments: dict = {
            "torch_dtype": dtype,
            "revision": model_revision,
        }
        if not enable_safety_checker:
            pipeline_keyword_arguments["safety_checker"] = None

        pipeline = diffusers.StableDiffusionPipeline.from_pretrained(
            model_id,
            **pipeline_keyword_arguments,
        )
        pipeline = pipeline.to(device)

        # Enable attention slicing to reduce peak GPU memory consumption
        # during inference.  This trades a small amount of inference speed
        # for significantly lower VRAM usage, which is appropriate for the
        # target deployment profile (single-GPU hosts with limited VRAM).
        pipeline.enable_attention_slicing()

        logger.info("stable_diffusion_pipeline_loaded")

        # Emit the specification-defined model_validation_at_startup_passed
        # event (v5.0.0 Section 18, event B-5) to confirm that the model
        # was loaded successfully and is ready for inference.
        logger.info(
            "model_validation_at_startup_passed",
            model_id=model_id,
            model_revision=model_revision,
            device=str(device),
        )

        return cls(
            pipeline=pipeline,
            device=device,
            number_of_inference_steps=number_of_inference_steps,
            guidance_scale=guidance_scale,
            inference_timeout_per_unit_seconds=inference_timeout_per_unit_seconds,
        )

    async def run_startup_warmup(self) -> None:
        """
        Run a minimal dummy inference during startup to trigger PyTorch's
        one-time kernel selection, memory allocation, and JIT compilation.

        This moves the first-inference warmup cost from the first user
        request to the application startup sequence, where it is expected
        and invisible to users.  The generated output is discarded
        immediately and memory is cleaned up.

        On success, emits a ``stable_diffusion_startup_warmup_completed``
        log event at INFO level with the warmup duration.  On failure,
        emits a ``stable_diffusion_startup_warmup_failed`` warning and
        returns without raising — the first user request will simply
        experience the warmup latency instead (the original fallback
        behaviour).

        The warmup uses intentionally minimal parameters to complete as
        quickly as possible:

        - **1 inference step** (not the configured number) — the goal is
          to trigger PyTorch's one-time setup, not to produce a usable
          image.
        - **64×64 resolution** — the smallest practical image size,
          minimising the computation and memory required.
        - **1 image** — a single image is sufficient to trigger all
          one-time initialisations.
        - **guidance_scale=1.0** — disables classifier-free guidance to
          skip the unconditional forward pass, halving the computation.
        """
        warmup_start_time = time.monotonic()

        try:
            random_number_generator = torch.Generator(device="cpu").manual_seed(0)

            warmup_result = await asyncio.to_thread(
                self._pipeline,  # type: ignore[operator]
                prompt="warmup",
                width=64,
                height=64,
                num_images_per_prompt=1,
                num_inference_steps=1,
                guidance_scale=1.0,
                generator=random_number_generator,
            )

            # Discard the output immediately to free memory.
            del warmup_result
            self._cleanup_after_inference()

            warmup_duration_seconds = time.monotonic() - warmup_start_time

            # Mark the first inference as completed so that the
            # ``generate_images`` method does not re-emit the
            # ``first_warmup_of_inference_of_stable_diffusion`` event on the
            # first real user request.  The warmup has already absorbed
            # PyTorch's one-time overhead.
            self._first_inference_completed = True

            # Report warmup latency in milliseconds for consistency with
            # the normative ``first_warmup_of_inference_of_stable_diffusion``
            # event (specification Section 18, event B-4).
            logger.info(
                "stable_diffusion_startup_warmup_completed",
                warmup_latency_milliseconds=round(
                    warmup_duration_seconds * 1000, 1
                ),
            )
        except Exception as warmup_error:
            # The warmup is a best-effort optimisation.  If it fails, the
            # service continues normally and the first user request will
            # absorb the warmup cost instead.
            self._cleanup_after_inference()
            logger.warning(
                "stable_diffusion_startup_warmup_failed",
                error=str(warmup_error),
            )

    def _compute_timeout(
        self,
        image_width: int,
        image_height: int,
        number_of_images: int,
    ) -> float:
        """
        Compute the inference timeout for a specific request.

        The timeout scales linearly with both the number of images and the
        pixel area relative to a 512×512 baseline.  On CPU hardware, a
        fixed multiplier is applied to account for the substantially
        slower inference speed::

            timeout = base × number_of_images × (width × height) / (512 × 512) [× CPU multiplier]

        Args:
            image_width: Width of each generated image in pixels.
            image_height: Height of each generated image in pixels.
            number_of_images: Number of images to generate in the batch.

        Returns:
            The computed timeout in seconds.
        """
        pixel_scale = (image_width * image_height) / _BASELINE_PIXEL_COUNT
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
        seed: int = 0,
    ) -> "ImageGenerationResult":
        """
        Generate images from a text prompt using the loaded pipeline.

        The inference is dispatched to a background thread via
        ``asyncio.to_thread`` to avoid blocking the async event loop.
        A per-request timeout is computed based on the image count,
        resolution, and device type.

        On the first call after model loading, a
        ``first_warmup_of_inference_of_stable_diffusion`` log event is emitted
        with the warmup latency in milliseconds (specification Section 18,
        event B-4).

        Args:
            prompt: The text prompt describing the desired image.
            image_width: Width of the generated image in pixels.
            image_height: Height of the generated image in pixels.
            number_of_images: Number of images to generate in one batch.
            seed: Integer seed for the random number generator, enabling
                reproducible generation.  Seed 0 is a valid deterministic
                seed with no special semantics.

        Returns:
            An ``ImageGenerationResult`` containing base64-encoded PNG
            strings (or ``None`` for content-safety-filtered images) and a list of
            indices that were flagged by the safety checker.

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
            seed=seed,
        )

        timeout_seconds = self._compute_timeout(image_width, image_height, number_of_images)

        # Record the start time for first-inference warmup measurement.
        inference_start_time = time.monotonic()

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    self._run_inference,
                    prompt,
                    image_width,
                    image_height,
                    number_of_images,
                    seed,
                ),
                timeout=timeout_seconds,
            )
        except TimeoutError as timeout_error:
            self._cleanup_after_inference()
            logger.error(
                "stable_diffusion_inference_timeout",
                timeout_seconds=timeout_seconds,
            )
            raise application.exceptions.ImageGenerationServiceUnavailableError(
                detail=(f"Image generation timed out after {timeout_seconds}s."),
            ) from timeout_error
        except RuntimeError as runtime_error:
            self._cleanup_after_inference()
            logger.error(
                "stable_diffusion_inference_failed",
                error=str(runtime_error),
            )
            raise application.exceptions.ImageGenerationServiceUnavailableError(
                detail="Image generation failed during inference.",
            ) from runtime_error

        inference_duration_seconds = time.monotonic() - inference_start_time

        # Emit the first-inference warmup event if this is the first
        # inference call since model loading.  The warmup latency includes
        # PyTorch's one-time kernel selection and JIT compilation overhead,
        # which makes the first call significantly slower than subsequent
        # calls on the same hardware.
        #
        # The warmup latency is reported in milliseconds as required by the
        # v5.0.0 specification (Section 18, event B-4).
        if not self._first_inference_completed:
            self._first_inference_completed = True
            logger.info(
                "first_warmup_of_inference_of_stable_diffusion",
                warmup_latency_milliseconds=round(inference_duration_seconds * 1000, 1),
                image_width=image_width,
                image_height=image_height,
                number_of_images=number_of_images,
            )

        pipeline_output_images = result.images

        if not pipeline_output_images:
            self._cleanup_after_inference()
            raise application.exceptions.ImageGenerationError(
                detail="The Stable Diffusion pipeline returned no images.",
            )

        # ── Content safety checker processing ─────────────────────────────
        #
        # The pipeline returns ``nsfw_content_detected`` (a library-defined
        # attribute from the ``diffusers`` package) as a list of booleans
        # when the safety checker is enabled.  Each entry corresponds to
        # an image in the batch: ``True`` means the image was flagged and
        # should be replaced with ``None`` in the response.
        content_safety_flags: list[bool] = getattr(result, "nsfw_content_detected", None) or [False] * len(
            pipeline_output_images
        )

        content_safety_flagged_indices: list[int] = [
            index for index, is_flagged in enumerate(content_safety_flags) if is_flagged
        ]

        if content_safety_flagged_indices:
            logger.warning(
                "image_generation_safety_filtered",
                flagged_indices=content_safety_flagged_indices,
                total_images=len(pipeline_output_images),
            )

        # Convert the flagged indices list to a frozenset for O(1)
        # membership testing in the per-image encoding loop below.
        content_safety_flagged_indices_set: frozenset[int] = frozenset(content_safety_flagged_indices)

        # ── Encode images to base64 PNG ───────────────────────────────────
        #
        # Each non-flagged image is encoded as a PNG and then base64-encoded
        # using the standard alphabet (RFC 4648 §4).  Flagged images are
        # replaced with ``None`` to indicate content policy filtering.
        base64_encoded_images: list[str | None] = []
        for index, individual_output_image in enumerate(pipeline_output_images):
            if index in content_safety_flagged_indices_set:
                base64_encoded_images.append(None)
            else:
                image_byte_buffer = io.BytesIO()
                individual_output_image.save(image_byte_buffer, format="PNG")
                encoded_image = base64.b64encode(image_byte_buffer.getvalue()).decode("utf-8")
                base64_encoded_images.append(encoded_image)

        # ── Mandatory post-inference memory cleanup (spec §15) ────────────
        #
        # Delete references to PIL images and intermediate tensors, then
        # force garbage collection to prevent monotonic RSS growth.
        del result
        del pipeline_output_images
        self._cleanup_after_inference()

        logger.info(
            "image_generation_completed",
            image_count=len(base64_encoded_images),
            image_width=image_width,
            image_height=image_height,
            content_safety_filtered_count=len(content_safety_flagged_indices),
            number_of_bytes_of_resident_set_size_of_process=psutil.Process().memory_info().rss,
        )

        return ImageGenerationResult(
            base64_encoded_images=base64_encoded_images,
            content_safety_flagged_indices=content_safety_flagged_indices,
        )

    def _run_inference(
        self,
        prompt: str,
        image_width: int,
        image_height: int,
        number_of_images: int,
        seed: int,
    ) -> diffusers.pipelines.stable_diffusion.StableDiffusionPipelineOutput:
        """
        Execute the synchronous pipeline call.

        This method is intended to be run in a background thread via
        ``asyncio.to_thread`` to prevent the synchronous PyTorch forward
        pass from blocking the async event loop.

        Uses a ``torch.Generator`` seeded with the provided seed value
        to enable reproducible image generation.  Seed 0 is a valid
        deterministic seed with no special semantics.

        Args:
            prompt: The text prompt describing the desired image.
            image_width: Width of the generated image in pixels.
            image_height: Height of the generated image in pixels.
            number_of_images: Number of images to generate in the batch.
            seed: Integer seed for the PyTorch random number generator.

        Returns:
            A ``StableDiffusionPipelineOutput`` containing the generated
            images and optional content safety detection flags.
        """
        random_number_generator = torch.Generator(device="cpu").manual_seed(seed)

        return self._pipeline(  # type: ignore[operator,no-any-return]
            prompt=prompt,
            width=image_width,
            height=image_height,
            num_images_per_prompt=number_of_images,
            num_inference_steps=self._number_of_inference_steps,
            guidance_scale=self._guidance_scale,
            generator=random_number_generator,
        )

    def _cleanup_after_inference(self) -> None:
        """
        Release intermediate tensors after each inference call.

        Invokes ``gc.collect()`` to force Python's garbage collector to
        release unreferenced tensors, and on CUDA devices additionally
        invokes ``torch.cuda.empty_cache()`` to release the GPU memory
        allocator's cached blocks back to the device.

        This is mandatory per the specification (§15, Memory Management
        After Inference) to prevent monotonic RSS growth that triggers
        the OS out-of-memory killer after 3–5 inference cycles on 8 GB RAM.
        """
        gc.collect()
        if self._device.type == "cuda":
            torch.cuda.empty_cache()

    def check_health(self) -> bool:
        """
        Return ``True`` if the Stable Diffusion pipeline is loaded and
        available for inference.

        This method is called by the readiness probe (``GET /health/ready``)
        to determine whether the image generation backend is operational.
        """
        return hasattr(self, "_pipeline") and self._pipeline is not None

    async def close(self) -> None:
        """
        Delete the pipeline and free GPU memory if applicable.

        This method must be called during application shutdown to release
        the substantial memory (CPU RAM and/or GPU VRAM) occupied by the
        loaded model weights.
        """
        if not hasattr(self, "_pipeline"):
            return
        del self._pipeline
        if self._device.type == "cuda":
            torch.cuda.empty_cache()
        logger.info("stable_diffusion_pipeline_released")


class ImageGenerationResult:
    """
    Container for the output of a single image generation operation.

    This class serves as a clean interface between the image generation
    service (which works with PIL images and PyTorch tensors) and the
    route handler (which works with base64 strings and JSON responses).

    Attributes:
        base64_encoded_images: A list of base64-encoded PNG strings, one
            per requested image.  Entries are ``None`` for images that
            were filtered by the content safety checker.
        content_safety_flagged_indices: A list of zero-based indices identifying
            which images in the batch were flagged by the content safety
            checker.  Empty when no images were flagged.
    """

    def __init__(
        self,
        base64_encoded_images: list[str | None],
        content_safety_flagged_indices: list[int],
    ) -> None:
        self.base64_encoded_images = base64_encoded_images
        self.content_safety_flagged_indices = content_safety_flagged_indices
