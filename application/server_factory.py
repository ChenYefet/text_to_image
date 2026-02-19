"""
FastAPI application factory.

The ``create_application`` function constructs a fully configured FastAPI
instance with service lifecycle management, error handling, and route
registration. Using a factory function (rather than a module-level global)
makes the application straightforward to test and re-create.
"""

import contextlib
import logging

import fastapi
import fastapi.middleware.cors

import application.error_handling
import application.logging_config
import application.middleware
import application.routes.health_routes
import application.routes.image_generation_routes
import application.routes.prompt_enhancement_routes
import application.services.image_generation_service
import application.services.language_model_service
import configuration

logger = logging.getLogger(__name__)


def create_application() -> fastapi.FastAPI:
    """
    Create and fully configure the FastAPI application.

    This function:
      1. Reads configuration from environment variables.
      2. Defines an async lifespan manager that initialises shared service
         instances on startup and closes them gracefully on shutdown.
      3. Registers all error handlers.
      4. Adds the correlation-ID middleware.
      5. Includes all route handlers.
    """
    application_configuration = configuration.ApplicationConfiguration()
    application.logging_config.configure_logging(
        log_level=application_configuration.log_level,
    )

    @contextlib.asynccontextmanager
    async def application_lifespan(
        fastapi_application: fastapi.FastAPI,
    ):
        """
        Manage the lifecycle of shared service instances.

        On startup, create the language model HTTP client and load the
        Stable Diffusion pipeline in-process. On shutdown, close them
        to release resources.
        """
        language_model_service_instance = (
            application.services.language_model_service.LanguageModelService(
                language_model_server_base_url=(
                    application_configuration.language_model_server_base_url
                ),
                request_timeout_seconds=(
                    application_configuration.language_model_request_timeout_seconds
                ),
            )
        )

        image_generation_service_instance = (
            application.services.image_generation_service.ImageGenerationService.load_pipeline(
                model_id=(
                    application_configuration.stable_diffusion_model_id
                ),
                device_preference=(
                    application_configuration.stable_diffusion_device
                ),
                enable_safety_checker=(
                    application_configuration.stable_diffusion_safety_checker
                ),
            )
        )

        fastapi_application.state.language_model_service = (
            language_model_service_instance
        )
        fastapi_application.state.image_generation_service = (
            image_generation_service_instance
        )

        logger.info(
            "Services initialised. Language model server: %s | "
            "Stable Diffusion model: %s",
            application_configuration.language_model_server_base_url,
            application_configuration.stable_diffusion_model_id,
        )

        yield

        await language_model_service_instance.close()
        await image_generation_service_instance.close()
        logger.info("Services shut down gracefully.")

    fastapi_application = fastapi.FastAPI(
        title="Text-to-Image with Prompt Assist",
        description=(
            "A production-grade REST API service that generates images from "
            "text prompts using Stable Diffusion, with optional prompt "
            "enhancement powered by a llama.cpp language model."
        ),
        version="1.0.0",
        lifespan=application_lifespan,
    )

    application.error_handling.register_error_handlers(fastapi_application)

    if application_configuration.cors_allowed_origins:
        fastapi_application.add_middleware(
            fastapi.middleware.cors.CORSMiddleware,
            allow_origins=application_configuration.cors_allowed_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )

    fastapi_application.add_middleware(
        application.middleware.CorrelationIdMiddleware,
    )

    fastapi_application.include_router(
        application.routes.prompt_enhancement_routes.prompt_enhancement_router,
    )
    fastapi_application.include_router(
        application.routes.image_generation_routes.image_generation_router,
    )
    fastapi_application.include_router(
        application.routes.health_routes.health_router,
    )

    return fastapi_application
