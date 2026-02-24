"""
Service for communicating with the llama.cpp language model server.

The llama.cpp server must be running in OpenAI-compatible mode, exposing
a ``POST /v1/chat/completions`` endpoint.  This service sends the user's
original prompt to that endpoint with a system instruction that guides
the model to produce an enhanced, image-generation-optimised prompt.

Defensive handling
------------------
This service implements several defensive measures prescribed by the
v5.0.0 specification (Section 15 — Upstream Communication) to protect
against misconfigured or misbehaving upstream servers:

- The request body includes ``"stream": false`` to explicitly request a
  non-streaming response.
- If the upstream returns a ``text/event-stream`` Content-Type despite
  this setting, the service treats it as a protocol violation and raises
  ``LanguageModelServiceUnavailableError`` (HTTP 502).
- If the upstream response body exceeds the configured maximum size
  (``maximum_response_bytes``), the service raises
  ``LanguageModelServiceUnavailableError`` (HTTP 502) to prevent memory
  exhaustion from unexpectedly large responses.
- If the ``finish_reason`` in the response is ``"length"``, the service
  logs a WARNING indicating the enhanced prompt was truncated by the
  token limit.  The truncated prompt is still forwarded to the caller
  because it may still produce a reasonable image.
"""

import httpx
import structlog

import application.exceptions

logger = structlog.get_logger()

DEFAULT_SYSTEM_PROMPT = (
    "You are an expert at enhancing text-to-image prompts. "
    "Transform the user's simple prompt into a detailed, visually "
    "descriptive prompt. Add artistic style, lighting, composition, "
    "and quality modifiers. Return only the enhanced prompt, nothing else."
)


