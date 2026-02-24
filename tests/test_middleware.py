"""Tests for application/middleware.py — InFlightRequestCounter,
CorrelationIdMiddleware, RequestTimeoutMiddleware,
ContentTypeValidationMiddleware, and RequestPayloadSizeLimitMiddleware."""

import asyncio
import uuid

import fastapi
import httpx
import pytest
import pytest_asyncio

import application.middleware


class TestInFlightRequestCounter:
    """
    Tests for the ``InFlightRequestCounter`` used to track the number of
    HTTP requests currently being processed by the service.

    The counter is read during graceful shutdown to emit the
    ``graceful_shutdown_initiated`` log event with the in-flight request
    count (specification FR40, event B-1).
    """

    def test_initial_count_is_zero(self):
        """A freshly created counter must report zero in-flight requests."""
        counter = application.middleware.InFlightRequestCounter()
        assert counter.count == 0

    def test_increment_increases_count(self):
        """Calling ``increment`` must increase the count by one."""
        counter = application.middleware.InFlightRequestCounter()
        counter.increment()
        assert counter.count == 1

    def test_decrement_decreases_count(self):
        """Calling ``decrement`` after ``increment`` must restore the count."""
        counter = application.middleware.InFlightRequestCounter()
        counter.increment()
        counter.increment()
        counter.decrement()
        assert counter.count == 1

    def test_multiple_increments_and_decrements(self):
        """The counter must correctly track multiple concurrent requests."""
        counter = application.middleware.InFlightRequestCounter()
        counter.increment()
        counter.increment()
        counter.increment()
        assert counter.count == 3
        counter.decrement()
        counter.decrement()
        assert counter.count == 1

    @pytest.mark.asyncio
    async def test_correlation_id_middleware_increments_and_decrements_counter(self):
        """
        The ``CorrelationIdMiddleware`` must increment the in-flight
        counter when a request begins and decrement it when the request
        completes, leaving the counter at zero after the request finishes.
        """
        counter = application.middleware.InFlightRequestCounter()
        counter_during_request: int | None = None

        async def inner_app(scope, receive, send):
            nonlocal counter_during_request
            # Record the counter value while the request is in flight.
            counter_during_request = counter.count

            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b'{"status": "ok"}',
                }
            )

        middleware = application.middleware.CorrelationIdMiddleware(
            inner_app,
            in_flight_request_counter=counter,
        )

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [],
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        sent_messages: list[dict] = []

        async def send(message: dict) -> None:
            sent_messages.append(message)

        await middleware(scope, receive, send)

        # During the request, the counter should have been 1.
        assert counter_during_request == 1
        # After the request completes, the counter should be back to 0.
        assert counter.count == 0

    @pytest.mark.asyncio
    async def test_counter_decremented_even_on_unhandled_exception(self):
        """
        When the inner application raises an unhandled exception, the
        ``CorrelationIdMiddleware`` must still decrement the in-flight
        counter in the ``finally`` block, ensuring the counter does not
        drift upward over time due to failed requests.
        """
        counter = application.middleware.InFlightRequestCounter()

        async def failing_inner_app(scope, receive, send):
            raise RuntimeError("Simulated application failure")

        middleware = application.middleware.CorrelationIdMiddleware(
            failing_inner_app,
            in_flight_request_counter=counter,
        )

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/error",
            "headers": [],
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        sent_messages: list[dict] = []

        async def send(message: dict) -> None:
            sent_messages.append(message)

        await middleware(scope, receive, send)

        # The counter must be back to 0 even though the request failed.
        assert counter.count == 0


def _create_test_app():
    """Create a minimal FastAPI app with the correlation ID middleware."""
    app = fastapi.FastAPI()
    app.add_middleware(application.middleware.CorrelationIdMiddleware)

    @app.get("/test")
    async def test_endpoint(request: fastapi.Request):
        return {"correlation_id": request.state.correlation_id}

    @app.get("/error")
    async def error_endpoint():
        raise RuntimeError("something broke")

    return app


def _create_timeout_test_app(request_timeout_seconds: float = 1.0):
    """
    Create a minimal FastAPI app with both the CorrelationIdMiddleware
    and the RequestTimeoutMiddleware for timeout testing.

    The CorrelationIdMiddleware is registered as the outermost middleware
    so that the timeout response includes a traceable correlation ID.
    """
    app = fastapi.FastAPI()

    @app.get("/fast")
    async def fast_endpoint():
        return {"status": "completed"}

    @app.get("/slow")
    async def slow_endpoint():
        await asyncio.sleep(5.0)
        return {"status": "completed"}

    # Register in reverse order: last registered = outermost.
    # Execution order: CorrelationId → RequestTimeout → App
    app.add_middleware(
        application.middleware.RequestTimeoutMiddleware,
        request_timeout_seconds=request_timeout_seconds,
    )
    app.add_middleware(application.middleware.CorrelationIdMiddleware)

    return app


