"""Tests for application/api/error_handlers.py — centralised error handler registration.

This module provides dedicated tests for the centralised error handling
layer, covering all seven exception handlers, the three helper functions,
and the ``register_error_handlers`` registration function.

Tests are organised by function under test:

- ``TestGetCorrelationId``: Direct tests for the ``_get_correlation_id``
  helper, including the ``"unknown"`` fallback path.
- ``TestDiscoverAllowedMethodsForPath``: Direct tests for the dynamic
  method discovery logic used by HTTP 405 responses.
- ``TestBuildErrorResponse``: Direct tests for the error response
  construction helper, including conditional ``details`` omission.
- ``TestHandleRequestValidationError``: Integration tests for JSON parse
  errors and schema validation errors via real HTTP requests.
- ``TestHandleLargeLanguageModelServiceUnavailableError``: Integration
  tests for the llama.cpp unavailability handler.
- ``TestHandleImageGenerationServiceUnavailableError``: Integration
  tests for the Stable Diffusion unavailability handler.
- ``TestHandlePromptEnhancementError``: Integration tests for the
  prompt enhancement failure handler.
- ``TestHandleImageGenerationError``: Integration tests for the image
  generation failure handler.
- ``TestHandleServiceBusyError``: Integration tests for the admission
  control rejection handler, including ``Retry-After`` header and
  concurrency limit details.
- ``TestHandleStarletteHttpException``: Integration tests for
  framework-raised HTTP exceptions (404, 405, unmapped status codes).
"""

import json
from unittest.mock import MagicMock

import fastapi
import fastapi.routing
import httpx
import pydantic
import pytest
import pytest_asyncio
import starlette.exceptions

import application.admission_control
import application.api.error_handlers
import application.api.middleware.correlation_identifier
import application.exceptions
import application.metrics

# ──────────────────────────────────────────────────────────────────────────────
#  Helper model used to trigger request validation errors in handler tests
# ──────────────────────────────────────────────────────────────────────────────


class RequestModelForValidationTesting(pydantic.BaseModel):
    """
    Minimal Pydantic model used by the test application to trigger
    ``RequestValidationError`` exceptions when the request body does
    not conform to the expected schema.
    """

    name: str

    model_config = pydantic.ConfigDict(extra="forbid")


# ──────────────────────────────────────────────────────────────────────────────
#  Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def test_application_with_error_handlers():
    """
    Create a minimal FastAPI application with all error handlers registered
    and deliberately-raising routes for each exception type.

    The ``CorrelationIdMiddleware`` is included to ensure correlation IDs
    are available in error responses, matching the real application
    configuration.
    """
    fastapi_application = fastapi.FastAPI()
    application.api.error_handlers.register_error_handlers(fastapi_application)

    metrics_collector = application.metrics.MetricsCollector()
    fastapi_application.add_middleware(
        application.api.middleware.correlation_identifier.CorrelationIdMiddleware,
    )

    fastapi_application.state.retry_after_busy_in_seconds = 5
    fastapi_application.state.metrics_collector = metrics_collector

    # ── Route for triggering request validation errors ────────────────
    #
    # Sending malformed JSON or schema-violating JSON to this endpoint
    # triggers FastAPI's RequestValidationError, which is handled by
    # handle_request_validation_error.

    @fastapi_application.post("/test/validation")
    async def route_for_validation_testing(
        body: RequestModelForValidationTesting,
    ) -> dict:
        return {"name": body.name}

    # ── Routes that raise each custom exception type ─────────────────

    @fastapi_application.post("/test/raise-large-language-model-service-unavailable")
    async def route_that_raises_large_language_model_service_unavailable() -> None:
        raise application.exceptions.LargeLanguageModelServiceUnavailableError(
            detail="The large language model server is not reachable.",
        )

    @fastapi_application.post("/test/raise-image-generation-service-unavailable")
    async def route_that_raises_image_generation_service_unavailable() -> None:
        raise application.exceptions.ImageGenerationServiceUnavailableError(
            detail="The image generation pipeline is not loaded.",
        )

    @fastapi_application.post("/test/raise-prompt-enhancement-error")
    async def route_that_raises_prompt_enhancement_error() -> None:
        raise application.exceptions.PromptEnhancementError(
            detail="The large language model returned an empty enhanced prompt.",
        )

    @fastapi_application.post("/test/raise-image-generation-error")
    async def route_that_raises_image_generation_error() -> None:
        raise application.exceptions.ImageGenerationError(
            detail="The Stable Diffusion pipeline returned no images.",
        )

    @fastapi_application.post("/test/raise-service-busy")
    async def route_that_raises_service_busy() -> None:
        raise application.exceptions.ServiceBusyError()

    # ── Route for testing unmapped Starlette status codes ────────────
    #
    # Starlette only raises HTTPException for 404 and 405 in normal
    # operation, but the handler has a fallback path for any other
    # status code.  This route exercises that fallback.

    @fastapi_application.get("/test/raise-starlette-exception-with-unmapped-status")
    async def route_that_raises_starlette_exception_with_unmapped_status() -> None:
        raise starlette.exceptions.HTTPException(
            status_code=418,
            detail="I'm a teapot",
        )

    return fastapi_application