class LanguageModelService:
    """
    Asynchronous HTTP client for the llama.cpp OpenAI-compatible server.

    This service maintains a persistent ``httpx.AsyncClient`` with a
    configurable connection pool for efficient HTTP communication with
    the llama.cpp server.  The client must be closed explicitly via the
    ``close`` method when the application shuts down to release network
    resources (file descriptors and TCP connections).

    The service is stateless with respect to request processing: each
    call to ``enhance_prompt`` is independent and does not rely on any
    state from previous calls.  This makes the service safe for
    concurrent use from multiple async tasks.
    """

    def __init__(
        self,
        language_model_server_base_url: str,
        request_timeout_seconds: float,
        temperature: float = 0.7,
        maximum_tokens: int = 512,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        connection_pool_size: int = 10,
        maximum_response_bytes: int = 1_048_576,
    ) -> None:
        """
        Initialise the language model service.

        Args:
            language_model_server_base_url: The base URL of the llama.cpp
                server (e.g. ``"http://localhost:8080"``).  The service
                appends ``/v1/chat/completions`` to this URL when sending
                prompt enhancement requests.
            request_timeout_seconds: Maximum time in seconds to wait for
                a response from the llama.cpp server before treating the
                request as failed.
            temperature: Sampling temperature for prompt enhancement.
                Higher values (closer to 2.0) produce more creative and
                varied output; 0.0 produces deterministic output.
            maximum_tokens: Maximum number of tokens the language model
                may generate for an enhanced prompt.  If the model's
                output exceeds this limit, the response is truncated and
                the ``finish_reason`` is set to ``"length"``.
            system_prompt: The system instruction sent to the language
                model on every prompt enhancement request.  Controls the
                enhancement style and output format.
            connection_pool_size: Maximum number of concurrent HTTP
                connections maintained in the ``httpx`` connection pool.
            maximum_response_bytes: Maximum response body size in bytes
                that the service will accept from the llama.cpp server.
                Responses exceeding this limit are treated as upstream
                failures (HTTP 502).
        """
        self.language_model_server_base_url = language_model_server_base_url
        self._temperature = temperature
        self._maximum_tokens = maximum_tokens
        self._system_prompt = system_prompt
        self._maximum_response_bytes = maximum_response_bytes
        self.http_client = httpx.AsyncClient(
            base_url=language_model_server_base_url,
            timeout=httpx.Timeout(request_timeout_seconds),
            limits=httpx.Limits(
                max_connections=connection_pool_size,
                max_keepalive_connections=connection_pool_size,
            ),
        )

    async def enhance_prompt(self, original_prompt: str) -> str:
        """
        Send a prompt to the language model for enhancement.

        Constructs a chat-completion request with a system instruction
        that guides the model to produce a richer, more descriptive
        prompt suitable for image generation.

        The request explicitly includes ``"stream": false`` to prevent
        accidental streaming response handling from the llama.cpp server.

        Args:
            original_prompt: The user-provided text prompt to be enhanced.

        Returns:
            The enhanced prompt text as a string, with leading and
            trailing whitespace stripped.

        Raises:
            LanguageModelServiceUnavailableError:
                When the llama.cpp server cannot be reached, returns a
                non-success HTTP status code, the request times out, the
                response is a streaming response, or the response body
                exceeds the configured maximum size.
            PromptEnhancementError:
                When the server responds but the response body is
                malformed or contains an empty completion.
        """
        logger.info(
            "prompt_enhancement_initiated",
            prompt_length=len(original_prompt),
        )

        chat_completion_request_body = {
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
            http_response = await self.http_client.post(
                "/v1/chat/completions",
                json=chat_completion_request_body,
            )
            http_response.raise_for_status()
        except httpx.ConnectError as connection_error:
            logger.error(
                "llama_cpp_connection_failed",
                error=str(connection_error),
            )
            raise application.exceptions.LanguageModelServiceUnavailableError(
                detail=(
                    "The language model server is not reachable. "
                    "Ensure that llama.cpp is running in OpenAI-compatible mode."
                ),
            ) from connection_error
        except httpx.HTTPStatusError as http_status_error:
            logger.error(
                "llama_cpp_http_error",
                status_code=http_status_error.response.status_code,
            )
            raise application.exceptions.LanguageModelServiceUnavailableError(
                detail=(f"The language model server returned HTTP status {http_status_error.response.status_code}."),
            ) from http_status_error
        except httpx.TimeoutException as timeout_error:
            logger.error(
                "llama_cpp_timeout",
                error=str(timeout_error),
            )
            raise application.exceptions.LanguageModelServiceUnavailableError(
                detail="The request to the language model server timed out.",
            ) from timeout_error
        except httpx.RequestError as request_error:
            # Catch-all for uncommon httpx failure modes such as
            # TooManyRedirects, DecodingError, ProxyError, and
            # UnsupportedProtocol.  These are extremely rare in the
            # llama.cpp deployment scenario (local network, no proxies,
            # no redirects) but mapping them to HTTP 502 is semantically
            # correct rather than letting them propagate to the 500
            # catch-all handler (audit finding P-2).
            logger.error(
                "llama_cpp_request_failed",
                error_type=type(request_error).__name__,
                error=str(request_error),
            )
            raise application.exceptions.LanguageModelServiceUnavailableError(
                detail=(
                    f"An unexpected communication error occurred with the "
                    f"language model server: {type(request_error).__name__}."
                ),
            ) from request_error

        # ── Streaming response detection ──────────────────────────────────
        #
        # A misconfigured llama.cpp server may ignore the "stream": false
        # setting in the request body and return Server-Sent Events
        # (Content-Type: text/event-stream) regardless.  This service
        # does not implement an SSE parser, so a streaming response would
        # cause a JSON parse failure downstream.  Instead, we detect it
        # early by inspecting the Content-Type header and raise a clear
        # error that identifies the root cause.
        upstream_content_type = http_response.headers.get("content-type", "")
        if upstream_content_type.startswith("text/event-stream"):
            logger.error(
                "llama_cpp_unexpected_streaming_response",
                content_type=upstream_content_type,
            )
            raise application.exceptions.LanguageModelServiceUnavailableError(
                detail=(
                    "The language model server returned a streaming response "
                    "despite stream: false being set in the request."
                ),
            )

        # ── Response body size enforcement ────────────────────────────────
        #
        # Enforce a maximum response body size to prevent memory exhaustion
        # from unexpectedly large upstream responses.  The llama.cpp server
        # should produce responses of a few kilobytes at most, but a
        # misconfigured server or proxy could return arbitrarily large
        # bodies.  The default limit is 1 MB.
        response_body_bytes = len(http_response.content)
        if response_body_bytes > self._maximum_response_bytes:
            logger.error(
                "llama_cpp_response_too_large",
                response_bytes=response_body_bytes,
                maximum_bytes=self._maximum_response_bytes,
            )
            raise application.exceptions.LanguageModelServiceUnavailableError(
                detail=(
                    f"The language model response body ({response_body_bytes} bytes) "
                    f"exceeds the configured maximum ({self._maximum_response_bytes} bytes)."
                ),
            )

        response_body = http_response.json()

        # ── Extract the enhanced prompt text ──────────────────────────────
        #
        # The llama.cpp server returns an OpenAI-compatible chat completion
        # response with the enhanced prompt in:
        #   response_body["choices"][0]["message"]["content"]
        #
        # If the response structure does not match this expected layout
        # (e.g. missing keys or empty choices list), we raise a
        # PromptEnhancementError rather than a generic KeyError so the
        # client receives a meaningful 502 error response.
        try:
            enhanced_prompt_text = response_body["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as parsing_error:
            logger.error(
                "llama_cpp_response_parsing_failed",
                error="Unexpected response structure from language model server",
            )
            raise application.exceptions.PromptEnhancementError(
                detail="The language model returned an unexpected response structure.",
            ) from parsing_error

        if not enhanced_prompt_text or not enhanced_prompt_text.strip():
            raise application.exceptions.PromptEnhancementError(
                detail="The language model returned an empty enhanced prompt.",
            )

        result: str = enhanced_prompt_text.strip()

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
                truncated_prompt_length=len(result),
                configured_maximum_tokens=self._maximum_tokens,
            )

        logger.info(
            "prompt_enhancement_completed",
            enhanced_prompt_length=len(result),
        )

        return result

    async def check_health(self) -> bool:
        """
        Ping the llama.cpp server to verify it is reachable.

        Sends a ``GET /health`` request with a short timeout (5 seconds)
        to the llama.cpp server.  Returns ``True`` if the server responds
        with HTTP 200, ``False`` otherwise.  Any HTTP error or connection
        failure is caught and treated as unhealthy.

        This method is called by the readiness probe (``GET /health/ready``)
        to determine whether the language model backend is available.
        """
        try:
            response = await self.http_client.get("/health", timeout=5.0)
            return response.status_code == 200
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
