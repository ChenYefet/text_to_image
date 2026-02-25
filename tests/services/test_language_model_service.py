"""
Tests for application/services/language_model_service.py.

Covers all public methods and defensive handling paths:
- Successful prompt enhancement and whitespace stripping.
- Network-level failures: connection error, HTTP status error, timeout.
- Malformed upstream responses and empty completions.
- Streaming response detection (text/event-stream Content-Type → HTTP 502).
- Response body size limit enforcement (oversized body → HTTP 502).
- Token-limit truncation monitoring (finish_reason: "length" → warning log).
- Health check connectivity probing.
- HTTP client lifecycle (close).
"""

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import application.circuit_breaker
import application.exceptions
import application.services.language_model_service


def _make_service(
    base_url: str = "http://localhost:8080",
    timeout: float = 30.0,
    maximum_response_bytes: int = 1_048_576,
    circuit_breaker: application.circuit_breaker.CircuitBreaker | None = None,
) -> application.services.language_model_service.LanguageModelService:
    """
    Create a LanguageModelService instance with configurable parameters.

    The ``maximum_response_bytes`` parameter controls the response body size
    limit for testing the oversized-response rejection path.

    The ``circuit_breaker`` parameter allows tests to inject a circuit
    breaker instance for verifying the integration between the service
    and the circuit breaker pattern.
    """
    return application.services.language_model_service.LanguageModelService(
        language_model_server_base_url=base_url,
        request_timeout_seconds=timeout,
        maximum_response_bytes=maximum_response_bytes,
        circuit_breaker=circuit_breaker,
    )


