"""
Tests for application/integrations/llama_cpp_client.py.

Covers all public methods and defensive handling paths:
- Successful prompt enhancement and whitespace stripping.
- Network-level failures: connection error, HTTP status error, timeout.
- Malformed upstream responses and empty completions.
- Streaming response detection (text/event-stream Content-Type → HTTP 502).
- Response body size limit enforcement via streaming reads (oversized body → HTTP 502).
- Token-limit truncation monitoring (finish_reason: "length" → warning log).
- Health check connectivity probing.
- HTTP client lifecycle (close).
"""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import structlog.testing

import application.circuit_breaker
import application.exceptions
import application.integrations.llama_cpp_client


def _build_llama_cpp_client(
    base_url: str = "http://localhost:8080",
    request_timeout_in_seconds: float = 30.0,
    maximum_number_of_bytes_of_response_body: int = 1_048_576,
    circuit_breaker: application.circuit_breaker.CircuitBreaker | None = None,
) -> application.integrations.llama_cpp_client.LlamaCppClient:
    """
    Create a LlamaCppClient instance with configurable parameters.

    The ``maximum_number_of_bytes_of_response_body`` parameter controls the response body size
    limit for testing the oversized-response rejection path.

    The ``circuit_breaker`` parameter allows tests to inject a circuit
    breaker instance for verifying the integration between the service
    and the circuit breaker pattern.
    """
    return application.integrations.llama_cpp_client.LlamaCppClient(
        base_url_of_large_language_model_server=base_url,
        request_timeout_in_seconds=request_timeout_in_seconds,
        maximum_number_of_bytes_of_response_body=maximum_number_of_bytes_of_response_body,
        circuit_breaker=circuit_breaker,
    )


def _build_mock_of_streaming_response(
    body_bytes: bytes,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
    raise_for_status_side_effect: Exception | None = None,
) -> MagicMock:
    """
    Create a mock that behaves as an httpx streaming response context manager.

    The mock provides ``__aenter__``/``__aexit__`` (via the
    ``_mock_stream_context`` helper), ``headers``,
    ``raise_for_status()``, and ``aiter_bytes()`` (yielding the body
    as a single chunk).

    The ``raise_for_status_side_effect`` parameter allows tests to
    simulate HTTP status errors raised inside the stream context.
    """
    if headers is None:
        headers = {"content-type": "application/json"}

    mock_response = MagicMock()
    mock_response.headers = headers
    mock_response.status_code = status_code

    if raise_for_status_side_effect is not None:
        mock_response.raise_for_status.side_effect = raise_for_status_side_effect
    else:
        mock_response.raise_for_status = MagicMock()

    async def _async_iter_bytes():
        yield body_bytes

    mock_response.aiter_bytes = _async_iter_bytes

    return mock_response


def _build_mock_of_json_streaming_response(
    content_text: str,
    status_code: int = 200,
    finish_reason: str = "stop",
    content_type: str = "application/json",
) -> MagicMock:
    """
    Create a mock streaming response with the standard chat-completion shape.

    This is the streaming equivalent of the former ``_build_mock_of_json_response``.
    The response body is serialised to bytes and yielded as a single chunk
    via ``aiter_bytes()``.
    """
    response_body = {
        "choices": [
            {
                "message": {"content": content_text},
                "finish_reason": finish_reason,
            },
        ],
    }

    serialised_body = json.dumps(response_body).encode("utf-8")

    return _build_mock_of_streaming_response(
        body_bytes=serialised_body,
        status_code=status_code,
        headers={"content-type": content_type},
    )


@asynccontextmanager
async def _mock_stream_context(mock_response):
    """
    Async context manager wrapper that yields the mock response.

    Used to replace ``http_client.stream()`` which returns an async
    context manager in production code.
    """
    yield mock_response


def _configure_stream_mock(service, mock_response):
    """
    Configure the service's http_client to return the given mock response
    when ``stream()`` is called as an async context manager.
    """
    service.http_client = AsyncMock()
    service.http_client.stream = MagicMock(
        return_value=_mock_stream_context(mock_response),
    )


