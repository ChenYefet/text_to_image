"""
FastAPI dependency injection providers.

Each function in this module retrieves a shared service instance from the
FastAPI application state. This pattern keeps route handlers decoupled from
service construction and makes the application straightforward to test.
"""

import fastapi

import application.admission_control
import application.exceptions
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

    When the Stable Diffusion model failed to load during startup (FR49),
    the service instance is ``None``.  In that case, this dependency raises
    ``ImageGenerationServiceUnavailableError`` immediately, producing an
    HTTP 502 response with the ``model_unavailable`` error code.  This
    ensures clients receive a meaningful error rather than an opaque 500.
    """
    image_generation_service_instance = getattr(request.app.state, "image_generation_service", None)
    if image_generation_service_instance is None:
        raise application.exceptions.ImageGenerationServiceUnavailableError(
            detail=(
                "The image generation service is not available. "
                "The Stable Diffusion model failed to load during startup."
            ),
        )
    return image_generation_service_instance  # type: ignore[no-any-return]


def get_image_generation_admission_controller(
    request: fastapi.Request,
) -> application.admission_control.ImageGenerationAdmissionController:
    """
    Retrieve the shared ImageGenerationAdmissionController from application
    state.  The controller is created during application startup with the
    operator-configured ``image_generation_maximum_concurrency`` value.
    """
    return request.app.state.image_generation_admission_controller  # type: ignore[no-any-return]