@pytest_asyncio.fixture
async def client_for_error_handling_tests(test_application_with_error_handlers):
    """
    Create an ``httpx.AsyncClient`` wired to the test application via
    ASGI transport, matching the pattern used by the route-level tests.
    """
    transport = httpx.ASGITransport(app=test_application_with_error_handlers)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as async_test_client:
        yield async_test_client


# ──────────────────────────────────────────────────────────────────────────────
#  Direct unit tests for helper functions
# ──────────────────────────────────────────────────────────────────────────────


class TestGetCorrelationId:
    """
    Tests for ``_get_correlation_id``, which extracts the correlation ID
    from the request state set by ``CorrelationIdMiddleware``.
    """

    def test_returns_correlation_id_from_request_state(self):
        """
        When the middleware has set ``correlation_id`` on the request
        state, the function must return that value.
        """
        mock_request = MagicMock()
        mock_request.state.correlation_id = "test-correlation-id-abc-123"

        result = application.api.error_handlers._get_correlation_id(mock_request)

        assert result == "test-correlation-id-abc-123"

    def test_returns_unknown_when_no_correlation_id_in_request_state(self):
        """
        When the middleware has not yet run (or the attribute is absent
        for any reason), the function must return ``"unknown"`` as a
        safe fallback rather than raising ``AttributeError``.
        """
        mock_request = MagicMock(spec=[])
        mock_request.state = MagicMock(spec=[])

        result = application.api.error_handlers._get_correlation_id(mock_request)

        assert result == "unknown"


class TestDiscoverAllowedMethodsForPath:
    """
    Tests for ``_discover_allowed_methods_for_path``, which dynamically
    introspects the application's registered routes to build the
    ``Allow`` header value for HTTP 405 responses.
    """

    def test_returns_post_for_post_only_endpoint(self):
        """
        A route registered with only POST must return ``"POST"``
        as the allowed methods string.
        """
        fastapi_application = fastapi.FastAPI()

        @fastapi_application.post("/example")
        async def example_route() -> None:
            pass

        result = application.api.error_handlers._discover_allowed_methods_for_path(
            fastapi_application,
            "/example",
        )

        assert result == "POST"

    def test_includes_head_when_get_is_registered(self):
        """
        Per RFC 9110 §9.3.2, servers that respond to GET must also
        respond to HEAD.  The function must include HEAD in the
        allowed methods when GET is present.
        """
        fastapi_application = fastapi.FastAPI()

        @fastapi_application.get("/example")
        async def example_route() -> None:
            pass

        result = application.api.error_handlers._discover_allowed_methods_for_path(
            fastapi_application,
            "/example",
        )

        assert "GET" in result
        assert "HEAD" in result

    def test_returns_empty_string_for_unregistered_path(self):
        """
        When no routes match the given path, the function must return
        an empty string.
        """
        fastapi_application = fastapi.FastAPI()

        result = application.api.error_handlers._discover_allowed_methods_for_path(
            fastapi_application,
            "/nonexistent",
        )

        assert result == ""

    def test_sorts_methods_alphabetically(self):
        """
        The allowed methods must be sorted alphabetically for
        deterministic output, ensuring consistent ``Allow`` header
        values across requests and simplifying test assertions.
        """
        fastapi_application = fastapi.FastAPI()

        @fastapi_application.get("/example")
        async def example_get() -> None:
            pass

        @fastapi_application.post("/example")
        async def example_post() -> None:
            pass

        result = application.api.error_handlers._discover_allowed_methods_for_path(
            fastapi_application,
            "/example",
        )

        methods_as_list = [method.strip() for method in result.split(",")]
        assert methods_as_list == sorted(methods_as_list)


