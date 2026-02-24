"""Tests for configuration.py — ApplicationConfiguration."""

import pydantic
import pytest

import configuration

# ── Helper: list of all environment variable names that the configuration
# model reads.  Used to clear stale values in tests that assert defaults. ──

ALL_CONFIGURATION_ENVIRONMENT_VARIABLE_NAMES: list[str] = [
    "TEXT_TO_IMAGE_APPLICATION_HOST",
    "TEXT_TO_IMAGE_APPLICATION_PORT",
    "TEXT_TO_IMAGE_CORS_ALLOWED_ORIGINS",
    "TEXT_TO_IMAGE_LOG_LEVEL",
    "TEXT_TO_IMAGE_RATE_LIMIT",
    "TEXT_TO_IMAGE_LANGUAGE_MODEL_PATH",
    "TEXT_TO_IMAGE_LANGUAGE_MODEL_SERVER_BASE_URL",
    "TEXT_TO_IMAGE_TIMEOUT_FOR_LANGUAGE_MODEL_REQUESTS_IN_SECONDS",
    "TEXT_TO_IMAGE_LANGUAGE_MODEL_TEMPERATURE",
    "TEXT_TO_IMAGE_LANGUAGE_MODEL_MAXIMUM_TOKENS",
    "TEXT_TO_IMAGE_LANGUAGE_MODEL_SYSTEM_PROMPT",
    "TEXT_TO_IMAGE_LANGUAGE_MODEL_CONNECTION_POOL_SIZE",
    "TEXT_TO_IMAGE_LANGUAGE_MODEL_MAXIMUM_RESPONSE_BYTES",
    "TEXT_TO_IMAGE_STABLE_DIFFUSION_MODEL_ID",
    "TEXT_TO_IMAGE_STABLE_DIFFUSION_MODEL_REVISION",
    "TEXT_TO_IMAGE_STABLE_DIFFUSION_DEVICE",
    "TEXT_TO_IMAGE_STABLE_DIFFUSION_INFERENCE_STEPS",
    "TEXT_TO_IMAGE_STABLE_DIFFUSION_GUIDANCE_SCALE",
    "TEXT_TO_IMAGE_STABLE_DIFFUSION_SAFETY_CHECKER",
    "TEXT_TO_IMAGE_STABLE_DIFFUSION_INFERENCE_TIMEOUT_PER_UNIT_SECONDS",
    "TEXT_TO_IMAGE_IMAGE_GENERATION_MAXIMUM_CONCURRENCY",
    "TEXT_TO_IMAGE_RETRY_AFTER_BUSY_SECONDS",
    "TEXT_TO_IMAGE_RETRY_AFTER_RATE_LIMIT_SECONDS",
    "TEXT_TO_IMAGE_RETRY_AFTER_NOT_READY_SECONDS",
    "TEXT_TO_IMAGE_MAXIMUM_REQUEST_PAYLOAD_BYTES",
    "TEXT_TO_IMAGE_TIMEOUT_FOR_REQUESTS_IN_SECONDS",
]