def _configure_stream_error(service, error):
    """
    Configure the service's http_client.stream to raise an error when
    entering the async context manager.
    """

    @asynccontextmanager
    async def _error_context(*args, **kwargs):
        raise error
        yield  # pragma: no cover

    service.http_client = AsyncMock()
    service.http_client.stream = MagicMock(side_effect=_error_context)


class TestEnhancePrompt:
    @pytest.mark.asyncio
    async def test_success(self):
        service = _build_llama_cpp_client()
        mock_response = _build_mock_of_json_streaming_response("Enhanced prompt text")
        _configure_stream_mock(service, mock_response)

        result = await service.enhance_prompt("A cat")

        assert result == "Enhanced prompt text"
        service.http_client.stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_strips_whitespace(self):
        service = _build_llama_cpp_client()
        mock_response = _build_mock_of_json_streaming_response("  Enhanced with spaces  ")
        _configure_stream_mock(service, mock_response)

        result = await service.enhance_prompt("A cat")

        assert result == "Enhanced with spaces"

    @pytest.mark.asyncio
    async def test_connection_error(self):
        service = _build_llama_cpp_client()
        _configure_stream_error(service, httpx.ConnectError("Connection refused"))

        with pytest.raises(application.exceptions.LargeLanguageModelServiceUnavailableError):
            await service.enhance_prompt("A cat")

    @pytest.mark.asyncio
    async def test_http_status_error(self):
        service = _build_llama_cpp_client()
        mock_error_response = MagicMock(spec=httpx.Response)
        mock_error_response.status_code = 500
        mock_response = _build_mock_of_streaming_response(
            body_bytes=b"",
            status_code=500,
            raise_for_status_side_effect=httpx.HTTPStatusError(
                "Server error",
                request=MagicMock(),
                response=mock_error_response,
            ),
        )
        _configure_stream_mock(service, mock_response)

        with pytest.raises(application.exceptions.LargeLanguageModelServiceUnavailableError):
            await service.enhance_prompt("A cat")

    @pytest.mark.asyncio
    async def test_timeout(self):
        service = _build_llama_cpp_client()
        _configure_stream_error(service, httpx.TimeoutException("Timed out"))

        with pytest.raises(application.exceptions.LargeLanguageModelServiceUnavailableError):
            await service.enhance_prompt("A cat")

    @pytest.mark.asyncio
    async def test_uncommon_request_error_maps_to_502(self):
        """Uncommon httpx failure modes such as TooManyRedirects must be
        caught by the httpx.RequestError catch-all and mapped to
        LargeLanguageModelServiceUnavailableError (HTTP 502) rather than
        propagating as unhandled 500 errors."""
        service = _build_llama_cpp_client()
        _configure_stream_error(
            service,
            httpx.TooManyRedirects(
                "Exceeded maximum redirects",
                request=MagicMock(),
            ),
        )

        with pytest.raises(
            application.exceptions.LargeLanguageModelServiceUnavailableError,
            match="TooManyRedirects",
        ):
            await service.enhance_prompt("A cat")

    @pytest.mark.asyncio
    async def test_malformed_response(self):
        service = _build_llama_cpp_client()
        malformed_body = {"unexpected": "structure"}
        serialised_malformed_body = json.dumps(malformed_body).encode("utf-8")

        mock_response = _build_mock_of_streaming_response(
            body_bytes=serialised_malformed_body,
        )
        _configure_stream_mock(service, mock_response)

        with pytest.raises(application.exceptions.PromptEnhancementError):
            await service.enhance_prompt("A cat")

    @pytest.mark.asyncio
    async def test_empty_content(self):
        service = _build_llama_cpp_client()
        mock_response = _build_mock_of_json_streaming_response("")
        _configure_stream_mock(service, mock_response)

        with pytest.raises(application.exceptions.PromptEnhancementError):
            await service.enhance_prompt("A cat")

    @pytest.mark.asyncio
    async def test_non_json_response_raises_unavailable_error(self):
        """A non-JSON response body (for example, an HTML error page) must
        be caught and mapped to LargeLanguageModelServiceUnavailableError
        (HTTP 502) rather than propagating as an unhandled ValueError."""
        service = _build_llama_cpp_client()
        html_body = b"<html><body>502 Bad Gateway</body></html>"

        mock_response = _build_mock_of_streaming_response(
            body_bytes=html_body,
            headers={"content-type": "text/html"},
        )
        _configure_stream_mock(service, mock_response)

        with pytest.raises(
            application.exceptions.LargeLanguageModelServiceUnavailableError,
            match="non-JSON response",
        ):
            await service.enhance_prompt("A cat")