@pytest_asyncio.fixture
async def client():
    app = _create_test_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client


@pytest_asyncio.fixture
async def timeout_client():
    """
    HTTP client connected to a test application with a very short
    request timeout (0.1 seconds) for deterministic timeout testing.
    """
    app = _create_timeout_test_app(request_timeout_seconds=0.1)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client


class TestCorrelationIdMiddleware:
    @pytest.mark.asyncio
    async def test_header_present(self, client):
        response = await client.get("/test")
        assert "X-Correlation-ID" in response.headers

    @pytest.mark.asyncio
    async def test_valid_uuid(self, client):
        response = await client.get("/test")
        correlation_id = response.headers["X-Correlation-ID"]
        # Should not raise
        parsed = uuid.UUID(correlation_id, version=4)
        assert str(parsed) == correlation_id

    @pytest.mark.asyncio
    async def test_matches_request_state(self, client):
        response = await client.get("/test")
        header_id = response.headers["X-Correlation-ID"]
        body_id = response.json()["correlation_id"]
        assert header_id == body_id

    @pytest.mark.asyncio
    async def test_unique_per_request(self, client):
        response1 = await client.get("/test")
        response2 = await client.get("/test")
        id1 = response1.headers["X-Correlation-ID"]
        id2 = response2.headers["X-Correlation-ID"]
        assert id1 != id2

    @pytest.mark.asyncio
    async def test_unhandled_exception_returns_json_500(self, client):
        response = await client.get("/error")

        assert response.status_code == 500
        body = response.json()
        assert body["error"]["code"] == "internal_server_error"
        assert "X-Correlation-ID" in response.headers

    @pytest.mark.asyncio
    async def test_non_http_scope_passed_through(self):
        """Non-HTTP scopes (e.g. websocket, lifespan) bypass the middleware."""
        inner_called = False

        async def inner_app(scope, receive, send):
            nonlocal inner_called
            inner_called = True

        middleware = application.middleware.CorrelationIdMiddleware(inner_app)
        await middleware({"type": "lifespan"}, None, None)
        assert inner_called

    @pytest.mark.asyncio
    async def test_malformed_content_length_header_does_not_crash_middleware(self):
        """
        When the ``Content-Length`` header contains a non-numeric value
        (for example, ``"not-a-number"``), the module-level
        ``extract_content_length_from_headers`` utility function must
        catch the ``ValueError`` and return ``None`` rather than crashing
        the middleware.

        This test exercises the ``except (ValueError, TypeError): return None``
        branch — the defensive fallback path that handles malformed
        Content-Length values in the logging context.

        The middleware should process the request normally and include
        ``request_payload_bytes=None`` in the ``http_request_received``
        log event.
        """

        async def inner_app(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b'{"status": "ok"}',
                }
            )

        middleware = application.middleware.CorrelationIdMiddleware(inner_app)

        # Construct a scope with a Content-Length header that cannot be
        # parsed as an integer.  The middleware must handle this gracefully.
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/test",
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", b"not-a-number"),
            ],
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        sent_messages: list[dict] = []

        async def send(message: dict) -> None:
            sent_messages.append(message)

        # The middleware must not raise an exception.
        await middleware(scope, receive, send)

        # The request should have been processed successfully (inner app
        # returned 200), confirming the malformed Content-Length did not
        # cause the middleware to crash.
        response_start_messages = [
            message
            for message in sent_messages
            if message.get("type") == "http.response.start"
        ]
        assert len(response_start_messages) == 1
        assert response_start_messages[0]["status"] == 200


