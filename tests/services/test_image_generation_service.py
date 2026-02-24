"""Tests for application/services/image_generation_service.py."""

from unittest.mock import MagicMock, patch

import pytest
import structlog
from PIL import Image

import application.exceptions
import application.services.image_generation_service


def _create_test_image(width=64, height=64):
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

        application.services.image_generation_service.ImageGenerationService._resolve_device("auto")

        mock_torch.device.assert_called_with("cuda")

    @patch("application.services.image_generation_service.torch")
    def test_auto_without_cuda(self, mock_torch):
        mock_torch.cuda.is_available.return_value = False
        mock_torch.device.return_value = MagicMock(type="cpu")

        application.services.image_generation_service.ImageGenerationService._resolve_device("auto")

        mock_torch.device.assert_called_with("cpu")

    @patch("application.services.image_generation_service.torch")
    def test_explicit_cpu(self, mock_torch):
        mock_torch.device.return_value = MagicMock(type="cpu")

        application.services.image_generation_service.ImageGenerationService._resolve_device("cpu")

        mock_torch.device.assert_called_with("cpu")

    @patch("application.services.image_generation_service.torch")
    def test_explicit_cuda(self, mock_torch):
        mock_torch.device.return_value = MagicMock(type="cuda")

        application.services.image_generation_service.ImageGenerationService._resolve_device("cuda")

        mock_torch.device.assert_called_with("cuda")