class TestStreamingResponseDetection:
    """
    Verify that the service detects and rejects streaming responses from
    the llama.cpp server (spec §15, streaming response defensive handling).

    A misconfigured llama.cpp server may ignore the ``stream: false``
    directive and return a ``text/event-stream`` Content-Type. The service
    must detect this condition and raise ``LargeLanguageModelServiceUnavailableError``
    rather than attempting to parse Server-Sent Events as JSON.
    """

    @pytest.mark.asyncio
    async def test_text_event_stream_content_type_raises_unavailable_error(
        self,
    ) -> None:
        """
        When the upstream returns ``text/event-stream`` despite
        ``stream: false``, the service raises
        ``LargeLanguageModelServiceUnavailableError``.
        """
        service = _build_llama_cpp_client()
        mock_response = _build_mock_of_json_streaming_response(
            "Enhanced text",
            content_type="text/event-stream",
        )
        _configure_stream_mock(service, mock_response)

        with pytest.raises(
            application.exceptions.LargeLanguageModelServiceUnavailableError,
            match="streaming response",
        ):
            await service.enhance_prompt("A cat")

    @pytest.mark.asyncio
    async def test_text_event_stream_with_charset_raises_unavailable_error(
        self,
    ) -> None:
        """
        The detection must match Content-Type values that include
        parameters (e.g., ``text/event-stream; charset=utf-8``).
        """
        service = _build_llama_cpp_client()
        mock_response = _build_mock_of_json_streaming_response(
            "Enhanced text",
            content_type="text/event-stream; charset=utf-8",
        )
        _configure_stream_mock(service, mock_response)

        with pytest.raises(
            application.exceptions.LargeLanguageModelServiceUnavailableError,
        ):
            await service.enhance_prompt("A cat")

    @pytest.mark.asyncio
    async def test_application_json_content_type_does_not_trigger_detection(
        self,
    ) -> None:
        """
        A well-behaved upstream returning ``application/json`` must not
        trigger the streaming response detection path.
        """
        service = _build_llama_cpp_client()
        mock_response = _build_mock_of_json_streaming_response(
            "Enhanced text",
            content_type="application/json",
        )
        _configure_stream_mock(service, mock_response)

        result = await service.enhance_prompt("A cat")

        assert result == "Enhanced text"


