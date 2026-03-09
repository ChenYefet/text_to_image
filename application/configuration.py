"""
Application configuration module.

Loads all configuration values from environment variables with the prefix
TEXT_TO_IMAGE_. Default values are provided for local development. A .env
file is also supported via pydantic-settings.

Every configuration variable is documented in the v5.10.0 specification
(Section 17 — Configuration Requirements). This module is the single
source of truth for all runtime configuration within the service process.

"""

import pydantic
import pydantic_settings

# ── Tier-dependent default constants ──────────────────────────────────────
#
# These constants define the GPU and CPU defaults for the 4 configuration
# variables that participate in sentinel-based auto-resolution.  When a
# field is left as None (the sentinel), the resolution method selects the
# appropriate constant based on the detected Stable Diffusion inference
# device at startup.

GPU_DEFAULT_INFERENCE_TIMEOUT_BY_STABLE_DIFFUSION_PER_BASELINE_UNIT_IN_SECONDS = 10.0
CPU_DEFAULT_INFERENCE_TIMEOUT_BY_STABLE_DIFFUSION_PER_BASELINE_UNIT_IN_SECONDS = 60.0
GPU_DEFAULT_MAXIMUM_NUMBER_OF_CONCURRENT_OPERATIONS_OF_IMAGE_GENERATION = 2
CPU_DEFAULT_MAXIMUM_NUMBER_OF_CONCURRENT_OPERATIONS_OF_IMAGE_GENERATION = 1
GPU_DEFAULT_RETRY_AFTER_BUSY_IN_SECONDS = 5
CPU_DEFAULT_RETRY_AFTER_BUSY_IN_SECONDS = 30
GPU_DEFAULT_TIMEOUT_FOR_REQUESTS_IN_SECONDS = 60.0
CPU_DEFAULT_TIMEOUT_FOR_REQUESTS_IN_SECONDS = 300.0


