"""
Centralised error-handling registration for the FastAPI application.

Every exception type that can be raised within the service is mapped to
a specific HTTP status code and a consistent JSON error response body.
The mapping follows the v5.0.0 specification requirements:

    - Invalid JSON                        →  400 Bad Request
    - Request validation failure          →  400 Bad Request
    - Undefined endpoint                  →  404 Not Found
    - Wrong HTTP method                   →  405 Method Not Allowed
    - Prompt enhancement failure          →  502 Bad Gateway
    - Image generation failure            →  502 Bad Gateway
    - Backend service unavailable         →  502 Bad Gateway
    - Admission control at capacity       →  429 Too Many Requests
    - Unexpected internal errors          →  500 Internal Server Error

Starlette raises its own ``HTTPException`` (distinct from FastAPI's
``HTTPException``) for framework-level errors such as 404 and 405.
We register a handler for ``starlette.exceptions.HTTPException`` to
intercept these and return structured JSON rather than the framework's
default plain-text or HTML responses.

Allow header on 405 responses
-----------------------------
Per RFC 9110 §15.5.6 and NFR22 of the v5.0.0 specification, every
HTTP 405 response must include an ``Allow`` header listing the methods
supported by the requested endpoint.  Rather than maintaining a static
dictionary that must be kept in sync with route registrations (audit
finding A-6), this module dynamically introspects the FastAPI application's
registered routes at the time the 405 response is generated.  This ensures
the ``Allow`` header is always accurate, even if new routes are added or
existing routes are modified.
"""

import fastapi
import fastapi.exceptions
import fastapi.responses
import fastapi.routing
import starlette.exceptions
import starlette.routing
import structlog

import application.exceptions
import application.models

logger = structlog.get_logger()

# ──────────────────────────────────────────────────────────────────────────────
#  HTTP status code → machine-readable error code mapping
# ──────────────────────────────────────────────────────────────────────────────
#
# Maps Starlette/FastAPI framework-raised HTTP status codes to the
# machine-readable error codes defined in the v5.0.0 specification
# (Section 11 — Error Response Schema).  Any status code not listed
# here falls back to "unexpected_error".

_HTTP_STATUS_CODE_TO_ERROR_CODE: dict[int, str] = {
    404: "not_found",
    405: "method_not_allowed",
}

_HTTP_STATUS_CODE_TO_ERROR_MESSAGE: dict[int, str] = {
    404: "The requested endpoint does not exist.",
    405: "The HTTP method is not allowed for this endpoint.",
}

# Maps Starlette/FastAPI framework-raised HTTP status codes to the
# specification-defined structured logging event names.  The v5.0.0
# specification's 31-event taxonomy (Section 18) requires distinct
# event names for each HTTP error condition — ``http_not_found`` for
# 404 responses and ``http_method_not_allowed`` for 405 responses —
# rather than a generic "http_framework_error" event.  This enables
# precise monitoring dashboard filters and alert rules that distinguish
# between routing failures and method mismatches.
_HTTP_STATUS_CODE_TO_LOG_EVENT_NAME: dict[int, str] = {
    404: "http_not_found",
    405: "http_method_not_allowed",
}


def _get_correlation_id(request: fastapi.Request) -> str:
    """
    Extract the correlation ID from the request state.

    The correlation ID is set by ``CorrelationIdMiddleware`` on every
    incoming request.  If the middleware has not yet run (which should
    never happen in practice), this function returns ``"unknown"`` as
    a safe fallback.
    """
    return getattr(request.state, "correlation_id", "unknown")


def _discover_allowed_methods_for_path(
    fastapi_application: fastapi.FastAPI,
    request_path: str,
) -> str:
    """
    Dynamically discover the HTTP methods allowed for a given path by
    introspecting the FastAPI application's registered routes.

    This replaces the previous static ``_ENDPOINT_PATH_TO_ALLOWED_METHODS``
    dictionary (audit finding A-6) with a dynamic lookup that is always
    in sync with the actual route registrations.

    For GET-only endpoints, HEAD is also included because FastAPI (via
    Starlette) automatically supports HEAD requests for any GET endpoint
    per RFC 9110 §9.3.2.

    Args:
        fastapi_application: The FastAPI application instance containing
            the registered routes.
        request_path: The URL path to look up (e.g. ``"/health"`` or
            ``"/v1/images/generations"``).

    Returns:
        A comma-separated string of allowed HTTP methods (e.g.
        ``"GET, HEAD"`` or ``"POST"``).  Returns an empty string if
        no routes match the given path.
    """
    allowed_methods: set[str] = set()

    for route in fastapi_application.routes:
        # FastAPI wraps route handlers in ``APIRoute`` instances, which
        # inherit from Starlette's ``Route``.  Each route has a ``path``
        # attribute and a ``methods`` set.  We match on the path and
        # collect all declared methods.
        if (
            isinstance(route, (fastapi.routing.APIRoute, starlette.routing.Route))
            and route.path == request_path
            and route.methods
        ):
            allowed_methods.update(route.methods)

    # Per RFC 9110 §9.3.2, servers that respond to GET requests MUST
    # also respond to HEAD requests.  FastAPI/Starlette handles this
    # automatically at the routing level, but we explicitly include HEAD
    # in the Allow header when GET is present to ensure full RFC
    # compliance in the advertised methods.
    if "GET" in allowed_methods:
        allowed_methods.add("HEAD")

    # Sort the methods alphabetically for deterministic output, which
    # simplifies testing and avoids non-deterministic header values.
    return ", ".join(sorted(allowed_methods))


