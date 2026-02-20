"""
Custom exception classes for the Text-to-Image with Prompt Assist service.

Each exception maps to a specific failure mode and is handled by the
centralised error-handling layer to produce a consistent JSON error response.
"""


class ServiceError(Exception):
    """
    Base exception for all service-level errors.

    Provides a ``detail`` attribute that error handlers use for the
    human-readable message in the JSON response body.
    """

    default_detail: str = "A service error occurred."

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.default_detail
        super().__init__(self.detail)


class LanguageModelServiceUnavailableError(ServiceError):
    """
    Raised when the llama.cpp language model server cannot be reached
    or returns a non-success HTTP status code.
    """

    default_detail = "The language model server is unavailable."


class ImageGenerationServiceUnavailableError(ServiceError):
    """
    Raised when the Stable Diffusion pipeline is not loaded or an
    unexpected runtime error occurs during inference.
    """

    default_detail = "The image generation server is unavailable."


class PromptEnhancementError(ServiceError):
    """
    Raised when prompt enhancement fails for a reason other than
    network connectivity (for example, a malformed response from the
    language model).
    """

    default_detail = "Prompt enhancement failed."


class ImageGenerationError(ServiceError):
    """
    Raised when image generation fails for a reason other than a runtime
    error (for example, the pipeline returned an empty image list).
    """

    default_detail = "Image generation failed."
