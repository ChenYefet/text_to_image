"""
FastAPI application factory and module-level application instance.

The ``create_application`` function constructs a fully configured FastAPI
instance with service lifecycle management, error handling, and route
registration. Using a factory function (rather than a module-level global)
makes the application straightforward to test and re-create.

The module-level ``fastapi_application`` instance is the entry point for
Uvicorn (``application.main:fastapi_application``).
"""

import collections.abc
import concurrent.futures
import contextlib
import copy

import fastapi
import fastapi.middleware.cors
import fastapi.openapi.utils
import structlog

import application.admission_control
import application.api.endpoints.health
import application.api.endpoints.image_generation
import application.api.endpoints.prompt_enhancement
import application.api.error_handlers
import application.api.middleware.content_type_validation
import application.api.middleware.correlation_identifier
import application.api.middleware.request_logging
import application.api.middleware.request_payload_size_limit
import application.api.middleware.request_timeout
import application.circuit_breaker
import application.configuration
import application.integrations.llama_cpp_client
import application.integrations.stable_diffusion_pipeline
import application.integrations.stable_diffusion_pipeline_pool
import application.logging_config
import application.metrics
import application.services.image_generation_service
import application.services.prompt_enhancement_service

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
    application_configuration = application.configuration.ApplicationConfiguration()
    application.logging_config.configure_logging(
        log_level=application_configuration.log_level,
    )

    metrics_collector = application.metrics.MetricsCollector()
    in_flight_request_counter = application.api.middleware.correlation_identifier.InFlightRequestCounter()

    @contextlib.asynccontextmanager
    async def application_lifespan(
        fastapi_application: fastapi.FastAPI,
    ) -> collections.abc.AsyncIterator[None]:
        """
        Manage the lifecycle of shared service instances.

        On startup, create the large language model HTTP client and load the
        Stable Diffusion pipeline in-process. On shutdown, close them
        to release resources.
        """
        circuit_breaker_for_large_language_model = application.circuit_breaker.CircuitBreaker(
            failure_threshold=(application_configuration.failure_threshold_of_circuit_breaker_for_large_language_model),
            timeout_for_recovery_in_seconds=(
                application_configuration.recovery_timeout_of_circuit_breaker_for_large_language_model_in_seconds
            ),
            name="large_language_model",
        )

        instance_of_llama_cpp_client = application.integrations.llama_cpp_client.LlamaCppClient(
            base_url_of_large_language_model_server=(application_configuration.base_url_of_large_language_model_server),
            request_timeout_in_seconds=(
                application_configuration.timeout_for_requests_to_large_language_model_in_seconds
            ),
            temperature=(application_configuration.large_language_model_temperature),
            maximum_tokens=(application_configuration.maximum_tokens_generated_by_large_language_model),
            system_prompt=(application_configuration.system_prompt_for_large_language_model),
            size_of_connection_pool=(application_configuration.size_of_connection_pool_for_large_language_model),
            maximum_number_of_bytes_of_response_body=(
                application_configuration.maximum_number_of_bytes_of_response_body_from_large_language_model
            ),
            circuit_breaker=circuit_breaker_for_large_language_model,
        )

        # ── Custom thread pool executor (spec §14) ────────────────────
        #
        # The specification mandates that the default thread pool executor
        # be sized to match the configured concurrency limit.  This
        # executor is used for all CPU-bound operations: Stable Diffusion
        # inference and image encoding (PIL → PNG → base64).  Sizing the
        # pool to the concurrency limit ensures that the number of
        # concurrent blocking threads never exceeds the admission control
        # boundary, preventing unnecessary memory consumption and
        # preserving the sizing-to-concurrency safety property.
        thread_pool_executor_for_inference = concurrent.futures.ThreadPoolExecutor(
            max_workers=application_configuration.maximum_number_of_concurrent_operations_of_image_generation,
            thread_name_prefix="inference",
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
        # ── Service-layer construction ────────────────────────────────
        #
        # The PromptEnhancementService wraps the LlamaCppClient,
        # providing the architectural boundary between API and
        # integration layers.
        instance_of_prompt_enhancement_service = (
            application.services.prompt_enhancement_service.PromptEnhancementService(
                llama_cpp_client=instance_of_llama_cpp_client,
            )
        )

        number_of_concurrency_slots = (
            application_configuration.maximum_number_of_concurrent_operations_of_image_generation
        )
        loaded_pipeline_instances: list[application.integrations.stable_diffusion_pipeline.StableDiffusionPipeline] = []
        try:
            for slot_index in range(number_of_concurrency_slots):
                loaded_pipeline_instances.append(
                    application.integrations.stable_diffusion_pipeline.StableDiffusionPipeline.load_pipeline(
                        model_id=(application_configuration.id_of_stable_diffusion_model),
                        thread_pool_executor_for_inference=thread_pool_executor_for_inference,
                        model_revision=(application_configuration.revision_of_stable_diffusion_model),
                        device_preference=(application_configuration.stable_diffusion_device),
                        enable_safety_checker=(application_configuration.safety_checker_for_stable_diffusion),
                        number_of_inference_steps=(
                            application_configuration.number_of_inference_steps_of_stable_diffusion
                        ),
                        guidance_scale=(application_configuration.guidance_scale_of_stable_diffusion),
                        inference_timeout_per_baseline_unit_in_seconds=(
                            application_configuration.inference_timeout_by_stable_diffusion_per_baseline_unit_in_seconds
                        ),
                        slot_index=slot_index,
                    )
                )
        except Exception as model_loading_error:
            logger.critical(
                "model_validation_at_startup_failed",
                model_id=application_configuration.id_of_stable_diffusion_model,
                model_revision=application_configuration.revision_of_stable_diffusion_model,
                error=str(model_loading_error),
            )
            # Clean up any instances that were successfully loaded before
            # the failure, to avoid leaking GPU memory.
            for previously_loaded_instance in loaded_pipeline_instances:
                await previously_loaded_instance.close()
            loaded_pipeline_instances.clear()

        instance_of_stable_diffusion_pipeline_pool = None
        if loaded_pipeline_instances:
            logger.info(
                "model_validation_at_startup_passed",
                model_id=application_configuration.id_of_stable_diffusion_model,
                model_revision=application_configuration.revision_of_stable_diffusion_model,
                device=str(loaded_pipeline_instances[0]._device),
                number_of_pool_instances=len(loaded_pipeline_instances),
            )

            instance_of_stable_diffusion_pipeline_pool = (
                application.integrations.stable_diffusion_pipeline_pool.StableDiffusionPipelinePool(
                    pipeline_instances=loaded_pipeline_instances,
                )
            )

        # ── Startup warmup (SA-3) ────────────────────────────────────
        #
        # Run a minimal dummy inference to trigger PyTorch's one-time
        # kernel selection and JIT compilation during the startup
        # sequence rather than on the first real user request.  This
        # is a best-effort optimisation: if the warmup fails, the
        # first user request absorbs the warmup cost instead.
        for pipeline_instance_to_warm_up in loaded_pipeline_instances:
            await pipeline_instance_to_warm_up.run_startup_warmup()

        # ── ImageGenerationService construction ──────────────────────
        #
        # The ImageGenerationService wraps the StableDiffusionPipelinePool
        # and PromptEnhancementService, absorbing orchestration logic
        # (seed resolution, prompt enhancement coordination, response
        # construction) that the endpoint handler delegates to it.
        # When the pipeline failed to load, the service is None and
        # the dependency provider raises ImageGenerationServiceUnavailableError.
        instance_of_image_generation_service = None
        if instance_of_stable_diffusion_pipeline_pool is not None:
            instance_of_image_generation_service = application.services.image_generation_service.ImageGenerationService(
                stable_diffusion_pipeline_pool=instance_of_stable_diffusion_pipeline_pool,
                prompt_enhancement_service=instance_of_prompt_enhancement_service,
            )

        instance_of_admission_controller_for_image_generation = (
            application.admission_control.AdmissionControllerForImageGeneration(
                maximum_number_of_concurrent_operations=(
                    application_configuration.maximum_number_of_concurrent_operations_of_image_generation
                ),
            )
        )

        fastapi_application.state.prompt_enhancement_service = instance_of_prompt_enhancement_service
        fastapi_application.state.image_generation_service = instance_of_image_generation_service
        fastapi_application.state.admission_controller_for_image_generation = (
            instance_of_admission_controller_for_image_generation
        )
        fastapi_application.state.metrics_collector = metrics_collector
        fastapi_application.state.retry_after_busy_in_seconds = application_configuration.retry_after_busy_in_seconds
        fastapi_application.state.retry_after_not_ready_in_seconds = (
            application_configuration.retry_after_not_ready_in_seconds
        )

        logger.info(
            "services_initialised",
            large_language_model_server=application_configuration.base_url_of_large_language_model_server,
            stable_diffusion_model=application_configuration.id_of_stable_diffusion_model,
            maximum_number_of_concurrent_operations_of_image_generation=(
                application_configuration.maximum_number_of_concurrent_operations_of_image_generation
            ),
        )

        yield

        # ── Graceful shutdown sequence (FR40) ─────────────────────────────
        #
        # The v5.4.0 specification requires a ``graceful_shutdown_initiated``
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
            in_flight_requests=in_flight_request_counter.number_of_in_flight_requests,
        )

        await instance_of_prompt_enhancement_service.close()
        if instance_of_stable_diffusion_pipeline_pool is not None:
            await instance_of_stable_diffusion_pipeline_pool.close()
        thread_pool_executor_for_inference.shutdown(wait=True)
        logger.info("services_shutdown_complete")

    fastapi_application = fastapi.FastAPI(
        title="Text-to-Image with Prompt Assist",
        description=(
            "A production-grade REST API service that generates images"
            " from text prompts using Stable Diffusion, with optional"
            " prompt enhancement powered by a llama.cpp large language"
            " model."
        ),
        version="1.0.0",
        lifespan=application_lifespan,
    )

    application.api.error_handlers.register_error_handlers(fastapi_application)

    if application_configuration.cors_allowed_origins:
        fastapi_application.add_middleware(
            fastapi.middleware.cors.CORSMiddleware,
            allow_origins=application_configuration.cors_allowed_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "Accept"],
            expose_headers=["X-Correlation-ID"],
        )

    # ── Middleware registration ───────────────────────────────────────
    #
    # ASGI middleware executes in reverse registration order (last
    # registered = outermost).  The resulting execution order is:
    #
    #   Request → CorrelationId → RequestLogging → RequestTimeout
    #           → ContentType → PayloadSizeLimit → CORS → App
    #
    # CorrelationId is outermost so that every request (including those
    # rejected by inner middleware) receives a traceable correlation ID.
    # RequestLogging is second so that every request is logged with its
    # correlation ID context.  RequestTimeout is third so that the
    # entire request processing pipeline (including validation and
    # inference) is bounded by the end-to-end timeout ceiling (NFR48).
    # ContentType rejects malformed POST requests before the body is
    # read.  PayloadSizeLimit then guards against oversized payloads.
    # CORS (registered above, if configured) is innermost.

    fastapi_application.add_middleware(
        application.api.middleware.request_payload_size_limit.RequestPayloadSizeLimitMiddleware,
        maximum_number_of_bytes_of_request_payload=(
            application_configuration.maximum_number_of_bytes_of_request_payload
        ),
    )

    fastapi_application.add_middleware(
        application.api.middleware.content_type_validation.ContentTypeValidationMiddleware,
    )

    fastapi_application.add_middleware(
        application.api.middleware.request_timeout.RequestTimeoutMiddleware,
        request_timeout_in_seconds=(application_configuration.timeout_for_requests_in_seconds),
    )

    fastapi_application.add_middleware(
        application.api.middleware.request_logging.RequestLoggingMiddleware,
        metrics_collector=metrics_collector,
    )

    fastapi_application.add_middleware(
        application.api.middleware.correlation_identifier.CorrelationIdMiddleware,
        in_flight_request_counter=in_flight_request_counter,
    )

    fastapi_application.include_router(
        application.api.endpoints.prompt_enhancement.prompt_enhancement_router,
    )
    fastapi_application.include_router(
        application.api.endpoints.image_generation.image_generation_router,
    )
    fastapi_application.include_router(
        application.api.endpoints.health.health_router,
    )

    # ── OpenAPI schema customisation ──────────────────────────────────
    #
    # FastAPI auto-generates a ``422 Unprocessable Entity`` response with
    # ``HTTPValidationError`` / ``ValidationError`` schemas for every route
    # that accepts a request body.  However, this service's custom error
    # handlers (see ``error_handlers.py``) intercept all validation errors
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
    _reference_to_error_response_schema = {
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
                **copy.deepcopy(_reference_to_error_response_schema),
                "description": ("Not Found — the requested endpoint does not exist (``not_found``)."),
            },
            "405": {
                **copy.deepcopy(_reference_to_error_response_schema),
                "description": (
                    "Method Not Allowed — the HTTP method is not"
                    " supported for this endpoint"
                    " (``method_not_allowed``). The ``Allow`` header"
                    " lists permitted methods."
                ),
            },
            "500": {
                **copy.deepcopy(_reference_to_error_response_schema),
                "description": (
                    "Internal Server Error — an unexpected error"
                    " occurred during request processing"
                    " (``internal_server_error``)."
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


fastapi_application = create_application()