def _build_error_response(
    status_code: int,
    code: str,
    message: str,
    correlation_id: str,
    details: list | None = None,
) -> fastapi.responses.JSONResponse:
    """
    Build a consistent JSON error response.

    When ``details`` is ``None`` (the default for non-validation errors),
    the ``details`` field is omitted from the serialised JSON payload
    entirely, matching the specification's annotated examples which prefer
    field omission over explicit ``null``.  When ``details`` is a list
    (for ``request_validation_failed`` responses), it is included as a
    structured array of validation error objects.

    Args:
        status_code: The HTTP status code for the response.
        code: The machine-readable error code in ``snake_case`` format.
        message: A human-readable error description safe for display
            to end users.
        correlation_id: The UUID v4 correlation identifier for this
            request.
        details: Optional structured details (used for validation errors).

    Returns:
        A ``JSONResponse`` with the standard error response body.
    """
    error_detail_keyword_arguments: dict = {
        "code": code,
        "message": message,
        "correlation_id": correlation_id,
    }
    if details is not None:
        error_detail_keyword_arguments["details"] = details

    error_response = application.models.ErrorResponse(
        error=application.models.ErrorDetail(**error_detail_keyword_arguments),
    )

    return fastapi.responses.JSONResponse(
        status_code=status_code,
        content=error_response.model_dump(exclude_unset=True),
    )


