"""Tests for application/dependencies.py — FastAPI dependency providers."""

from unittest.mock import MagicMock

import application.dependencies


class TestGetLanguageModelService:

    def test_returns_service_from_app_state(self):
        mock_service = MagicMock()
        mock_request = MagicMock()
        mock_request.app.state.language_model_service = mock_service

        result = application.dependencies.get_language_model_service(mock_request)

        assert result is mock_service


class TestGetImageGenerationService:

    def test_returns_service_from_app_state(self):
        mock_service = MagicMock()
        mock_request = MagicMock()
        mock_request.app.state.image_generation_service = mock_service

        result = application.dependencies.get_image_generation_service(mock_request)

        assert result is mock_service