def _clear_all_configuration_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every TEXT_TO_IMAGE_* variable so the test reads only defaults."""
    for variable_name in ALL_CONFIGURATION_ENVIRONMENT_VARIABLE_NAMES:
        monkeypatch.delenv(variable_name, raising=False)


class TestApplicationConfigurationDefaults:
    """Verify that every field resolves to its specification-defined default."""

    def test_default_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_all_configuration_environment_variables(monkeypatch)
        application_configuration = configuration.ApplicationConfiguration()

        # ── Application settings ──
        assert application_configuration.application_host == "127.0.0.1"
        assert application_configuration.application_port == 8000
        assert application_configuration.cors_allowed_origins == []
        assert application_configuration.log_level == "INFO"
        assert application_configuration.rate_limit == "10/minute"

        # ── Language model settings ──
        assert application_configuration.language_model_path == ""
        assert application_configuration.language_model_server_base_url == "http://localhost:8080"
        assert application_configuration.timeout_for_language_model_requests_in_seconds == 120.0
        assert application_configuration.language_model_temperature == 0.7
        assert application_configuration.language_model_maximum_tokens == 512
        assert "enhancing text-to-image prompts" in application_configuration.language_model_system_prompt
        assert application_configuration.language_model_connection_pool_size == 10
        assert application_configuration.language_model_maximum_response_bytes == 1_048_576

        # ── Stable Diffusion settings ──
        assert application_configuration.stable_diffusion_model_id == "stable-diffusion-v1-5/stable-diffusion-v1-5"
        assert application_configuration.stable_diffusion_model_revision == "main"
        assert application_configuration.stable_diffusion_device == "auto"
        assert application_configuration.stable_diffusion_inference_steps == 20
        assert application_configuration.stable_diffusion_guidance_scale == 7.0
        assert application_configuration.stable_diffusion_safety_checker is True
        assert application_configuration.stable_diffusion_inference_timeout_per_unit_seconds == 60.0

        # ── Admission control and resilience settings ──
        assert application_configuration.image_generation_maximum_concurrency == 1
        assert application_configuration.retry_after_busy_seconds == 30
        assert application_configuration.retry_after_rate_limit_seconds == 60
        assert application_configuration.retry_after_not_ready_seconds == 10
        assert application_configuration.maximum_request_payload_bytes == 1_048_576
        assert application_configuration.timeout_for_requests_in_seconds == 300.0


class TestApplicationConfigurationOverrides:
    """Verify that each environment variable correctly overrides the default."""

    def test_environment_variable_override_for_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_APPLICATION_PORT", "9999")
        application_configuration = configuration.ApplicationConfiguration()
        assert application_configuration.application_port == 9999

    def test_type_coercion_for_integer_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_APPLICATION_PORT", "3000")
        application_configuration = configuration.ApplicationConfiguration()
        assert application_configuration.application_port == 3000
        assert isinstance(application_configuration.application_port, int)

    def test_system_prompt_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        custom_prompt = "You are a helpful assistant that improves prompts."
        monkeypatch.setenv("TEXT_TO_IMAGE_LANGUAGE_MODEL_SYSTEM_PROMPT", custom_prompt)
        application_configuration = configuration.ApplicationConfiguration()
        assert application_configuration.language_model_system_prompt == custom_prompt

    def test_connection_pool_size_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_LANGUAGE_MODEL_CONNECTION_POOL_SIZE", "25")
        application_configuration = configuration.ApplicationConfiguration()
        assert application_configuration.language_model_connection_pool_size == 25

    def test_maximum_response_bytes_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_LANGUAGE_MODEL_MAXIMUM_RESPONSE_BYTES", "2097152")
        application_configuration = configuration.ApplicationConfiguration()
        assert application_configuration.language_model_maximum_response_bytes == 2_097_152

    def test_language_model_path_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TEXT_TO_IMAGE_LANGUAGE_MODEL_PATH is reference-only but must be
        accepted as a configuration variable for deployment visibility."""
        monkeypatch.setenv(
            "TEXT_TO_IMAGE_LANGUAGE_MODEL_PATH",
            "/models/Meta-Llama-3-8B-Instruct.Q4_K_M.gguf",
        )
        application_configuration = configuration.ApplicationConfiguration()
        assert application_configuration.language_model_path == "/models/Meta-Llama-3-8B-Instruct.Q4_K_M.gguf"

    def test_model_revision_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "TEXT_TO_IMAGE_STABLE_DIFFUSION_MODEL_REVISION",
            "39593d5650112b4cc580433f6b0435385882d819",
        )
        application_configuration = configuration.ApplicationConfiguration()
        assert application_configuration.stable_diffusion_model_revision == "39593d5650112b4cc580433f6b0435385882d819"

    def test_maximum_concurrency_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_IMAGE_GENERATION_MAXIMUM_CONCURRENCY", "3")
        application_configuration = configuration.ApplicationConfiguration()
        assert application_configuration.image_generation_maximum_concurrency == 3

    def test_retry_after_busy_seconds_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_RETRY_AFTER_BUSY_SECONDS", "60")
        application_configuration = configuration.ApplicationConfiguration()
        assert application_configuration.retry_after_busy_seconds == 60

    def test_retry_after_rate_limit_seconds_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_RETRY_AFTER_RATE_LIMIT_SECONDS", "90")
        application_configuration = configuration.ApplicationConfiguration()
        assert application_configuration.retry_after_rate_limit_seconds == 90

    def test_retry_after_not_ready_seconds_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_RETRY_AFTER_NOT_READY_SECONDS", "20")
        application_configuration = configuration.ApplicationConfiguration()
        assert application_configuration.retry_after_not_ready_seconds == 20

    def test_maximum_request_payload_bytes_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_MAXIMUM_REQUEST_PAYLOAD_BYTES", "5242880")
        application_configuration = configuration.ApplicationConfiguration()
        assert application_configuration.maximum_request_payload_bytes == 5_242_880

    def test_request_timeout_seconds_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_TIMEOUT_FOR_REQUESTS_IN_SECONDS", "600")
        application_configuration = configuration.ApplicationConfiguration()
        assert application_configuration.timeout_for_requests_in_seconds == 600.0