def register_error_handlers(fastapi_application: fastapi.FastAPI) -> None:
    """
    Register all custom exception handlers on the given FastAPI application.

    This function must be called once during application initialisation
    (see ``server_factory.create_application``).  It registers handlers
    for every exception type that may be raised during request processing,
    ensuring that all error responses follow the specification's
    ``ErrorResponse`` JSON schema.

    The catch-all handler for unexpected exceptions (HTTP 500) lives in
    ``CorrelationIdMiddleware`` rather than here.  Starlette routes
    ``Exception`` handlers to ``ServerErrorMiddleware``, which always
    re-raises after sending the response.  Handling it in the outermost
    middleware avoids this re-raise and fully contains the error.
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

        Distinguishes between two types of validation failure:

        1. **JSON parse errors** (``invalid_request_json``): The request
           body is not valid JSON (e.g. malformed syntax, trailing commas).
        2. **Schema validation errors** (``request_validation_failed``):
           The JSON is syntactically valid but does not conform to the
           expected schema (e.g. missing required fields, invalid types).
        """
        errors = validation_error.errors()
        logger.warning("http_validation_failed", errors=errors)

        is_json_parse_error = any(error.get("type", "").startswith("json") for error in errors)

        if is_json_parse_error:
            return _build_error_response(
                status_code=400,
                code="invalid_request_json",
                message="The request body contains invalid JSON.",
                correlation_id=_get_correlation_id(request),
            )

        # Build a sanitised, structured details array containing only the
        # field location, a human-readable message, and the error type for
        # each validation failure.  Raw Pydantic error dictionaries are
        # never exposed in the message field — this prevents leaking
        # internal implementation details such as documentation URLs,
        # actual input values, and internal field paths (NFR14).
        sanitised_validation_error_details = [
            {
                "loc": error.get("loc", []),
                "msg": error.get("msg", ""),
                "type": error.get("type", ""),
            }
            for error in errors
        ]

        return _build_error_response(
            status_code=400,
            code="request_validation_failed",
            message="Request body failed schema validation.",
            correlation_id=_get_correlation_id(request),
            details=sanitised_validation_error_details,
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
        cannot be reached or returns a non-success status code.
        """
        logger.error(
            "upstream_service_error",
            upstream="language_model",
            detail=unavailable_error.detail,
        )
        return _build_error_response(
            502,
            "upstream_service_unavailable",
            unavailable_error.detail,
            _get_correlation_id(request),
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
        encounters a runtime failure or is not loaded.
        """
        logger.error(
            "upstream_service_error",
            upstream="image_generation",
            detail=unavailable_error.detail,
        )
        return _build_error_response(
            502,
            "model_unavailable",
            unavailable_error.detail,
            _get_correlation_id(request),
        )

    @fastapi_application.exception_handler(
        application.exceptions.PromptEnhancementError,
    )
    async def handle_prompt_enhancement_error(
        request: fastapi.Request,
        enhancement_error: application.exceptions.PromptEnhancementError,
    ) -> fastapi.responses.JSONResponse:
        """
        Return 502 Bad Gateway when prompt enhancement fails for a
        reason other than network connectivity (e.g. malformed response).
        """
        logger.error(
            "upstream_service_error",
            upstream="language_model",
            detail=enhancement_error.detail,
        )
        return _build_error_response(
            502,
            "upstream_service_unavailable",
            enhancement_error.detail,
            _get_correlation_id(request),
        )

    @fastapi_application.exception_handler(
        application.exceptions.ImageGenerationError,
    )
    async def handle_image_generation_error(
        request: fastapi.Request,
        generation_error: application.exceptions.ImageGenerationError,
    ) -> fastapi.responses.JSONResponse:
        """
        Return 502 Bad Gateway when image generation fails for a
        non-connectivity reason (e.g. empty pipeline output).
        """
        logger.error(
            "upstream_service_error",
            upstream="image_generation",
            detail=generation_error.detail,
        )
        return _build_error_response(
            502,
            "model_unavailable",
            generation_error.detail,
            _get_correlation_id(request),
        )

    @fastapi_application.exception_handler(
        application.exceptions.ServiceBusyError,
    )
    async def handle_service_busy_error(
        request: fastapi.Request,
        busy_error: application.exceptions.ServiceBusyError,
    ) -> fastapi.responses.JSONResponse:
        """
        Return 429 Too Many Requests when the image generation admission
        control concurrency limit is fully occupied.

        This is distinct from IP-based rate limiting: admission control
        limits the total number of concurrent image generation operations
        across all clients, whilst rate limiting restricts request
        frequency from a single IP address.

        The ``Retry-After`` header is populated from the operator-
        configured ``retry_after_busy_seconds`` value stored on
        ``app.state`` during application startup.
        """
        logger.warning(
            "image_generation_rejected_at_capacity",
            detail=busy_error.detail,
        )

        retry_after_seconds = getattr(request.app.state, "retry_after_busy_seconds", 30)

        response = _build_error_response(
            429,
            "service_busy",
            busy_error.detail,
            _get_correlation_id(request),
        )
        response.headers["Retry-After"] = str(retry_after_seconds)

        return response

    @fastapi_application.exception_handler(
        starlette.exceptions.HTTPException,
    )
    async def handle_starlette_http_exception(
        request: fastapi.Request,
        http_exception: starlette.exceptions.HTTPException,
    ) -> fastapi.responses.JSONResponse:
        """
        Return structured JSON for framework-raised HTTP errors.

        Starlette raises ``HTTPException`` for situations such as
        undefined endpoints (404) and disallowed HTTP methods (405).
        Without this handler, the framework returns plain-text or HTML
        responses that do not conform to the API error contract.

        The handler looks up the machine-readable error code from the
        ``_HTTP_STATUS_CODE_TO_ERROR_CODE`` mapping.  Unmapped status
        codes fall back to ``"unexpected_error"`` to ensure every
        framework-originated error still produces valid JSON.

        For HTTP 405 (Method Not Allowed), the handler dynamically
        discovers the allowed methods for the requested path by
        introspecting the application's registered routes, and includes
        the result in an ``Allow`` header as required by RFC 9110 §15.5.6
        and NFR22 of the v5.0.0 specification.
        """
        error_code = _HTTP_STATUS_CODE_TO_ERROR_CODE.get(
            http_exception.status_code,
            "unexpected_error",
        )
        error_message = _HTTP_STATUS_CODE_TO_ERROR_MESSAGE.get(
            http_exception.status_code,
            str(http_exception.detail),
        )

        # Emit specification-aligned log events for 404 and 405 responses.
        # The v5.0.0 specification's 31-event logging taxonomy defines
        # distinct event names for each HTTP error condition rather than
        # a generic "http_framework_error" event, enabling precise
        # monitoring dashboard filters and alert rules.
        log_event_name = _HTTP_STATUS_CODE_TO_LOG_EVENT_NAME.get(
            http_exception.status_code,
            "http_framework_error",
        )
        logger.warning(
            log_event_name,
            status_code=http_exception.status_code,
            error_code=error_code,
            detail=str(http_exception.detail),
        )

        response = _build_error_response(
            http_exception.status_code,
            error_code,
            error_message,
            _get_correlation_id(request),
        )

        # Per RFC 9110 §15.5.6, HTTP 405 responses MUST include an
        # ``Allow`` header listing the methods supported by the target
        # resource.  We dynamically discover the allowed methods by
        # introspecting the application's registered routes (audit
        # finding A-6), ensuring the header is always in sync with
        # actual route registrations.
        if http_exception.status_code == 405:
            allowed_methods = _discover_allowed_methods_for_path(
                fastapi_application=request.app,  # type: ignore[arg-type]
                request_path=request.url.path,
            )
            response.headers["Allow"] = allowed_methods

        return response
