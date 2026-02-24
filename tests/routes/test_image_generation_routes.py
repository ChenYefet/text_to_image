"""
Tests for the POST /v1/images/generations endpoint.

Covers:
- Successful generation with and without prompt enhancement.
- Response schema: ``created``, ``seed``, ``data``, conditional
  ``enhanced_prompt`` and ``warnings`` fields.
- Request validation: prompt constraints, size, n, seed, response_format.
- Upstream service failures (502).
- Admission control rejection (429 ``service_busy`` with ``Retry-After``).
"""

import asyncio
import collections.abc
from unittest.mock import AsyncMock

import fastapi
import httpx
import pytest
import pytest_asyncio
import slowapi.errors

import application.admission_control
import application.dependencies
import application.error_handling
import application.exceptions
import application.metrics
import application.middleware
import application.rate_limiting
import application.routes.image_generation_routes
import application.services.image_generation_service


class TestImageGenerationRoutes:
    @pytest.mark.asyncio
    async def test_success(self, client, mock_image_generation_service) -> None:
        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset"},
        )

        assert response.status_code == 200
        assert "X-Correlation-ID" in response.headers
        body = response.json()
        assert "created" in body
        assert "seed" in body
        assert isinstance(body["seed"], int)
        assert len(body["data"]) == 1
        assert body["data"][0]["base64_json"] == "base64encodedimage"

    @pytest.mark.asyncio
    async def test_success_includes_cache_control_no_store_header(self, client, mock_image_generation_service) -> None:
        """
        Successful image generation responses must include a
        ``Cache-Control: no-store`` header to prevent intermediate proxies
        and CDNs from caching dynamically generated content (§12 of the
        v5.0.0 specification, SHOULD-level advisory).
        """
        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset"},
        )

        assert response.status_code == 200
        assert "cache-control" in response.headers
        assert response.headers["cache-control"] == "no-store"

    @pytest.mark.asyncio
    async def test_success_does_not_include_enhanced_prompt_when_enhancer_off(
        self,
        client,
        mock_image_generation_service,
    ) -> None:
        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "use_enhancer": False},
        )

        assert response.status_code == 200
        body = response.json()
        assert "enhanced_prompt" not in body

    @pytest.mark.asyncio
    async def test_success_does_not_include_warnings_when_no_filtering(
        self,
        client,
        mock_image_generation_service,
    ) -> None:
        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset"},
        )

        assert response.status_code == 200
        body = response.json()
        assert "warnings" not in body

    @pytest.mark.asyncio
    async def test_with_enhancer_includes_enhanced_prompt(
        self,
        client,
        mock_language_model_service,
        mock_image_generation_service,
    ) -> None:
        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "use_enhancer": True},
        )

        assert response.status_code == 200
        assert "X-Correlation-ID" in response.headers
        body = response.json()
        assert body["enhanced_prompt"] == "Enhanced prompt"
        assert "seed" in body
        mock_language_model_service.enhance_prompt.assert_awaited_once()
        mock_image_generation_service.generate_images.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_without_enhancer(
        self,
        client,
        mock_language_model_service,
        mock_image_generation_service,
    ) -> None:
        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "use_enhancer": False},
        )

        assert response.status_code == 200
        assert "X-Correlation-ID" in response.headers
        mock_language_model_service.enhance_prompt.assert_not_awaited()
        mock_image_generation_service.generate_images.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_seed_echoed_when_provided(
        self,
        client,
        mock_image_generation_service,
    ) -> None:
        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "seed": 42},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["seed"] == 42

    @pytest.mark.asyncio
    async def test_seed_generated_when_null(
        self,
        client,
        mock_image_generation_service,
    ) -> None:
        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "seed": None},
        )

        assert response.status_code == 200
        body = response.json()
        assert "seed" in body
        assert isinstance(body["seed"], int)
        assert 0 <= body["seed"] <= 4_294_967_295

    @pytest.mark.asyncio
    async def test_seed_generated_when_omitted(
        self,
        client,
        mock_image_generation_service,
    ) -> None:
        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset"},
        )

        assert response.status_code == 200
        body = response.json()
        assert "seed" in body
        assert isinstance(body["seed"], int)

    @pytest.mark.asyncio
    async def test_content_safety_warning_propagation_returns_warnings_and_null_images(
        self,
        client,
        mock_image_generation_service,
    ) -> None:
        """
        When the content safety checker flags one or more generated images,
        the response must include:

        1. A ``warnings`` array containing one
           ``ImageGenerationWarning`` per flagged image, each with the
           zero-based ``index`` of the affected image and the
           machine-readable ``reason`` string
           ``"content_policy_violation"``.

        2. The ``base64_json`` field of every flagged image set to
           ``null``, indicating the image data was withheld.

        3. Unflagged images retain their base64-encoded data.

        This validates the complete content safety warning propagation
        path from the ``ImageGenerationResult.content_safety_flagged_indices``
        through the route handler to the serialised JSON response (FR45).
        """
        content_safety_generation_result = application.services.image_generation_service.ImageGenerationResult(
            base64_encoded_images=[
                "base64encodedimage_0",
                None,
                "base64encodedimage_2",
                None,
            ],
            content_safety_flagged_indices=[1, 3],
        )
        mock_image_generation_service.generate_images = AsyncMock(
            return_value=content_safety_generation_result,
        )

        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "n": 4},
        )

        assert response.status_code == 200
        body = response.json()

        # ── Verify the warnings array ────────────────────────────────
        assert (
            "warnings" in body
        ), "The response must include a 'warnings' field when the content safety checker flags any images."
        warnings = body["warnings"]
        assert len(warnings) == 2

        warning_indices = [warning["index"] for warning in warnings]
        assert warning_indices == [1, 3]

        for warning in warnings:
            assert warning["reason"] == "content_policy_violation"

        # ── Verify the data array ────────────────────────────────────
        data = body["data"]
        assert len(data) == 4

        assert (
            data[0]["base64_json"] == "base64encodedimage_0"
        ), "Unflagged images must retain their base64-encoded data."
        assert data[1]["base64_json"] is None, "Content-safety-flagged images must have base64_json set to null."
        assert (
            data[2]["base64_json"] == "base64encodedimage_2"
        ), "Unflagged images must retain their base64-encoded data."
        assert data[3]["base64_json"] is None, "Content-safety-flagged images must have base64_json set to null."

    @pytest.mark.asyncio
    async def test_content_safety_warning_single_flagged_image_in_batch(
        self,
        client,
        mock_image_generation_service,
    ) -> None:
        """
        When only one image in a multi-image batch is flagged by the
        content safety checker, the ``warnings`` array contains exactly
        one entry, and the remaining images are unaffected.
        """
        single_content_safety_generation_result = application.services.image_generation_service.ImageGenerationResult(
            base64_encoded_images=[
                "base64encodedimage_0",
                None,
            ],
            content_safety_flagged_indices=[1],
        )
        mock_image_generation_service.generate_images = AsyncMock(
            return_value=single_content_safety_generation_result,
        )

        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "n": 2},
        )

        assert response.status_code == 200
        body = response.json()

        assert "warnings" in body
        assert len(body["warnings"]) == 1
        assert body["warnings"][0]["index"] == 1
        assert body["warnings"][0]["reason"] == "content_policy_violation"

        assert body["data"][0]["base64_json"] == "base64encodedimage_0"
        assert body["data"][1]["base64_json"] is None

    @pytest.mark.asyncio
    async def test_seed_zero_accepted_as_valid(
        self,
        client,
        mock_image_generation_service,
    ) -> None:
        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "seed": 0},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["seed"] == 0

    @pytest.mark.asyncio
    async def test_response_format_base64_json_accepted(
        self,
        client,
        mock_image_generation_service,
    ) -> None:
        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "response_format": "base64_json"},
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_response_format_url_rejected(self, client) -> None:
        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "response_format": "url"},
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_size(self, client) -> None:
        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "size": "999x999"},
        )

        assert response.status_code == 400
        assert "X-Correlation-ID" in response.headers

    @pytest.mark.asyncio
    async def test_256x256_rejected(self, client) -> None:
        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "size": "256x256"},
        )

        assert response.status_code == 400
        assert "X-Correlation-ID" in response.headers

    @pytest.mark.asyncio
    async def test_invalid_n(self, client) -> None:
        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "n": 0},
        )

        assert response.status_code == 400
        assert "X-Correlation-ID" in response.headers

    @pytest.mark.asyncio
    async def test_missing_prompt(self, client) -> None:
        response = await client.post(
            "/v1/images/generations",
            json={},
        )

        assert response.status_code == 400
        assert "X-Correlation-ID" in response.headers

    @pytest.mark.asyncio
    async def test_whitespace_only_prompt(self, client) -> None:
        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "   "},
        )

        assert response.status_code == 400
        assert "X-Correlation-ID" in response.headers

    @pytest.mark.asyncio
    async def test_extra_fields_rejected(self, client) -> None:
        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "foo": "bar"},
        )

        assert response.status_code == 400
        assert "X-Correlation-ID" in response.headers

    @pytest.mark.asyncio
    async def test_service_unavailable(self, client, mock_image_generation_service) -> None:
        mock_image_generation_service.generate_images.side_effect = (
            application.exceptions.ImageGenerationServiceUnavailableError(detail="Pipeline not loaded")
        )

        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset"},
        )

        assert response.status_code == 502
        assert "X-Correlation-ID" in response.headers
        body = response.json()
        assert body["error"]["code"] == "model_unavailable"
        assert "Pipeline not loaded" in body["error"]["message"]

    @pytest.mark.asyncio
    async def test_generation_error(self, client, mock_image_generation_service) -> None:
        mock_image_generation_service.generate_images.side_effect = application.exceptions.ImageGenerationError(
            detail="No images returned"
        )

        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset"},
        )

        assert response.status_code == 502
        assert "X-Correlation-ID" in response.headers
        body = response.json()
        assert body["error"]["code"] == "model_unavailable"
        assert "No images returned" in body["error"]["message"]

    @pytest.mark.asyncio
    async def test_enhancer_failure_returns_502(
        self,
        client,
        mock_language_model_service,
        mock_image_generation_service,
    ) -> None:
        """Per spec §16, when use_enhancer is true and llama.cpp fails,
        the service returns HTTP 502 — no silent fallback."""
        mock_language_model_service.enhance_prompt.side_effect = (
            application.exceptions.LanguageModelServiceUnavailableError(detail="Server down")
        )

        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "use_enhancer": True},
        )

        assert response.status_code == 502
        body = response.json()
        assert body["error"]["code"] == "upstream_service_unavailable"
        mock_image_generation_service.generate_images.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_seed_negative_rejected(self, client) -> None:
        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "seed": -1},
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_seed_above_maximum_rejected(self, client) -> None:
        response = await client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset", "seed": 4_294_967_296},
        )

        assert response.status_code == 400


