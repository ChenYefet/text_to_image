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
import application.services.prompt_enhancement_service


def get_prompt_enhancement_service(
    request: fastapi.Request,
) -> application.services.prompt_enhancement_service.PromptEnhancementService:
    """
    Retrieve the shared PromptEnhancementService instance from application state.
    """
    return request.app.state.prompt_enhancement_service  # type: ignore[no-any-return]


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
    instance_of_image_generation_service = getattr(request.app.state, "image_generation_service", None)
    if instance_of_image_generation_service is None:
        raise application.exceptions.ImageGenerationServiceUnavailableError(
            detail=(
                "The image generation service is not available."
                " The Stable Diffusion model failed to load"
                " during startup."
            ),
        )
    return instance_of_image_generation_service  # type: ignore[no-any-return]


def get_admission_controller_for_image_generation(
    request: fastapi.Request,
) -> application.admission_control.AdmissionControllerForImageGeneration:
    """
    Retrieve the shared AdmissionControllerForImageGeneration from application
    state.  The controller is created during application startup with the
    operator-configured ``maximum_number_of_concurrent_operations_of_image_generation`` value.
    """
    return request.app.state.admission_controller_for_image_generation  # type: ignore[no-any-return]
