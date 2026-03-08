"""Tests for the Prometheus metrics instrumentation."""

import prometheus_client
import pytest

import application.prometheus_metrics

# Alias the module for shorter references in this test file, reducing
# line lengths while keeping the fully qualified module path visible
# at the import site.
prometheus = application.prometheus_metrics


class TestPrometheusMetrics:
    @pytest.fixture(autouse=True)
    def fresh_registry(self):
        """
        Replace the module-level registry and instruments with fresh
        instances for each test to ensure isolation.
        """
        original_registry = prometheus.registry_for_prometheus_metrics
        original_counter = prometheus.counter_of_http_requests_received
        original_histogram = prometheus.histogram_of_duration_of_http_requests_in_seconds
        original_circuit_breaker_state = prometheus.state_of_circuit_breaker
        original_total_instances_gauge = (
            prometheus.gauge_of_total_number_of_instances_in_pipeline_pool_of_stable_diffusion
        )
        original_healthy_instances_gauge = (
            prometheus.gauge_of_number_of_healthy_instances_in_pipeline_pool_of_stable_diffusion
        )
        original_in_flight_gauge = prometheus.gauge_of_number_of_http_requests_in_flight
        original_safety_filter_counter = prometheus.counter_of_number_of_generated_images_rejected_by_safety_filter

        test_registry = prometheus_client.CollectorRegistry()
        prometheus.registry_for_prometheus_metrics = test_registry
        prometheus.counter_of_http_requests_received = prometheus_client.Counter(
            "http_requests_received_total",
            "Total number of HTTP requests received by the service",
            ["method", "path", "status_code"],
            registry=test_registry,
        )
        prometheus.histogram_of_duration_of_http_requests_in_seconds = prometheus_client.Histogram(
            "http_request_duration_in_seconds",
            "Duration of HTTP requests in seconds",
            ["method", "path"],
            buckets=(
                0.005,
                0.01,
                0.025,
                0.05,
                0.1,
                0.25,
                0.5,
                1.0,
                2.5,
                5.0,
                10.0,
                30.0,
                60.0,
                90.0,
            ),
            registry=test_registry,
        )
        prometheus.state_of_circuit_breaker = prometheus_client.Enum(
            "circuit_breaker_state",
            "Current state of the circuit breaker",
            ["circuit_name"],
            states=["closed", "half_open", "open"],
            registry=test_registry,
        )
        prometheus.gauge_of_total_number_of_instances_in_pipeline_pool_of_stable_diffusion = prometheus_client.Gauge(
            "stable_diffusion_pipeline_pool_total_number_of_instances",
            "Total number of Stable Diffusion pipeline instances in the pool",
            registry=test_registry,
        )
        prometheus.gauge_of_number_of_healthy_instances_in_pipeline_pool_of_stable_diffusion = prometheus_client.Gauge(
            "stable_diffusion_pipeline_pool_number_of_healthy_instances",
            "Number of healthy Stable Diffusion pipeline instances in the pool",
            registry=test_registry,
        )
        prometheus.gauge_of_number_of_http_requests_in_flight = prometheus_client.Gauge(
            "number_of_http_requests_in_flight",
            "The current number of HTTP requests being processed by the service",
            registry=test_registry,
        )
        prometheus.counter_of_number_of_generated_images_rejected_by_safety_filter = prometheus_client.Counter(
            "number_of_generated_images_rejected_by_safety_filter_total",
            "Total number of generated images rejected by the NSFW safety checker",
            registry=test_registry,
        )

        yield test_registry

        prometheus.registry_for_prometheus_metrics = original_registry
        prometheus.counter_of_http_requests_received = original_counter
        prometheus.histogram_of_duration_of_http_requests_in_seconds = original_histogram
        prometheus.state_of_circuit_breaker = original_circuit_breaker_state
        prometheus.gauge_of_total_number_of_instances_in_pipeline_pool_of_stable_diffusion = (
            original_total_instances_gauge
        )
        prometheus.gauge_of_number_of_healthy_instances_in_pipeline_pool_of_stable_diffusion = (
            original_healthy_instances_gauge
        )
        prometheus.gauge_of_number_of_http_requests_in_flight = original_in_flight_gauge
        prometheus.counter_of_number_of_generated_images_rejected_by_safety_filter = original_safety_filter_counter

    def test_counter_increments(self):
        prometheus.counter_of_http_requests_received.labels(
            method="GET",
            path="/health",
            status_code="200",
        ).inc()

        value = prometheus.counter_of_http_requests_received.labels(
            method="GET",
            path="/health",
            status_code="200",
        )._value.get()
        assert value == 1.0

    def test_histogram_observes(self):
        prometheus.histogram_of_duration_of_http_requests_in_seconds.labels(
            method="GET",
            path="/health",
        ).observe(0.05)

        output = prometheus_client.generate_latest(
            prometheus.registry_for_prometheus_metrics,
        ).decode("utf-8")
        assert "http_request_duration_in_seconds_count" in output
        assert "http_request_duration_in_seconds_bucket" in output

    def test_circuit_breaker_state_enum_reports_active_state(self):
        prometheus.state_of_circuit_breaker.labels(
            circuit_name="test_circuit",
        ).state("open")

        output = prometheus_client.generate_latest(
            prometheus.registry_for_prometheus_metrics,
        ).decode("utf-8")
        assert ('circuit_breaker_state{circuit_breaker_state="open",circuit_name="test_circuit"} 1.0') in output
        assert ('circuit_breaker_state{circuit_breaker_state="closed",circuit_name="test_circuit"} 0.0') in output

    def test_total_instances_gauge_sets_value(self):
        total_gauge = prometheus.gauge_of_total_number_of_instances_in_pipeline_pool_of_stable_diffusion
        total_gauge.set(3)

        assert total_gauge._value.get() == 3.0

    def test_healthy_instances_gauge_sets_value(self):
        healthy_gauge = prometheus.gauge_of_number_of_healthy_instances_in_pipeline_pool_of_stable_diffusion
        healthy_gauge.set(2)

        assert healthy_gauge._value.get() == 2.0

    def test_in_flight_gauge_increments_and_decrements(self):
        gauge = prometheus.gauge_of_number_of_http_requests_in_flight
        gauge.inc()
        assert gauge._value.get() == 1.0

        gauge.inc()
        assert gauge._value.get() == 2.0

        gauge.dec()
        assert gauge._value.get() == 1.0

    def test_safety_filter_counter_increments(self):
        counter = prometheus.counter_of_number_of_generated_images_rejected_by_safety_filter
        counter.inc(3)

        assert counter._value.get() == 3.0

    def test_generate_latest_produces_text(self):
        output = prometheus_client.generate_latest(
            prometheus.registry_for_prometheus_metrics,
        )
        assert isinstance(output, bytes)
