"""Tests for configuration.py — ApplicationConfiguration."""

import configuration


class TestApplicationConfiguration:

    def test_default_values(self, monkeypatch):
        monkeypatch.delenv("TEXT_TO_IMAGE_LANGUAGE_MODEL_SERVER_BASE_URL", raising=False)
        monkeypatch.delenv("TEXT_TO_IMAGE_LANGUAGE_MODEL_PATH", raising=False)
        monkeypatch.delenv("TEXT_TO_IMAGE_STABLE_DIFFUSION_MODEL_ID", raising=False)
        monkeypatch.delenv("TEXT_TO_IMAGE_STABLE_DIFFUSION_DEVICE", raising=False)
        monkeypatch.delenv("TEXT_TO_IMAGE_APPLICATION_HOST", raising=False)
        monkeypatch.delenv("TEXT_TO_IMAGE_APPLICATION_PORT", raising=False)
        monkeypatch.delenv("TEXT_TO_IMAGE_LANGUAGE_MODEL_REQUEST_TIMEOUT_SECONDS", raising=False)

        config = configuration.ApplicationConfiguration()

        assert config.language_model_server_base_url == "http://localhost:8080"
        assert config.language_model_path == ""
        assert config.stable_diffusion_model_id == "stable-diffusion-v1-5/stable-diffusion-v1-5"
        assert config.stable_diffusion_device == "auto"
        assert config.application_host == "0.0.0.0"
        assert config.application_port == 8000
        assert config.language_model_request_timeout_seconds == 120.0

    def test_environment_variable_override(self, monkeypatch):
        monkeypatch.setenv("TEXT_TO_IMAGE_APPLICATION_PORT", "9999")
        config = configuration.ApplicationConfiguration()
        assert config.application_port == 9999

    def test_type_coercion(self, monkeypatch):
        monkeypatch.setenv("TEXT_TO_IMAGE_APPLICATION_PORT", "3000")
        config = configuration.ApplicationConfiguration()
        assert config.application_port == 3000
        assert isinstance(config.application_port, int)
