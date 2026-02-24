"""
Application configuration module.

Loads all configuration values from environment variables with the prefix
TEXT_TO_IMAGE_. Default values are provided for local development. A .env
file is also supported via pydantic-settings.

Every configuration variable is documented in the v5.0.0 specification
(Section 17 — Configuration Requirements). This module is the single
source of truth for all runtime configuration within the service process.

"""

import pydantic
import pydantic_settings


class ApplicationConfiguration(pydantic_settings.BaseSettings):
    """
    Centralised configuration for the Text-to-Image with Prompt Assist service.

    Every field maps to an environment variable prefixed with TEXT_TO_IMAGE_.
    For example, the field ``language_model_server_base_url`` is populated from
    the environment variable TEXT_TO_IMAGE_LANGUAGE_MODEL_SERVER_BASE_URL.

    Configuration categories
    ------------------------
    - **Application**: host, port, CORS, log level, rate limit
    - **Language model (llama.cpp)**: server URL, timeout, temperature,
      maximum tokens, system prompt, connection pool size, maximum response bytes
    - **Stable Diffusion**: model ID, model revision, device, inference
      steps, guidance scale, safety checker, inference timeout
    - **Admission control and resilience**: maximum concurrency, retry-after
      durations, maximum request payload size, end-to-end request timeout

    Inference timeout note
    ----------------------
    The ``stable_diffusion_inference_timeout_per_unit_seconds`` (default 60 s)
    is the base timeout for generating a single 512×512 image.  The service
    scales it automatically for larger or batched requests and applies a 30×
    multiplier on CPU::

        timeout = base × n_images × (w × h) / (512 × 512)  [× 30 on CPU]

    The default works out of the box on both GPU (~1 min per unit) and CPU
    (~30 min per unit).  Operators on unusually slow hardware can override
    this value via the environment variable.
    """

    # ── Application settings ─────────────────────────────────────────────

    application_host: str = "127.0.0.1"

    application_port: int = pydantic.Field(default=8000, ge=1, le=65535)

    cors_allowed_origins: list[str] = pydantic.Field(
        default=[],
        description=(
            "Allowed CORS origins as a JSON list. An empty list disables CORS "
            "entirely. Example: '[\"http://localhost:3000\"]'."
        ),
    )

    log_level: str = pydantic.Field(
        default="INFO",
        description=(
            "Minimum log level for structured JSON logging. "
            "Accepted values: DEBUG, INFO, WARNING, ERROR, CRITICAL."
        ),
    )

    rate_limit: str = pydantic.Field(
        default="10/minute",
        description=(
            "Rate limit for inference endpoints (prompt enhancement and image "
            "generation). Uses the format 'count/period' where period is one "
            "of: second, minute, hour, day. Set to '0/second' to disable."
        ),
    )

    # ── Language model (llama.cpp) settings ───────────────────────────────

    language_model_path: str = pydantic.Field(
        default="",
        description=(
            "File path of the GGUF language model used by the llama.cpp "
            "server. This variable is reference only — it is not used at "
            "runtime by this service (which communicates with llama.cpp via "
            "HTTP), but is declared for tooling visibility, deployment "
            "automation, and environment variable inventory completeness "
            "(§17 of the v5.0.0 specification)."
        ),
    )

    language_model_server_base_url: str = pydantic.Field(
        default="http://localhost:8080",
        description=(
            "Base URL of the llama.cpp server running in OpenAI-compatible "
            "mode. The service appends /v1/chat/completions to this URL."
        ),
    )

    timeout_for_language_model_requests_in_seconds: float = pydantic.Field(
        default=120.0,
        gt=0,
        description=(
            "Maximum time in seconds to wait for a response from the "
            "llama.cpp server before treating the request as failed."
        ),
    )

    language_model_temperature: float = pydantic.Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description=(
            "Sampling temperature for prompt enhancement. Higher values "
            "produce more creative output; 0.0 is deterministic."
        ),
    )

    language_model_maximum_tokens: int = pydantic.Field(
        default=512,
        ge=1,
        description=(
            "Maximum number of tokens the language model may generate "
            "for an enhanced prompt."
        ),
    )

    language_model_system_prompt: str = pydantic.Field(
        default=(
            "You are an expert at enhancing text-to-image prompts. "
            "Transform the user's simple prompt into a detailed, visually "
            "descriptive prompt. Add artistic style, lighting, composition, "
            "and quality modifiers. Return only the enhanced prompt, nothing else."
        ),
        min_length=1,
        description=(
            "System prompt sent to the llama.cpp server on every prompt "
            "enhancement request. Controls the enhancement style and output "
            "format. Must be a non-empty string when set."
        ),
    )

    language_model_connection_pool_size: int = pydantic.Field(
        default=10,
        ge=1,
        description=(
            "Maximum number of connections maintained in the httpx connection "
            "pool for the llama.cpp HTTP client."
        ),
    )

    language_model_maximum_response_bytes: int = pydantic.Field(
        default=1_048_576,
        ge=1,
        description=(
            "Maximum response body size in bytes the service will read from "
            "the llama.cpp server. Responses exceeding this limit are treated "
            "as upstream failures (HTTP 502). Default is 1 MB."
        ),
    )

    # ── Stable Diffusion settings ─────────────────────────────────────────

    stable_diffusion_model_id: str = pydantic.Field(
        default="stable-diffusion-v1-5/stable-diffusion-v1-5",
        description=(
            "Hugging Face model identifier or local filesystem path for the "
            "Stable Diffusion pipeline."
        ),
    )

    stable_diffusion_model_revision: str = pydantic.Field(
        default="main",
        description=(
            "Hugging Face model revision identifier (a specific commit hash "
            "or branch name). Pinning to a commit hash ensures identical "
            "model weights across all deployments."
        ),
    )

    stable_diffusion_device: str = pydantic.Field(
        default="auto",
        description=(
            "Inference device selection: 'auto' selects CUDA when a compatible "
            "GPU is available, otherwise falls back to CPU. Explicit values "
            "'cpu' and 'cuda' are also supported."
        ),
    )

    stable_diffusion_inference_steps: int = pydantic.Field(
        default=20,
        ge=1,
        description=(
            "Number of diffusion inference steps per image. Lower values "
            "reduce latency at the cost of output quality."
        ),
    )

    stable_diffusion_guidance_scale: float = pydantic.Field(
        default=7.0,
        ge=0.0,
        description=(
            "Classifier-free guidance scale. Higher values follow the prompt "
            "more closely; lower values are more creative."
        ),
    )

    stable_diffusion_safety_checker: bool = pydantic.Field(
        default=True,
        description=(
            "Enable the NSFW safety checker. Disabling removes content "
            "filtering from generated images."
        ),
    )

    stable_diffusion_inference_timeout_per_unit_seconds: float = pydantic.Field(
        default=60.0,
        gt=0,
        description=(
            "Base timeout (seconds) for one 512×512 image. "
            "A 30× multiplier is auto-applied on CPU. "
            "Actual timeout: base × n_images × (w × h) / (512 × 512) [× 30 on CPU]."
        ),
    )

    # ── Admission control and resilience settings ─────────────────────────

    image_generation_maximum_concurrency: int = pydantic.Field(
        default=1,
        ge=1,
        description=(
            "Maximum number of image generation inference operations "
            "permitted to execute concurrently within a single service "
            "instance. When this limit is reached, additional requests are "
            "rejected immediately with HTTP 429 (service_busy)."
        ),
    )

    retry_after_busy_seconds: int = pydantic.Field(
        default=30,
        ge=0,
        description=(
            "Value (in seconds) of the Retry-After response header on "
            "HTTP 429 (Too Many Requests) responses when the image "
            "generation admission control concurrency limit is reached "
            "(error code: service_busy). This is a global capacity "
            "signal indicating that the GPU/CPU inference resource is "
            "fully occupied."
        ),
    )

    retry_after_rate_limit_seconds: int = pydantic.Field(
        default=60,
        ge=0,
        description=(
            "Value (in seconds) of the Retry-After response header on "
            "HTTP 429 (Too Many Requests) responses when the per-IP "
            "rate limit is exceeded (error code: rate_limit_exceeded). "
            "This is a per-client throttling signal distinct from the "
            "admission-control Retry-After value. A longer default (60 s "
            "versus 30 s) reflects that rate-limit violations indicate "
            "sustained high request frequency from a single client, "
            "which typically requires a longer backoff period."
        ),
    )

    retry_after_not_ready_seconds: int = pydantic.Field(
        default=10,
        ge=0,
        description=(
            "Value (in seconds) of the Retry-After response header on "
            "HTTP 503 (Service Unavailable) responses."
        ),
    )

    maximum_request_payload_bytes: int = pydantic.Field(
        default=1_048_576,
        ge=1,
        description=(
            "Maximum request payload size in bytes. Requests exceeding "
            "this limit are rejected with HTTP 413 before the body is "
            "fully read. Default is 1 MB (1,048,576 bytes)."
        ),
    )

    timeout_for_requests_in_seconds: float = pydantic.Field(
        default=300.0,
        gt=0,
        description=(
            "Maximum end-to-end duration in seconds for any single HTTP "
            "request. Requests exceeding this ceiling are aborted with "
            "HTTP 504 (request_timeout)."
        ),
    )

    model_config = pydantic_settings.SettingsConfigDict(
        env_file=".env",
        env_prefix="TEXT_TO_IMAGE_",
    )
