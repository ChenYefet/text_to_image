"""
Application configuration module.

Loads all configuration values from environment variables with the prefix
TEXT_TO_IMAGE_. Default values are provided for local development. A .env
file is also supported via pydantic-settings.
"""

import pydantic_settings


class ApplicationConfiguration(pydantic_settings.BaseSettings):
    """
    Centralised configuration for the Text-to-Image with Prompt Assist service.

    Every field maps to an environment variable prefixed with TEXT_TO_IMAGE_.
    For example, the field ``language_model_server_base_url`` is populated from
    the environment variable TEXT_TO_IMAGE_LANGUAGE_MODEL_SERVER_BASE_URL.
    """

    language_model_server_base_url: str = "http://localhost:8080"
    language_model_path: str = ""
    stable_diffusion_model_id: str = "stable-diffusion-v1-5/stable-diffusion-v1-5"
    stable_diffusion_device: str = "auto"
    application_host: str = "127.0.0.1"
    application_port: int = 8000
    language_model_request_timeout_seconds: float = 120.0
    cors_allowed_origins: list[str] = []
    stable_diffusion_safety_checker: bool = True
    log_level: str = "INFO"
    language_model_temperature: float = 0.7
    language_model_max_tokens: int = 512
    stable_diffusion_inference_steps: int = 20
    stable_diffusion_guidance_scale: float = 7.0

    model_config = pydantic_settings.SettingsConfigDict(
        env_file=".env",
        env_prefix="TEXT_TO_IMAGE_",
    )
