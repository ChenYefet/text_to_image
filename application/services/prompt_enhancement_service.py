"""
Service-layer orchestrator for prompt enhancement.

This thin orchestration layer wraps the ``LlamaCppClient`` integration,
providing a service interface for prompt enhancement that the API
endpoints and health checks depend on.  Placing the integration client
behind a service boundary ensures that the API layer never references
the integration layer directly, maintaining the prescribed three-layer
architecture (API → Services → Integrations).
"""

import application.integrations.llama_cpp_client


class PromptEnhancementService:
    """
    Orchestrate prompt enhancement through the llama.cpp integration client.

    This service delegates all operations to the underlying ``LlamaCppClient``
    instance.  It serves as the architectural boundary between the API layer
    (which depends on services) and the integration layer (which communicates
    with external systems).
    """

    def __init__(
        self,
        llama_cpp_client: application.integrations.llama_cpp_client.LlamaCppClient,
    ) -> None:
        """
        Initialise the prompt enhancement service.

        Args:
            llama_cpp_client: The llama.cpp HTTP client instance used
                for all prompt enhancement operations.
        """
        self._llama_cpp_client = llama_cpp_client

    async def enhance_prompt(self, original_prompt: str) -> str:
        """
        Enhance the provided prompt by delegating to the llama.cpp client.

        Args:
            original_prompt: The user-provided text prompt to be enhanced.

        Returns:
            The enhanced prompt text as a string.

        Raises:
            LargeLanguageModelServiceUnavailableError:
                When the llama.cpp server cannot be reached or returns
                an error.
            PromptEnhancementError:
                When the server responds but the response is malformed
                or contains an empty completion.
        """
        return await self._llama_cpp_client.enhance_prompt(
            original_prompt=original_prompt,
        )

    async def check_health(self) -> bool:
        """
        Check whether the llama.cpp server is reachable.

        Delegates to ``LlamaCppClient.check_health()``, which sends a
        ``GET /health`` request to the llama.cpp server with a short
        timeout.

        Returns:
            ``True`` if the server responds with a 2xx status code,
            ``False`` otherwise.
        """
        return await self._llama_cpp_client.check_health()

    async def close(self) -> None:
        """
        Close the underlying HTTP client and release network resources.

        Delegates to ``LlamaCppClient.close()``.
        """
        await self._llama_cpp_client.close()
