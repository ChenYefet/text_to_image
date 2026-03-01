"""Tests for application/exceptions.py — custom exception classes."""

import application.exceptions


class TestServiceErrorBase:
    def test_all_exceptions_inherit_from_service_error(self):
        for exception_class in (
            application.exceptions.LargeLanguageModelServiceUnavailableError,
            application.exceptions.ImageGenerationServiceUnavailableError,
            application.exceptions.PromptEnhancementError,
            application.exceptions.ImageGenerationError,
            application.exceptions.ServiceBusyError,
        ):
            assert issubclass(exception_class, application.exceptions.ServiceError)


class TestLargeLanguageModelServiceUnavailableError:
    def test_default_message(self):
        exception = application.exceptions.LargeLanguageModelServiceUnavailableError()
        assert exception.detail == "The large language model server is unavailable."
        assert str(exception) == "The large language model server is unavailable."

    def test_custom_message(self):
        exception = application.exceptions.LargeLanguageModelServiceUnavailableError(detail="Custom detail")
        assert exception.detail == "Custom detail"
        assert str(exception) == "Custom detail"


class TestImageGenerationServiceUnavailableError:
    def test_default_message(self):
        exception = application.exceptions.ImageGenerationServiceUnavailableError()
        assert exception.detail == "The image generation server is unavailable."


class TestPromptEnhancementError:
    def test_default_message(self):
        exception = application.exceptions.PromptEnhancementError()
        assert exception.detail == "Prompt enhancement failed."


class TestImageGenerationError:
    def test_default_message(self):
        exception = application.exceptions.ImageGenerationError()
        assert exception.detail == "Image generation failed."


class TestServiceBusyError:
    def test_default_message(self):
        exception = application.exceptions.ServiceBusyError()
        assert "at capacity" in exception.detail
        assert "Retry-After" in exception.detail

    def test_custom_message(self):
        exception = application.exceptions.ServiceBusyError(detail="Custom busy message")
        assert exception.detail == "Custom busy message"
        assert str(exception) == "Custom busy message"