class TestResponseBodySizeLimit:
    """
    Verify that the service rejects upstream responses whose body exceeds
    the configured maximum size (spec §15, upstream response size limiting)
    using streaming reads that enforce the limit during receipt.

    An unexpectedly large response from a misconfigured llama.cpp server
    could exhaust memory. The service enforces a configurable ceiling
    (``maximum_number_of_bytes_of_response_body``) via incremental byte
    iteration and raises ``LargeLanguageModelServiceUnavailableError``
    when the ceiling is breached.
    """

    @pytest.mark.asyncio
    async def test_oversized_response_raises_unavailable_error(self) -> None:
        """
        When the upstream response body exceeds ``maximum_number_of_bytes_of_response_body``,
        the service raises ``LargeLanguageModelServiceUnavailableError``.
        """
        # Create a service with a very small response body limit (100 bytes).
        service = _build_llama_cpp_client(maximum_number_of_bytes_of_response_body=100)

        # Create a response whose serialised body exceeds 100 bytes.
        large_content_text = "A" * 200
        mock_response = _build_mock_of_json_streaming_response(large_content_text)
        _configure_stream_mock(service, mock_response)

        with pytest.raises(
            application.exceptions.LargeLanguageModelServiceUnavailableError,
            match="exceeds the configured maximum",
        ):
            await service.enhance_prompt("A cat")

    @pytest.mark.asyncio
    async def test_response_within_limit_succeeds(self) -> None:
        """
        A response body within the configured limit must be accepted
        and parsed normally.
        """
        service = _build_llama_cpp_client(maximum_number_of_bytes_of_response_body=10_000)
        mock_response = _build_mock_of_json_streaming_response("Short enhanced text")
        _configure_stream_mock(service, mock_response)

        result = await service.enhance_prompt("A cat")

        assert result == "Short enhanced text"

    @pytest.mark.asyncio
    async def test_response_exactly_at_limit_succeeds(self) -> None:
        """
        A response body whose size equals exactly ``maximum_number_of_bytes_of_response_body``
        must be accepted — the limit is exclusive (greater than, not
        greater than or equal to).
        """
        response_body = {
            "choices": [
                {
                    "message": {"content": "test content"},
                    "finish_reason": "stop",
                },
            ],
        }
        serialised_body = json.dumps(response_body).encode("utf-8")
        response_body_size = len(serialised_body)

        service = _build_llama_cpp_client(maximum_number_of_bytes_of_response_body=response_body_size)
        mock_response = _build_mock_of_streaming_response(
            body_bytes=serialised_body,
        )
        _configure_stream_mock(service, mock_response)

        result = await service.enhance_prompt("A cat")

        assert result == "test content"

    @pytest.mark.asyncio
    async def test_oversized_response_detected_during_streaming(self) -> None:
        """
        Verify that the size limit is enforced incrementally during
        streaming: the service detects the oversized response during
        byte iteration rather than after buffering the full body.
        Multiple chunks are yielded to simulate realistic streaming.
        """
        service = _build_llama_cpp_client(maximum_number_of_bytes_of_response_body=50)

        chunk_one = b"A" * 30
        chunk_two = b"B" * 30  # Total 60 bytes, exceeding the 50-byte limit.

        mock_response = MagicMock()
        mock_response.headers = {"content-type": "application/json"}
        mock_response.raise_for_status = MagicMock()

        async def _multi_chunk_iter():
            yield chunk_one
            yield chunk_two

        mock_response.aiter_bytes = _multi_chunk_iter
        _configure_stream_mock(service, mock_response)

        with pytest.raises(
            application.exceptions.LargeLanguageModelServiceUnavailableError,
            match="exceeds the configured maximum",
        ):
            await service.enhance_prompt("A cat")


