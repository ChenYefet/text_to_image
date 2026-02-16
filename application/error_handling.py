"""
Centralised error-handling registration for the FastAPI application.

Every exception type that can be raised within the service is mapped to
a specific HTTP status code and a consistent JSON error response body.
The mapping follows the specification requirements:

    - Invalid JSON or validation failure  ->  400 Bad Request
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

        This handler intercepts FastAPI's default 422 Unprocessable Entity
        and converts it to a 400 Bad Request, as required by the specification.
        """
        logger.warning(
            "Request validation failed: %s",
            validation_error.errors(),
        )
        return fastapi.responses.JSONResponse(
            status_code=400,
            content=application.models.ErrorResponse(
                error=f"Invalid request: {validation_error.errors()}",
                status_code=400,
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
                error=unavailable_error.detail,
                status_code=502,
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
        Return 502 Bad Gateway when the Stable Diffusion server
        cannot be reached.
        """
        logger.error(
            "Image generation service unavailable: %s",
            unavailable_error.detail,
        )
        return fastapi.responses.JSONResponse(
            status_code=502,
            content=application.models.ErrorResponse(
                error=unavailable_error.detail,
                status_code=502,
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
        Return 500 Internal Server Error when prompt enhancement fails
        for a non-connectivity reason.
        """
        logger.error(
            "Prompt enhancement failed: %s",
            enhancement_error.detail,
        )
        return fastapi.responses.JSONResponse(
            status_code=500,
            content=application.models.ErrorResponse(
                error=enhancement_error.detail,
                status_code=500,
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
        Return 500 Internal Server Error when image generation fails
        for a non-connectivity reason.
        """
        logger.error(
            "Image generation failed: %s",
            generation_error.detail,
        )
        return fastapi.responses.JSONResponse(
            status_code=500,
            content=application.models.ErrorResponse(
                error=generation_error.detail,
                status_code=500,
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
                error="An unexpected internal error occurred.",
                status_code=500,
            ).model_dump(),
        )