class TestGenerateImages:
    @pytest.mark.asyncio
    async def test_success(self):
        service = _make_service()
        test_image = _create_test_image()
        mock_result = MagicMock()
        mock_result.images = [test_image]
        mock_result.nsfw_content_detected = None
        service._pipeline.return_value = mock_result

        generation_result = await service.generate_images(
            prompt="A cat",
            image_width=512,
            image_height=512,
            number_of_images=1,
        )

        assert len(generation_result.base64_encoded_images) == 1
        assert isinstance(generation_result.base64_encoded_images[0], str)
        assert generation_result.content_safety_flagged_indices == []
        # Verify the output is valid base64 by decoding it
        import base64

        decoded_image_bytes = base64.b64decode(generation_result.base64_encoded_images[0])
        assert len(decoded_image_bytes) > 0

    @pytest.mark.asyncio
    async def test_multiple_images(self):
        service = _make_service()
        test_images = [_create_test_image() for _ in range(2)]
        mock_result = MagicMock()
        mock_result.images = test_images
        mock_result.nsfw_content_detected = None
        service._pipeline.return_value = mock_result

        generation_result = await service.generate_images(
            prompt="A cat",
            image_width=512,
            image_height=512,
            number_of_images=2,
        )

        assert len(generation_result.base64_encoded_images) == 2
        assert generation_result.content_safety_flagged_indices == []

    @pytest.mark.asyncio
    async def test_content_safety_flagged_image_replaced_with_none(self):
        """When the content safety checker flags an image, its base64 data
        is replaced with None and the index appears in content_safety_flagged_indices."""
        service = _make_service()
        test_images = [_create_test_image(), _create_test_image()]
        mock_result = MagicMock()
        mock_result.images = test_images
        mock_result.nsfw_content_detected = [False, True]
        service._pipeline.return_value = mock_result

        generation_result = await service.generate_images(
            prompt="A cat",
            image_width=512,
            image_height=512,
            number_of_images=2,
        )

        assert len(generation_result.base64_encoded_images) == 2
        assert generation_result.base64_encoded_images[0] is not None
        assert generation_result.base64_encoded_images[1] is None
        assert generation_result.content_safety_flagged_indices == [1]

    @pytest.mark.asyncio
    async def test_runtime_error(self):
        service = _make_service()
        service._pipeline.side_effect = RuntimeError("GPU out of memory")

        with pytest.raises(application.exceptions.ImageGenerationServiceUnavailableError):
            await service.generate_images(
                prompt="A cat",
                image_width=512,
                image_height=512,
                number_of_images=1,
            )

    @pytest.mark.asyncio
    async def test_inference_timeout(self):
        service = _make_service()
        # With per-unit base of 0.01s and 512×512×1 the computed timeout is 0.01s
        service._inference_timeout_per_unit_seconds = 0.01

        def slow_inference(*args, **kwargs):
            import time

            time.sleep(1)

        service._pipeline.side_effect = slow_inference

        with pytest.raises(
            application.exceptions.ImageGenerationServiceUnavailableError,
            match="timed out",
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
        mock_result.nsfw_content_detected = None
        service._pipeline.return_value = mock_result

        with pytest.raises(application.exceptions.ImageGenerationError):
            await service.generate_images(
                prompt="A cat",
                image_width=512,
                image_height=512,
                number_of_images=1,
            )

    @pytest.mark.asyncio
    async def test_success_on_cuda_device_invokes_gpu_memory_cleanup(self):
        """
        When image generation succeeds on a CUDA device, the
        ``_cleanup_after_inference`` method must invoke
        ``torch.cuda.empty_cache()`` to release the GPU memory
        allocator's cached blocks back to the device.

        This test exercises the CUDA branch at
        image_generation_service.py line 500 — the ``if
        self._device.type == "cuda": torch.cuda.empty_cache()``
        path inside ``_cleanup_after_inference()``.  The equivalent
        code path in the ``close()`` method is tested separately in
        ``TestClose.test_close_cuda``.
        """
        service = _make_service(device_type="cuda")
        test_image = _create_test_image()
        mock_result = MagicMock()
        mock_result.images = [test_image]
        mock_result.nsfw_content_detected = None
        service._pipeline.return_value = mock_result

        with patch("application.services.image_generation_service.torch") as mock_torch:
            # Ensure the device type check in _cleanup_after_inference
            # evaluates the real device mock (not the patched torch).
            # The service's _device attribute was set by _make_service
            # to a MagicMock with .type = "cuda".
            generation_result = await service.generate_images(
                prompt="A cat",
                image_width=512,
                image_height=512,
                number_of_images=1,
            )

            assert len(generation_result.base64_encoded_images) == 1
            assert isinstance(generation_result.base64_encoded_images[0], str)
            mock_torch.cuda.empty_cache.assert_called()

    @pytest.mark.asyncio
    async def test_image_generation_completed_log_includes_resident_set_size(self):
        """
        The ``image_generation_completed`` log event must include a
        ``number_of_bytes_of_resident_set_size_of_process`` field reporting
        the process resident set size at the time of completion, as required
        by the v5.0.0 specification (§15, Operational Observability,
        Finding A-17).
        """
        service = _make_service()
        test_image = _create_test_image()
        mock_result = MagicMock()
        mock_result.images = [test_image]
        mock_result.nsfw_content_detected = None
        service._pipeline.return_value = mock_result

        with structlog.testing.capture_logs() as captured_log_events:
            await service.generate_images(
                prompt="A cat",
                image_width=512,
                image_height=512,
                number_of_images=1,
            )

        completion_events = [
            event for event in captured_log_events if event.get("event") == "image_generation_completed"
        ]
        assert len(completion_events) == 1
        assert "number_of_bytes_of_resident_set_size_of_process" in completion_events[0]
        assert isinstance(
            completion_events[0]["number_of_bytes_of_resident_set_size_of_process"],
            int,
        )
        assert completion_events[0]["number_of_bytes_of_resident_set_size_of_process"] > 0


class TestRunStartupWarmup:
    """
    Tests for the ``run_startup_warmup`` method, which performs a minimal
    dummy inference during application startup to trigger PyTorch's
    one-time kernel selection and JIT compilation.

    The warmup is a best-effort optimisation: on success, the first user
    request avoids the warmup latency; on failure, the service continues
    normally and the first user request absorbs the cost instead.
    """

    @pytest.mark.asyncio
    async def test_successful_warmup_marks_first_inference_completed(self):
        """
        After a successful warmup, ``_first_inference_completed`` must be
        ``True`` so that the ``generate_images`` method does not re-emit
        the ``first_warmup_of_inference_of_stable_diffusion`` log event on the
        first real user request.
        """
        service = _make_service()
        mock_result = MagicMock()
        mock_result.images = [_create_test_image()]
        service._pipeline.return_value = mock_result

        assert service._first_inference_completed is False

        await service.run_startup_warmup()

        assert service._first_inference_completed is True

    @pytest.mark.asyncio
    async def test_successful_warmup_calls_pipeline_with_minimal_parameters(self):
        """
        The warmup must invoke the pipeline with intentionally minimal
        parameters (1 step, 64×64, 1 image, guidance_scale=1.0) to
        complete as quickly as possible.
        """
        service = _make_service()
        mock_result = MagicMock()
        service._pipeline.return_value = mock_result

        await service.run_startup_warmup()

        service._pipeline.assert_called_once()
        call_kwargs = service._pipeline.call_args
        assert call_kwargs.kwargs["prompt"] == "warmup"
        assert call_kwargs.kwargs["width"] == 64
        assert call_kwargs.kwargs["height"] == 64
        assert call_kwargs.kwargs["num_images_per_prompt"] == 1
        assert call_kwargs.kwargs["num_inference_steps"] == 1
        assert call_kwargs.kwargs["guidance_scale"] == 1.0

    @pytest.mark.asyncio
    async def test_warmup_failure_does_not_raise(self):
        """
        When the warmup inference fails (for example, due to an out-of-memory
        condition or a corrupted model), the method must log a warning and
        return without raising an exception.  The service should continue
        starting up normally.
        """
        service = _make_service()
        service._pipeline.side_effect = RuntimeError("Simulated warmup failure")

        # Must not raise.
        await service.run_startup_warmup()

        # _first_inference_completed should remain False because the
        # warmup did not succeed — the first real user request will
        # absorb the warmup cost instead.
        assert service._first_inference_completed is False

    @pytest.mark.asyncio
    async def test_warmup_failure_still_cleans_up_memory(self):
        """
        Even when the warmup fails, ``_cleanup_after_inference`` must be
        called to release any intermediate tensors that may have been
        allocated before the failure.
        """
        service = _make_service(device_type="cuda")
        service._pipeline.side_effect = RuntimeError("Simulated warmup failure")

        with patch("application.services.image_generation_service.torch") as mock_torch:
            await service.run_startup_warmup()
            # gc.collect() is called inside _cleanup_after_inference,
            # and on CUDA devices, torch.cuda.empty_cache() is also called.
            mock_torch.cuda.empty_cache.assert_called()


class TestLoadPipeline:
    @patch("application.services.image_generation_service.diffusers")
    @patch("application.services.image_generation_service.torch")
    def test_safety_checker_enabled_by_default(self, mock_torch, mock_diffusers):
        mock_torch.cuda.is_available.return_value = False
        mock_torch.device.return_value = MagicMock(type="cpu")
        mock_torch.float32 = "float32"
        mock_pipeline = MagicMock()
        mock_pipeline.to.return_value = mock_pipeline
        mock_diffusers.StableDiffusionPipeline.from_pretrained.return_value = mock_pipeline

        application.services.image_generation_service.ImageGenerationService.load_pipeline(
            model_id="test-model",
            device_preference="cpu",
        )

        mock_diffusers.StableDiffusionPipeline.from_pretrained.assert_called_once_with(
            "test-model",
            torch_dtype="float32",
            revision="main",
        )

    @patch("application.services.image_generation_service.diffusers")
    @patch("application.services.image_generation_service.torch")
    def test_safety_checker_disabled(self, mock_torch, mock_diffusers):
        mock_torch.cuda.is_available.return_value = False
        mock_torch.device.return_value = MagicMock(type="cpu")
        mock_torch.float32 = "float32"
        mock_pipeline = MagicMock()
        mock_pipeline.to.return_value = mock_pipeline
        mock_diffusers.StableDiffusionPipeline.from_pretrained.return_value = mock_pipeline

        application.services.image_generation_service.ImageGenerationService.load_pipeline(
            model_id="test-model",
            device_preference="cpu",
            enable_safety_checker=False,
        )

        mock_diffusers.StableDiffusionPipeline.from_pretrained.assert_called_once_with(
            "test-model",
            torch_dtype="float32",
            revision="main",
            safety_checker=None,
        )

    @patch("application.services.image_generation_service.diffusers")
    @patch("application.services.image_generation_service.torch")
    def test_model_revision_passed_to_from_pretrained(self, mock_torch, mock_diffusers):
        """The ``model_revision`` parameter is forwarded as the ``revision``
        keyword argument to ``StableDiffusionPipeline.from_pretrained()``,
        enabling operators to pin deployments to a specific commit hash
        for reproducible model weights."""
        mock_torch.cuda.is_available.return_value = False
        mock_torch.device.return_value = MagicMock(type="cpu")
        mock_torch.float32 = "float32"
        mock_pipeline = MagicMock()
        mock_pipeline.to.return_value = mock_pipeline
        mock_diffusers.StableDiffusionPipeline.from_pretrained.return_value = mock_pipeline

        application.services.image_generation_service.ImageGenerationService.load_pipeline(
            model_id="test-model",
            model_revision="abc123def456",
            device_preference="cpu",
        )

        mock_diffusers.StableDiffusionPipeline.from_pretrained.assert_called_once_with(
            "test-model",
            torch_dtype="float32",
            revision="abc123def456",
        )


class TestCheckHealth:
    def test_healthy_when_pipeline_loaded(self):
        service = _make_service()
        assert service.check_health() is True

    def test_unhealthy_after_close(self):
        service = _make_service()
        del service._pipeline
        assert service.check_health() is False

    def test_unhealthy_when_pipeline_is_none(self):
        service = _make_service()
        service._pipeline = None
        assert service.check_health() is False


class TestClose:
    @pytest.mark.asyncio
    async def test_close_cpu(self):
        service = _make_service(device_type="cpu")

        with patch("application.services.image_generation_service.torch") as mock_torch:
            await service.close()
            mock_torch.cuda.empty_cache.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_cuda(self):
        service = _make_service(device_type="cuda")

        with patch("application.services.image_generation_service.torch") as mock_torch:
            await service.close()
            mock_torch.cuda.empty_cache.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_twice_is_safe(self):
        service = _make_service(device_type="cpu")

        with patch("application.services.image_generation_service.torch"):
            await service.close()
            await service.close()  # should not raise


class TestComputeTimeout:
    def test_gpu_baseline_image(self):
        service = _make_service(device_type="cuda")
        service._inference_timeout_per_unit_seconds = 60.0
        # 1 image × 512×512 → 60s (no multiplier on GPU)
        assert service._compute_timeout(512, 512, 1) == pytest.approx(60.0)

    def test_gpu_four_baseline_images(self):
        service = _make_service(device_type="cuda")
        service._inference_timeout_per_unit_seconds = 60.0
        # 4 images × 512×512 → 240s
        assert service._compute_timeout(512, 512, 4) == pytest.approx(240.0)

    def test_gpu_double_resolution(self):
        service = _make_service(device_type="cuda")
        service._inference_timeout_per_unit_seconds = 60.0
        # 1 image × 1024×1024 → pixel_scale=4.0 → 240s
        assert service._compute_timeout(1024, 1024, 1) == pytest.approx(240.0)

    def test_gpu_worst_case(self):
        service = _make_service(device_type="cuda")
        service._inference_timeout_per_unit_seconds = 60.0
        # 4 images × 1024×1024 → 960s
        assert service._compute_timeout(1024, 1024, 4) == pytest.approx(960.0)

    def test_cpu_baseline_image(self):
        service = _make_service(device_type="cpu")
        service._inference_timeout_per_unit_seconds = 60.0
        # 1 image × 512×512 × 30 → 1800s
        assert service._compute_timeout(512, 512, 1) == pytest.approx(1800.0)

    def test_cpu_double_resolution(self):
        service = _make_service(device_type="cpu")
        service._inference_timeout_per_unit_seconds = 60.0
        # 1 image × 1024×1024 × 30 → 7200s
        assert service._compute_timeout(1024, 1024, 1) == pytest.approx(7200.0)

    def test_cpu_worst_case(self):
        service = _make_service(device_type="cpu")
        service._inference_timeout_per_unit_seconds = 60.0
        # 4 images × 1024×1024 × 30 → 28800s
        assert service._compute_timeout(1024, 1024, 4) == pytest.approx(28800.0)
