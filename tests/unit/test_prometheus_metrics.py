"""Tests for the Prometheus metrics instrumentation."""

import prometheus_client
import pytest

import application.prometheus_metrics


class TestPrometheusMetrics:
    @pytest.fixture(autouse=True)
    def fresh_registry(self):
        """
        Replace the module-level registry and instruments with fresh
        instances for each test to ensure isolation.
        """
        original_registry = application.prometheus_metrics.registry_for_prometheus_metrics
        original_counter = application.prometheus_metrics.counter_of_http_requests_received
        original_histogram = application.prometheus_metrics.histogram_of_duration_of_http_requests_in_seconds

        test_registry = prometheus_client.CollectorRegistry()
        application.prometheus_metrics.registry_for_prometheus_metrics = test_registry
        application.prometheus_metrics.counter_of_http_requests_received = prometheus_client.Counter(
            "http_requests_received_total",
            "Total number of HTTP requests received by the service",
            ["method", "path", "status_code"],
            registry=test_registry,
        )
        application.prometheus_metrics.histogram_of_duration_of_http_requests_in_seconds = prometheus_client.Histogram(
            "http_request_duration_in_seconds",
            "Duration of HTTP requests in seconds",
            ["method", "path"],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 90.0),
            registry=test_registry,
        )

        yield test_registry

        application.prometheus_metrics.registry_for_prometheus_metrics = original_registry
        application.prometheus_metrics.counter_of_http_requests_received = original_counter
        application.prometheus_metrics.histogram_of_duration_of_http_requests_in_seconds = original_histogram

    def test_counter_increments(self):
        application.prometheus_metrics.counter_of_http_requests_received.labels(
            method="GET", path="/health", status_code="200",
        ).inc()

        value = application.prometheus_metrics.counter_of_http_requests_received.labels(
            method="GET", path="/health", status_code="200",
        )._value.get()
        assert value == 1.0

    def test_histogram_observes(self):
        application.prometheus_metrics.histogram_of_duration_of_http_requests_in_seconds.labels(
            method="GET", path="/health",
        ).observe(0.05)

        output = prometheus_client.generate_latest(
            application.prometheus_metrics.registry_for_prometheus_metrics,
        ).decode("utf-8")
        assert "http_request_duration_in_seconds_count" in output
        assert "http_request_duration_in_seconds_bucket" in output

    def test_generate_latest_produces_text(self):
        output = prometheus_client.generate_latest(
            application.prometheus_metrics.registry_for_prometheus_metrics,
        )
        assert isinstance(output, bytes)
