"""
FastAPI application factory.

The ``create_application`` function constructs a fully configured FastAPI
instance with service lifecycle management, error handling, and route
registration. Using a factory function (rather than a module-level global)
makes the application straightforward to test and re-create.
"""

import collections.abc
import contextlib
import copy

import fastapi
import fastapi.middleware.cors
import fastapi.openapi.utils
import slowapi.errors
import structlog

import application.admission_control
import application.error_handling
import application.logging_config
import application.metrics
import application.middleware
import application.rate_limiting
import application.routes.health_routes
import application.routes.image_generation_routes
import application.routes.prompt_enhancement_routes
import application.services.image_generation_service
import application.services.language_model_service
import configuration

logger = structlog.get_logger()


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

    metrics_collector = application.metrics.MetricsCollector()
    in_flight_request_counter = application.middleware.InFlightRequestCounter()

    @contextlib.asynccontextmanager
    async def application_lifespan(
        fastapi_application: fastapi.FastAPI,
    ) -> collections.abc.AsyncIterator[None]:
        """
        Manage the lifecycle of shared service instances.

        On startup, create the language model HTTP client and load the
        Stable Diffusion pipeline in-process. On shutdown, close them
        to release resources.
        """
        language_model_service_instance = application.services.language_model_service.LanguageModelService(
            language_model_server_base_url=(application_configuration.language_model_server_base_url),
            request_timeout_seconds=(application_configuration.timeout_for_language_model_requests_in_seconds),
            temperature=(application_configuration.language_model_temperature),
            maximum_tokens=(application_configuration.language_model_maximum_tokens),
            system_prompt=(application_configuration.language_model_system_prompt),
            connection_pool_size=(application_configuration.language_model_connection_pool_size),
            maximum_response_bytes=(application_configuration.language_model_maximum_response_bytes),
        )

        # FR49 — Startup Model File Validation
        #
        # The specification requires the service to validate model file
        # availability during startup.  If the model cannot be loaded
        # (for example, because the model files are missing, corrupted,
        # or the model identifier is invalid), the service must:
        #
        #   1. Log a CRITICAL-level event describing the failure.
        #   2. Continue running (the liveness probe at GET /health
        #      returns HTTP 200 because the process is alive).
        #   3. Report not_ready on the readiness probe (GET /health/ready
        #      returns HTTP 503 with checks.image_generation = "unavailable").
        #
        # This enables orchestrators such as Kubernetes to detect the
        # degraded state via the readiness probe and take corrective
        # action (for example, restarting the pod or alerting operators)
        # without losing the ability to diagnose the failure via the
        # liveness probe and structured logs.
        image_generation_service_instance = None
        try:
            image_generation_service_instance = (
                application.services.image_generation_service.ImageGenerationService.load_pipeline(
                    model_id=(application_configuration.stable_diffusion_model_id),
                    model_revision=(application_configuration.stable_diffusion_model_revision),
                    device_preference=(application_configuration.stable_diffusion_device),
                    enable_safety_checker=(application_configuration.stable_diffusion_safety_checker),
                    number_of_inference_steps=(application_configuration.stable_diffusion_inference_steps),
                    guidance_scale=(application_configuration.stable_diffusion_guidance_scale),
                    inference_timeout_per_unit_seconds=(
                        application_configuration.stable_diffusion_inference_timeout_per_unit_seconds
                    ),
                )
            )
        except Exception as model_loading_error:
            logger.critical(
                "model_validation_at_startup_failed",
                model_id=application_configuration.stable_diffusion_model_id,
                model_revision=application_configuration.stable_diffusion_model_revision,
                error=str(model_loading_error),
            )

        # ── Startup warmup (SA-3) ────────────────────────────────────
        #
        # Run a minimal dummy inference to trigger PyTorch's one-time
        # kernel selection and JIT compilation during the startup
        # sequence rather than on the first real user request.  This
        # is a best-effort optimisation: if the warmup fails, the
        # first user request absorbs the warmup cost instead.
        if image_generation_service_instance is not None:
            await image_generation_service_instance.run_startup_warmup()

        image_generation_admission_controller_instance = (
            application.admission_control.ImageGenerationAdmissionController(
                maximum_concurrency=(application_configuration.image_generation_maximum_concurrency),
            )
        )

        fastapi_application.state.language_model_service = language_model_service_instance
        fastapi_application.state.image_generation_service = image_generation_service_instance
        fastapi_application.state.image_generation_admission_controller = image_generation_admission_controller_instance
        fastapi_application.state.metrics_collector = metrics_collector
        fastapi_application.state.retry_after_busy_seconds = application_configuration.retry_after_busy_seconds
        fastapi_application.state.retry_after_rate_limit_seconds = (
            application_configuration.retry_after_rate_limit_seconds
        )
        fastapi_application.state.retry_after_not_ready_seconds = (
            application_configuration.retry_after_not_ready_seconds
        )

        logger.info(
            "services_initialised",
            language_model_server=application_configuration.language_model_server_base_url,
            stable_diffusion_model=application_configuration.stable_diffusion_model_id,
            image_generation_maximum_concurrency=(application_configuration.image_generation_maximum_concurrency),
        )

        yield

        # ── Graceful shutdown sequence (FR40) ─────────────────────────────
        #
        # The v5.0.0 specification requires a ``graceful_shutdown_initiated``
        # log event at INFO level when the service begins its shutdown
        # sequence.  This event must include the number of HTTP requests
        # still in progress at the moment of shutdown initiation, allowing
        # operators to assess whether the graceful shutdown timeout
        # (``timeout_graceful_shutdown`` in Uvicorn) is sufficient for all
        # in-flight requests to complete before the process is forcefully
        # terminated.
        #
        # This is the first action in the shutdown sequence so that the
        # logged in-flight count reflects the state at the moment shutdown
        # begins, before any cleanup actions (such as closing HTTP clients
        # or releasing model pipelines) have taken place.
        logger.info(
            "graceful_shutdown_initiated",
            in_flight_requests=in_flight_request_counter.count,
        )

        await language_model_service_instance.close()
        if image_generation_service_instance is not None:
            await image_generation_service_instance.close()
        logger.info("services_shutdown_complete")

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

    application.rate_limiting.inference_rate_limit_configuration.configure(
        application_configuration.rate_limit,
    )
    fastapi_application.state.limiter = application.rate_limiting.rate_limiter
    fastapi_application.add_exception_handler(
        slowapi.errors.RateLimitExceeded,
        application.rate_limiting.rate_limit_exceeded_handler,  # type: ignore[arg-type]
    )

    if application_configuration.cors_allowed_origins:
        fastapi_application.add_middleware(
            fastapi.middleware.cors.CORSMiddleware,
            allow_origins=application_configuration.cors_allowed_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "Accept"],
        )

    # ── Middleware registration ───────────────────────────────────────
    #
    # ASGI middleware executes in reverse registration order: the last
    # call to ``add_middleware`` produces the outermost layer.  The
    # resulting execution order is:
    #
    #   Request → CorrelationId → RequestTimeout → ContentType
    #           → PayloadSizeLimit → CORS → App
    #
    # CorrelationId is outermost so that every request (including those
    # rejected by inner middleware) receives a traceable correlation ID.
    # RequestTimeout is second so that the entire request processing
    # pipeline (including validation and inference) is bounded by the
    # end-to-end timeout ceiling (NFR48).  ContentType rejects malformed
    # POST requests before the body is read.  PayloadSizeLimit then
    # guards against oversized payloads.  CORS (registered above, if
    # configured) is innermost.

    fastapi_application.add_middleware(
        application.middleware.RequestPayloadSizeLimitMiddleware,
        maximum_request_payload_bytes=(application_configuration.maximum_request_payload_bytes),
    )

    fastapi_application.add_middleware(
        application.middleware.ContentTypeValidationMiddleware,
    )

    fastapi_application.add_middleware(
        application.middleware.RequestTimeoutMiddleware,
        request_timeout_seconds=(application_configuration.timeout_for_requests_in_seconds),
    )

    fastapi_application.add_middleware(
        application.middleware.CorrelationIdMiddleware,
        metrics_collector=metrics_collector,
        in_flight_request_counter=in_flight_request_counter,
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

    # ── OpenAPI schema customisation ──────────────────────────────────
    #
    # FastAPI auto-generates a ``422 Unprocessable Entity`` response with
    # ``HTTPValidationError`` / ``ValidationError`` schemas for every route
    # that accepts a request body.  However, this service's custom error
    # handlers (see ``error_handling.py``) intercept all validation errors
    # and return ``400 Bad Request`` with the ``ErrorResponse`` schema
    # instead.  The 422 status code is never emitted by the live service.
    #
    # This customisation removes the phantom 422 entries and the unused
    # ``HTTPValidationError`` / ``ValidationError`` component schemas from
    # the generated OpenAPI specification, ensuring the documented API
    # contract accurately reflects the implementation.  It also adds
    # global error responses (404, 405, 500) that apply to every endpoint
    # but are handled at the framework level rather than per-route.
    _customise_openapi_schema(fastapi_application)

    return fastapi_application


def _customise_openapi_schema(fastapi_application: fastapi.FastAPI) -> None:
    """
    Post-process the FastAPI-generated OpenAPI schema to remove phantom
    entries and add global error responses.

    This function overrides the application's ``openapi()`` method with a
    custom implementation that:

    1. Generates the default OpenAPI schema via FastAPI's built-in
       ``get_openapi()`` utility.
    2. Removes the ``422`` response entry from every path operation,
       because the live service never returns HTTP 422 (all validation
       errors are intercepted and returned as HTTP 400).
    3. Removes the ``HTTPValidationError`` and ``ValidationError``
       component schemas that FastAPI generates to support the 422
       response, since they are no longer referenced.
    4. Caches the result on ``fastapi_application.openapi_schema`` so
       subsequent calls return the pre-computed schema without repeating
       the processing.
    """

    # The error response schema reference used for global error entries
    # (404, 405, 500).  These errors are handled at the framework and
    # middleware level and apply to every endpoint, but FastAPI does not
    # add them automatically because they are not declared per-route.
    _error_response_schema_reference = {
        "content": {
            "application/json": {
                "schema": {
                    "$ref": "#/components/schemas/ErrorResponse",
                },
            },
        },
    }

    def customised_openapi() -> dict:
        """
        Generate the OpenAPI schema with phantom 422 entries removed
        and global error responses added.
        """
        # Return the cached schema if it has already been generated.
        if fastapi_application.openapi_schema:
            return fastapi_application.openapi_schema

        openapi_schema = fastapi.openapi.utils.get_openapi(
            title=fastapi_application.title,
            version=fastapi_application.version,
            description=fastapi_application.description,
            routes=fastapi_application.routes,
        )

        # ── Step 1: Remove phantom 422 responses from all paths ───────
        for path_item in openapi_schema.get("paths", {}).values():
            for operation in path_item.values():
                if isinstance(operation, dict) and "responses" in operation:
                    operation["responses"].pop("422", None)

        # ── Step 2: Remove unused validation error schemas ────────────
        component_schemas = openapi_schema.get("components", {}).get(
            "schemas",
            {},
        )
        component_schemas.pop("HTTPValidationError", None)
        component_schemas.pop("ValidationError", None)

        # ── Step 3: Add global error responses to all path operations ─
        #
        # These errors are handled by the framework (404, 405) or by the
        # outermost middleware (500) and can occur on any endpoint.  Adding
        # them to every operation ensures the OpenAPI specification
        # accurately documents all possible error responses.
        global_error_responses = {
            "404": {
                **copy.deepcopy(_error_response_schema_reference),
                "description": ("Not Found — the requested endpoint does not exist (``not_found``)."),
            },
            "405": {
                **copy.deepcopy(_error_response_schema_reference),
                "description": (
                    "Method Not Allowed — the HTTP method is not "
                    "supported for this endpoint "
                    "(``method_not_allowed``). The ``Allow`` header "
                    "lists permitted methods."
                ),
            },
            "500": {
                **copy.deepcopy(_error_response_schema_reference),
                "description": (
                    "Internal Server Error — an unexpected error "
                    "occurred during request processing "
                    "(``internal_server_error``)."
                ),
            },
        }

        for path_item in openapi_schema.get("paths", {}).values():
            for operation in path_item.values():
                if isinstance(operation, dict) and "responses" in operation:
                    for status_code, response_schema in global_error_responses.items():
                        if status_code not in operation["responses"]:
                            operation["responses"][status_code] = copy.deepcopy(
                                response_schema,
                            )

        # Cache the customised schema so it is only computed once.
        fastapi_application.openapi_schema = openapi_schema
        return openapi_schema

    fastapi_application.openapi = customised_openapi  # type: ignore[method-assign]
