"""
Custom exception classes for the Text-to-Image with Prompt Assist service.

Each exception maps to a specific failure mode and is handled by the
centralised error-handling layer to produce a consistent JSON error response.
"""


class LanguageModelServiceUnavailableError(Exception):
    """
    Raised when the llama.cpp language model server cannot be reached
    or returns a non-success HTTP status code.
    """

    def __init__(
        self,
        detail: str = "The language model server is unavailable.",
    ) -> None:
        self.detail = detail
        super().__init__(self.detail)


class ImageGenerationServiceUnavailableError(Exception):
    """
    Raised when the Stable Diffusion image generation server cannot be
    reached or returns a non-success HTTP status code.
    """

    def __init__(
        self,
        detail: str = "The image generation server is unavailable.",
    ) -> None:
        self.detail = detail
        super().__init__(self.detail)


class PromptEnhancementError(Exception):
    """
    Raised when prompt enhancement fails for a reason other than
    network connectivity (for example, a malformed response from the
    language model).
    """

    def __init__(
        self,
        detail: str = "Prompt enhancement failed.",
    ) -> None:
        self.detail = detail
        super().__init__(self.detail)


class ImageGenerationError(Exception):
    """
    Raised when image generation fails for a reason other than network
    connectivity (for example, the Stable Diffusion server returned an
    empty image list).
    """

    def __init__(
        self,
        detail: str = "Image generation failed.",
    ) -> None:
        self.detail = detail
        super().__init__(self.detail)
