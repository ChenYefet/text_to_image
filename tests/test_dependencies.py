"""Tests for application/dependencies.py — FastAPI dependency providers."""

from unittest.mock import MagicMock

import pytest

import application.dependencies
import application.exceptions


class TestGetLargeLanguageModelService:
    def test_returns_service_from_app_state(self):
        mock_service = MagicMock()
        mock_request = MagicMock()
        mock_request.app.state.large_language_model_service = mock_service

        result = application.dependencies.get_large_language_model_service(mock_request)

        assert result is mock_service


class TestGetImageGenerationService:
    def test_returns_service_from_app_state(self):
        mock_service = MagicMock()
        mock_request = MagicMock()
        mock_request.app.state.image_generation_service = mock_service

        result = application.dependencies.get_image_generation_service(mock_request)

        assert result is mock_service

    def test_raises_unavailable_error_when_service_is_none(self):
        """
        When the Stable Diffusion model failed to load during startup
        (FR49 degraded state), the ``image_generation_service`` attribute
        on ``app.state`` is ``None``.  The dependency must raise
        ``ImageGenerationServiceUnavailableError`` so the client
        receives HTTP 502 with the ``model_unavailable`` error code
        rather than an opaque ``AttributeError``.
        """
        mock_request = MagicMock()
        mock_request.app.state.image_generation_service = None

        with pytest.raises(application.exceptions.ImageGenerationServiceUnavailableError) as exception_context:
            application.dependencies.get_image_generation_service(mock_request)

        assert "failed to load" in exception_context.value.detail

    def test_raises_unavailable_error_when_attribute_is_missing(self):
        """
        When the ``image_generation_service`` attribute does not exist
        on ``app.state`` at all (for example, if the startup sequence
        was interrupted before the attribute was set), the dependency
        must raise ``ImageGenerationServiceUnavailableError`` rather
        than ``AttributeError``.  This is achieved via ``getattr``
        with a ``None`` default.
        """
        mock_request = MagicMock(spec=[])
        mock_request.app = MagicMock(spec=[])
        mock_request.app.state = MagicMock(spec=[])

        with pytest.raises(application.exceptions.ImageGenerationServiceUnavailableError):
            application.dependencies.get_image_generation_service(mock_request)


class TestGetAdmissionControllerForImageGeneration:
    def test_returns_admission_controller_from_app_state(self):
        """
        The dependency must return the ``AdmissionControllerForImageGeneration``
        instance stored on ``app.state`` during application startup.
        """
        mock_controller = MagicMock()
        mock_request = MagicMock()
        mock_request.app.state.admission_controller_for_image_generation = mock_controller

        result = application.dependencies.get_admission_controller_for_image_generation(mock_request)

        assert result is mock_controller