class TestFinishReasonTruncationDetection:
    """
    Verify that the service detects and logs a warning when the llama.cpp
    server returns ``finish_reason: "length"`` (spec §15, token-limit
    truncation monitoring advisory).

    A ``finish_reason`` of ``"length"`` indicates the completion was cut
    short by the ``max_tokens`` ceiling.  The truncated prompt is still
    returned (it may still produce a reasonable image), but a WARNING is
    logged so operators can increase ``max_tokens`` if truncation recurs.
    """

    @pytest.mark.asyncio
    async def test_finish_reason_length_logs_warning(self) -> None:
        """
        When the upstream returns ``finish_reason: "length"``, the
        service logs a WARNING containing ``prompt_enhancement_truncated``.
        """
        service = _build_llama_cpp_client()
        mock_response = _build_mock_of_json_streaming_response(
            "Truncated enhanced prompt text",
            finish_reason="length",
        )
        _configure_stream_mock(service, mock_response)

        with structlog.testing.capture_logs() as captured_log_events:
            result = await service.enhance_prompt("A cat")

        assert result == "Truncated enhanced prompt text"
        truncation_events = [
            event for event in captured_log_events if event.get("event") == "prompt_enhancement_truncated"
        ]
        assert len(truncation_events) == 1

    @pytest.mark.asyncio
    async def test_finish_reason_length_still_returns_prompt(self) -> None:
        """
        The truncated prompt is still returned to the caller — truncation
        is informational, not a hard failure.
        """
        service = _build_llama_cpp_client()
        mock_response = _build_mock_of_json_streaming_response(
            "Truncated but usable prompt",
            finish_reason="length",
        )
        _configure_stream_mock(service, mock_response)

        result = await service.enhance_prompt("A cat")

        assert result == "Truncated but usable prompt"

    @pytest.mark.asyncio
    async def test_finish_reason_stop_does_not_log_warning(self, capsys: pytest.CaptureFixture[str]) -> None:
        """
        A normal ``finish_reason: "stop"`` must not trigger the
        truncation warning.
        """
        service = _build_llama_cpp_client()
        mock_response = _build_mock_of_json_streaming_response(
            "Complete enhanced prompt",
            finish_reason="stop",
        )
        _configure_stream_mock(service, mock_response)

        await service.enhance_prompt("A cat")

        captured_output = capsys.readouterr()
        assert "prompt_enhancement_truncated" not in captured_output.out

    @pytest.mark.asyncio
    async def test_missing_finish_reason_does_not_log_warning(self, capsys: pytest.CaptureFixture[str]) -> None:
        """
        When the response lacks a ``finish_reason`` field entirely, the
        service must not raise or log a truncation warning.
        """
        service = _build_llama_cpp_client()

        # Build a response without any finish_reason field.
        response_body = {
            "choices": [
                {
                    "message": {"content": "Enhanced prompt without finish_reason"},
                },
            ],
        }
        serialised_body = json.dumps(response_body).encode("utf-8")

        mock_response = _build_mock_of_streaming_response(
            body_bytes=serialised_body,
        )
        _configure_stream_mock(service, mock_response)

        result = await service.enhance_prompt("A cat")

        assert result == "Enhanced prompt without finish_reason"
        captured_output = capsys.readouterr()
        assert "prompt_enhancement_truncated" not in captured_output.out

    @pytest.mark.asyncio
    async def test_finish_reason_extraction_survives_corrupted_choices_structure(
        self,
    ) -> None:
        """
        The ``finish_reason`` extraction is wrapped in a defensive
        ``try/except (KeyError, IndexError)`` guard.  This guard
        protects against the unlikely scenario where the ``choices``
        list is accessible during prompt extraction but becomes
        inaccessible during the subsequent ``finish_reason`` lookup.

        This test uses a custom list subclass that empties itself after
        the first index access, simulating a consumable-once data
        structure.  The prompt extraction succeeds on the first access,
        then the ``finish_reason`` extraction encounters an empty list
        and enters the ``except IndexError`` branch.

        The enhanced prompt must still be returned successfully — the
        ``finish_reason`` guard is informational and must never prevent
        a valid prompt from being delivered.
        """

        class SingleAccessList(list):
            """
            A list that clears itself after the first ``__getitem__``
            call, causing subsequent index operations to raise
            ``IndexError``.
            """

            def __init__(self, *args):
                super().__init__(*args)
                self._first_access_completed = False

            def __getitem__(self, index):
                result = super().__getitem__(index)
                if not self._first_access_completed:
                    self._first_access_completed = True
                    self.clear()
                return result

        choices_entry = {
            "message": {"content": "Enhanced prompt from corrupted response"},
            "finish_reason": "stop",
        }

        # The raw bytes use a normal list for valid JSON serialisation.
        serialised_body = json.dumps({"choices": [choices_entry]}).encode("utf-8")

        mock_response = _build_mock_of_streaming_response(
            body_bytes=serialised_body,
        )
        _configure_stream_mock(service := _build_llama_cpp_client(), mock_response)

        # After json.loads produces the dict, we replace the choices
        # list with the SingleAccessList so that the second index
        # access (for finish_reason) raises IndexError.
        import unittest.mock

        original_json_loads = json.loads

        def _patched_json_loads(data, **kwargs):
            result = original_json_loads(data, **kwargs)
            result["choices"] = SingleAccessList([choices_entry])
            return result

        with unittest.mock.patch(
            "application.integrations.llama_cpp_client.json.loads",
            side_effect=_patched_json_loads,
        ):
            result = await service.enhance_prompt("A cat")

        assert result == "Enhanced prompt from corrupted response"


