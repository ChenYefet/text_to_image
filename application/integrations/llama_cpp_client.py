"""
Asynchronous HTTP client (``LlamaCppClient``) for the llama.cpp large
language model server.

The llama.cpp server must be running in OpenAI-compatible mode, exposing
a ``POST /v1/chat/completions`` endpoint.  This client sends the user's
original prompt to that endpoint with a system instruction that guides
the model to produce an enhanced, image-generation-optimised prompt.

Defensive handling
------------------
This client implements several defensive measures prescribed by the
v5.11.0 specification (Section 15 — Upstream Communication) to protect
against misconfigured or misbehaving upstream servers:

- The request body includes ``"stream": false`` to explicitly request a
  non-streaming response.
- If the upstream returns a ``text/event-stream`` Content-Type despite
  this setting, the client treats it as a protocol violation and raises
  ``LargeLanguageModelServiceUnavailableError`` (HTTP 502).
- If the upstream response body exceeds the configured maximum size
  (``maximum_number_of_bytes_of_response_body``), the client raises
  ``LargeLanguageModelServiceUnavailableError`` (HTTP 502) to prevent memory
  exhaustion from unexpectedly large responses.
- If the ``finish_reason`` in the response is ``"length"``, the client
  logs a WARNING indicating the enhanced prompt was truncated by the
  token limit.  The truncated prompt is still forwarded to the caller
  because it may still produce a reasonable image.

Circuit breaker integration
---------------------------
An optional ``CircuitBreaker`` instance (from ``circuit_breaker.py``)
can be provided at construction time to prevent the client from
repeatedly waiting for the full timeout duration when the llama.cpp
server is consistently failing.  When the circuit is open, requests
are rejected immediately with ``LargeLanguageModelServiceUnavailableError``
(HTTP 502) without attempting to contact the upstream server.

When no circuit breaker is provided, the client behaves exactly as
before — every request is sent to the upstream regardless of prior
failure history.
"""

import json

import httpx
import structlog

import application.circuit_breaker
import application.exceptions

logger = structlog.get_logger()

DEFAULT_SYSTEM_PROMPT = (
    "You are an expert at enhancing text-to-image prompts."
    " Transform the user's simple prompt into a detailed, visually descriptive prompt."
    " Add artistic style, lighting, composition, and quality modifiers."
    " Return only the enhanced prompt, nothing else."
)


