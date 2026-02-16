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

import configuration
import application.error_handling
import application.routes.prompt_enhancement_routes
import application.routes.image_generation_routes
import application.services.language_model_service
import application.services.image_generation_service

logger = logging.getLogger(__name__)


def create_application() -> fastapi.FastAPI:
    """
    Create and fully configure the FastAPI application.

    This function:
      1. Reads configuration from environment variables.
      2. Defines an async lifespan manager that initialises shared service
         instances on startup and closes them gracefully on shutdown.
      3. Registers all error handlers.
      4. Includes all route handlers.
    """
    application_configuration = configuration.ApplicationConfiguration()

    @contextlib.asynccontextmanager
    async def application_lifespan(
        fastapi_application: fastapi.FastAPI,
    ):
        """
        Manage the lifecycle of shared service instances.

        On startup, create the HTTP clients for the language model and
        image generation backends. On shutdown, close them to release
        network resources.
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
            application.services.image_generation_service.ImageGenerationService(
                stable_diffusion_server_base_url=(
                    application_configuration.stable_diffusion_server_base_url
                ),
                request_timeout_seconds=(
                    application_configuration.image_generation_request_timeout_seconds
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
            "Stable Diffusion server: %s",
            application_configuration.language_model_server_base_url,
            application_configuration.stable_diffusion_server_base_url,
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

    fastapi_application.include_router(
        application.routes.prompt_enhancement_routes.prompt_enhancement_router,
    )
    fastapi_application.include_router(
        application.routes.image_generation_routes.image_generation_router,
    )

    return fastapi_application