class TestBuildErrorResponse:
    """
    Tests for ``_build_error_response``, which constructs the
    consistent JSON error response body used by all handlers.
    """

    def test_response_has_correct_status_code(self):
        """
        The returned ``JSONResponse`` must carry the HTTP status code
        passed to the builder.
        """
        response = application.api.error_handlers._build_error_response(
            status_code=502,
            code="upstream_service_unavailable",
            message="The server is unreachable.",
            correlation_id="test-id",
        )

        assert response.status_code == 502

    def test_response_body_omits_details_when_details_is_none(self):
        """
        When ``details`` is ``None`` (the default), the ``details``
        field must be omitted entirely from the serialised JSON body
        rather than being present as ``null``.
        """
        response = application.api.error_handlers._build_error_response(
            status_code=500,
            code="internal_server_error",
            message="An unexpected error occurred.",
            correlation_id="test-id",
            details=None,
        )

        response_body = json.loads(response.body)

        assert "details" not in response_body["error"]

    def test_response_body_includes_string_details(self):
        """
        When ``details`` is a string (for single-cause errors such as
        ``service_busy`` or ``payload_too_large``), the field must be
        present in the response body as that string value.
        """
        response = application.api.error_handlers._build_error_response(
            status_code=429,
            code="service_busy",
            message="The service is at capacity.",
            correlation_id="test-id",
            details="Current concurrency limit: 1. All inference slots are occupied.",
        )

        response_body = json.loads(response.body)

        assert response_body["error"]["details"] == ("Current concurrency limit: 1. All inference slots are occupied.")

    def test_response_body_includes_list_details(self):
        """
        When ``details`` is a list (for ``request_validation_failed``
        responses), the field must be present in the response body as
        that list value.
        """
        validation_errors = [
            {"location": ["body", "name"], "message": "Field required", "type": "missing"},
        ]

        response = application.api.error_handlers._build_error_response(
            status_code=400,
            code="request_validation_failed",
            message="Request body failed schema validation.",
            correlation_id="test-id",
            details=validation_errors,
        )

        response_body = json.loads(response.body)

        assert isinstance(response_body["error"]["details"], list)
        assert len(response_body["error"]["details"]) == 1
        assert response_body["error"]["details"][0]["location"] == ["body", "name"]

    def test_response_body_contains_error_code_and_message_and_correlation_id(self):
        """
        Every error response must include the machine-readable error
        code, the human-readable message, and the correlation ID in
        the nested ``error`` object.
        """
        response = application.api.error_handlers._build_error_response(
            status_code=404,
            code="not_found",
            message="The requested endpoint does not exist.",
            correlation_id="abc-123-def",
        )

        response_body = json.loads(response.body)

        assert response_body["error"]["code"] == "not_found"
        assert response_body["error"]["message"] == "The requested endpoint does not exist."
        assert response_body["error"]["correlation_id"] == "abc-123-def"


# ──────────────────────────────────────────────────────────────────────────────
#  Integration tests for exception handlers (via HTTP requests)
# ──────────────────────────────────────────────────────────────────────────────


