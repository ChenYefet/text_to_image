"""Tests for application/exceptions.py — custom exception classes."""

import application.exceptions


class TestServiceErrorBase:

    def test_all_exceptions_inherit_from_service_error(self):
        for exc_cls in (
            application.exceptions.LanguageModelServiceUnavailableError,
            application.exceptions.ImageGenerationServiceUnavailableError,
            application.exceptions.PromptEnhancementError,
            application.exceptions.ImageGenerationError,
        ):
            assert issubclass(exc_cls, application.exceptions.ServiceError)


class TestLanguageModelServiceUnavailableError:

    def test_default_message(self):
        exc = application.exceptions.LanguageModelServiceUnavailableError()
        assert exc.detail == "The language model server is unavailable."
        assert str(exc) == "The language model server is unavailable."

    def test_custom_message(self):
        exc = application.exceptions.LanguageModelServiceUnavailableError(
            detail="Custom detail"
        )
        assert exc.detail == "Custom detail"
        assert str(exc) == "Custom detail"


class TestImageGenerationServiceUnavailableError:

    def test_default_message(self):
        exc = application.exceptions.ImageGenerationServiceUnavailableError()
        assert exc.detail == "The image generation server is unavailable."


class TestPromptEnhancementError:

    def test_default_message(self):
        exc = application.exceptions.PromptEnhancementError()
        assert exc.detail == "Prompt enhancement failed."


class TestImageGenerationError:

    def test_default_message(self):
        exc = application.exceptions.ImageGenerationError()
        assert exc.detail == "Image generation failed."
