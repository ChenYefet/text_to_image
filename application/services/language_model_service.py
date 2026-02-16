"""
Service for communicating with the llama.cpp language model server.

The llama.cpp server must be running in OpenAI-compatible mode, exposing
a POST /v1/chat/completions endpoint. This service sends the user's
original prompt to that endpoint with a system instruction that guides
the model to produce an enhanced, image-generation-optimised prompt.
"""

import logging

import httpx

import application.exceptions

logger = logging.getLogger(__name__)

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
    ) -> None:
        self.language_model_server_base_url = language_model_server_base_url
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
            "temperature": 0.7,
            "max_tokens": 512,
        }

        try:
            http_response = await self.http_client.post(
                "/v1/chat/completions",
                json=chat_completion_request_body,
            )
            http_response.raise_for_status()
        except httpx.ConnectError as connection_error:
            logger.error(
                "Failed to connect to language model server at %s: %s",
                self.language_model_server_base_url,
                connection_error,
            )
            raise application.exceptions.LanguageModelServiceUnavailableError(
                detail=(
                    f"Cannot connect to the language model server at "
                    f"{self.language_model_server_base_url}. "
                    f"Ensure that llama.cpp is running in OpenAI-compatible mode."
                ),
            ) from connection_error
        except httpx.HTTPStatusError as http_status_error:
            logger.error(
                "Language model server returned HTTP %s: %s",
                http_status_error.response.status_code,
                http_status_error,
            )
            raise application.exceptions.LanguageModelServiceUnavailableError(
                detail=(
                    f"The language model server returned HTTP status "
                    f"{http_status_error.response.status_code}."
                ),
            ) from http_status_error
        except httpx.TimeoutException as timeout_error:
            logger.error(
                "Request to language model server timed out: %s",
                timeout_error,
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
                "Unexpected response structure from language model server: %s",
                response_body,
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

        return enhanced_prompt_text.strip()

    async def close(self) -> None:
        """Close the underlying HTTP client and release network resources."""
        await self.http_client.aclose()
