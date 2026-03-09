"""Tests for configuration.py — ApplicationConfiguration."""

import pydantic
import pytest

import application.configuration

# ── Helper: list of all environment variable names that the configuration
# model reads.  Used to clear stale values in tests that assert defaults. ──

ALL_CONFIGURATION_ENVIRONMENT_VARIABLE_NAMES: list[str] = [
    "TEXT_TO_IMAGE_APPLICATION_HOST",
    "TEXT_TO_IMAGE_APPLICATION_PORT",
    "TEXT_TO_IMAGE_CORS_ALLOWED_ORIGINS",
    "TEXT_TO_IMAGE_LOG_LEVEL",
    "TEXT_TO_IMAGE_LARGE_LANGUAGE_MODEL_PATH",
    "TEXT_TO_IMAGE_BASE_URL_OF_LARGE_LANGUAGE_MODEL_SERVER",
    "TEXT_TO_IMAGE_TIMEOUT_FOR_REQUESTS_TO_LARGE_LANGUAGE_MODEL_IN_SECONDS",
    "TEXT_TO_IMAGE_LARGE_LANGUAGE_MODEL_TEMPERATURE",
    "TEXT_TO_IMAGE_MAXIMUM_TOKENS_GENERATED_BY_LARGE_LANGUAGE_MODEL",
    "TEXT_TO_IMAGE_SYSTEM_PROMPT_FOR_LARGE_LANGUAGE_MODEL",
    "TEXT_TO_IMAGE_SIZE_OF_CONNECTION_POOL_FOR_LARGE_LANGUAGE_MODEL",
    "TEXT_TO_IMAGE_MAXIMUM_NUMBER_OF_BYTES_OF_RESPONSE_BODY_FROM_LARGE_LANGUAGE_MODEL",
    "TEXT_TO_IMAGE_ID_OF_STABLE_DIFFUSION_MODEL",
    "TEXT_TO_IMAGE_REVISION_OF_STABLE_DIFFUSION_MODEL",
    "TEXT_TO_IMAGE_STABLE_DIFFUSION_DEVICE",
    "TEXT_TO_IMAGE_NUMBER_OF_INFERENCE_STEPS_OF_STABLE_DIFFUSION",
    "TEXT_TO_IMAGE_GUIDANCE_SCALE_OF_STABLE_DIFFUSION",
    "TEXT_TO_IMAGE_SAFETY_CHECKER_FOR_STABLE_DIFFUSION",
    "TEXT_TO_IMAGE_INFERENCE_TIMEOUT_BY_STABLE_DIFFUSION_PER_BASELINE_UNIT_IN_SECONDS",
    "TEXT_TO_IMAGE_MAXIMUM_NUMBER_OF_CONCURRENT_OPERATIONS_OF_IMAGE_GENERATION",
    "TEXT_TO_IMAGE_RETRY_AFTER_BUSY_IN_SECONDS",
    "TEXT_TO_IMAGE_RETRY_AFTER_NOT_READY_IN_SECONDS",
    "TEXT_TO_IMAGE_MAXIMUM_NUMBER_OF_BYTES_OF_REQUEST_PAYLOAD",
    "TEXT_TO_IMAGE_TIMEOUT_FOR_REQUESTS_IN_SECONDS",
    "TEXT_TO_IMAGE_FAILURE_THRESHOLD_OF_CIRCUIT_BREAKER_FOR_LARGE_LANGUAGE_MODEL",
    "TEXT_TO_IMAGE_RECOVERY_TIMEOUT_OF_CIRCUIT_BREAKER_FOR_LARGE_LANGUAGE_MODEL_IN_SECONDS",
]


