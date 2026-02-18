"""
Centralised error-handling registration for the FastAPI application.

Every exception type that can be raised within the service is mapped to
a specific HTTP status code and a consistent JSON error response body.
The mapping follows the specification requirements:

    - Invalid JSON                        ->  400 Bad Request
    - Request validation failure          ->  400 Bad Request
    - Prompt enhancement failure          ->  502 Bad Gateway
    - Image generation failure            ->  502 Bad Gateway
    - Backend service unavailable         ->  502 Bad Gateway
    - Unexpected internal errors          ->  500 Internal Server Error
"""

import logging

import fastapi
import fastapi.exceptions
import fastapi.responses

import application.exceptions
import application.models

logger = logging.getLogger(__name__)


def _get_correlation_id(request: fastapi.Request) -> str:
    """Extract the correlation ID set by the middleware, or fall back."""
    return getattr(request.state, "correlation_id", "unknown")


def register_error_handlers(fastapi_application: fastapi.FastAPI) -> None:
    """
    Register all custom exception handlers on the given FastAPI application.

    This function must be called once during application initialisation
    (see ``server_factory.create_application``).
    """

    @fastapi_application.exception_handler(
        fastapi.exceptions.RequestValidationError,
    )
    async def handle_request_validation_error(
        request: fastapi.Request,
        validation_error: fastapi.exceptions.RequestValidationError,
    ) -> fastapi.responses.JSONResponse:
        """
        Return 400 Bad Request for invalid request bodies.

        Distinguishes between JSON parse errors (invalid_request_json)
        and schema validation errors (request_validation_failed).
        """
        errors = validation_error.errors()
        logger.warning("Request validation failed: %s", errors)

        is_json_error = any(
            error.get("type", "").startswith("json") for error in errors
        )

        if is_json_error:
            code = "invalid_request_json"
            message = "The request body contains invalid JSON."
        else:
            code = "request_validation_failed"
            message = f"Invalid request: {errors}"

        return fastapi.responses.JSONResponse(
            status_code=400,
            content=application.models.ErrorResponse(
                error=application.models.ErrorDetail(
                    code=code,
                    message=message,
                    correlation_id=_get_correlation_id(request),
                ),
            ).model_dump(),
        )

    @fastapi_application.exception_handler(
        application.exceptions.LanguageModelServiceUnavailableError,
    )
    async def handle_language_model_unavailable(
        request: fastapi.Request,
        unavailable_error: application.exceptions.LanguageModelServiceUnavailableError,
    ) -> fastapi.responses.JSONResponse:
        """
        Return 502 Bad Gateway when the llama.cpp language model server
        cannot be reached.
        """
        logger.error(
            "Language model service unavailable: %s",
            unavailable_error.detail,
        )
        return fastapi.responses.JSONResponse(
            status_code=502,
            content=application.models.ErrorResponse(
                error=application.models.ErrorDetail(
                    code="upstream_service_unavailable",
                    message=unavailable_error.detail,
                    correlation_id=_get_correlation_id(request),
                ),
            ).model_dump(),
        )

    @fastapi_application.exception_handler(
        application.exceptions.ImageGenerationServiceUnavailableError,
    )
    async def handle_image_generation_unavailable(
        request: fastapi.Request,
        unavailable_error: application.exceptions.ImageGenerationServiceUnavailableError,
    ) -> fastapi.responses.JSONResponse:
        """
        Return 502 Bad Gateway when the Stable Diffusion pipeline
        encounters a runtime failure.
        """
        logger.error(
            "Image generation service unavailable: %s",
            unavailable_error.detail,
        )
        return fastapi.responses.JSONResponse(
            status_code=502,
            content=application.models.ErrorResponse(
                error=application.models.ErrorDetail(
                    code="model_unavailable",
                    message=unavailable_error.detail,
                    correlation_id=_get_correlation_id(request),
                ),
            ).model_dump(),
        )

    @fastapi_application.exception_handler(
        application.exceptions.PromptEnhancementError,
    )
    async def handle_prompt_enhancement_error(
        request: fastapi.Request,
        enhancement_error: application.exceptions.PromptEnhancementError,
    ) -> fastapi.responses.JSONResponse:
        """
        Return 502 Bad Gateway when prompt enhancement fails.
        """
        logger.error(
            "Prompt enhancement failed: %s",
            enhancement_error.detail,
        )
        return fastapi.responses.JSONResponse(
            status_code=502,
            content=application.models.ErrorResponse(
                error=application.models.ErrorDetail(
                    code="upstream_service_unavailable",
                    message=enhancement_error.detail,
                    correlation_id=_get_correlation_id(request),
                ),
            ).model_dump(),
        )

    @fastapi_application.exception_handler(
        application.exceptions.ImageGenerationError,
    )
    async def handle_image_generation_error(
        request: fastapi.Request,
        generation_error: application.exceptions.ImageGenerationError,
    ) -> fastapi.responses.JSONResponse:
        """
        Return 502 Bad Gateway when image generation fails
        for a non-connectivity reason.
        """
        logger.error(
            "Image generation failed: %s",
            generation_error.detail,
        )
        return fastapi.responses.JSONResponse(
            status_code=502,
            content=application.models.ErrorResponse(
                error=application.models.ErrorDetail(
                    code="model_unavailable",
                    message=generation_error.detail,
                    correlation_id=_get_correlation_id(request),
                ),
            ).model_dump(),
        )

    @fastapi_application.exception_handler(Exception)
    async def handle_unexpected_error(
        request: fastapi.Request,
        unexpected_error: Exception,
    ) -> fastapi.responses.JSONResponse:
        """
        Return 500 Internal Server Error for any unhandled exception.

        This is the catch-all handler that ensures the service never returns
        a non-JSON error response, regardless of the failure mode.
        """
        logger.exception(
            "An unexpected error occurred: %s",
            unexpected_error,
        )
        return fastapi.responses.JSONResponse(
            status_code=500,
            content=application.models.ErrorResponse(
                error=application.models.ErrorDetail(
                    code="internal_server_error",
                    message="An unexpected internal error occurred.",
                    correlation_id=_get_correlation_id(request),
                ),
            ).model_dump(),
        )
