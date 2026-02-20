"""Tests for configuration.py — ApplicationConfiguration."""

import pydantic
import pytest

import configuration


class TestApplicationConfiguration:
    def test_default_values(self, monkeypatch):
        monkeypatch.delenv("TEXT_TO_IMAGE_LANGUAGE_MODEL_SERVER_BASE_URL", raising=False)
        monkeypatch.delenv("TEXT_TO_IMAGE_STABLE_DIFFUSION_MODEL_ID", raising=False)
        monkeypatch.delenv("TEXT_TO_IMAGE_STABLE_DIFFUSION_DEVICE", raising=False)
        monkeypatch.delenv("TEXT_TO_IMAGE_APPLICATION_HOST", raising=False)
        monkeypatch.delenv("TEXT_TO_IMAGE_APPLICATION_PORT", raising=False)
        monkeypatch.delenv("TEXT_TO_IMAGE_LANGUAGE_MODEL_REQUEST_TIMEOUT_SECONDS", raising=False)
        monkeypatch.delenv("TEXT_TO_IMAGE_CORS_ALLOWED_ORIGINS", raising=False)
        monkeypatch.delenv("TEXT_TO_IMAGE_STABLE_DIFFUSION_SAFETY_CHECKER", raising=False)
        monkeypatch.delenv("TEXT_TO_IMAGE_LOG_LEVEL", raising=False)
        monkeypatch.delenv("TEXT_TO_IMAGE_LANGUAGE_MODEL_TEMPERATURE", raising=False)
        monkeypatch.delenv("TEXT_TO_IMAGE_LANGUAGE_MODEL_MAX_TOKENS", raising=False)
        monkeypatch.delenv("TEXT_TO_IMAGE_STABLE_DIFFUSION_INFERENCE_STEPS", raising=False)
        monkeypatch.delenv("TEXT_TO_IMAGE_STABLE_DIFFUSION_GUIDANCE_SCALE", raising=False)
        monkeypatch.delenv("TEXT_TO_IMAGE_STABLE_DIFFUSION_INFERENCE_TIMEOUT_PER_UNIT_SECONDS", raising=False)

        config = configuration.ApplicationConfiguration()

        assert config.language_model_server_base_url == "http://localhost:8080"
        assert config.stable_diffusion_model_id == "stable-diffusion-v1-5/stable-diffusion-v1-5"
        assert config.stable_diffusion_device == "auto"
        assert config.application_host == "127.0.0.1"
        assert config.application_port == 8000
        assert config.language_model_request_timeout_seconds == 120.0
        assert config.cors_allowed_origins == []
        assert config.stable_diffusion_safety_checker is True
        assert config.log_level == "INFO"
        assert config.language_model_temperature == 0.7
        assert config.language_model_max_tokens == 512
        assert config.stable_diffusion_inference_steps == 20
        assert config.stable_diffusion_guidance_scale == 7.0
        assert config.stable_diffusion_inference_timeout_per_unit_seconds == 60.0

    def test_environment_variable_override(self, monkeypatch):
        monkeypatch.setenv("TEXT_TO_IMAGE_APPLICATION_PORT", "9999")
        config = configuration.ApplicationConfiguration()
        assert config.application_port == 9999

    def test_type_coercion(self, monkeypatch):
        monkeypatch.setenv("TEXT_TO_IMAGE_APPLICATION_PORT", "3000")
        config = configuration.ApplicationConfiguration()
        assert config.application_port == 3000
        assert isinstance(config.application_port, int)


class TestConfigurationValidation:
    def test_port_below_minimum_rejected(self, monkeypatch):
        monkeypatch.setenv("TEXT_TO_IMAGE_APPLICATION_PORT", "0")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_port_above_maximum_rejected(self, monkeypatch):
        monkeypatch.setenv("TEXT_TO_IMAGE_APPLICATION_PORT", "70000")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_negative_timeout_rejected(self, monkeypatch):
        monkeypatch.setenv("TEXT_TO_IMAGE_LANGUAGE_MODEL_REQUEST_TIMEOUT_SECONDS", "-1")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_zero_timeout_rejected(self, monkeypatch):
        monkeypatch.setenv("TEXT_TO_IMAGE_LANGUAGE_MODEL_REQUEST_TIMEOUT_SECONDS", "0")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_temperature_above_maximum_rejected(self, monkeypatch):
        monkeypatch.setenv("TEXT_TO_IMAGE_LANGUAGE_MODEL_TEMPERATURE", "3.0")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_negative_temperature_rejected(self, monkeypatch):
        monkeypatch.setenv("TEXT_TO_IMAGE_LANGUAGE_MODEL_TEMPERATURE", "-0.1")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_zero_inference_steps_rejected(self, monkeypatch):
        monkeypatch.setenv("TEXT_TO_IMAGE_STABLE_DIFFUSION_INFERENCE_STEPS", "0")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_negative_guidance_scale_rejected(self, monkeypatch):
        monkeypatch.setenv("TEXT_TO_IMAGE_STABLE_DIFFUSION_GUIDANCE_SCALE", "-1")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_zero_max_tokens_rejected(self, monkeypatch):
        monkeypatch.setenv("TEXT_TO_IMAGE_LANGUAGE_MODEL_MAX_TOKENS", "0")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()

    def test_zero_inference_timeout_rejected(self, monkeypatch):
        monkeypatch.setenv("TEXT_TO_IMAGE_STABLE_DIFFUSION_INFERENCE_TIMEOUT_PER_UNIT_SECONDS", "0")
        with pytest.raises(pydantic.ValidationError):
            configuration.ApplicationConfiguration()
