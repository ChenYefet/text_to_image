"""
Application configuration module.

Loads all configuration values from environment variables with the prefix
TEXT_TO_IMAGE_. Default values are provided for local development. A .env
file is also supported via pydantic-settings.
"""

import pydantic
import pydantic_settings


class ApplicationConfiguration(pydantic_settings.BaseSettings):
    """
    Centralised configuration for the Text-to-Image with Prompt Assist service.

    Every field maps to an environment variable prefixed with TEXT_TO_IMAGE_.
    For example, the field ``language_model_server_base_url`` is populated from
    the environment variable TEXT_TO_IMAGE_LANGUAGE_MODEL_SERVER_BASE_URL.

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

    language_model_server_base_url: str = "http://localhost:8080"
    stable_diffusion_model_id: str = "stable-diffusion-v1-5/stable-diffusion-v1-5"
    stable_diffusion_device: str = "auto"
    application_host: str = "127.0.0.1"
    application_port: int = pydantic.Field(default=8000, ge=1, le=65535)
    language_model_request_timeout_seconds: float = pydantic.Field(
        default=120.0, gt=0,
    )
    cors_allowed_origins: list[str] = []
    stable_diffusion_safety_checker: bool = True
    log_level: str = "INFO"
    language_model_temperature: float = pydantic.Field(
        default=0.7, ge=0.0, le=2.0,
    )
    language_model_max_tokens: int = pydantic.Field(default=512, ge=1)
    stable_diffusion_inference_steps: int = pydantic.Field(default=20, ge=1)
    stable_diffusion_guidance_scale: float = pydantic.Field(
        default=7.0, ge=0.0,
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
    rate_limit: str = pydantic.Field(
        default="10/minute",
        description=(
            "Rate limit for inference endpoints (prompt enhancement and image "
            "generation). Uses the format 'count/period' where period is one "
            "of: second, minute, hour, day. Set to '0/second' to disable."
        ),
    )

    model_config = pydantic_settings.SettingsConfigDict(
        env_file=".env",
        env_prefix="TEXT_TO_IMAGE_",
    )