class ApplicationConfiguration(pydantic_settings.BaseSettings):
    """
    Centralised configuration for the Text-to-Image with Prompt Assist service.

    Every field maps to an environment variable prefixed with TEXT_TO_IMAGE_.
    For example, the field ``base_url_of_large_language_model_server`` is populated from
    the environment variable TEXT_TO_IMAGE_BASE_URL_OF_LARGE_LANGUAGE_MODEL_SERVER.

    Configuration categories
    ------------------------
    - **Application**: host, port, CORS, log level
    - **Large language model (llama.cpp)**: server URL, timeout, temperature,
      maximum tokens, system prompt, connection pool size, maximum response bytes
    - **Stable Diffusion**: model ID, model revision, device, inference
      steps, guidance scale, safety checker, inference timeout
    - **Admission control and resilience**: maximum number of concurrent operations, retry-after
      durations, maximum request payload size, end-to-end request timeout

    Sentinel-based auto-resolution
    ------------------------------
    Four tier-dependent settings default to ``None`` (sentinel).  After
    instantiation, call ``resolve_tier_dependent_defaults_for_inference_device()``
    to replace each ``None`` with the appropriate GPU or CPU default based on
    the detected Stable Diffusion inference device.  Explicit operator overrides
    are preserved unconditionally.

    Inference timeout note
    ----------------------
    The ``inference_timeout_by_stable_diffusion_per_baseline_unit_in_seconds``
    is the base timeout for generating a single 512×512 baseline unit image.
    The service scales it automatically for larger or batched requests::

        timeout = base × n_images × (w × h) / (512 × 512)

    No device-type multiplier is applied; the sentinel-based auto-resolution
    provides device-appropriate values directly (10 s on GPU, 60 s on CPU).
    """

    # ── Application settings ─────────────────────────────────────────────

    application_host: str = "127.0.0.1"

    application_port: int = pydantic.Field(default=8000, ge=1, le=65535)

    cors_allowed_origins: list[str] = pydantic.Field(
        default=[],
        description=(
            "Allowed CORS origins as a JSON list. An empty list disables CORS entirely. Example: '[\"http://localhost:3000\"]'."
        ),
    )

    log_level: str = pydantic.Field(
        default="INFO",
        description=(
            "Minimum log level for structured JSON logging. Accepted values: DEBUG, INFO, WARNING, ERROR, CRITICAL."
        ),
    )

    # ── Large language model (llama.cpp) settings ───────────────────────────────

    large_language_model_path: str = pydantic.Field(
        default="",
        description=(
            "File path of the GGUF large language model used by the llama.cpp "
            "server. This variable is reference only — it is not used at "
            "runtime by this service (which communicates with llama.cpp via "
            "HTTP), but is declared for tooling visibility, deployment "
            "automation, and environment variable inventory completeness "
            "(§17 of the v5.10.0 specification)."
        ),
    )

    base_url_of_large_language_model_server: str = pydantic.Field(
        default="http://localhost:8080",
        description=(
            "Base URL of the llama.cpp server running in OpenAI-compatible mode. "
            "The service appends /v1/chat/completions to this URL."
        ),
    )

    timeout_for_requests_to_large_language_model_in_seconds: float = pydantic.Field(
        default=30.0,
        gt=0,
        description=(
            "Maximum time in seconds to wait for a response from the llama.cpp server "
            "before treating the request as failed. The default of 30 seconds is "
            "optimised for GPU-accelerated inference; CPU-only operators should "
            "increase to 120."
        ),
    )

    large_language_model_temperature: float = pydantic.Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description=(
            "Sampling temperature for prompt enhancement. Higher values produce more "
            "creative output; 0.0 is deterministic."
        ),
    )

    maximum_tokens_generated_by_large_language_model: int = pydantic.Field(
        default=512,
        ge=1,
        description=("Maximum number of tokens the large language model may generate for an enhanced prompt."),
    )

    system_prompt_for_large_language_model: str = pydantic.Field(
        default=(
            "You are an expert at enhancing text-to-image prompts. Transform the "
            "user's simple prompt into a detailed, visually descriptive prompt. Add "
            "artistic style, lighting, composition, and quality modifiers. Return "
            "only the enhanced prompt, nothing else."
        ),
        min_length=1,
        description=(
            "System prompt sent to the llama.cpp server on every prompt enhancement "
            "request. Controls the enhancement style and output format. Must be a "
            "non-empty string when set."
        ),
    )

    size_of_connection_pool_for_large_language_model: int = pydantic.Field(
        default=10,
        ge=1,
        description=(
            "Maximum number of connections maintained in the httpx connection pool for the llama.cpp HTTP client."
        ),
    )

    maximum_number_of_bytes_of_response_body_from_large_language_model: int = pydantic.Field(
        default=1_048_576,
        ge=1,
        description=(
            "Maximum response body size in bytes the service will read from the "
            "llama.cpp server. Responses exceeding this limit are treated as "
            "upstream failures (HTTP 502). Default is 1 MB."
        ),
    )

    # ── Stable Diffusion settings ─────────────────────────────────────────

    id_of_stable_diffusion_model: str = pydantic.Field(
        default="stable-diffusion-v1-5/stable-diffusion-v1-5",
        description=("Hugging Face model identifier or local filesystem path for the Stable Diffusion pipeline."),
    )

    revision_of_stable_diffusion_model: str = pydantic.Field(
        default="main",
        description=(
            "Hugging Face model revision identifier (a specific commit hash or "
            "branch name). Pinning to a commit hash ensures identical model "
            "weights across all deployments."
        ),
    )

    stable_diffusion_device: str = pydantic.Field(
        default="auto",
        description=(
            "Inference device selection: 'auto' selects CUDA when a compatible GPU "
            "is available, otherwise falls back to CPU. Explicit values 'cpu' and "
            "'cuda' are also supported."
        ),
    )

    number_of_inference_steps_of_stable_diffusion: int = pydantic.Field(
        default=20,
        ge=1,
        description=(
            "Number of diffusion inference steps per image. Lower values reduce latency at the cost of output quality."
        ),
    )

    guidance_scale_of_stable_diffusion: float = pydantic.Field(
        default=7.0,
        ge=0.0,
        description=(
            "Classifier-free guidance scale. Higher values follow the prompt more "
            "closely; lower values are more creative."
        ),
    )

    safety_checker_for_stable_diffusion: bool = pydantic.Field(
        default=True,
        description=("Enable the NSFW safety checker. Disabling removes content filtering from generated images."),
    )

    inference_timeout_by_stable_diffusion_per_baseline_unit_in_seconds: float | None = pydantic.Field(
        default=None,
        gt=0,
        description=(
            "Base timeout (seconds) for one 512x512 baseline unit image. "
            "None triggers auto-resolution: 10 on GPU, 60 on CPU. An explicit "
            "value overrides auto-detection unconditionally. No device-type "
            "multiplier is applied; the resolved value is the direct effective "
            "timeout. Actual timeout: base x n_images x (w x h) / (512 x 512)."
        ),
    )

    # ── Circuit breaker settings ──────────────────────────────────────────

    failure_threshold_of_circuit_breaker_for_large_language_model: int = pydantic.Field(
        default=5,
        ge=1,
        description=(
            "Number of consecutive failures to the llama.cpp language model server "
            "required to open the circuit breaker and begin rejecting requests "
            "immediately. A value of 1 opens the circuit on the very first failure. "
            "Higher values tolerate transient errors before triggering fail-fast "
            "behaviour."
        ),
    )

    recovery_timeout_of_circuit_breaker_for_large_language_model_in_seconds: float = pydantic.Field(
        default=30.0,
        gt=0,
        description=(
            "Duration in seconds that the circuit breaker remains in the open "
            "state (rejecting all requests immediately) before transitioning to "
            "half-open state and allowing a single probe request through to test "
            "whether the llama.cpp server has recovered."
        ),
    )

    # ── Admission control and resilience settings ─────────────────────────

    maximum_number_of_concurrent_operations_of_image_generation: int | None = pydantic.Field(
        default=None,
        ge=1,
        description=(
            "Maximum number of image generation inference operations permitted to "
            "execute concurrently within a single service instance. When this limit "
            "is reached, additional requests are rejected immediately with "
            "HTTP 429 (service_busy). None triggers auto-resolution: 2 on GPU, "
            "1 on CPU. An explicit value overrides auto-detection unconditionally."
        ),
    )

    retry_after_busy_in_seconds: int | None = pydantic.Field(
        default=None,
        ge=0,
        description=(
            "Value (in seconds) of the Retry-After response header on HTTP 429 "
            "(Too Many Requests) responses when the image generation admission "
            "control concurrency limit is reached (error code: service_busy). "
            "None triggers auto-resolution: 5 on GPU, 30 on CPU. An explicit "
            "value overrides auto-detection unconditionally."
        ),
    )

    retry_after_not_ready_in_seconds: int = pydantic.Field(
        default=10,
        ge=0,
        description=(
            "Value (in seconds) of the Retry-After response header on HTTP 503 (Service Unavailable) responses."
        ),
    )

    maximum_number_of_bytes_of_request_payload: int = pydantic.Field(
        default=1_048_576,
        ge=1,
        description=(
            "Maximum request payload size in bytes. Requests exceeding this limit "
            "are rejected with HTTP 413 before the body is fully read. Default is "
            "1 MB (1,048,576 bytes)."
        ),
    )

    timeout_for_requests_in_seconds: float | None = pydantic.Field(
        default=None,
        gt=0,
        description=(
            "Maximum end-to-end duration in seconds for any single HTTP request. "
            "Requests exceeding this ceiling are aborted with "
            "HTTP 504 (request_timeout). None triggers auto-resolution: 60 on GPU, "
            "300 on CPU. An explicit value overrides auto-detection unconditionally."
        ),
    )

    model_config = pydantic_settings.SettingsConfigDict(
        env_file=".env",
        env_prefix="TEXT_TO_IMAGE_",
    )

    # ── Sentinel resolution ───────────────────────────────────────────────

    _resolved_inference_device: str = ""

    def resolve_tier_dependent_defaults_for_inference_device(self) -> None:
        """
        Replace ``None`` sentinels with GPU or CPU defaults based on the
        detected Stable Diffusion inference device.

        This method must be called once after instantiation and before the
        configuration values are consumed by middleware or service
        construction.  Explicit operator overrides (non-``None`` values)
        are preserved unconditionally.
        """
        import torch  # noqa: PLC0415

        if self.stable_diffusion_device == "auto":
            detected_device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            detected_device = self.stable_diffusion_device

        self._resolved_inference_device = detected_device
        is_gpu = detected_device == "cuda"

        if self.inference_timeout_by_stable_diffusion_per_baseline_unit_in_seconds is None:
            self.inference_timeout_by_stable_diffusion_per_baseline_unit_in_seconds = (
                GPU_DEFAULT_INFERENCE_TIMEOUT_BY_STABLE_DIFFUSION_PER_BASELINE_UNIT_IN_SECONDS
                if is_gpu
                else CPU_DEFAULT_INFERENCE_TIMEOUT_BY_STABLE_DIFFUSION_PER_BASELINE_UNIT_IN_SECONDS
            )

        if self.maximum_number_of_concurrent_operations_of_image_generation is None:
            self.maximum_number_of_concurrent_operations_of_image_generation = (
                GPU_DEFAULT_MAXIMUM_NUMBER_OF_CONCURRENT_OPERATIONS_OF_IMAGE_GENERATION
                if is_gpu
                else CPU_DEFAULT_MAXIMUM_NUMBER_OF_CONCURRENT_OPERATIONS_OF_IMAGE_GENERATION
            )

        if self.retry_after_busy_in_seconds is None:
            self.retry_after_busy_in_seconds = (
                GPU_DEFAULT_RETRY_AFTER_BUSY_IN_SECONDS if is_gpu else CPU_DEFAULT_RETRY_AFTER_BUSY_IN_SECONDS
            )

        if self.timeout_for_requests_in_seconds is None:
            self.timeout_for_requests_in_seconds = (
                GPU_DEFAULT_TIMEOUT_FOR_REQUESTS_IN_SECONDS if is_gpu else CPU_DEFAULT_TIMEOUT_FOR_REQUESTS_IN_SECONDS
            )
