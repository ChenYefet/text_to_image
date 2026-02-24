"""
Custom exception classes for the Text-to-Image with Prompt Assist service.

This module defines the complete exception hierarchy for all anticipated
failure modes in the service.  Each exception class maps to a specific
category of operational failure and is handled by the centralised
error-handling layer (``error_handling.py``) to produce a consistent
JSON error response with a machine-readable error code.

Exception hierarchy
-------------------
::

    Exception (Python built-in)
    └── ServiceError (base class for all service exceptions)
        ├── LanguageModelServiceUnavailableError  → HTTP 502
        ├── ImageGenerationServiceUnavailableError → HTTP 502
        ├── PromptEnhancementError                → HTTP 502
        ├── ImageGenerationError                  → HTTP 502
        └── ServiceBusyError                      → HTTP 429

Why a custom hierarchy?
~~~~~~~~~~~~~~~~~~~~~~~
Using a shared base class (``ServiceError``) with a ``detail`` attribute
allows the error-handling layer to extract a human-readable message from
any service exception without type-checking each subclass individually.
Each subclass carries a ``default_detail`` class attribute that provides
a sensible default message when no explicit detail is supplied at the
raise site.
"""


class ServiceError(Exception):
    """
    Base exception for all service-level errors.

    Every service exception carries a ``detail`` attribute containing a
    human-readable description of the failure.  This message is included
    in the JSON error response body sent to the client.

    Subclasses define a ``default_detail`` class attribute that provides
    a reasonable fallback message when no explicit detail string is passed
    to the constructor.

    Attributes:
        detail: A human-readable description of the error, safe for
            inclusion in API responses (no internal implementation details,
            stack traces, or sensitive information).
    """

    default_detail: str = "A service error occurred."

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.default_detail
        super().__init__(self.detail)


class LanguageModelServiceUnavailableError(ServiceError):
    """
    Raised when the llama.cpp language model server cannot be reached
    or returns a non-success HTTP status code.

    This exception is mapped to HTTP 502 (Bad Gateway) with the error
    code ``upstream_service_unavailable`` by the error-handling layer.

    Common causes:
        - The llama.cpp server process is not running.
        - The server URL in the configuration is incorrect.
        - The server returned a streaming response despite ``stream: false``.
        - The response body exceeded the configured maximum size.
        - The HTTP request to the server timed out.
    """

    default_detail = "The language model server is unavailable."


class ImageGenerationServiceUnavailableError(ServiceError):
    """
    Raised when the Stable Diffusion pipeline is not loaded or an
    unexpected runtime error occurs during inference.

    This exception is mapped to HTTP 502 (Bad Gateway) with the error
    code ``model_unavailable`` by the error-handling layer.

    Common causes:
        - The Stable Diffusion model failed to load during startup (FR49
          degraded state) and the pipeline reference is ``None``.
        - A PyTorch ``RuntimeError`` occurred during inference (for
          example, out-of-memory on the GPU).
        - The inference operation exceeded the computed timeout.
    """

    default_detail = "The image generation server is unavailable."


class PromptEnhancementError(ServiceError):
    """
    Raised when prompt enhancement fails for a reason other than
    network connectivity — typically a malformed or empty response
    from the language model.

    This exception is mapped to HTTP 502 (Bad Gateway) with the error
    code ``upstream_service_unavailable`` by the error-handling layer.

    Common causes:
        - The llama.cpp response body has an unexpected JSON structure
          (missing ``choices[0].message.content``).
        - The language model returned an empty enhanced prompt.
    """

    default_detail = "Prompt enhancement failed."


class ImageGenerationError(ServiceError):
    """
    Raised when image generation fails for a reason other than a runtime
    error — typically the pipeline returned an empty image list.

    This exception is mapped to HTTP 502 (Bad Gateway) with the error
    code ``model_unavailable`` by the error-handling layer.

    Common causes:
        - The Stable Diffusion pipeline returned zero images in its
          output, which should not happen under normal operation but
          may indicate a pipeline configuration error.
    """

    default_detail = "Image generation failed."


class ServiceBusyError(ServiceError):
    """
    Raised when the image generation admission control concurrency
    limit is fully occupied and cannot accept additional concurrent
    requests.

    The error-handling layer maps this to HTTP 429 (Too Many Requests)
    with the machine-readable error code ``service_busy`` and a
    ``Retry-After`` response header.

    This is distinct from IP-based rate limiting
    (``rate_limit_exceeded``):

    - **Admission control** (this exception) limits the *total* number
      of concurrent image generation operations across *all* clients
      within a single service instance.  It protects the GPU/CPU from
      overcommitment.

    - **Rate limiting** limits the *frequency* of requests from a
      *single* client IP address.  It prevents any one client from
      monopolising the service.
    """

    default_detail = (
        "The image generation service is at maximum concurrency. Please retry after the current operation completes."
    )