class TestRequestTimeoutMiddleware:
    """
    Tests for the end-to-end request timeout middleware (NFR48).

    The middleware must abort requests exceeding the configured timeout
    ceiling and return HTTP 504 with a structured JSON error response
    containing the error code ``request_timeout``.
    """

    @pytest.mark.asyncio
    async def test_fast_request_completes_normally(self, timeout_client):
        """Requests that finish within the timeout ceiling succeed normally."""
        response = await timeout_client.get("/fast")

        assert response.status_code == 200
        assert response.json()["status"] == "completed"

    @pytest.mark.asyncio
    async def test_slow_request_returns_504(self, timeout_client):
        """Requests exceeding the timeout ceiling receive HTTP 504."""
        response = await timeout_client.get("/slow")

        assert response.status_code == 504

    @pytest.mark.asyncio
    async def test_timeout_response_has_correct_error_code(self, timeout_client):
        """The 504 response body contains the ``request_timeout`` error code."""
        response = await timeout_client.get("/slow")

        body = response.json()
        assert body["error"]["code"] == "request_timeout"

    @pytest.mark.asyncio
    async def test_timeout_response_has_correlation_id(self, timeout_client):
        """The 504 response body includes a correlation ID for traceability."""
        response = await timeout_client.get("/slow")

        body = response.json()
        assert "correlation_id" in body["error"]
        assert body["error"]["correlation_id"] != "unknown"

    @pytest.mark.asyncio
    async def test_timeout_response_has_json_content_type(self, timeout_client):
        """The 504 response declares application/json as its Content-Type."""
        response = await timeout_client.get("/slow")

        assert response.headers["content-type"] == "application/json"

    @pytest.mark.asyncio
    async def test_timeout_after_headers_sent_does_not_replace_response(self):
        """
        When the inner application has already sent the
        ``http.response.start`` message (committing the HTTP status
        code) and then exceeds the timeout, the middleware must NOT
        attempt to send a second ``http.response.start`` with status
        504.  Doing so would violate the ASGI protocol (duplicate
        response headers) and cause a server error.

        Instead, the middleware logs a warning
        (``request_timeout_after_headers_sent``) and returns silently,
        allowing the already-committed partial response to stand.

        This test exercises the ``response_headers_already_sent`` guard
        at middleware.py lines 239–249.
        """
        sent_messages: list[dict] = []

        async def send(message: dict) -> None:
            sent_messages.append(message)

        async def slow_inner_app_that_sends_headers_first(
            scope,
            receive,
            send_callable,
        ):
            """
            Simulate an application that sends response headers
            immediately and then blocks for longer than the timeout
            before sending the response body.
            """
            await send_callable(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            # Sleep long enough to exceed the 0.05-second timeout.
            # The middleware should detect that headers have already
            # been sent and refrain from sending a 504 response.
            await asyncio.sleep(1.0)
            await send_callable(
                {
                    "type": "http.response.body",
                    "body": b'{"status": "completed"}',
                }
            )

        middleware = application.middleware.RequestTimeoutMiddleware(
            slow_inner_app_that_sends_headers_first,
            request_timeout_seconds=0.05,
        )

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/slow-with-headers",
            "state": {"correlation_id": "test-correlation-id"},
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        await middleware(scope, receive, send)

        # ── Assertions ───────────────────────────────────────────────
        #
        # The middleware must NOT have injected a second
        # http.response.start with status 504.  Only the original 200
        # response should be present.
        response_start_messages = [message for message in sent_messages if message.get("type") == "http.response.start"]

        assert len(response_start_messages) == 1, (
            "The middleware must not send a second http.response.start when headers have already been committed."
        )
        assert response_start_messages[0]["status"] == 200, (
            "The already-committed 200 status code must not be replaced with 504."
        )

    @pytest.mark.asyncio
    async def test_non_http_scope_passed_through(self):
        """Non-HTTP scopes (e.g. lifespan) bypass the timeout middleware."""
        inner_called = False

        async def inner_app(scope, receive, send):
            nonlocal inner_called
            inner_called = True

        middleware = application.middleware.RequestTimeoutMiddleware(
            inner_app,
            request_timeout_seconds=1.0,
        )
        await middleware({"type": "lifespan"}, None, None)
        assert inner_called


# ──────────────────────────────────────────────────────────────────────────────
#  ContentTypeValidationMiddleware tests
# ──────────────────────────────────────────────────────────────────────────────


def _create_content_type_test_app():
    """
    Create a minimal FastAPI app with both the CorrelationIdMiddleware
    (outermost) and the ContentTypeValidationMiddleware (inner) for
    Content-Type enforcement testing.

    Includes a POST endpoint that echoes the request body and a GET
    endpoint that returns a simple response.
    """
    app = fastapi.FastAPI()

    @app.post("/echo")
    async def echo_endpoint(request: fastapi.Request):
        body = await request.json()
        return {"received": body}

    @app.get("/ping")
    async def ping_endpoint():
        return {"status": "ok"}

    # Register in reverse order: last registered = outermost.
    # Execution order: CorrelationId → ContentType → App
    app.add_middleware(
        application.middleware.ContentTypeValidationMiddleware,
    )
    app.add_middleware(application.middleware.CorrelationIdMiddleware)

    return app


@pytest_asyncio.fixture
async def content_type_client():
    """HTTP client connected to a test app with Content-Type validation."""
    app = _create_content_type_test_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client


class TestContentTypeValidationMiddleware:
    """
    Tests for the Content-Type enforcement middleware (NFR18).

    The middleware rejects POST requests that do not declare
    ``application/json`` as their Content-Type with HTTP 415
    (Unsupported Media Type).  GET, HEAD, OPTIONS, DELETE, and TRACE
    requests are exempt.
    """

    @pytest.mark.asyncio
    async def test_post_with_correct_content_type_passes(self, content_type_client):
        """POST requests with Content-Type: application/json pass through."""
        response = await content_type_client.post(
            "/echo",
            json={"key": "value"},
        )

        assert response.status_code == 200
        assert response.json()["received"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_post_with_content_type_including_charset_passes(self, content_type_client):
        """POST requests with Content-Type: application/json; charset=utf-8
        pass through (the startswith check accommodates parameters)."""
        response = await content_type_client.post(
            "/echo",
            content=b'{"key": "value"}',
            headers={"Content-Type": "application/json; charset=utf-8"},
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_post_with_missing_content_type_returns_415(self, content_type_client):
        """POST requests without a Content-Type header are rejected with 415."""
        response = await content_type_client.post(
            "/echo",
            content=b'{"key": "value"}',
            headers={"Content-Type": ""},
        )

        # An empty Content-Type is treated as missing/invalid
        assert response.status_code == 415

    @pytest.mark.asyncio
    async def test_post_with_wrong_content_type_returns_415(self, content_type_client):
        """POST requests with Content-Type: text/plain are rejected with 415."""
        response = await content_type_client.post(
            "/echo",
            content=b'{"key": "value"}',
            headers={"Content-Type": "text/plain"},
        )

        assert response.status_code == 415

    @pytest.mark.asyncio
    async def test_post_with_xml_content_type_returns_415(self, content_type_client):
        """POST requests with Content-Type: application/xml are rejected with 415."""
        response = await content_type_client.post(
            "/echo",
            content=b"<root/>",
            headers={"Content-Type": "application/xml"},
        )

        assert response.status_code == 415

    @pytest.mark.asyncio
    async def test_415_response_has_correct_error_code(self, content_type_client):
        """The 415 response body contains the ``unsupported_media_type`` error code."""
        response = await content_type_client.post(
            "/echo",
            content=b'{"key": "value"}',
            headers={"Content-Type": "text/plain"},
        )

        body = response.json()
        assert body["error"]["code"] == "unsupported_media_type"

    @pytest.mark.asyncio
    async def test_415_response_has_correlation_id(self, content_type_client):
        """The 415 response body includes a correlation ID for traceability."""
        response = await content_type_client.post(
            "/echo",
            content=b'{"key": "value"}',
            headers={"Content-Type": "text/plain"},
        )

        body = response.json()
        assert "correlation_id" in body["error"]
        assert body["error"]["correlation_id"] != "unknown"

    @pytest.mark.asyncio
    async def test_415_response_has_json_content_type(self, content_type_client):
        """The 415 response itself declares application/json as its Content-Type."""
        response = await content_type_client.post(
            "/echo",
            content=b'{"key": "value"}',
            headers={"Content-Type": "text/plain"},
        )

        assert response.headers["content-type"] == "application/json"

    @pytest.mark.asyncio
    async def test_415_response_has_correlation_id_header(self, content_type_client):
        """The 415 response includes an X-Correlation-ID response header."""
        response = await content_type_client.post(
            "/echo",
            content=b'{"key": "value"}',
            headers={"Content-Type": "text/plain"},
        )

        assert "x-correlation-id" in response.headers

    @pytest.mark.asyncio
    async def test_get_request_bypasses_content_type_check(self, content_type_client):
        """GET requests are exempt from Content-Type validation."""
        response = await content_type_client.get("/ping")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_options_request_bypasses_content_type_check(self, content_type_client):
        """OPTIONS requests are exempt from Content-Type validation."""
        response = await content_type_client.options("/echo")

        # OPTIONS may return 405 if no handler, but not 415
        assert response.status_code != 415

    @pytest.mark.asyncio
    async def test_non_http_scope_passed_through(self):
        """Non-HTTP scopes (e.g. lifespan) bypass the Content-Type middleware."""
        inner_called = False

        async def inner_app(scope, receive, send):
            nonlocal inner_called
            inner_called = True

        middleware = application.middleware.ContentTypeValidationMiddleware(inner_app)
        await middleware({"type": "lifespan"}, None, None)
        assert inner_called

    @pytest.mark.asyncio
    async def test_post_with_completely_absent_content_type_header_returns_415(self):
        """
        When a POST request carries no ``Content-Type`` header at all
        (not an empty value — the header is completely absent from the
        ASGI scope), the ``_extract_content_type_from_headers`` method
        iterates through all headers without finding a match and falls
        through to the final ``return None`` statement.

        This test exercises the ``return None`` fallback at
        middleware.py line 496 — the code path where the Content-Type
        header is entirely missing rather than present-but-invalid.

        The middleware must reject the request with HTTP 415
        (Unsupported Media Type) because a missing Content-Type is
        treated identically to an invalid one for POST requests.
        """

        async def inner_app(scope, receive, send):
            # This inner app should never be reached because the
            # middleware rejects the request before it gets here.
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b'{"status": "ok"}',
                }
            )

        middleware = application.middleware.ContentTypeValidationMiddleware(inner_app)

        # Construct a scope with NO Content-Type header at all.
        # The headers list contains only an Accept header — no
        # content-type entry exists for the loop to find.
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/echo",
            "headers": [
                (b"accept", b"application/json"),
            ],
            "state": {"correlation_id": "test-correlation-id"},
        }

        async def receive():
            return {"type": "http.request", "body": b'{"key": "value"}', "more_body": False}

        sent_messages: list[dict] = []

        async def send(message: dict) -> None:
            sent_messages.append(message)

        await middleware(scope, receive, send)

        # The middleware must have rejected the request with HTTP 415.
        response_start_messages = [
            message
            for message in sent_messages
            if message.get("type") == "http.response.start"
        ]
        assert len(response_start_messages) == 1
        assert response_start_messages[0]["status"] == 415

        # Verify the response body contains the correct error code.
        import json

        response_body_message = next(
            message
            for message in sent_messages
            if message.get("type") == "http.response.body"
        )
        response_body = json.loads(response_body_message["body"])
        assert response_body["error"]["code"] == "unsupported_media_type"