def _clear_all_configuration_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every TEXT_TO_IMAGE_* variable so the test reads only defaults.

    Also changes the working directory to a temporary location so that the
    ``.env`` file in the project root is not loaded by pydantic-settings,
    which reads ``env_file=".env"`` relative to the current working directory.
    Without this, values present in ``.env`` would override the code-level
    defaults that the test intends to verify.
    """
    for variable_name in ALL_CONFIGURATION_ENVIRONMENT_VARIABLE_NAMES:
        monkeypatch.delenv(variable_name, raising=False)
    import tempfile  # noqa: PLC0415

    monkeypatch.chdir(tempfile.gettempdir())


class TestApplicationConfigurationDefaults:
    """Verify that every field resolves to its specification-defined default."""

    def test_default_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_all_configuration_environment_variables(monkeypatch)
        application_configuration = application.configuration.ApplicationConfiguration()

        # ── Application settings ──
        assert application_configuration.application_host == "127.0.0.1"
        assert application_configuration.application_port == 8000
        assert application_configuration.cors_allowed_origins == []
        assert application_configuration.log_level == "INFO"

        # ── Language model settings ──
        assert application_configuration.large_language_model_path == ""
        assert application_configuration.base_url_of_large_language_model_server == "http://localhost:8080"
        assert application_configuration.timeout_for_requests_to_large_language_model_in_seconds == 30.0
        assert application_configuration.large_language_model_temperature == 0.7
        assert application_configuration.maximum_tokens_generated_by_large_language_model == 512
        assert "enhancing text-to-image prompts" in application_configuration.system_prompt_for_large_language_model
        assert application_configuration.size_of_connection_pool_for_large_language_model == 10
        assert application_configuration.maximum_number_of_bytes_of_response_body_from_large_language_model == 1_048_576

        # ── Stable Diffusion settings ──
        assert application_configuration.id_of_stable_diffusion_model == "stable-diffusion-v1-5/stable-diffusion-v1-5"
        assert application_configuration.revision_of_stable_diffusion_model == "main"
        assert application_configuration.stable_diffusion_device == "auto"
        assert application_configuration.number_of_inference_steps_of_stable_diffusion == 20
        assert application_configuration.guidance_scale_of_stable_diffusion == 7.0
        assert application_configuration.safety_checker_for_stable_diffusion is True
        assert application_configuration.inference_timeout_by_stable_diffusion_per_baseline_unit_in_seconds is None

        # ── Circuit breaker settings ──
        assert application_configuration.failure_threshold_of_circuit_breaker_for_large_language_model == 5
        assert application_configuration.recovery_timeout_of_circuit_breaker_for_large_language_model_in_seconds == 30.0

        # ── Admission control and resilience settings ──
        assert application_configuration.maximum_number_of_concurrent_operations_of_image_generation is None
        assert application_configuration.retry_after_busy_in_seconds is None
        assert application_configuration.retry_after_not_ready_in_seconds == 10
        assert application_configuration.maximum_number_of_bytes_of_request_payload == 1_048_576
        assert application_configuration.timeout_for_requests_in_seconds is None


class TestApplicationConfigurationOverrides:
    """Verify that each environment variable correctly overrides the default."""

    def test_environment_variable_override_for_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_APPLICATION_PORT", "9999")
        application_configuration = application.configuration.ApplicationConfiguration()
        assert application_configuration.application_port == 9999

    def test_type_coercion_for_integer_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_APPLICATION_PORT", "3000")
        application_configuration = application.configuration.ApplicationConfiguration()
        assert application_configuration.application_port == 3000
        assert isinstance(application_configuration.application_port, int)

    def test_system_prompt_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        custom_prompt = "You are a helpful assistant that improves prompts."
        monkeypatch.setenv("TEXT_TO_IMAGE_SYSTEM_PROMPT_FOR_LARGE_LANGUAGE_MODEL", custom_prompt)
        application_configuration = application.configuration.ApplicationConfiguration()
        assert application_configuration.system_prompt_for_large_language_model == custom_prompt

    def test_size_of_connection_pool_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_SIZE_OF_CONNECTION_POOL_FOR_LARGE_LANGUAGE_MODEL", "25")
        application_configuration = application.configuration.ApplicationConfiguration()
        assert application_configuration.size_of_connection_pool_for_large_language_model == 25

    def test_maximum_number_of_bytes_of_response_body_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "TEXT_TO_IMAGE_MAXIMUM_NUMBER_OF_BYTES_OF_RESPONSE_BODY_FROM_LARGE_LANGUAGE_MODEL",
            "2097152",
        )
        application_configuration = application.configuration.ApplicationConfiguration()
        assert application_configuration.maximum_number_of_bytes_of_response_body_from_large_language_model == 2_097_152

    def test_path_override_for_large_language_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TEXT_TO_IMAGE_LARGE_LANGUAGE_MODEL_PATH is reference-only but must be
        accepted as a configuration variable for deployment visibility."""
        monkeypatch.setenv(
            "TEXT_TO_IMAGE_LARGE_LANGUAGE_MODEL_PATH",
            "/models/Meta-Llama-3-8B-Instruct.Q4_K_M.gguf",
        )
        application_configuration = application.configuration.ApplicationConfiguration()
        assert application_configuration.large_language_model_path == "/models/Meta-Llama-3-8B-Instruct.Q4_K_M.gguf"

    def test_model_revision_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "TEXT_TO_IMAGE_REVISION_OF_STABLE_DIFFUSION_MODEL",
            "39593d5650112b4cc580433f6b0435385882d819",
        )
        application_configuration = application.configuration.ApplicationConfiguration()
        assert (
            application_configuration.revision_of_stable_diffusion_model == "39593d5650112b4cc580433f6b0435385882d819"
        )

    def test_maximum_number_of_concurrent_operations_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_MAXIMUM_NUMBER_OF_CONCURRENT_OPERATIONS_OF_IMAGE_GENERATION", "3")
        application_configuration = application.configuration.ApplicationConfiguration()
        assert application_configuration.maximum_number_of_concurrent_operations_of_image_generation == 3

    def test_retry_after_busy_in_seconds_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_RETRY_AFTER_BUSY_IN_SECONDS", "60")
        application_configuration = application.configuration.ApplicationConfiguration()
        assert application_configuration.retry_after_busy_in_seconds == 60

    def test_retry_after_not_ready_in_seconds_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_RETRY_AFTER_NOT_READY_IN_SECONDS", "20")
        application_configuration = application.configuration.ApplicationConfiguration()
        assert application_configuration.retry_after_not_ready_in_seconds == 20

    def test_maximum_number_of_bytes_of_request_payload_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_MAXIMUM_NUMBER_OF_BYTES_OF_REQUEST_PAYLOAD", "5242880")
        application_configuration = application.configuration.ApplicationConfiguration()
        assert application_configuration.maximum_number_of_bytes_of_request_payload == 5_242_880

    def test_request_timeout_seconds_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_TIMEOUT_FOR_REQUESTS_IN_SECONDS", "600")
        application_configuration = application.configuration.ApplicationConfiguration()
        assert application_configuration.timeout_for_requests_in_seconds == 600.0

    def test_circuit_breaker_failure_threshold_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_FAILURE_THRESHOLD_OF_CIRCUIT_BREAKER_FOR_LARGE_LANGUAGE_MODEL", "10")
        application_configuration = application.configuration.ApplicationConfiguration()
        assert application_configuration.failure_threshold_of_circuit_breaker_for_large_language_model == 10

    def test_circuit_breaker_recovery_timeout_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "TEXT_TO_IMAGE_RECOVERY_TIMEOUT_OF_CIRCUIT_BREAKER_FOR_LARGE_LANGUAGE_MODEL_IN_SECONDS",
            "60",
        )
        application_configuration = application.configuration.ApplicationConfiguration()
        assert application_configuration.recovery_timeout_of_circuit_breaker_for_large_language_model_in_seconds == 60.0


