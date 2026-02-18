"""Tests for application/services/image_generation_service.py."""

from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

import application.exceptions
import application.services.image_generation_service


def _create_test_pil_image(width=64, height=64):
    """Create a small test PIL image."""
    return Image.new("RGB", (width, height), color="red")


def _make_service(device_type="cpu"):
    """Create an ImageGenerationService with a mocked pipeline."""
    mock_pipeline = MagicMock()
    mock_device = MagicMock()
    mock_device.type = device_type
    return application.services.image_generation_service.ImageGenerationService(
        pipeline=mock_pipeline,
        device=mock_device,
    )


class TestResolveDevice:

    @patch("application.services.image_generation_service.torch")
    def test_auto_with_cuda(self, mock_torch):
        mock_torch.cuda.is_available.return_value = True
        mock_torch.device.return_value = MagicMock(type="cuda")

        application.services.image_generation_service.ImageGenerationService._resolve_device(
            "auto"
        )

        mock_torch.device.assert_called_with("cuda")

    @patch("application.services.image_generation_service.torch")
    def test_auto_without_cuda(self, mock_torch):
        mock_torch.cuda.is_available.return_value = False
        mock_torch.device.return_value = MagicMock(type="cpu")

        application.services.image_generation_service.ImageGenerationService._resolve_device(
            "auto"
        )

        mock_torch.device.assert_called_with("cpu")

    @patch("application.services.image_generation_service.torch")
    def test_explicit_cpu(self, mock_torch):
        mock_torch.device.return_value = MagicMock(type="cpu")

        application.services.image_generation_service.ImageGenerationService._resolve_device(
            "cpu"
        )

        mock_torch.device.assert_called_with("cpu")

    @patch("application.services.image_generation_service.torch")
    def test_explicit_cuda(self, mock_torch):
        mock_torch.device.return_value = MagicMock(type="cuda")

        application.services.image_generation_service.ImageGenerationService._resolve_device(
            "cuda"
        )

        mock_torch.device.assert_called_with("cuda")


class TestGenerateImages:

    @pytest.mark.asyncio
    async def test_success(self):
        service = _make_service()
        test_image = _create_test_pil_image()
        mock_result = MagicMock()
        mock_result.images = [test_image]
        service._pipeline.return_value = mock_result

        images = await service.generate_images(
            prompt="A cat",
            image_width=512,
            image_height=512,
            number_of_images=1,
        )

        assert len(images) == 1
        assert isinstance(images[0], str)
        # Verify it's valid base64 by decoding
        import base64
        decoded = base64.b64decode(images[0])
        assert len(decoded) > 0

    @pytest.mark.asyncio
    async def test_multiple_images(self):
        service = _make_service()
        test_images = [_create_test_pil_image() for _ in range(2)]
        mock_result = MagicMock()
        mock_result.images = test_images
        service._pipeline.return_value = mock_result

        images = await service.generate_images(
            prompt="A cat",
            image_width=512,
            image_height=512,
            number_of_images=2,
        )

        assert len(images) == 2

    @pytest.mark.asyncio
    async def test_runtime_error(self):
        service = _make_service()
        service._pipeline.side_effect = RuntimeError("GPU out of memory")

        with pytest.raises(
            application.exceptions.ImageGenerationServiceUnavailableError
        ):
            await service.generate_images(
                prompt="A cat",
                image_width=512,
                image_height=512,
                number_of_images=1,
            )

    @pytest.mark.asyncio
    async def test_no_images(self):
        service = _make_service()
        mock_result = MagicMock()
        mock_result.images = []
        service._pipeline.return_value = mock_result

        with pytest.raises(application.exceptions.ImageGenerationError):
            await service.generate_images(
                prompt="A cat",
                image_width=512,
                image_height=512,
                number_of_images=1,
            )


class TestLoadPipeline:

    @patch("application.services.image_generation_service.diffusers")
    @patch("application.services.image_generation_service.torch")
    def test_passes_safety_checker_none(self, mock_torch, mock_diffusers):
        mock_torch.cuda.is_available.return_value = False
        mock_torch.device.return_value = MagicMock(type="cpu")
        mock_torch.float32 = "float32"
        mock_pipeline = MagicMock()
        mock_pipeline.to.return_value = mock_pipeline
        mock_diffusers.StableDiffusionPipeline.from_pretrained.return_value = (
            mock_pipeline
        )

        application.services.image_generation_service.ImageGenerationService.load_pipeline(
            model_id="test-model",
            device_preference="cpu",
        )

        mock_diffusers.StableDiffusionPipeline.from_pretrained.assert_called_once_with(
            "test-model",
            torch_dtype="float32",
            safety_checker=None,
        )


class TestClose:

    @pytest.mark.asyncio
    async def test_close_cpu(self):
        service = _make_service(device_type="cpu")

        with patch(
            "application.services.image_generation_service.torch"
        ) as mock_torch:
            await service.close()
            mock_torch.cuda.empty_cache.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_cuda(self):
        service = _make_service(device_type="cuda")

        with patch(
            "application.services.image_generation_service.torch"
        ) as mock_torch:
            await service.close()
            mock_torch.cuda.empty_cache.assert_called_once()