class TestHandleRequestValidationError:
    """
    Tests for the ``RequestValidationError`` handler, which distinguishes
    between JSON parse errors (``invalid_request_json``) and schema
    validation errors (``request_validation_failed``).
    """

    @pytest.mark.asyncio
    async def test_malformed_json_returns_400_with_invalid_request_json_code(
        self,
        client_for_error_handling_tests,
    ):
        """
        When the request body contains syntactically invalid JSON,
        the handler must return HTTP 400 with the error code
        ``invalid_request_json``.
        """
        response = await client_for_error_handling_tests.post(
            "/test/validation",
            content=b"{invalid json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 400

        response_body = response.json()

        assert response_body["error"]["code"] == "invalid_request_json"
        assert response_body["error"]["message"] == "The request body contains invalid JSON."

    @pytest.mark.asyncio
    async def test_json_parse_error_details_is_descriptive_string(
        self,
        client_for_error_handling_tests,
    ):
        """
        For JSON parse errors, the ``details`` field must be a
        descriptive string explaining the parse failure, not a list
        of validation error objects.
        """
        response = await client_for_error_handling_tests.post(
            "/test/validation",
            content=b"{invalid json",
            headers={"Content-Type": "application/json"},
        )

        response_body = response.json()

        assert isinstance(response_body["error"]["details"], str)
        assert len(response_body["error"]["details"]) > 0

    @pytest.mark.asyncio
    async def test_schema_violation_returns_400_with_request_validation_failed_code(
        self,
        client_for_error_handling_tests,
    ):
        """
        When the request body is valid JSON but does not conform to
        the expected schema (e.g. missing required fields), the handler
        must return HTTP 400 with the error code
        ``request_validation_failed``.
        """
        response = await client_for_error_handling_tests.post(
            "/test/validation",
            json={"wrong_field": "value"},
        )

        assert response.status_code == 400

        response_body = response.json()

        assert response_body["error"]["code"] == "request_validation_failed"

    @pytest.mark.asyncio
    async def test_sanitised_validation_details_contain_only_location_message_and_type(
        self,
        client_for_error_handling_tests,
    ):
        """
        For schema validation errors, each entry in the ``details``
        array must contain only ``location``, ``message``, and ``type``
        — no raw Pydantic error fields such as ``ctx``, ``input``, or
        ``url`` may be exposed (NFR14 — error message sanitisation).
        """
        response = await client_for_error_handling_tests.post(
            "/test/validation",
            json={"wrong_field": "value"},
        )

        response_body = response.json()
        details = response_body["error"]["details"]

        assert isinstance(details, list)
        assert len(details) > 0

        allowed_keys = {"location", "message", "type"}
        for detail_entry in details:
            assert set(detail_entry.keys()) == allowed_keys

    @pytest.mark.asyncio
    async def test_validation_error_response_includes_correlation_id(
        self,
        client_for_error_handling_tests,
    ):
        """
        Validation error responses must include a correlation ID,
        confirming that the middleware has run and the handler
        correctly extracts it from the request state.
        """
        response = await client_for_error_handling_tests.post(
            "/test/validation",
            json={},
        )

        response_body = response.json()

        assert "correlation_id" in response_body["error"]
        assert len(response_body["error"]["correlation_id"]) > 0


class TestHandleLargeLanguageModelServiceUnavailableError:
    """
    Tests for the ``LargeLanguageModelServiceUnavailableError`` handler,
    which returns HTTP 502 with the ``upstream_service_unavailable``
    error code.
    """

    @pytest.mark.asyncio
    async def test_returns_502_with_upstream_service_unavailable_code(
        self,
        client_for_error_handling_tests,
    ):
        """
        The handler must return HTTP 502 with the machine-readable
        error code ``upstream_service_unavailable``.
        """
        response = await client_for_error_handling_tests.post(
            "/test/raise-large-language-model-service-unavailable",
        )

        assert response.status_code == 502

        response_body = response.json()

        assert response_body["error"]["code"] == "upstream_service_unavailable"

    @pytest.mark.asyncio
    async def test_response_message_contains_exception_detail(
        self,
        client_for_error_handling_tests,
    ):
        """
        The error message in the response must contain the ``detail``
        string from the raised exception, providing the client with
        a meaningful description of the upstream failure.
        """
        response = await client_for_error_handling_tests.post(
            "/test/raise-large-language-model-service-unavailable",
        )

        response_body = response.json()

        assert response_body["error"]["message"] == ("The large language model server is not reachable.")


class TestHandleImageGenerationServiceUnavailableError:
    """
    Tests for the ``ImageGenerationServiceUnavailableError`` handler,
    which returns HTTP 502 with the ``model_unavailable`` error code.
    """

    @pytest.mark.asyncio
    async def test_returns_502_with_model_unavailable_code(
        self,
        client_for_error_handling_tests,
    ):
        """
        The handler must return HTTP 502 with the machine-readable
        error code ``model_unavailable`` and include the exception
        detail in the message.
        """
        response = await client_for_error_handling_tests.post(
            "/test/raise-image-generation-service-unavailable",
        )

        assert response.status_code == 502

        response_body = response.json()

        assert response_body["error"]["code"] == "model_unavailable"
        assert response_body["error"]["message"] == ("The image generation pipeline is not loaded.")


class TestHandlePromptEnhancementError:
    """
    Tests for the ``PromptEnhancementError`` handler, which returns
    HTTP 502 with the ``upstream_service_unavailable`` error code.
    """

    @pytest.mark.asyncio
    async def test_returns_502_with_upstream_service_unavailable_code(
        self,
        client_for_error_handling_tests,
    ):
        """
        The handler must return HTTP 502 with the machine-readable
        error code ``upstream_service_unavailable``, matching the
        same code used for ``LargeLanguageModelServiceUnavailableError``
        because both represent upstream llama.cpp failures.
        """
        response = await client_for_error_handling_tests.post(
            "/test/raise-prompt-enhancement-error",
        )

        assert response.status_code == 502

        response_body = response.json()

        assert response_body["error"]["code"] == "upstream_service_unavailable"
        assert response_body["error"]["message"] == ("The large language model returned an empty enhanced prompt.")


class TestHandleImageGenerationError:
    """
    Tests for the ``ImageGenerationError`` handler, which returns
    HTTP 502 with the ``model_unavailable`` error code.
    """

    @pytest.mark.asyncio
    async def test_returns_502_with_model_unavailable_code(
        self,
        client_for_error_handling_tests,
    ):
        """
        The handler must return HTTP 502 with the machine-readable
        error code ``model_unavailable``, matching the same code used
        for ``ImageGenerationServiceUnavailableError`` because both
        represent Stable Diffusion pipeline failures.
        """
        response = await client_for_error_handling_tests.post(
            "/test/raise-image-generation-error",
        )

        assert response.status_code == 502

        response_body = response.json()

        assert response_body["error"]["code"] == "model_unavailable"
        assert response_body["error"]["message"] == ("The Stable Diffusion pipeline returned no images.")


class TestHandleServiceBusyError:
    """
    Tests for the ``ServiceBusyError`` handler, which returns HTTP 429
    with a ``Retry-After`` header and concurrency limit details.
    """

    @pytest.mark.asyncio
    async def test_returns_429_with_service_busy_code(
        self,
        client_for_error_handling_tests,
    ):
        """
        The handler must return HTTP 429 with the machine-readable
        error code ``service_busy``.
        """
        response = await client_for_error_handling_tests.post(
            "/test/raise-service-busy",
        )

        assert response.status_code == 429

        response_body = response.json()

        assert response_body["error"]["code"] == "service_busy"

    @pytest.mark.asyncio
    async def test_response_includes_retry_after_header(
        self,
        client_for_error_handling_tests,
    ):
        """
        The handler must include a ``Retry-After`` header with the
        operator-configured value from ``app.state.retry_after_busy_in_seconds``.
        """
        response = await client_for_error_handling_tests.post(
            "/test/raise-service-busy",
        )

        assert "retry-after" in response.headers
        assert response.headers["retry-after"] == "5"

    @pytest.mark.asyncio
    async def test_details_include_concurrency_limit_when_admission_controller_is_present(
        self,
        test_application_with_error_handlers,
        client_for_error_handling_tests,
    ):
        """
        When the admission controller is present on ``app.state``, the
        ``details`` field must include the configured concurrency limit
        to help operators diagnose capacity constraints.
        """
        admission_controller = application.admission_control.AdmissionControllerForImageGeneration(
            maximum_number_of_concurrent_operations=5,
        )
        test_application_with_error_handlers.state.admission_controller_for_image_generation = admission_controller

        response = await client_for_error_handling_tests.post(
            "/test/raise-service-busy",
        )

        response_body = response.json()

        assert "5" in response_body["error"]["details"]
        assert "concurrency limit" in response_body["error"]["details"].lower()

    @pytest.mark.asyncio
    async def test_details_exclude_concurrency_limit_when_admission_controller_is_absent(
        self,
        client_for_error_handling_tests,
    ):
        """
        When the admission controller is not present on ``app.state``
        (the attribute does not exist), the ``details`` field must
        still be present with a generic message and must not raise
        an ``AttributeError``.
        """
        response = await client_for_error_handling_tests.post(
            "/test/raise-service-busy",
        )

        response_body = response.json()

        assert response_body["error"]["details"] == ("All inference slots are occupied.")


class TestHandleStarletteHttpException:
    """
    Tests for the ``starlette.exceptions.HTTPException`` handler, which
    intercepts framework-raised HTTP errors (404, 405) and returns
    structured JSON instead of Starlette's default plain-text responses.
    """

    @pytest.mark.asyncio
    async def test_returns_404_with_not_found_code_and_path_in_details(
        self,
        client_for_error_handling_tests,
    ):
        """
        Requesting a non-existent path must return HTTP 404 with the
        error code ``not_found`` and the requested path in the
        ``details`` field.
        """
        response = await client_for_error_handling_tests.get(
            "/this/path/does/not/exist",
        )

        assert response.status_code == 404

        response_body = response.json()

        assert response_body["error"]["code"] == "not_found"
        assert response_body["error"]["message"] == ("The requested endpoint does not exist.")
        assert response_body["error"]["details"] == "/this/path/does/not/exist"

    @pytest.mark.asyncio
    async def test_returns_405_with_method_not_allowed_code(
        self,
        client_for_error_handling_tests,
    ):
        """
        Sending the wrong HTTP method to an existing endpoint must
        return HTTP 405 with the error code ``method_not_allowed``.
        """
        # The /test/validation endpoint only accepts POST.  Sending
        # GET triggers a 405 response from Starlette.
        response = await client_for_error_handling_tests.get(
            "/test/validation",
        )

        assert response.status_code == 405

        response_body = response.json()

        assert response_body["error"]["code"] == "method_not_allowed"

    @pytest.mark.asyncio
    async def test_405_response_includes_allow_header(
        self,
        client_for_error_handling_tests,
    ):
        """
        Per RFC 9110 §15.5.6 and NFR22, every HTTP 405 response must
        include an ``Allow`` header listing the methods supported by
        the requested endpoint.
        """
        response = await client_for_error_handling_tests.get(
            "/test/validation",
        )

        assert response.status_code == 405
        assert "allow" in response.headers
        assert "POST" in response.headers["allow"]

    @pytest.mark.asyncio
    async def test_405_details_list_allowed_methods(
        self,
        client_for_error_handling_tests,
    ):
        """
        The ``details`` field in a 405 response must contain the
        allowed methods string, prefixed with ``"Allowed methods: "``.
        """
        response = await client_for_error_handling_tests.get(
            "/test/validation",
        )

        response_body = response.json()

        assert response_body["error"]["details"].startswith("Allowed methods:")
        assert "POST" in response_body["error"]["details"]

    @pytest.mark.asyncio
    async def test_unmapped_status_code_falls_back_to_internal_server_error_code(
        self,
        client_for_error_handling_tests,
    ):
        """
        When Starlette raises an ``HTTPException`` with a status code
        not in the ``_HTTP_STATUS_CODE_TO_ERROR_CODE`` mapping (which
        covers only 404, 405, and 500), the handler must fall back to
        the ``internal_server_error`` error code while preserving the
        original HTTP status code.
        """
        response = await client_for_error_handling_tests.get(
            "/test/raise-starlette-exception-with-unmapped-status",
        )

        assert response.status_code == 418

        response_body = response.json()

        assert response_body["error"]["code"] == "internal_server_error"

    @pytest.mark.asyncio
    async def test_unmapped_status_code_uses_exception_detail_as_message(
        self,
        client_for_error_handling_tests,
    ):
        """
        For unmapped status codes, the handler must use the exception's
        ``detail`` string as the error message (since no predefined
        message exists in the ``_HTTP_STATUS_CODE_TO_ERROR_MESSAGE``
        mapping).
        """
        response = await client_for_error_handling_tests.get(
            "/test/raise-starlette-exception-with-unmapped-status",
        )

        response_body = response.json()

        assert response_body["error"]["message"] == "I'm a teapot"