# ──────────────────────────────────────────────────────────────────────────────
#  RequestPayloadSizeLimitMiddleware tests
# ──────────────────────────────────────────────────────────────────────────────


def _create_payload_size_test_app(maximum_request_payload_bytes: int = 100):
    """
    Create a minimal FastAPI app with both the CorrelationIdMiddleware
    (outermost) and the RequestPayloadSizeLimitMiddleware (inner) for
    payload size enforcement testing.

    The maximum payload size is deliberately small (100 bytes by default)
    so that test payloads can be crafted without allocating large buffers.

    Includes a POST endpoint that reads the request body and echoes its
    length, and a GET endpoint that returns a simple response.
    """
    app = fastapi.FastAPI()

    @app.post("/upload")
    async def upload_endpoint(request: fastapi.Request):
        body_bytes = await request.body()
        return {"received_bytes": len(body_bytes)}

    @app.get("/ping")
    async def ping_endpoint():
        return {"status": "ok"}

    # Register in reverse order: last registered = outermost.
    # Execution order: CorrelationId → PayloadSizeLimit → App
    app.add_middleware(
        application.middleware.RequestPayloadSizeLimitMiddleware,
        maximum_request_payload_bytes=maximum_request_payload_bytes,
    )
    app.add_middleware(application.middleware.CorrelationIdMiddleware)

    return app