class TestCheckHealth:
    @pytest.mark.asyncio
    async def test_healthy_when_server_returns_2xx(self):
        service = _build_llama_cpp_client()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.is_success = True
        service.http_client = AsyncMock()
        service.http_client.get = AsyncMock(return_value=mock_response)

        assert await service.check_health() is True

    @pytest.mark.asyncio
    async def test_unhealthy_when_server_returns_non_2xx(self):
        service = _build_llama_cpp_client()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.is_success = False
        service.http_client = AsyncMock()
        service.http_client.get = AsyncMock(return_value=mock_response)

        assert await service.check_health() is False

    @pytest.mark.asyncio
    async def test_unhealthy_when_connection_fails(self):
        service = _build_llama_cpp_client()
        service.http_client = AsyncMock()
        service.http_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        assert await service.check_health() is False


class TestCircuitBreakerIntegration:
    """
    Verify the integration between LlamaCppClient and the circuit
    breaker pattern.

    The circuit breaker prevents the service from repeatedly waiting for
    the full timeout duration when the llama.cpp server is consistently
    failing.  These tests verify that:

    - An open circuit causes immediate rejection without contacting upstream.
    - Failures are recorded with the circuit breaker.
    - Successes are recorded with the circuit breaker.
    - When no circuit breaker is configured, the service operates normally.
    """

    @pytest.mark.asyncio
    async def test_open_circuit_rejects_without_calling_upstream(self) -> None:
        """
        When the circuit breaker is open, the service raises
        LargeLanguageModelServiceUnavailableError without sending any HTTP
        request to the upstream server.
        """
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=1,
            timeout_for_recovery_in_seconds=60.0,
            name="test",
        )
        await breaker.record_failure()

        service = _build_llama_cpp_client(circuit_breaker=breaker)
        service.http_client = AsyncMock()

        with pytest.raises(
            application.exceptions.LargeLanguageModelServiceUnavailableError,
            match="circuit breaker",
        ):
            await service.enhance_prompt("A cat")

        # The HTTP client should never have been called.
        service.http_client.stream.assert_not_called()

    @pytest.mark.asyncio
    async def test_success_records_with_circuit_breaker(self) -> None:
        """A successful prompt enhancement resets the circuit breaker failure counter."""
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=5,
            name="test",
        )
        # Simulate some prior failures.
        await breaker.record_failure()
        await breaker.record_failure()

        assert breaker.number_of_consecutive_failures == 2

        service = _build_llama_cpp_client(circuit_breaker=breaker)
        mock_response = _build_mock_of_json_streaming_response("Enhanced prompt text")
        _configure_stream_mock(service, mock_response)

        await service.enhance_prompt("A cat")

        assert breaker.number_of_consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_connection_failure_records_with_circuit_breaker(self) -> None:
        """A connection error increments the circuit breaker failure counter."""
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=5,
            name="test",
        )

        service = _build_llama_cpp_client(circuit_breaker=breaker)
        _configure_stream_error(service, httpx.ConnectError("Connection refused"))

        with pytest.raises(application.exceptions.LargeLanguageModelServiceUnavailableError):
            await service.enhance_prompt("A cat")

        assert breaker.number_of_consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_timeout_failure_records_with_circuit_breaker(self) -> None:
        """A timeout error increments the circuit breaker failure counter."""
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=5,
            name="test",
        )

        service = _build_llama_cpp_client(circuit_breaker=breaker)
        _configure_stream_error(service, httpx.TimeoutException("Timed out"))

        with pytest.raises(application.exceptions.LargeLanguageModelServiceUnavailableError):
            await service.enhance_prompt("A cat")

        assert breaker.number_of_consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_http_5xx_error_records_with_circuit_breaker(self) -> None:
        """An HTTP 5xx status error increments the circuit breaker failure counter."""
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=5,
            name="test",
        )

        service = _build_llama_cpp_client(circuit_breaker=breaker)
        mock_error_response = MagicMock(spec=httpx.Response)
        mock_error_response.status_code = 500
        mock_response = _build_mock_of_streaming_response(
            body_bytes=b"",
            status_code=500,
            raise_for_status_side_effect=httpx.HTTPStatusError(
                "Server error",
                request=MagicMock(),
                response=mock_error_response,
            ),
        )
        _configure_stream_mock(service, mock_response)

        with pytest.raises(application.exceptions.LargeLanguageModelServiceUnavailableError):
            await service.enhance_prompt("A cat")

        assert breaker.number_of_consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_http_4xx_error_does_not_record_with_circuit_breaker(self) -> None:
        """An HTTP 4xx status error must not increment the circuit breaker failure counter."""
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=5,
            name="test",
        )

        service = _build_llama_cpp_client(circuit_breaker=breaker)
        mock_error_response = MagicMock(spec=httpx.Response)
        mock_error_response.status_code = 400
        mock_response = _build_mock_of_streaming_response(
            body_bytes=b"",
            status_code=400,
            raise_for_status_side_effect=httpx.HTTPStatusError(
                "Bad request",
                request=MagicMock(),
                response=mock_error_response,
            ),
        )
        _configure_stream_mock(service, mock_response)

        with pytest.raises(application.exceptions.LargeLanguageModelServiceUnavailableError):
            await service.enhance_prompt("A cat")

        assert breaker.number_of_consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_http_4xx_error_raises_unavailable_error(self) -> None:
        """An HTTP 4xx status error still raises LargeLanguageModelServiceUnavailableError."""
        service = _build_llama_cpp_client()
        mock_error_response = MagicMock(spec=httpx.Response)
        mock_error_response.status_code = 422
        mock_response = _build_mock_of_streaming_response(
            body_bytes=b"",
            status_code=422,
            raise_for_status_side_effect=httpx.HTTPStatusError(
                "Unprocessable entity",
                request=MagicMock(),
                response=mock_error_response,
            ),
        )
        _configure_stream_mock(service, mock_response)

        with pytest.raises(application.exceptions.LargeLanguageModelServiceUnavailableError):
            await service.enhance_prompt("A cat")

    @pytest.mark.asyncio
    async def test_request_error_records_with_circuit_breaker(self) -> None:
        """An uncommon httpx RequestError increments the circuit breaker failure counter."""
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=5,
            name="test",
        )

        service = _build_llama_cpp_client(circuit_breaker=breaker)
        _configure_stream_error(
            service,
            httpx.TooManyRedirects(
                "Too many redirects",
                request=MagicMock(),
            ),
        )

        with pytest.raises(application.exceptions.LargeLanguageModelServiceUnavailableError):
            await service.enhance_prompt("A cat")

        assert breaker.number_of_consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_no_circuit_breaker_operates_normally(self) -> None:
        """When no circuit breaker is configured, the service operates normally."""
        service = _build_llama_cpp_client(circuit_breaker=None)
        mock_response = _build_mock_of_json_streaming_response("Enhanced prompt text")
        _configure_stream_mock(service, mock_response)

        result = await service.enhance_prompt("A cat")

        assert result == "Enhanced prompt text"

    @pytest.mark.asyncio
    async def test_consecutive_failures_open_circuit_then_reject(self) -> None:
        """
        End-to-end test: consecutive failures through the service open the
        circuit, then the next request is rejected immediately.
        """
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=2,
            timeout_for_recovery_in_seconds=60.0,
            name="test",
        )

        service = _build_llama_cpp_client(circuit_breaker=breaker)
        _configure_stream_error(service, httpx.ConnectError("Connection refused"))

        # First two failures should still attempt the upstream call.
        with pytest.raises(application.exceptions.LargeLanguageModelServiceUnavailableError):
            await service.enhance_prompt("A cat")

        # Re-configure because _configure_stream_error creates a new context each call.
        _configure_stream_error(service, httpx.ConnectError("Connection refused"))

        with pytest.raises(application.exceptions.LargeLanguageModelServiceUnavailableError):
            await service.enhance_prompt("A dog")

        assert breaker.state == application.circuit_breaker.CircuitState.OPEN

        # Third request should be rejected by the circuit breaker
        # without calling the upstream.
        service.http_client = AsyncMock()

        with pytest.raises(
            application.exceptions.LargeLanguageModelServiceUnavailableError,
            match="circuit breaker",
        ):
            await service.enhance_prompt("A bird")

        service.http_client.stream.assert_not_called()


class TestClose:
    @pytest.mark.asyncio
    async def test_close_calls_aclose(self):
        service = _build_llama_cpp_client()
        service.http_client = AsyncMock()

        await service.close()

        service.http_client.aclose.assert_awaited_once()