def _mock_json_response(
    content_text: str,
    status_code: int = 200,
    finish_reason: str = "stop",
    content_type: str = "application/json",
) -> MagicMock:
    """
    Create a mock httpx.Response with the standard chat-completion shape.

    Includes the ``headers`` and ``content`` attributes that the
    LanguageModelService inspects for streaming response detection (checking
    Content-Type for ``text/event-stream``) and response body size
    enforcement (checking ``len(response.content)``).

    The ``content_type`` parameter allows tests to simulate misconfigured
    upstream servers that return ``text/event-stream`` despite the
    ``stream: false`` directive.
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

    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = response_body
    response.raise_for_status = MagicMock()
    response.headers = {"content-type": content_type}
    response.content = serialised_body
    return response


class TestEnhancePrompt:
    @pytest.mark.asyncio
    async def test_success(self):
        service = _make_service()
        mock_response = _mock_json_response("Enhanced prompt text")
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(return_value=mock_response)

        result = await service.enhance_prompt("A cat")

        assert result == "Enhanced prompt text"
        service.http_client.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_strips_whitespace(self):
        service = _make_service()
        mock_response = _mock_json_response("  Enhanced with spaces  ")
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(return_value=mock_response)

        result = await service.enhance_prompt("A cat")

        assert result == "Enhanced with spaces"

    @pytest.mark.asyncio
    async def test_connection_error(self):
        service = _make_service()
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        with pytest.raises(application.exceptions.LanguageModelServiceUnavailableError):
            await service.enhance_prompt("A cat")

    @pytest.mark.asyncio
    async def test_http_status_error(self):
        service = _make_service()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Server error",
                request=MagicMock(),
                response=mock_response,
            )
        )

        with pytest.raises(application.exceptions.LanguageModelServiceUnavailableError):
            await service.enhance_prompt("A cat")

    @pytest.mark.asyncio
    async def test_timeout(self):
        service = _make_service()
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(side_effect=httpx.TimeoutException("Timed out"))

        with pytest.raises(application.exceptions.LanguageModelServiceUnavailableError):
            await service.enhance_prompt("A cat")

    @pytest.mark.asyncio
    async def test_uncommon_request_error_maps_to_502(self):
        """Uncommon httpx failure modes such as TooManyRedirects must be
        caught by the httpx.RequestError catch-all and mapped to
        LanguageModelServiceUnavailableError (HTTP 502) rather than
        propagating as unhandled 500 errors (audit finding P-2)."""
        service = _make_service()
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(
            side_effect=httpx.TooManyRedirects(
                "Exceeded maximum redirects",
                request=MagicMock(),
            )
        )

        with pytest.raises(application.exceptions.LanguageModelServiceUnavailableError, match="TooManyRedirects"):
            await service.enhance_prompt("A cat")

    @pytest.mark.asyncio
    async def test_malformed_response(self):
        service = _make_service()
        malformed_body = {"unexpected": "structure"}
        import json

        serialised_malformed_body = json.dumps(malformed_body).encode("utf-8")

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = malformed_body
        mock_response.headers = {"content-type": "application/json"}
        mock_response.content = serialised_malformed_body
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(application.exceptions.PromptEnhancementError):
            await service.enhance_prompt("A cat")

    @pytest.mark.asyncio
    async def test_empty_content(self):
        service = _make_service()
        mock_response = _mock_json_response("")
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(application.exceptions.PromptEnhancementError):
            await service.enhance_prompt("A cat")


class TestStreamingResponseDetection:
    """
    Verify that the service detects and rejects streaming responses from
    the llama.cpp server (spec §15, streaming response defensive handling).

    A misconfigured llama.cpp server may ignore the ``stream: false``
    directive and return a ``text/event-stream`` Content-Type. The service
    must detect this condition and raise ``LanguageModelServiceUnavailableError``
    rather than attempting to parse Server-Sent Events as JSON.
    """

    @pytest.mark.asyncio
    async def test_text_event_stream_content_type_raises_unavailable_error(self) -> None:
        """
        When the upstream returns ``text/event-stream`` despite
        ``stream: false``, the service raises
        ``LanguageModelServiceUnavailableError``.
        """
        service = _make_service()
        mock_response = _mock_json_response(
            "Enhanced text",
            content_type="text/event-stream",
        )
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(
            application.exceptions.LanguageModelServiceUnavailableError,
            match="streaming response",
        ):
            await service.enhance_prompt("A cat")

    @pytest.mark.asyncio
    async def test_text_event_stream_with_charset_raises_unavailable_error(self) -> None:
        """
        The detection must match Content-Type values that include
        parameters (e.g., ``text/event-stream; charset=utf-8``).
        """
        service = _make_service()
        mock_response = _mock_json_response(
            "Enhanced text",
            content_type="text/event-stream; charset=utf-8",
        )
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(
            application.exceptions.LanguageModelServiceUnavailableError,
        ):
            await service.enhance_prompt("A cat")

    @pytest.mark.asyncio
    async def test_application_json_content_type_does_not_trigger_detection(self) -> None:
        """
        A well-behaved upstream returning ``application/json`` must not
        trigger the streaming response detection path.
        """
        service = _make_service()
        mock_response = _mock_json_response(
            "Enhanced text",
            content_type="application/json",
        )
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(return_value=mock_response)

        result = await service.enhance_prompt("A cat")

        assert result == "Enhanced text"


class TestResponseBodySizeLimit:
    """
    Verify that the service rejects upstream responses whose body exceeds
    the configured maximum size (spec §15, upstream response size limiting).

    An unexpectedly large response from a misconfigured llama.cpp server
    could exhaust memory. The service enforces a configurable ceiling
    (``maximum_response_bytes``) and raises
    ``LanguageModelServiceUnavailableError`` when the ceiling is breached.
    """

    @pytest.mark.asyncio
    async def test_oversized_response_raises_unavailable_error(self) -> None:
        """
        When the upstream response body exceeds ``maximum_response_bytes``,
        the service raises ``LanguageModelServiceUnavailableError``.
        """
        # Create a service with a very small response body limit (100 bytes).
        service = _make_service(maximum_response_bytes=100)

        # Create a response whose serialised body exceeds 100 bytes.
        large_content_text = "A" * 200
        mock_response = _mock_json_response(large_content_text)
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(
            application.exceptions.LanguageModelServiceUnavailableError,
            match="exceeds the configured maximum",
        ):
            await service.enhance_prompt("A cat")

    @pytest.mark.asyncio
    async def test_response_within_limit_succeeds(self) -> None:
        """
        A response body within the configured limit must be accepted
        and parsed normally.
        """
        service = _make_service(maximum_response_bytes=10_000)
        mock_response = _mock_json_response("Short enhanced text")
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(return_value=mock_response)

        result = await service.enhance_prompt("A cat")

        assert result == "Short enhanced text"

    @pytest.mark.asyncio
    async def test_response_exactly_at_limit_succeeds(self) -> None:
        """
        A response body whose size equals exactly ``maximum_response_bytes``
        must be accepted — the limit is exclusive (greater than, not
        greater than or equal to).
        """
        mock_response = _mock_json_response("test content")
        response_body_size = len(mock_response.content)

        service = _make_service(maximum_response_bytes=response_body_size)
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(return_value=mock_response)

        result = await service.enhance_prompt("A cat")

        assert result == "test content"


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
    async def test_finish_reason_length_logs_warning(self, capsys: pytest.CaptureFixture[str]) -> None:
        """
        When the upstream returns ``finish_reason: "length"``, the
        service logs a WARNING containing ``prompt_enhancement_truncated``.

        Note: structlog in the test environment writes to stdout rather
        than through the standard ``caplog`` mechanism, so we capture
        the stdout stream directly via ``capsys``.
        """
        service = _make_service()
        mock_response = _mock_json_response(
            "Truncated enhanced prompt text",
            finish_reason="length",
        )
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(return_value=mock_response)

        result = await service.enhance_prompt("A cat")

        assert result == "Truncated enhanced prompt text"
        captured_output = capsys.readouterr()
        assert "prompt_enhancement_truncated" in captured_output.out

    @pytest.mark.asyncio
    async def test_finish_reason_length_still_returns_prompt(self) -> None:
        """
        The truncated prompt is still returned to the caller — truncation
        is informational, not a hard failure.
        """
        service = _make_service()
        mock_response = _mock_json_response(
            "Truncated but usable prompt",
            finish_reason="length",
        )
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(return_value=mock_response)

        result = await service.enhance_prompt("A cat")

        assert result == "Truncated but usable prompt"

    @pytest.mark.asyncio
    async def test_finish_reason_stop_does_not_log_warning(self, capsys: pytest.CaptureFixture[str]) -> None:
        """
        A normal ``finish_reason: "stop"`` must not trigger the
        truncation warning.
        """
        service = _make_service()
        mock_response = _mock_json_response(
            "Complete enhanced prompt",
            finish_reason="stop",
        )
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(return_value=mock_response)

        await service.enhance_prompt("A cat")

        captured_output = capsys.readouterr()
        assert "prompt_enhancement_truncated" not in captured_output.out

    @pytest.mark.asyncio
    async def test_missing_finish_reason_does_not_log_warning(self, capsys: pytest.CaptureFixture[str]) -> None:
        """
        When the response lacks a ``finish_reason`` field entirely, the
        service must not raise or log a truncation warning.
        """
        service = _make_service()

        # Build a response without any finish_reason field.
        response_body = {
            "choices": [
                {
                    "message": {"content": "Enhanced prompt without finish_reason"},
                },
            ],
        }
        serialised_body = json.dumps(response_body).encode("utf-8")

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = response_body
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {"content-type": "application/json"}
        mock_response.content = serialised_body

        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(return_value=mock_response)

        result = await service.enhance_prompt("A cat")

        assert result == "Enhanced prompt without finish_reason"
        captured_output = capsys.readouterr()
        assert "prompt_enhancement_truncated" not in captured_output.out

    @pytest.mark.asyncio
    async def test_finish_reason_extraction_survives_corrupted_choices_structure(
        self,
    ) -> None:
        """
        The ``finish_reason`` extraction (language_model_service.py lines
        212–215) is wrapped in a defensive ``try/except (KeyError,
        IndexError)`` guard.  This guard protects against the unlikely
        scenario where the ``choices`` list is accessible during prompt
        extraction (line 190) but becomes inaccessible during the
        subsequent ``finish_reason`` lookup (line 213) — for example,
        due to a non-standard JSON-like object returned by an
        intermediary proxy.

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

            This simulates a non-standard response object whose
            ``choices`` array is consumable only once — an extreme edge
            case that the defensive guard protects against.
            """

            def __init__(self, *args):
                super().__init__(*args)
                self._first_access_completed = False

            def __getitem__(self, index):
                result = super().__getitem__(index)
                if not self._first_access_completed:
                    self._first_access_completed = True
                    # Schedule clearing after the first successful access.
                    # The caller (line 190) receives the value normally.
                    # On the next __getitem__ call (line 213), the list
                    # is empty, triggering IndexError.
                    self.clear()
                return result

        choices_entry = {
            "message": {"content": "Enhanced prompt from corrupted response"},
            "finish_reason": "stop",
        }

        response_body = {
            "choices": SingleAccessList([choices_entry]),
        }
        serialised_body = json.dumps({"choices": [choices_entry]}).encode("utf-8")

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = response_body
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {"content-type": "application/json"}
        mock_response.content = serialised_body

        service = _make_service()
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(return_value=mock_response)

        result = await service.enhance_prompt("A cat")

        # The enhanced prompt must still be returned — the finish_reason
        # guard is purely informational and must not block delivery.
        assert result == "Enhanced prompt from corrupted response"


class TestCheckHealth:
    @pytest.mark.asyncio
    async def test_healthy_when_server_returns_200(self):
        service = _make_service()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        service.http_client = AsyncMock()
        service.http_client.get = AsyncMock(return_value=mock_response)

        assert await service.check_health() is True

    @pytest.mark.asyncio
    async def test_unhealthy_when_server_returns_500(self):
        service = _make_service()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500
        service.http_client = AsyncMock()
        service.http_client.get = AsyncMock(return_value=mock_response)

        assert await service.check_health() is False

    @pytest.mark.asyncio
    async def test_unhealthy_when_connection_fails(self):
        service = _make_service()
        service.http_client = AsyncMock()
        service.http_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        assert await service.check_health() is False


class TestCircuitBreakerIntegration:
    """
    Verify the integration between LanguageModelService and the circuit
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
        LanguageModelServiceUnavailableError without sending any HTTP
        request to the upstream server.
        """
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=1,
            recovery_timeout_seconds=60.0,
            name="test",
        )
        await breaker.record_failure()

        service = _make_service(circuit_breaker=breaker)
        service.http_client = AsyncMock()

        with pytest.raises(
            application.exceptions.LanguageModelServiceUnavailableError,
            match="circuit breaker",
        ):
            await service.enhance_prompt("A cat")

        # The HTTP client should never have been called.
        service.http_client.post.assert_not_awaited()

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

        assert breaker.consecutive_failure_count == 2

        service = _make_service(circuit_breaker=breaker)
        mock_response = _mock_json_response("Enhanced prompt text")
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(return_value=mock_response)

        await service.enhance_prompt("A cat")

        assert breaker.consecutive_failure_count == 0

    @pytest.mark.asyncio
    async def test_connection_failure_records_with_circuit_breaker(self) -> None:
        """A connection error increments the circuit breaker failure counter."""
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=5,
            name="test",
        )

        service = _make_service(circuit_breaker=breaker)
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused"),
        )

        with pytest.raises(application.exceptions.LanguageModelServiceUnavailableError):
            await service.enhance_prompt("A cat")

        assert breaker.consecutive_failure_count == 1

    @pytest.mark.asyncio
    async def test_timeout_failure_records_with_circuit_breaker(self) -> None:
        """A timeout error increments the circuit breaker failure counter."""
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=5,
            name="test",
        )

        service = _make_service(circuit_breaker=breaker)
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(
            side_effect=httpx.TimeoutException("Timed out"),
        )

        with pytest.raises(application.exceptions.LanguageModelServiceUnavailableError):
            await service.enhance_prompt("A cat")

        assert breaker.consecutive_failure_count == 1

    @pytest.mark.asyncio
    async def test_http_error_records_with_circuit_breaker(self) -> None:
        """An HTTP status error increments the circuit breaker failure counter."""
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=5,
            name="test",
        )

        service = _make_service(circuit_breaker=breaker)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Server error",
                request=MagicMock(),
                response=mock_response,
            ),
        )

        with pytest.raises(application.exceptions.LanguageModelServiceUnavailableError):
            await service.enhance_prompt("A cat")

        assert breaker.consecutive_failure_count == 1

    @pytest.mark.asyncio
    async def test_request_error_records_with_circuit_breaker(self) -> None:
        """An uncommon httpx RequestError increments the circuit breaker failure counter."""
        breaker = application.circuit_breaker.CircuitBreaker(
            failure_threshold=5,
            name="test",
        )

        service = _make_service(circuit_breaker=breaker)
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(
            side_effect=httpx.TooManyRedirects(
                "Too many redirects",
                request=MagicMock(),
            ),
        )

        with pytest.raises(application.exceptions.LanguageModelServiceUnavailableError):
            await service.enhance_prompt("A cat")

        assert breaker.consecutive_failure_count == 1

    @pytest.mark.asyncio
    async def test_no_circuit_breaker_operates_normally(self) -> None:
        """When no circuit breaker is configured, the service operates normally."""
        service = _make_service(circuit_breaker=None)
        mock_response = _mock_json_response("Enhanced prompt text")
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(return_value=mock_response)

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
            recovery_timeout_seconds=60.0,
            name="test",
        )

        service = _make_service(circuit_breaker=breaker)
        service.http_client = AsyncMock()
        service.http_client.post = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused"),
        )

        # First two failures should still attempt the upstream call.
        with pytest.raises(application.exceptions.LanguageModelServiceUnavailableError):
            await service.enhance_prompt("A cat")

        with pytest.raises(application.exceptions.LanguageModelServiceUnavailableError):
            await service.enhance_prompt("A dog")

        assert breaker.state == application.circuit_breaker.CircuitState.OPEN

        # Third request should be rejected by the circuit breaker
        # without calling the upstream.
        service.http_client.post.reset_mock()

        with pytest.raises(
            application.exceptions.LanguageModelServiceUnavailableError,
            match="circuit breaker",
        ):
            await service.enhance_prompt("A bird")

        service.http_client.post.assert_not_awaited()


class TestClose:
    @pytest.mark.asyncio
    async def test_close_calls_aclose(self):
        service = _make_service()
        service.http_client = AsyncMock()

        await service.close()

        service.http_client.aclose.assert_awaited_once()