class TestServiceBusyErrorHandler:
    """
    Verify the ``ServiceBusyError`` exception handler (error_handling.py
    lines 226–263) produces the correct HTTP 429 response.

    When the image generation admission controller rejects a request
    because the maximum concurrency limit has been reached, the error
    handler must:

    - Return HTTP 429 (Too Many Requests).
    - Include the machine-readable error code ``service_busy``.
    - Include a ``Retry-After`` response header populated from the
      operator-configured ``retry_after_busy_seconds``.
    - Include the ``X-Correlation-ID`` header for request traceability.
    - Include the standard ``ErrorResponse`` JSON body structure.

    These tests construct a dedicated FastAPI application with an
    admission controller whose concurrency limit is set to 1, then
    occupy the single slot while firing a second request to trigger
    the rejection path.
    """

    @pytest_asyncio.fixture
    async def saturated_admission_controller_client(
        self,
        mock_language_model_service,
        mock_image_generation_service,
    ) -> collections.abc.AsyncGenerator:
        """
        Build a test application with an admission controller set to
        ``maximum_concurrency=1``.  The fixture holds the single slot
        occupied via a background task, ensuring that any image
        generation request during the test will be rejected with
        ``ServiceBusyError``.
        """
        admission_controller = application.admission_control.ImageGenerationAdmissionController(
            maximum_concurrency=1,
        )

        app = fastapi.FastAPI()
        application.error_handling.register_error_handlers(app)

        app.add_middleware(
            application.middleware.CorrelationIdMiddleware,
        )

        app.include_router(
            application.routes.image_generation_routes.image_generation_router,
        )

        app.dependency_overrides[application.dependencies.get_language_model_service] = lambda: (
            mock_language_model_service
        )

        app.dependency_overrides[application.dependencies.get_image_generation_service] = lambda: (
            mock_image_generation_service
        )

        app.dependency_overrides[application.dependencies.get_image_generation_admission_controller] = lambda: (
            admission_controller
        )

        app.state.limiter = application.rate_limiting.rate_limiter
        application.rate_limiting.inference_rate_limit_configuration.configure("1000/minute")
        app.add_exception_handler(
            slowapi.errors.RateLimitExceeded,
            application.rate_limiting.rate_limit_exceeded_handler,
        )

        app.state.retry_after_busy_seconds = 45

        # Occupy the single admission slot for the duration of the test.
        hold_slot_signal = asyncio.Event()

        async def hold_admission_slot() -> None:
            async with admission_controller.acquire_or_reject():
                await hold_slot_signal.wait()

        background_task = asyncio.create_task(hold_admission_slot())
        await asyncio.sleep(0)  # Let the task acquire the slot.

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            yield http_client

        # Release the background task.
        hold_slot_signal.set()
        await background_task

    @pytest.mark.asyncio
    async def test_returns_http_429_when_concurrency_limit_reached(
        self,
        saturated_admission_controller_client,
    ) -> None:
        """
        A request that arrives when all admission slots are occupied
        receives HTTP 429 (Too Many Requests).
        """
        response = await saturated_admission_controller_client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset"},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 429

    @pytest.mark.asyncio
    async def test_error_code_is_service_busy(
        self,
        saturated_admission_controller_client,
    ) -> None:
        """
        The error response body uses the ``service_busy`` error code,
        which is distinct from ``rate_limit_exceeded`` (IP-based
        rate limiting).
        """
        response = await saturated_admission_controller_client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset"},
            headers={"Content-Type": "application/json"},
        )

        body = response.json()
        assert body["error"]["code"] == "service_busy"

    @pytest.mark.asyncio
    async def test_includes_retry_after_header(
        self,
        saturated_admission_controller_client,
    ) -> None:
        """
        The 429 response includes a ``Retry-After`` header populated
        from the operator-configured ``retry_after_busy_seconds``
        value (set to 45 in the fixture).
        """
        response = await saturated_admission_controller_client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset"},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 429
        assert "Retry-After" in response.headers
        assert response.headers["Retry-After"] == "45"

    @pytest.mark.asyncio
    async def test_includes_correlation_id_header(
        self,
        saturated_admission_controller_client,
    ) -> None:
        """
        The 429 response includes the ``X-Correlation-ID`` header for
        request traceability, injected by the outer
        ``CorrelationIdMiddleware``.
        """
        response = await saturated_admission_controller_client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset"},
            headers={"Content-Type": "application/json"},
        )

        assert "X-Correlation-ID" in response.headers

    @pytest.mark.asyncio
    async def test_includes_correlation_id_in_body(
        self,
        saturated_admission_controller_client,
    ) -> None:
        """
        The ``correlation_id`` field in the JSON error body matches the
        ``X-Correlation-ID`` response header.
        """
        response = await saturated_admission_controller_client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset"},
            headers={"Content-Type": "application/json"},
        )

        body = response.json()
        assert body["error"]["correlation_id"] == response.headers["X-Correlation-ID"]

    @pytest.mark.asyncio
    async def test_error_body_matches_standard_schema(
        self,
        saturated_admission_controller_client,
    ) -> None:
        """
        The 429 response body follows the standard ``ErrorResponse``
        schema with nested ``error`` object containing ``code``,
        ``message``, and ``correlation_id``.
        """
        response = await saturated_admission_controller_client.post(
            "/v1/images/generations",
            json={"prompt": "A sunset"},
            headers={"Content-Type": "application/json"},
        )

        body = response.json()
        assert "error" in body
        error_detail = body["error"]
        assert "code" in error_detail
        assert "message" in error_detail
        assert "correlation_id" in error_detail
        assert error_detail["code"] == "service_busy"
        assert len(error_detail["message"]) > 0