class LlamaCppClient:
    """
    Asynchronous HTTP client for the llama.cpp OpenAI-compatible server.

    This client maintains a persistent ``httpx.AsyncClient`` with a
    configurable connection pool for efficient HTTP communication with
    the llama.cpp server.  The client must be closed explicitly via the
    ``close`` method when the application shuts down to release network
    resources (file descriptors and TCP connections).

    The client is stateless with respect to request processing: each
    call to ``enhance_prompt`` is independent and does not rely on any
    state from previous calls.  This makes the client safe for
    concurrent use from multiple async tasks.
    """

    def __init__(
        self,
        base_url_of_large_language_model_server: str,
        request_timeout_in_seconds: float,
        temperature: float = 0.7,
        maximum_tokens: int = 512,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        size_of_connection_pool: int = 10,
        maximum_number_of_bytes_of_response_body: int = 1_048_576,
        circuit_breaker: application.circuit_breaker.CircuitBreaker | None = None,
    ) -> None:
        """
        Initialise the llama.cpp client.

        Args:
            base_url_of_large_language_model_server: The base URL of the llama.cpp
                server (e.g. ``"http://localhost:8080"``).  The client
                appends ``/v1/chat/completions`` to this URL when sending
                prompt enhancement requests.
            request_timeout_in_seconds: Maximum time in seconds to wait for
                a response from the llama.cpp server before treating the
                request as failed.
            temperature: Sampling temperature for prompt enhancement.
                Higher values (closer to 2.0) produce more creative and
                varied output; 0.0 produces deterministic output.
            maximum_tokens: Maximum number of tokens the large language model
                may generate for an enhanced prompt.  If the model's
                output exceeds this limit, the response is truncated and
                the ``finish_reason`` is set to ``"length"``.
            system_prompt: The system instruction sent to the language
                model on every prompt enhancement request.  Controls the
                enhancement style and output format.
            size_of_connection_pool: Maximum number of concurrent HTTP
                connections maintained in the ``httpx`` connection pool.
            maximum_number_of_bytes_of_response_body: Maximum response body size in bytes
                that the client will accept from the llama.cpp server.
                Responses exceeding this limit are treated as upstream
                failures (HTTP 502).
            circuit_breaker: An optional ``CircuitBreaker`` instance that
                prevents the client from repeatedly waiting for the full
                timeout duration when the llama.cpp server is consistently
                failing.  When ``None``, every request is sent to the
                upstream regardless of prior failure history.
        """
        self.base_url_of_large_language_model_server = base_url_of_large_language_model_server
        self._temperature = temperature
        self._maximum_tokens = maximum_tokens
        self._system_prompt = system_prompt
        self._maximum_number_of_bytes_of_response_body = maximum_number_of_bytes_of_response_body
        self._circuit_breaker = circuit_breaker
        self.http_client = httpx.AsyncClient(
            base_url=base_url_of_large_language_model_server,
            timeout=httpx.Timeout(request_timeout_in_seconds),
            limits=httpx.Limits(
                max_connections=size_of_connection_pool,
                max_keepalive_connections=size_of_connection_pool,
            ),
        )

    async def enhance_prompt(self, original_prompt: str) -> str:
        """
        Send a prompt to the large language model for enhancement.

        Constructs a chat-completion request with a system instruction
        that guides the model to produce a richer, more descriptive
        prompt suitable for image generation.

        The request explicitly includes ``"stream": false`` to prevent
        accidental streaming response handling from the llama.cpp server.

        When a circuit breaker is configured, this method checks the
        circuit state before attempting the upstream call.  If the
        circuit is open (the upstream has been consistently failing),
        the method raises ``LargeLanguageModelServiceUnavailableError``
        immediately without waiting for the full timeout duration.
        On success, the circuit breaker records a success (potentially
        closing a half-open circuit).  On failure, the circuit breaker
        records a failure (potentially opening the circuit).

        Args:
            original_prompt: The user-provided text prompt to be enhanced.

        Returns:
            The enhanced prompt text as a string, with leading and
            trailing whitespace stripped.

        Raises:
            LargeLanguageModelServiceUnavailableError:
                When the llama.cpp server cannot be reached, returns a
                non-success HTTP status code, the request times out, the
                response is a streaming response, the response body
                exceeds the configured maximum size, or the circuit
                breaker is open.
            PromptEnhancementError:
                When the server responds but the response body is
                malformed or contains an empty completion.
        """
        logger.info(
            "prompt_enhancement_initiated",
            prompt_length=len(original_prompt),
        )

        # ── Circuit breaker check ─────────────────────────────────────
        #
        # When a circuit breaker is configured, check whether the circuit
        # is open before attempting the upstream call.  This prevents the
        # client from repeatedly waiting for the full timeout duration
        # (potentially 120 seconds) when the llama.cpp server is known
        # to be consistently failing.
        if self._circuit_breaker is not None:
            try:
                await self._circuit_breaker.ensure_circuit_is_not_open()
            except application.circuit_breaker.CircuitOpenError as circuit_open_error:
                logger.warning(
                    "llama_cpp_circuit_breaker_rejected",
                    circuit_name=circuit_open_error.circuit_name,
                    remaining_number_of_seconds_until_recovery=round(
                        circuit_open_error.remaining_number_of_seconds_until_recovery,
                        1,
                    ),
                )
                raise application.exceptions.LargeLanguageModelServiceUnavailableError(
                    detail=(
                        "The large language model server has been consistently failing."
                        " The circuit breaker is preventing further requests to avoid"
                        " prolonged timeouts. The client will automatically retry"
                        " after a recovery period."
                    ),
                ) from circuit_open_error

        request_body_for_chat_completion = {
            "messages": [
                {
                    "role": "system",
                    "content": self._system_prompt,
                },
                {
                    "role": "user",
                    "content": original_prompt,
                },
            ],
            "temperature": self._temperature,
            "max_tokens": self._maximum_tokens,
            "stream": False,
        }

        try:
            async with self.http_client.stream(
                "POST",
                "/v1/chat/completions",
                json=request_body_for_chat_completion,
            ) as http_response:
                http_response.raise_for_status()

                # ── Streaming response detection ──────────────────────────
                #
                # A misconfigured llama.cpp server may ignore the
                # "stream": false setting in the request body and return
                # Server-Sent Events (Content-Type: text/event-stream)
                # regardless.  This client does not implement an SSE
                # parser, so a streaming response would cause a JSON parse
                # failure downstream.  Headers are available immediately
                # after the response status line is received.
                upstream_content_type = http_response.headers.get("content-type", "")
                if upstream_content_type.startswith("text/event-stream"):
                    await self._record_circuit_breaker_failure()
                    logger.error(
                        "llama_cpp_unexpected_streaming_response",
                        content_type=upstream_content_type,
                    )
                    raise application.exceptions.LargeLanguageModelServiceUnavailableError(
                        detail=(
                            "The large language model server returned a streaming"
                            " response despite stream: false being set in the"
                            " request."
                        ),
                    )

                # ── Streaming body read with size enforcement ─────────────
                #
                # Read the response body incrementally, checking the
                # accumulated byte count against the configured maximum
                # during receipt.  This ensures that an oversized response
                # is detected and the connection closed as soon as the
                # limit is exceeded, rather than buffering the full body
                # into memory before checking its size.
                chunks_of_response_body: list[bytes] = []
                number_of_bytes_read = 0
                async for chunk in http_response.aiter_bytes():
                    number_of_bytes_read += len(chunk)
                    if number_of_bytes_read > self._maximum_number_of_bytes_of_response_body:
                        await self._record_circuit_breaker_failure()
                        logger.error(
                            "llama_cpp_response_too_large",
                            number_of_bytes_of_response_body=number_of_bytes_read,
                            maximum_number_of_bytes_of_response_body=self._maximum_number_of_bytes_of_response_body,
                        )
                        raise application.exceptions.LargeLanguageModelServiceUnavailableError(
                            detail=(
                                f"The large language model response body"
                                f" ({number_of_bytes_read} bytes) exceeds the"
                                f" configured maximum"
                                f" ({self._maximum_number_of_bytes_of_response_body}"
                                f" bytes)."
                            ),
                        )
                    chunks_of_response_body.append(chunk)

                raw_response_body = b"".join(chunks_of_response_body)

        except httpx.ConnectError as connection_error:
            await self._record_circuit_breaker_failure()
            logger.error(
                "llama_cpp_connection_failed",
                error=str(connection_error),
            )
            raise application.exceptions.LargeLanguageModelServiceUnavailableError(
                detail=(
                    "The large language model server is not reachable."
                    " Ensure that llama.cpp is running in"
                    " OpenAI-compatible mode."
                ),
            ) from connection_error
        except httpx.HTTPStatusError as http_status_error:
            status_code_from_upstream = http_status_error.response.status_code
            if status_code_from_upstream >= 500:
                await self._record_circuit_breaker_failure()
            logger.error(
                "llama_cpp_http_error",
                status_code=status_code_from_upstream,
            )
            raise application.exceptions.LargeLanguageModelServiceUnavailableError(
                detail="The large language model server returned an error response.",
            ) from http_status_error
        except httpx.TimeoutException as timeout_error:
            await self._record_circuit_breaker_failure()
            logger.error(
                "llama_cpp_timeout",
                error=str(timeout_error),
            )
            raise application.exceptions.LargeLanguageModelServiceUnavailableError(
                detail="The request to the large language model server timed out.",
            ) from timeout_error
        except application.exceptions.LargeLanguageModelServiceUnavailableError:
            # Re-raise errors already converted to the application
            # exception type (streaming detection, size enforcement)
            # without wrapping them in the catch-all below.
            raise
        except httpx.RequestError as request_error:
            # Catch-all for uncommon httpx failure modes such as
            # TooManyRedirects, DecodingError, ProxyError, and
            # UnsupportedProtocol.  These are extremely rare in the
            # llama.cpp deployment scenario (local network, no proxies,
            # no redirects) but mapping them to HTTP 502 is semantically
            # correct rather than letting them propagate to the 500
            # catch-all handler.
            await self._record_circuit_breaker_failure()
            logger.error(
                "llama_cpp_request_failed",
                error_type=type(request_error).__name__,
                error=str(request_error),
            )
            raise application.exceptions.LargeLanguageModelServiceUnavailableError(
                detail=(
                    "An unexpected communication error occurred with"
                    " the large language model server:"
                    f" {type(request_error).__name__}."
                ),
            ) from request_error

        # ── Parse JSON from raw bytes ─────────────────────────────────────
        #
        # In streaming mode, response.json() is not available.  Parse the
        # collected bytes directly via json.loads().
        try:
            response_body = json.loads(raw_response_body)
        except (ValueError, UnicodeDecodeError) as json_decode_error:
            await self._record_circuit_breaker_failure()
            logger.error(
                "llama_cpp_response_parsing_failed",
                error="Response body is not valid JSON",
                content_type=upstream_content_type,
            )
            raise application.exceptions.LargeLanguageModelServiceUnavailableError(
                detail="The large language model server returned a non-JSON response.",
            ) from json_decode_error

        # ── Extract the enhanced prompt text ──────────────────────────────
        #
        # The llama.cpp server returns an OpenAI-compatible chat completion
        # response with the enhanced prompt in:
        #   response_body["choices"][0]["message"]["content"]
        #
        # If the response structure does not match this expected layout
        # (e.g. missing keys or empty choices list), we raise a
        # LargeLanguageModelServiceUnavailableError rather than a generic
        # KeyError so the client receives a meaningful 502 error response.
        try:
            enhanced_prompt_text = response_body["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as parsing_error:
            await self._record_circuit_breaker_failure()
            logger.error(
                "llama_cpp_response_parsing_failed",
                error="Unexpected response structure from large language model server",
            )
            raise application.exceptions.PromptEnhancementError(
                detail="The large language model returned an unexpected response structure.",
            ) from parsing_error

        if not enhanced_prompt_text or not enhanced_prompt_text.strip():
            await self._record_circuit_breaker_failure()
            raise application.exceptions.PromptEnhancementError(
                detail="The large language model returned an empty enhanced prompt.",
            )

        cleaned_text_of_enhanced_prompt: str = enhanced_prompt_text.strip()

        # ── Token-limit truncation detection ──────────────────────────────
        #
        # The ``finish_reason`` field in the chat completion response
        # indicates why the model stopped generating tokens:
        #   - "stop": the model completed naturally.
        #   - "length": the model was cut short by the maximum_tokens limit.
        #
        # When the finish_reason is "length", the enhanced prompt is
        # incomplete (truncated).  We still return it because a truncated
        # prompt may still produce a reasonable image, but we log a WARNING
        # so operators can increase maximum_tokens if truncation recurs.
        try:
            finish_reason = response_body["choices"][0].get("finish_reason")
        except (KeyError, IndexError):
            finish_reason = None

        if finish_reason == "length":
            logger.warning(
                "prompt_enhancement_truncated",
                truncated_prompt_length=len(cleaned_text_of_enhanced_prompt),
                configured_maximum_tokens=self._maximum_tokens,
            )

        # Record success with the circuit breaker (if configured) so
        # that a half-open circuit transitions back to closed and the
        # counter of consecutive failures is reset.
        await self._record_circuit_breaker_success()

        logger.info(
            "prompt_enhancement_completed",
            enhanced_prompt_length=len(cleaned_text_of_enhanced_prompt),
        )

        return cleaned_text_of_enhanced_prompt

    async def _record_circuit_breaker_failure(self) -> None:
        """
        Notify the circuit breaker (if configured) of an upstream failure.

        This method is called from every exception handler in
        ``enhance_prompt`` to track consecutive failures and potentially
        open the circuit.
        """
        if self._circuit_breaker is not None:
            await self._circuit_breaker.record_failure()

    async def _record_circuit_breaker_success(self) -> None:
        """
        Notify the circuit breaker (if configured) of an upstream success.

        This method is called after a successful prompt enhancement to
        reset the counter of consecutive failures and potentially close a
        half-open circuit.
        """
        if self._circuit_breaker is not None:
            await self._circuit_breaker.record_success()

    async def check_health(self) -> bool:
        """
        Ping the llama.cpp server to verify it is reachable.

        Sends a ``GET /health`` request with a short timeout (5 seconds)
        to the llama.cpp server.  Returns ``True`` if the server responds
        with a 2xx status code, ``False`` otherwise.  Any HTTP error or
        connection failure is caught and treated as unhealthy.

        This method is called by the readiness probe (``GET /health/ready``)
        to determine whether the large language model backend is available.
        """
        try:
            response = await self.http_client.get("/health", timeout=5.0)
            return response.is_success
        except httpx.HTTPError:
            return False

    async def close(self) -> None:
        """
        Close the underlying HTTP client and release network resources.

        This method must be called during application shutdown to properly
        close all TCP connections in the connection pool and release the
        associated file descriptors.
        """
        await self.http_client.aclose()
