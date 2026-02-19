"""Tests for application/metrics.py."""

import application.metrics


class TestMetricsCollector:

    def test_initial_snapshot_is_empty(self):
        collector = application.metrics.MetricsCollector()
        snapshot = collector.snapshot()

        assert snapshot["request_counts"] == {}
        assert snapshot["request_latencies"] == {}

    def test_records_request_count(self):
        collector = application.metrics.MetricsCollector()
        collector.record_request("GET", "/health", 200, 5.0)
        collector.record_request("GET", "/health", 200, 3.0)

        snapshot = collector.snapshot()
        assert snapshot["request_counts"]["GET /health 200"] == 2

    def test_records_different_status_codes_separately(self):
        collector = application.metrics.MetricsCollector()
        collector.record_request("POST", "/v1/prompts/enhance", 200, 10.0)
        collector.record_request("POST", "/v1/prompts/enhance", 400, 1.0)

        snapshot = collector.snapshot()
        assert snapshot["request_counts"]["POST /v1/prompts/enhance 200"] == 1
        assert snapshot["request_counts"]["POST /v1/prompts/enhance 400"] == 1

    def test_records_latency_statistics(self):
        collector = application.metrics.MetricsCollector()
        collector.record_request("GET", "/health", 200, 5.0)
        collector.record_request("GET", "/health", 200, 10.0)
        collector.record_request("GET", "/health", 200, 15.0)

        snapshot = collector.snapshot()
        latency = snapshot["request_latencies"]["GET /health"]

        assert latency["count"] == 3
        assert latency["min_ms"] == 5.0
        assert latency["max_ms"] == 15.0
        assert latency["avg_ms"] == 10.0

    def test_single_request_latency(self):
        collector = application.metrics.MetricsCollector()
        collector.record_request("POST", "/v1/images/generations", 200, 42.5)

        snapshot = collector.snapshot()
        latency = snapshot["request_latencies"]["POST /v1/images/generations"]

        assert latency["count"] == 1
        assert latency["min_ms"] == 42.5
        assert latency["max_ms"] == 42.5
        assert latency["p95_ms"] == 42.5
