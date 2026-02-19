"""
Service for communicating with the llama.cpp language model server.

The llama.cpp server must be running in OpenAI-compatible mode, exposing
a POST /v1/chat/completions endpoint. This service sends the user's
original prompt to that endpoint with a system instruction that guides
the model to produce an enhanced, image-generation-optimised prompt.
"""

import httpx
import structlog

import application.exceptions

logger = structlog.get_logger()

PROMPT_ENHANCEMENT_SYSTEM_INSTRUCTION = (
    "You are an expert prompt engineer specialising in text-to-image generation. "
    "Your task is to enhance the user's prompt to produce higher-quality images. "
    "Improve the prompt by adding descriptive details about lighting, composition, "
    "style, colour palette, mood, and artistic technique. "
    "Return ONLY the enhanced prompt text with no preamble, explanation, or formatting. "
    "Do not wrap your response in quotation marks."
)


class LanguageModelService:
    """
    Asynchronous client for the llama.cpp OpenAI-compatible HTTP server.

    This service maintains a persistent ``httpx.AsyncClient`` for connection
    pooling and must be closed explicitly via the ``close`` method when the
    application shuts down.
    """

    def __init__(
        self,
        language_model_server_base_url: str,
        request_timeout_seconds: float,
        temperature: float = 0.7,
        max_tokens: int = 512,
    ) -> None:
        self.language_model_server_base_url = language_model_server_base_url
        self._temperature = temperature
        self._max_tokens = max_tokens
        self.http_client = httpx.AsyncClient(
            base_url=language_model_server_base_url,
            timeout=httpx.Timeout(request_timeout_seconds),
        )

    async def enhance_prompt(self, original_prompt: str) -> str:
        """
        Send a prompt to the language model for enhancement.

        Constructs a chat-completion request with a system instruction
        that guides the model to produce a richer, more descriptive
        prompt suitable for image generation.

        Returns:
            The enhanced prompt text as a string.

        Raises:
            LanguageModelServiceUnavailableError:
                When the llama.cpp server cannot be reached, returns a
                non-success status code, or the request times out.
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
                    "content": PROMPT_ENHANCEMENT_SYSTEM_INSTRUCTION,
                },
                {
                    "role": "user",
                    "content": original_prompt,
                },
            ],
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
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
                "llama_cpp_connection_failed",
                status_code=http_status_error.response.status_code,
            )
            raise application.exceptions.LanguageModelServiceUnavailableError(
                detail=(
                    f"The language model server returned HTTP status "
                    f"{http_status_error.response.status_code}."
                ),
            ) from http_status_error
        except httpx.TimeoutException as timeout_error:
            logger.error(
                "llama_cpp_timeout",
                error=str(timeout_error),
            )
            raise application.exceptions.LanguageModelServiceUnavailableError(
                detail="The request to the language model server timed out.",
            ) from timeout_error

        response_body = http_response.json()

        try:
            enhanced_prompt_text = (
                response_body["choices"][0]["message"]["content"]
            )
        except (KeyError, IndexError) as parsing_error:
            logger.error(
                "llama_cpp_connection_failed",
                error="Unexpected response structure from language model server",
            )
            raise application.exceptions.PromptEnhancementError(
                detail=(
                    "The language model returned an unexpected response "
                    "structure."
                ),
            ) from parsing_error

        if not enhanced_prompt_text or not enhanced_prompt_text.strip():
            raise application.exceptions.PromptEnhancementError(
                detail="The language model returned an empty enhanced prompt.",
            )

        result = enhanced_prompt_text.strip()

        logger.info(
            "prompt_enhancement_completed",
            enhanced_prompt_length=len(result),
        )

        return result

    async def close(self) -> None:
        """Close the underlying HTTP client and release network resources."""
        await self.http_client.aclose()