class TestConfigurationEnvironmentVariables:
    """
    Verify that environment variable names set the correct configuration values.

    These tests confirm that the canonical environment variable names defined
    in Section 17 of the v5.11.0 specification are accepted and mapped to the
    correct Python fields.
    """

    def test_environment_variable_for_large_language_model_path_is_accepted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEXT_TO_IMAGE_LARGE_LANGUAGE_MODEL_PATH is accepted and mapped to the
        large_language_model_path field (reference-only variable for deployment
        tooling visibility, §17 of the v5.11.0 specification)."""
        _clear_all_configuration_environment_variables(monkeypatch)
        monkeypatch.setenv(
            "TEXT_TO_IMAGE_LARGE_LANGUAGE_MODEL_PATH",
            "/opt/models/llama-3-8b.gguf",
        )
        application_configuration = application.configuration.ApplicationConfiguration()
        assert application_configuration.large_language_model_path == "/opt/models/llama-3-8b.gguf"

    def test_maximum_tokens_env_var_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TEXT_TO_IMAGE_MAXIMUM_TOKENS_GENERATED_BY_LARGE_LANGUAGE_MODEL overrides the default."""
        _clear_all_configuration_environment_variables(monkeypatch)
        monkeypatch.setenv("TEXT_TO_IMAGE_MAXIMUM_TOKENS_GENERATED_BY_LARGE_LANGUAGE_MODEL", "1024")
        application_configuration = application.configuration.ApplicationConfiguration()
        assert application_configuration.maximum_tokens_generated_by_large_language_model == 1024

    def test_maximum_number_of_bytes_of_response_body_env_var_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TEXT_TO_IMAGE_MAXIMUM_NUMBER_OF_BYTES_OF_RESPONSE_BODY_FROM_LARGE_LANGUAGE_MODEL overrides the default."""
        _clear_all_configuration_environment_variables(monkeypatch)
        monkeypatch.setenv("TEXT_TO_IMAGE_MAXIMUM_NUMBER_OF_BYTES_OF_RESPONSE_BODY_FROM_LARGE_LANGUAGE_MODEL", "524288")
        application_configuration = application.configuration.ApplicationConfiguration()
        assert application_configuration.maximum_number_of_bytes_of_response_body_from_large_language_model == 524_288

    def test_maximum_number_of_concurrent_operations_env_var_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TEXT_TO_IMAGE_MAXIMUM_NUMBER_OF_CONCURRENT_OPERATIONS_OF_IMAGE_GENERATION overrides the default."""
        _clear_all_configuration_environment_variables(monkeypatch)
        monkeypatch.setenv("TEXT_TO_IMAGE_MAXIMUM_NUMBER_OF_CONCURRENT_OPERATIONS_OF_IMAGE_GENERATION", "2")
        application_configuration = application.configuration.ApplicationConfiguration()
        assert application_configuration.maximum_number_of_concurrent_operations_of_image_generation == 2

    def test_maximum_tokens_validation_applied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Validation constraints are enforced for MAXIMUM_TOKENS."""
        _clear_all_configuration_environment_variables(monkeypatch)
        monkeypatch.setenv("TEXT_TO_IMAGE_MAXIMUM_TOKENS_GENERATED_BY_LARGE_LANGUAGE_MODEL", "0")
        with pytest.raises(pydantic.ValidationError):
            application.configuration.ApplicationConfiguration()

    def test_maximum_number_of_concurrent_operations_validation_applied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Validation constraints are enforced for MAXIMUM_NUMBER_OF_CONCURRENT_OPERATIONS_OF_IMAGE_GENERATION."""
        _clear_all_configuration_environment_variables(monkeypatch)
        monkeypatch.setenv("TEXT_TO_IMAGE_MAXIMUM_NUMBER_OF_CONCURRENT_OPERATIONS_OF_IMAGE_GENERATION", "0")
        with pytest.raises(pydantic.ValidationError):
            application.configuration.ApplicationConfiguration()