class TestConfigurationEnvironmentVariables:
    """
    Verify that environment variable names set the correct configuration values.

    These tests confirm that the canonical environment variable names defined
    in Section 17 of the v5.0.0 specification are accepted and mapped to the
    correct Python fields.
    """

    def test_language_model_path_env_var_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TEXT_TO_IMAGE_LANGUAGE_MODEL_PATH is accepted and mapped to the
        language_model_path field (reference-only variable for deployment
        tooling visibility, §17 of the v5.0.0 specification)."""
        _clear_all_configuration_environment_variables(monkeypatch)
        monkeypatch.setenv(
            "TEXT_TO_IMAGE_LANGUAGE_MODEL_PATH",
            "/opt/models/llama-3-8b.gguf",
        )
        application_configuration = configuration.ApplicationConfiguration()
        assert application_configuration.language_model_path == "/opt/models/llama-3-8b.gguf"

    def test_maximum_tokens_env_var_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TEXT_TO_IMAGE_LANGUAGE_MODEL_MAXIMUM_TOKENS overrides the default."""
        _clear_all_configuration_environment_variables(monkeypatch)
        monkeypatch.setenv("TEXT_TO_IMAGE_LANGUAGE_MODEL_MAXIMUM_TOKENS", "1024")
        application_configuration = configuration.ApplicationConfiguration()
        assert application_configuration.language_model_maximum_tokens == 1024

    def test_maximum_response_bytes_env_var_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TEXT_TO_IMAGE_LANGUAGE_MODEL_MAXIMUM_RESPONSE_BYTES overrides the default."""
        _clear_all_configuration_environment_variables(monkeypatch)
        monkeypatch.setenv("TEXT_TO_IMAGE_LANGUAGE_MODEL_MAXIMUM_RESPONSE_BYTES", "524288")
        application_configuration = configuration.ApplicationConfiguration()
        assert application_configuration.language_model_maximum_response_bytes == 524_288

    def test_maximum_concurrency_env_var_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TEXT_TO_IMAGE_IMAGE_GENERATION_MAXIMUM_CONCURRENCY overrides the default."""
        _clear_all_configuration_environment_variables(monkeypatch)
        monkeypatch.setenv("TEXT_TO_IMAGE_IMAGE_GENERATION_MAXIMUM_CONCURRENCY", "2")
        application_configuration = configuration.ApplicationConfiguration()
        assert application_configuration.image_generation_maximum_concurrency == 2

    def test_maximum_tokens_validation_applied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Validation constraints are enforced for MAXIMUM_TOKENS."""
        _clear_all_configuration_environment_variables(monkeypatch)
        monkeypatch.setenv("TEXT_TO_IMAGE_LANGUAGE_MODEL_MAXIMUM_TOKENS", "0")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_maximum_concurrency_validation_applied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Validation constraints are enforced for MAXIMUM_CONCURRENCY."""
        _clear_all_configuration_environment_variables(monkeypatch)
        monkeypatch.setenv("TEXT_TO_IMAGE_IMAGE_GENERATION_MAXIMUM_CONCURRENCY", "0")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()


class TestConfigurationValidation:
    """Verify that invalid values are rejected during construction."""

    def test_port_below_minimum_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_APPLICATION_PORT", "0")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_port_above_maximum_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_APPLICATION_PORT", "70000")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_negative_timeout_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_TIMEOUT_FOR_LANGUAGE_MODEL_REQUESTS_IN_SECONDS", "-1")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_zero_timeout_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_TIMEOUT_FOR_LANGUAGE_MODEL_REQUESTS_IN_SECONDS", "0")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_temperature_above_maximum_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_LANGUAGE_MODEL_TEMPERATURE", "3.0")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_negative_temperature_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_LANGUAGE_MODEL_TEMPERATURE", "-0.1")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_zero_inference_steps_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_STABLE_DIFFUSION_INFERENCE_STEPS", "0")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_negative_guidance_scale_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_STABLE_DIFFUSION_GUIDANCE_SCALE", "-1")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_zero_maximum_tokens_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_LANGUAGE_MODEL_MAXIMUM_TOKENS", "0")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_zero_inference_timeout_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_STABLE_DIFFUSION_INFERENCE_TIMEOUT_PER_UNIT_SECONDS", "0")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    # ── New configuration variable validation ──

    def test_empty_system_prompt_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_LANGUAGE_MODEL_SYSTEM_PROMPT", "")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_zero_connection_pool_size_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_LANGUAGE_MODEL_CONNECTION_POOL_SIZE", "0")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_zero_maximum_response_bytes_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_LANGUAGE_MODEL_MAXIMUM_RESPONSE_BYTES", "0")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_zero_maximum_concurrency_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_IMAGE_GENERATION_MAXIMUM_CONCURRENCY", "0")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_negative_retry_after_busy_seconds_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_RETRY_AFTER_BUSY_SECONDS", "-1")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_negative_retry_after_rate_limit_seconds_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_RETRY_AFTER_RATE_LIMIT_SECONDS", "-1")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_negative_retry_after_not_ready_seconds_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_RETRY_AFTER_NOT_READY_SECONDS", "-1")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_zero_maximum_request_payload_bytes_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_MAXIMUM_REQUEST_PAYLOAD_BYTES", "0")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_zero_request_timeout_seconds_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_TIMEOUT_FOR_REQUESTS_IN_SECONDS", "0")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_negative_request_timeout_seconds_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_TIMEOUT_FOR_REQUESTS_IN_SECONDS", "-10")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()