@pytest_asyncio.fixture
async def payload_size_client():
    """
    HTTP client connected to a test app with a 100-byte payload size limit.

    The limit is deliberately small so that tests can trigger rejection
    with compact payloads.
    """
    app = _create_payload_size_test_app(maximum_request_payload_bytes=100)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client


class TestRequestPayloadSizeLimitMiddleware:
    """
    Tests for the request payload size enforcement middleware (NFR15).

    The middleware rejects requests whose body exceeds the configured
    maximum with HTTP 413 (Payload Too Large).  It uses two strategies:

    1. Fast-path rejection when the Content-Length header declares a
       size exceeding the limit (before any body bytes are read).

    2. Streaming accumulation guard that tracks actual body bytes
       received and truncates the body when the limit is exceeded.
    """

    @pytest.mark.asyncio
    async def test_request_within_limit_passes(self, payload_size_client):
        """Requests with a body smaller than the limit pass through normally."""
        small_body = b"x" * 50  # 50 bytes, well within the 100-byte limit

        response = await payload_size_client.post(
            "/upload",
            content=small_body,
            headers={"Content-Type": "application/octet-stream"},
        )

        assert response.status_code == 200
        assert response.json()["received_bytes"] == 50

    @pytest.mark.asyncio
    async def test_request_exactly_at_limit_passes(self, payload_size_client):
        """Requests with a body exactly at the limit pass through (the
        check is strictly greater-than, not greater-than-or-equal)."""
        exact_body = b"x" * 100  # Exactly 100 bytes

        response = await payload_size_client.post(
            "/upload",
            content=exact_body,
            headers={"Content-Type": "application/octet-stream"},
        )

        assert response.status_code == 200
        assert response.json()["received_bytes"] == 100

    @pytest.mark.asyncio
    async def test_content_length_exceeding_limit_returns_413(self, payload_size_client):
        """When the Content-Length header declares a size exceeding the limit,
        the middleware rejects the request immediately with HTTP 413 before
        reading any body bytes (fast-path rejection)."""
        oversized_body = b"x" * 200  # 200 bytes, exceeds the 100-byte limit

        response = await payload_size_client.post(
            "/upload",
            content=oversized_body,
            headers={"Content-Type": "application/octet-stream"},
        )

        assert response.status_code == 413

    @pytest.mark.asyncio
    async def test_413_response_has_correct_error_code(self, payload_size_client):
        """The 413 response body contains the ``payload_too_large`` error code."""
        oversized_body = b"x" * 200

        response = await payload_size_client.post(
            "/upload",
            content=oversized_body,
            headers={"Content-Type": "application/octet-stream"},
        )

        body = response.json()
        assert body["error"]["code"] == "payload_too_large"

    @pytest.mark.asyncio
    async def test_413_response_has_correlation_id(self, payload_size_client):
        """The 413 response body includes a correlation ID for traceability."""
        oversized_body = b"x" * 200

        response = await payload_size_client.post(
            "/upload",
            content=oversized_body,
            headers={"Content-Type": "application/octet-stream"},
        )

        body = response.json()
        assert "correlation_id" in body["error"]
        assert body["error"]["correlation_id"] != "unknown"

    @pytest.mark.asyncio
    async def test_413_response_has_json_content_type(self, payload_size_client):
        """The 413 response declares application/json as its Content-Type."""
        oversized_body = b"x" * 200

        response = await payload_size_client.post(
            "/upload",
            content=oversized_body,
            headers={"Content-Type": "application/octet-stream"},
        )

        assert response.headers["content-type"] == "application/json"

    @pytest.mark.asyncio
    async def test_413_response_has_correlation_id_header(self, payload_size_client):
        """The 413 response includes an X-Correlation-ID response header."""
        oversized_body = b"x" * 200

        response = await payload_size_client.post(
            "/upload",
            content=oversized_body,
            headers={"Content-Type": "application/octet-stream"},
        )

        assert "x-correlation-id" in response.headers

    @pytest.mark.asyncio
    async def test_413_response_message_includes_limit(self, payload_size_client):
        """The 413 error message includes the configured maximum size."""
        oversized_body = b"x" * 200

        response = await payload_size_client.post(
            "/upload",
            content=oversized_body,
            headers={"Content-Type": "application/octet-stream"},
        )

        body = response.json()
        assert "100" in body["error"]["message"]

    @pytest.mark.asyncio
    async def test_get_request_without_body_passes(self, payload_size_client):
        """GET requests (which typically carry no body) pass through."""
        response = await payload_size_client.get("/ping")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_non_http_scope_passed_through(self):
        """Non-HTTP scopes (e.g. lifespan) bypass the payload size middleware."""
        inner_called = False

        async def inner_app(scope, receive, send):
            nonlocal inner_called
            inner_called = True

        middleware = application.middleware.RequestPayloadSizeLimitMiddleware(
            inner_app,
            maximum_request_payload_bytes=100,
        )
        await middleware({"type": "lifespan"}, None, None)
        assert inner_called