class TestConfigurationValidation:
    """Verify that invalid values are rejected during construction."""

    def test_port_below_minimum_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_APPLICATION_PORT", "0")
        with pytest.raises(pydantic.ValidationError):
            application.configuration.ApplicationConfiguration()

    def test_port_above_maximum_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_APPLICATION_PORT", "70000")
        with pytest.raises(pydantic.ValidationError):
            application.configuration.ApplicationConfiguration()

    def test_negative_timeout_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_TIMEOUT_FOR_REQUESTS_TO_LARGE_LANGUAGE_MODEL_IN_SECONDS", "-1")
        with pytest.raises(pydantic.ValidationError):
            application.configuration.ApplicationConfiguration()

    def test_zero_timeout_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_TIMEOUT_FOR_REQUESTS_TO_LARGE_LANGUAGE_MODEL_IN_SECONDS", "0")
        with pytest.raises(pydantic.ValidationError):
            application.configuration.ApplicationConfiguration()

    def test_temperature_above_maximum_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_LARGE_LANGUAGE_MODEL_TEMPERATURE", "3.0")
        with pytest.raises(pydantic.ValidationError):
            application.configuration.ApplicationConfiguration()

    def test_negative_temperature_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_LARGE_LANGUAGE_MODEL_TEMPERATURE", "-0.1")
        with pytest.raises(pydantic.ValidationError):
            application.configuration.ApplicationConfiguration()

    def test_zero_inference_steps_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_NUMBER_OF_INFERENCE_STEPS_OF_STABLE_DIFFUSION", "0")
        with pytest.raises(pydantic.ValidationError):
            application.configuration.ApplicationConfiguration()

    def test_negative_guidance_scale_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_GUIDANCE_SCALE_OF_STABLE_DIFFUSION", "-1")
        with pytest.raises(pydantic.ValidationError):
            application.configuration.ApplicationConfiguration()

    def test_zero_maximum_tokens_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_MAXIMUM_TOKENS_GENERATED_BY_LARGE_LANGUAGE_MODEL", "0")
        with pytest.raises(pydantic.ValidationError):
            application.configuration.ApplicationConfiguration()

    def test_zero_inference_timeout_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_INFERENCE_TIMEOUT_BY_STABLE_DIFFUSION_PER_BASELINE_UNIT_IN_SECONDS", "0")
        with pytest.raises(pydantic.ValidationError):
            application.configuration.ApplicationConfiguration()

    # ── New configuration variable validation ──

    def test_empty_system_prompt_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_SYSTEM_PROMPT_FOR_LARGE_LANGUAGE_MODEL", "")
        with pytest.raises(pydantic.ValidationError):
            application.configuration.ApplicationConfiguration()

    def test_zero_size_of_connection_pool_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_SIZE_OF_CONNECTION_POOL_FOR_LARGE_LANGUAGE_MODEL", "0")
        with pytest.raises(pydantic.ValidationError):
            application.configuration.ApplicationConfiguration()

    def test_zero_maximum_number_of_bytes_of_response_body_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_MAXIMUM_NUMBER_OF_BYTES_OF_RESPONSE_BODY_FROM_LARGE_LANGUAGE_MODEL", "0")
        with pytest.raises(pydantic.ValidationError):
            application.configuration.ApplicationConfiguration()

    def test_zero_maximum_number_of_concurrent_operations_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_MAXIMUM_NUMBER_OF_CONCURRENT_OPERATIONS_OF_IMAGE_GENERATION", "0")
        with pytest.raises(pydantic.ValidationError):
            application.configuration.ApplicationConfiguration()

    def test_negative_retry_after_busy_in_seconds_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_RETRY_AFTER_BUSY_IN_SECONDS", "-1")
        with pytest.raises(pydantic.ValidationError):
            application.configuration.ApplicationConfiguration()

    def test_negative_retry_after_not_ready_in_seconds_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_RETRY_AFTER_NOT_READY_IN_SECONDS", "-1")
        with pytest.raises(pydantic.ValidationError):
            application.configuration.ApplicationConfiguration()

    def test_zero_maximum_number_of_bytes_of_request_payload_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_MAXIMUM_NUMBER_OF_BYTES_OF_REQUEST_PAYLOAD", "0")
        with pytest.raises(pydantic.ValidationError):
            application.configuration.ApplicationConfiguration()

    def test_zero_request_timeout_seconds_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_TIMEOUT_FOR_REQUESTS_IN_SECONDS", "0")
        with pytest.raises(pydantic.ValidationError):
            application.configuration.ApplicationConfiguration()

    def test_negative_request_timeout_seconds_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_TIMEOUT_FOR_REQUESTS_IN_SECONDS", "-10")
        with pytest.raises(pydantic.ValidationError):
            application.configuration.ApplicationConfiguration()

    # ── Circuit breaker configuration validation ──

    def test_zero_circuit_breaker_failure_threshold_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_FAILURE_THRESHOLD_OF_CIRCUIT_BREAKER_FOR_LARGE_LANGUAGE_MODEL", "0")
        with pytest.raises(pydantic.ValidationError):
            application.configuration.ApplicationConfiguration()

    def test_negative_circuit_breaker_failure_threshold_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_IMAGE_FAILURE_THRESHOLD_OF_CIRCUIT_BREAKER_FOR_LARGE_LANGUAGE_MODEL", "-1")
        with pytest.raises(pydantic.ValidationError):
            application.configuration.ApplicationConfiguration()

    def test_zero_circuit_breaker_recovery_timeout_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "TEXT_TO_IMAGE_RECOVERY_TIMEOUT_OF_CIRCUIT_BREAKER_FOR_LARGE_LANGUAGE_MODEL_IN_SECONDS",
            "0",
        )
        with pytest.raises(pydantic.ValidationError):
            application.configuration.ApplicationConfiguration()

    def test_negative_circuit_breaker_recovery_timeout_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "TEXT_TO_IMAGE_RECOVERY_TIMEOUT_OF_CIRCUIT_BREAKER_FOR_LARGE_LANGUAGE_MODEL_IN_SECONDS",
            "-5",
        )
        with pytest.raises(pydantic.ValidationError):
            application.configuration.ApplicationConfiguration()


