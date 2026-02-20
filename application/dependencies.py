"""
FastAPI dependency injection providers.

Each function in this module retrieves a shared service instance from the
FastAPI application state. This pattern keeps route handlers decoupled from
service construction and makes the application straightforward to test.
"""

import fastapi

import application.services.image_generation_service
import application.services.language_model_service


def get_language_model_service(
    request: fastapi.Request,
) -> application.services.language_model_service.LanguageModelService:
    """
    Retrieve the shared LanguageModelService instance from application state.
    """
    return request.app.state.language_model_service  # type: ignore[no-any-return]


def get_image_generation_service(
    request: fastapi.Request,
) -> application.services.image_generation_service.ImageGenerationService:
    """
    Retrieve the shared ImageGenerationService instance from application state.
    """
    return request.app.state.image_generation_service  # type: ignore[no-any-return]
