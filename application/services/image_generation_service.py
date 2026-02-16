"""
Service for communicating with the Stable Diffusion image generation server.

This service integrates with the AUTOMATIC1111 Stable Diffusion Web UI API,
which exposes a POST /sdapi/v1/txt2img endpoint for text-to-image generation.
The server must be started with the ``--api`` flag to enable REST access.
"""

import logging

import httpx

import application.exceptions

logger = logging.getLogger(__name__)


class ImageGenerationService:
    """
    Asynchronous client for the AUTOMATIC1111 Stable Diffusion Web UI API.

    This service maintains a persistent ``httpx.AsyncClient`` for connection
    pooling and must be closed explicitly via the ``close`` method when the
    application shuts down.
    """

    def __init__(
        self,
        stable_diffusion_server_base_url: str,
        request_timeout_seconds: float,
    ) -> None:
        self.stable_diffusion_server_base_url = (
            stable_diffusion_server_base_url
        )
        self.http_client = httpx.AsyncClient(
            base_url=stable_diffusion_server_base_url,
            timeout=httpx.Timeout(request_timeout_seconds),
        )

    async def generate_images(
        self,
        prompt: str,
        image_width: int,
        image_height: int,
        number_of_images: int,
    ) -> list[str]:
        """
        Generate images from a text prompt using Stable Diffusion.

        Sends a text-to-image request to the AUTOMATIC1111 API and returns
        the generated images as base64-encoded PNG strings.

        Returns:
            A list of base64-encoded image strings, one per generated image.

        Raises:
            ImageGenerationServiceUnavailableError:
                When the Stable Diffusion server cannot be reached, returns
                a non-success status code, or the request times out.
            ImageGenerationError:
                When the server responds but the response body contains
                no images.
        """
        text_to_image_request_body = {
            "prompt": prompt,
            "width": image_width,
            "height": image_height,
            "batch_size": number_of_images,
            "steps": 20,
            "cfg_scale": 7.0,
            "sampler_name": "Euler a",
        }

        try:
            http_response = await self.http_client.post(
                "/sdapi/v1/txt2img",
                json=text_to_image_request_body,
            )
            http_response.raise_for_status()
        except httpx.ConnectError as connection_error:
            logger.error(
                "Failed to connect to Stable Diffusion server at %s: %s",
                self.stable_diffusion_server_base_url,
                connection_error,
            )
            raise application.exceptions.ImageGenerationServiceUnavailableError(
                detail=(
                    f"Cannot connect to the Stable Diffusion server at "
                    f"{self.stable_diffusion_server_base_url}. "
                    f"Ensure that the Stable Diffusion Web UI is running "
                    f"with the --api flag."
                ),
            ) from connection_error
        except httpx.HTTPStatusError as http_status_error:
            logger.error(
                "Stable Diffusion server returned HTTP %s: %s",
                http_status_error.response.status_code,
                http_status_error,
            )
            raise application.exceptions.ImageGenerationServiceUnavailableError(
                detail=(
                    f"The Stable Diffusion server returned HTTP status "
                    f"{http_status_error.response.status_code}."
                ),
            ) from http_status_error
        except httpx.TimeoutException as timeout_error:
            logger.error(
                "Request to Stable Diffusion server timed out: %s",
                timeout_error,
            )
            raise application.exceptions.ImageGenerationServiceUnavailableError(
                detail=(
                    "The request to the Stable Diffusion server timed out."
                ),
            ) from timeout_error

        response_body = http_response.json()

        base64_encoded_images = response_body.get("images", [])

        if not base64_encoded_images:
            raise application.exceptions.ImageGenerationError(
                detail=(
                    "The Stable Diffusion server returned no images in "
                    "its response."
                ),
            )

        return base64_encoded_images

    async def close(self) -> None:
        """Close the underlying HTTP client and release network resources."""
        await self.http_client.aclose()