class TestTierDependentDefaultResolution:
    """Verify sentinel-based auto-resolution of tier-dependent configuration defaults."""

    def test_gpu_defaults_when_device_is_cuda(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_all_configuration_environment_variables(monkeypatch)
        monkeypatch.setenv("TEXT_TO_IMAGE_STABLE_DIFFUSION_DEVICE", "cuda")
        application_configuration = application.configuration.ApplicationConfiguration()
        application_configuration.resolve_tier_dependent_defaults_for_inference_device()

        assert application_configuration.inference_timeout_by_stable_diffusion_per_baseline_unit_in_seconds == 10.0
        assert application_configuration.maximum_number_of_concurrent_operations_of_image_generation == 2
        assert application_configuration.retry_after_busy_in_seconds == 5
        assert application_configuration.timeout_for_requests_in_seconds == 60.0
        assert application_configuration._resolved_inference_device == "cuda"

    def test_cpu_defaults_when_device_is_cpu(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_all_configuration_environment_variables(monkeypatch)
        monkeypatch.setenv("TEXT_TO_IMAGE_STABLE_DIFFUSION_DEVICE", "cpu")
        application_configuration = application.configuration.ApplicationConfiguration()
        application_configuration.resolve_tier_dependent_defaults_for_inference_device()

        assert application_configuration.inference_timeout_by_stable_diffusion_per_baseline_unit_in_seconds == 60.0
        assert application_configuration.maximum_number_of_concurrent_operations_of_image_generation == 1
        assert application_configuration.retry_after_busy_in_seconds == 30
        assert application_configuration.timeout_for_requests_in_seconds == 300.0
        assert application_configuration._resolved_inference_device == "cpu"

    def test_auto_detection_with_cuda_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_all_configuration_environment_variables(monkeypatch)
        import unittest.mock

        application_configuration = application.configuration.ApplicationConfiguration()
        with unittest.mock.patch("torch.cuda.is_available", return_value=True):
            application_configuration.resolve_tier_dependent_defaults_for_inference_device()

        assert application_configuration.inference_timeout_by_stable_diffusion_per_baseline_unit_in_seconds == 10.0
        assert application_configuration.maximum_number_of_concurrent_operations_of_image_generation == 2
        assert application_configuration.retry_after_busy_in_seconds == 5
        assert application_configuration.timeout_for_requests_in_seconds == 60.0
        assert application_configuration._resolved_inference_device == "cuda"

    def test_auto_detection_without_cuda(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_all_configuration_environment_variables(monkeypatch)
        import unittest.mock

        application_configuration = application.configuration.ApplicationConfiguration()
        with unittest.mock.patch("torch.cuda.is_available", return_value=False):
            application_configuration.resolve_tier_dependent_defaults_for_inference_device()

        assert application_configuration.inference_timeout_by_stable_diffusion_per_baseline_unit_in_seconds == 60.0
        assert application_configuration.maximum_number_of_concurrent_operations_of_image_generation == 1
        assert application_configuration.retry_after_busy_in_seconds == 30
        assert application_configuration.timeout_for_requests_in_seconds == 300.0
        assert application_configuration._resolved_inference_device == "cpu"

    def test_explicit_override_preserved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_all_configuration_environment_variables(monkeypatch)
        monkeypatch.setenv("TEXT_TO_IMAGE_STABLE_DIFFUSION_DEVICE", "cpu")
        monkeypatch.setenv("TEXT_TO_IMAGE_INFERENCE_TIMEOUT_BY_STABLE_DIFFUSION_PER_BASELINE_UNIT_IN_SECONDS", "25.0")
        monkeypatch.setenv("TEXT_TO_IMAGE_MAXIMUM_NUMBER_OF_CONCURRENT_OPERATIONS_OF_IMAGE_GENERATION", "4")
        monkeypatch.setenv("TEXT_TO_IMAGE_RETRY_AFTER_BUSY_IN_SECONDS", "15")
        monkeypatch.setenv("TEXT_TO_IMAGE_TIMEOUT_FOR_REQUESTS_IN_SECONDS", "120.0")
        application_configuration = application.configuration.ApplicationConfiguration()
        application_configuration.resolve_tier_dependent_defaults_for_inference_device()

        assert application_configuration.inference_timeout_by_stable_diffusion_per_baseline_unit_in_seconds == 25.0
        assert application_configuration.maximum_number_of_concurrent_operations_of_image_generation == 4
        assert application_configuration.retry_after_busy_in_seconds == 15
        assert application_configuration.timeout_for_requests_in_seconds == 120.0

    def test_mixed_sentinel_and_explicit_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_all_configuration_environment_variables(monkeypatch)
        monkeypatch.setenv("TEXT_TO_IMAGE_STABLE_DIFFUSION_DEVICE", "cuda")
        monkeypatch.setenv("TEXT_TO_IMAGE_TIMEOUT_FOR_REQUESTS_IN_SECONDS", "120.0")
        monkeypatch.setenv("TEXT_TO_IMAGE_RETRY_AFTER_BUSY_IN_SECONDS", "15")
        application_configuration = application.configuration.ApplicationConfiguration()
        application_configuration.resolve_tier_dependent_defaults_for_inference_device()

        assert application_configuration.inference_timeout_by_stable_diffusion_per_baseline_unit_in_seconds == 10.0
        assert application_configuration.maximum_number_of_concurrent_operations_of_image_generation == 2
        assert application_configuration.retry_after_busy_in_seconds == 15
        assert application_configuration.timeout_for_requests_in_seconds == 120.0