class TestRequestPayloadSizeLimitStreamingGuard:
    """
    Tests for the streaming accumulation guard in
    ``RequestPayloadSizeLimitMiddleware``.

    The streaming guard is the second line of defence: when the
    ``Content-Length`` header is absent (chunked transfer) or the client
    lies about the body size, the middleware wraps the ASGI ``receive``
    callable and tracks the actual number of body bytes received.  When
    the accumulated total exceeds the configured limit, the middleware
    truncates the body and flags the request for rejection.

    These tests exercise the middleware at the ASGI level (bypassing
    httpx) because httpx always sets the ``Content-Length`` header based
    on the actual body size, which would trigger the fast-path rejection
    instead of the streaming guard.
    """

    @staticmethod
    def _build_http_scope(
        content_length: int | None = None,
    ) -> dict:
        """
        Build a minimal ASGI HTTP scope for POST requests.

        When ``content_length`` is ``None``, no Content-Length header
        is included (simulating chunked transfer encoding or a
        malicious client that omits the header).
        """
        headers: list[tuple[bytes, bytes]] = [
            (b"content-type", b"application/octet-stream"),
        ]
        if content_length is not None:
            headers.append(
                (b"content-length", str(content_length).encode()),
            )

        return {
            "type": "http",
            "method": "POST",
            "path": "/upload",
            "headers": headers,
            "state": {"correlation_id": "test-correlation-id"},
        }

    @staticmethod
    def _build_receive_returning_chunks(
        chunks: list[bytes],
    ):
        """
        Build an ASGI ``receive`` callable that returns the given body
        chunks sequentially, followed by an empty terminal message.

        Each chunk is wrapped in an ``http.request`` message.  The final
        chunk has ``more_body: False`` to signal end of body.
        """
        messages = []
        for index, chunk in enumerate(chunks):
            is_last_chunk = index == len(chunks) - 1
            messages.append(
                {
                    "type": "http.request",
                    "body": chunk,
                    "more_body": not is_last_chunk,
                }
            )

        call_count = 0

        async def receive() -> dict:
            nonlocal call_count
            if call_count < len(messages):
                message = messages[call_count]
                call_count += 1
                return message
            # After all chunks have been consumed, return a
            # disconnect event.
            return {"type": "http.disconnect"}

        return receive

    @pytest.mark.asyncio
    async def test_streaming_body_within_limit_passes(self) -> None:
        """
        When no Content-Length header is present and the actual body
        bytes are within the limit, the inner application receives the
        full body and the request succeeds.
        """
        inner_app_received_body = bytearray()

        async def inner_app(scope, receive, send):
            while True:
                message = await receive()
                if message["type"] == "http.request":
                    inner_app_received_body.extend(message.get("body", b""))
                    if not message.get("more_body", False):
                        break

            # Send a 200 response.
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b'{"status": "ok"}',
                }
            )

        middleware = application.middleware.RequestPayloadSizeLimitMiddleware(
            inner_app,
            maximum_request_payload_bytes=100,
        )

        scope = self._build_http_scope(content_length=None)
        receive = self._build_receive_returning_chunks([b"x" * 50])
        sent_messages: list[dict] = []

        async def send(message: dict) -> None:
            sent_messages.append(message)

        await middleware(scope, receive, send)

        # The inner app should have received the full 50-byte body.
        assert len(inner_app_received_body) == 50
        # The response should be 200 (from the inner app).
        assert sent_messages[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_streaming_body_exceeding_limit_truncates_body(self) -> None:
        """
        When no Content-Length header is present and the accumulated
        body bytes exceed the limit, the streaming guard truncates the
        body by returning an empty chunk with ``more_body: False``.

        The inner application then receives a truncated body, which
        typically causes a parsing error.
        """
        inner_app_received_body = bytearray()
        inner_app_raised = False

        async def inner_app(scope, receive, send):
            nonlocal inner_app_raised
            try:
                while True:
                    message = await receive()
                    if message["type"] == "http.request":
                        inner_app_received_body.extend(
                            message.get("body", b""),
                        )
                        if not message.get("more_body", False):
                            break
                # Inner app tries to process the truncated body and raises.
                raise ValueError("Invalid body — simulating parse failure")
            except ValueError:
                inner_app_raised = True
                raise

        middleware = application.middleware.RequestPayloadSizeLimitMiddleware(
            inner_app,
            maximum_request_payload_bytes=100,
        )

        # Send two chunks: 80 + 80 = 160 bytes total, exceeding the 100-byte limit.
        scope = self._build_http_scope(content_length=None)
        receive = self._build_receive_returning_chunks(
            [b"A" * 80, b"B" * 80],
        )
        sent_messages: list[dict] = []

        async def send(message: dict) -> None:
            sent_messages.append(message)

        await middleware(scope, receive, send)

        # The middleware should have caught the inner app's exception
        # and sent a 413 response instead.
        assert any(
            message.get("status") == 413 for message in sent_messages if message.get("type") == "http.response.start"
        )

    @pytest.mark.asyncio
    async def test_streaming_guard_sends_413_when_app_raises(self) -> None:
        """
        When the streaming guard truncates the body and the inner
        application raises an exception (because the body is invalid),
        the middleware catches the exception and sends HTTP 413 with
        the ``payload_too_large`` error code.
        """

        async def inner_app(scope, receive, send):
            # Read the body, which will be truncated by the guard.
            await receive()
            # Simulate a parse failure on the truncated body.
            raise ValueError("Simulated parse failure on truncated body")

        middleware = application.middleware.RequestPayloadSizeLimitMiddleware(
            inner_app,
            maximum_request_payload_bytes=50,
        )

        # Send a single chunk of 100 bytes, exceeding the 50-byte limit.
        scope = self._build_http_scope(content_length=None)
        receive = self._build_receive_returning_chunks([b"Z" * 100])
        sent_messages: list[dict] = []

        async def send(message: dict) -> None:
            sent_messages.append(message)

        await middleware(scope, receive, send)

        # Verify a 413 response was sent.
        response_start = next(message for message in sent_messages if message.get("type") == "http.response.start")
        assert response_start["status"] == 413

        # Verify the response body contains the correct error code.
        import json

        response_body_message = next(
            message for message in sent_messages if message.get("type") == "http.response.body"
        )
        response_body = json.loads(response_body_message["body"])
        assert response_body["error"]["code"] == "payload_too_large"

    @pytest.mark.asyncio
    async def test_streaming_guard_includes_correlation_id_in_413(self) -> None:
        """
        The 413 response sent by the streaming guard includes the
        correlation ID from the ASGI scope state, matching the
        ``X-Correlation-ID`` header set by the outer
        ``CorrelationIdMiddleware``.
        """

        async def inner_app(scope, receive, send):
            await receive()
            raise ValueError("Simulated parse failure")

        middleware = application.middleware.RequestPayloadSizeLimitMiddleware(
            inner_app,
            maximum_request_payload_bytes=50,
        )

        scope = self._build_http_scope(content_length=None)
        scope["state"] = {"correlation_id": "test-id-12345"}
        receive = self._build_receive_returning_chunks([b"Z" * 100])
        sent_messages: list[dict] = []

        async def send(message: dict) -> None:
            sent_messages.append(message)

        await middleware(scope, receive, send)

        import json

        response_body_message = next(
            message for message in sent_messages if message.get("type") == "http.response.body"
        )
        response_body = json.loads(response_body_message["body"])
        assert response_body["error"]["correlation_id"] == "test-id-12345"

    @pytest.mark.asyncio
    async def test_non_exceeding_exception_re_raised(self) -> None:
        """
        When the inner application raises an exception for a reason
        other than payload truncation (i.e., ``payload_limit_exceeded``
        is still ``False``), the middleware re-raises the exception
        rather than swallowing it.
        """

        async def inner_app(scope, receive, send):
            raise RuntimeError("Unrelated application error")

        middleware = application.middleware.RequestPayloadSizeLimitMiddleware(
            inner_app,
            maximum_request_payload_bytes=1000,
        )

        scope = self._build_http_scope(content_length=None)
        receive = self._build_receive_returning_chunks([b"small body"])
        sent_messages: list[dict] = []

        async def send(message: dict) -> None:
            sent_messages.append(message)

        with pytest.raises(RuntimeError, match="Unrelated application error"):
            await middleware(scope, receive, send)

    @pytest.mark.asyncio
    async def test_streaming_guard_no_response_when_app_succeeds_after_truncation(
        self,
    ) -> None:
        """
        When the streaming guard truncates the body but the inner
        application does not raise (for example, FastAPI reads partial
        body and returns a validation error), the middleware does not
        attempt to send a second response.

        This is the ``if payload_limit_exceeded: pass`` branch — the
        middleware recognises that the app has already sent a response
        and silently accepts the degraded behaviour.
        """

        async def inner_app(scope, receive, send):
            # Read the truncated body without raising.
            await receive()
            # The inner app sends its own response (e.g. a 400 validation error).
            await send(
                {
                    "type": "http.response.start",
                    "status": 400,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b'{"error": "validation_failed"}',
                }
            )

        middleware = application.middleware.RequestPayloadSizeLimitMiddleware(
            inner_app,
            maximum_request_payload_bytes=50,
        )

        # Send 100 bytes — exceeds the 50-byte limit.
        scope = self._build_http_scope(content_length=None)
        receive = self._build_receive_returning_chunks([b"Z" * 100])
        sent_messages: list[dict] = []

        async def send(message: dict) -> None:
            sent_messages.append(message)

        await middleware(scope, receive, send)

        # The middleware should NOT have sent a second response.
        # Only the inner app's 400 response should be present.
        response_starts = [message for message in sent_messages if message.get("type") == "http.response.start"]
        assert len(response_starts) == 1
        assert response_starts[0]["status"] == 400

    @pytest.mark.asyncio
    async def test_malformed_content_length_header_falls_through_to_streaming_guard(
        self,
    ) -> None:
        """
        When the ``Content-Length`` header contains a non-numeric value
        (for example, ``"abc"`` or an empty string), the module-level
        ``extract_content_length_from_headers`` utility function catches
        the ``ValueError`` and returns ``None``.  The middleware then
        falls through to the streaming accumulation guard rather than
        performing fast-path rejection.

        The body is within the payload limit, so the streaming guard
        does not trigger and the inner application receives the
        full request body.
        """
        inner_app_received_body = bytearray()

        async def inner_app(scope, receive, send):
            while True:
                message = await receive()
                if message["type"] == "http.request":
                    inner_app_received_body.extend(message.get("body", b""))
                    if not message.get("more_body", False):
                        break

            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b'{"status": "ok"}',
                }
            )

        middleware = application.middleware.RequestPayloadSizeLimitMiddleware(
            inner_app,
            maximum_request_payload_bytes=100,
        )

        # Construct a scope with a malformed Content-Length header that
        # cannot be parsed as an integer.  The middleware must treat this
        # as "no Content-Length" and fall through to the streaming guard.
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/upload",
            "headers": [
                (b"content-type", b"application/octet-stream"),
                (b"content-length", b"not-a-number"),
            ],
            "state": {"correlation_id": "test-correlation-id"},
        }
        receive = self._build_receive_returning_chunks([b"x" * 50])
        sent_messages: list[dict] = []

        async def send(message: dict) -> None:
            sent_messages.append(message)

        await middleware(scope, receive, send)

        # The inner app should have received the full 50-byte body
        # (the streaming guard did not trigger because 50 < 100).
        assert len(inner_app_received_body) == 50

        # The response should be 200 (from the inner app), confirming
        # the malformed Content-Length did not cause a rejection.
        assert sent_messages[0]["status"] == 200
