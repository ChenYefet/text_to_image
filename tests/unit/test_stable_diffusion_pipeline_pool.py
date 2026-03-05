"""Tests for application/integrations/stable_diffusion_pipeline_pool.py."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import application.integrations.stable_diffusion_pipeline_pool


def _create_mock_pipeline(healthy: bool = True) -> MagicMock:
    """Create a mock StableDiffusionPipeline instance."""
    mock = AsyncMock()
    mock.check_health = MagicMock(return_value=healthy)
    mock.close = AsyncMock()
    mock.generate_images = AsyncMock()
    return mock


class TestPoolConstruction:
    def test_pool_size_matches_number_of_instances(self):
        pipelines = [_create_mock_pipeline() for _ in range(3)]
        pool = application.integrations.stable_diffusion_pipeline_pool.StableDiffusionPipelinePool(
            pipeline_instances=pipelines,
        )
        assert pool.number_of_instances == 3

    def test_pool_with_single_instance(self):
        pool = application.integrations.stable_diffusion_pipeline_pool.StableDiffusionPipelinePool(
            pipeline_instances=[_create_mock_pipeline()],
        )
        assert pool.number_of_instances == 1


class TestPoolAcquire:
    @pytest.mark.asyncio
    async def test_acquire_yields_pipeline_instance(self):
        mock_pipeline = _create_mock_pipeline()
        pool = application.integrations.stable_diffusion_pipeline_pool.StableDiffusionPipelinePool(
            pipeline_instances=[mock_pipeline],
        )

        async with pool.acquire() as acquired_pipeline:
            assert acquired_pipeline is mock_pipeline

    @pytest.mark.asyncio
    async def test_acquire_releases_instance_back_to_pool(self):
        mock_pipeline = _create_mock_pipeline()
        pool = application.integrations.stable_diffusion_pipeline_pool.StableDiffusionPipelinePool(
            pipeline_instances=[mock_pipeline],
        )

        async with pool.acquire() as _:
            pass

        # The instance should be available for a second acquire.
        async with pool.acquire() as second_acquired:
            assert second_acquired is mock_pipeline

    @pytest.mark.asyncio
    async def test_acquire_releases_instance_on_exception(self):
        mock_pipeline = _create_mock_pipeline()
        pool = application.integrations.stable_diffusion_pipeline_pool.StableDiffusionPipelinePool(
            pipeline_instances=[mock_pipeline],
        )

        with pytest.raises(RuntimeError, match="test error"):
            async with pool.acquire() as _:
                raise RuntimeError("test error")

        # The instance should still be available after the exception.
        async with pool.acquire() as reacquired:
            assert reacquired is mock_pipeline

    @pytest.mark.asyncio
    async def test_concurrent_acquire_distributes_instances(self):
        """With n=2, two concurrent acquires should each get a different instance."""
        pipeline_a = _create_mock_pipeline()
        pipeline_b = _create_mock_pipeline()
        pool = application.integrations.stable_diffusion_pipeline_pool.StableDiffusionPipelinePool(
            pipeline_instances=[pipeline_a, pipeline_b],
        )

        acquired_instances: list = []
        release_signals = [asyncio.Event(), asyncio.Event()]

        async def acquire_and_hold(index: int) -> None:
            async with pool.acquire() as pipeline:
                acquired_instances.append(pipeline)
                await release_signals[index].wait()

        task_a = asyncio.create_task(acquire_and_hold(0))
        task_b = asyncio.create_task(acquire_and_hold(1))
        await asyncio.sleep(0)  # Let both tasks acquire.

        assert len(acquired_instances) == 2
        assert acquired_instances[0] is not acquired_instances[1]

        release_signals[0].set()
        release_signals[1].set()
        await task_a
        await task_b


class TestPoolCheckHealth:
    def test_healthy_when_all_instances_healthy(self):
        pool = application.integrations.stable_diffusion_pipeline_pool.StableDiffusionPipelinePool(
            pipeline_instances=[_create_mock_pipeline(healthy=True)],
        )
        assert pool.check_health() is True

    def test_unhealthy_when_all_instances_unhealthy(self):
        pool = application.integrations.stable_diffusion_pipeline_pool.StableDiffusionPipelinePool(
            pipeline_instances=[_create_mock_pipeline(healthy=False)],
        )
        assert pool.check_health() is False

    def test_healthy_when_at_least_one_instance_healthy(self):
        pool = application.integrations.stable_diffusion_pipeline_pool.StableDiffusionPipelinePool(
            pipeline_instances=[
                _create_mock_pipeline(healthy=False),
                _create_mock_pipeline(healthy=True),
            ],
        )
        assert pool.check_health() is True


class TestPoolClose:
    @pytest.mark.asyncio
    async def test_close_calls_close_on_all_instances(self):
        pipelines = [_create_mock_pipeline() for _ in range(3)]
        pool = application.integrations.stable_diffusion_pipeline_pool.StableDiffusionPipelinePool(
            pipeline_instances=pipelines,
        )

        await pool.close()

        for pipeline in pipelines:
            pipeline.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_skips_checked_out_instance_without_crashing(self):
        """When a pipeline instance is still acquired (in-flight inference)
        at shutdown time, the pool cannot dequeue it.  The pool must
        gracefully skip the missing instance rather than crashing."""
        pipeline_a = _create_mock_pipeline()
        pipeline_b = _create_mock_pipeline()
        pool = application.integrations.stable_diffusion_pipeline_pool.StableDiffusionPipelinePool(
            pipeline_instances=[pipeline_a, pipeline_b],
        )

        # Acquire one instance without releasing it, simulating an
        # in-flight inference operation during shutdown.
        still_acquired = await pool._queue.get()

        await pool.close()

        # The instance that remained in the queue should have been closed.
        # The checked-out instance should NOT have been closed by the pool.
        assert still_acquired.close.await_count == 0
        # One of the two instances was closed (the one still in the queue).
        total_close_calls = pipeline_a.close.await_count + pipeline_b.close.await_count
        assert total_close_calls == 1
