"""
Tests for the in-memory request metrics collector (application/metrics.py).

Validates that the MetricsCollector correctly:

- Returns ISO 8601 UTC timestamps for ``collected_at`` and
  ``service_started_at`` as required by the v5.0.0 specification (FR38).
- Records request counts grouped by method, path, and status code.
- Computes latency statistics (count, minimum, maximum, average, and
  95th percentile) from accumulated observations.
- Enforces bounded observation retention via sliding-window eviction
  to prevent unbounded memory growth (audit finding P-1).
"""

import datetime
import re

import application.metrics

# A regular expression pattern that matches ISO 8601 UTC timestamps with
# microsecond precision and the 'Z' suffix, as required by the v5.0.0
# specification (FR38, Section 11).
#
# Example match: "2026-02-23T14:32:10.123456Z"
_ISO_8601_UTC_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


class TestMetricsCollectorTimestamps:
    """Tests for the temporal metadata fields (FR38, NFR12)."""

    def test_collected_at_is_iso_8601_utc_string(self):
        """The ``collected_at`` field must be an ISO 8601 UTC string with
        microsecond precision and a 'Z' suffix, not a Unix integer
        timestamp (specification FR38, Section 11)."""
        collector = application.metrics.MetricsCollector()
        snapshot = collector.snapshot()

        assert isinstance(snapshot["collected_at"], str)
        assert _ISO_8601_UTC_TIMESTAMP_PATTERN.match(snapshot["collected_at"]), (
            f"collected_at value '{snapshot['collected_at']}' does not match "
            f"the expected ISO 8601 UTC format (YYYY-MM-DDTHH:MM:SS.ffffffZ)"
        )

    def test_service_started_at_is_iso_8601_utc_string(self):
        """The ``service_started_at`` field must be an ISO 8601 UTC string
        with microsecond precision and a 'Z' suffix, not a Unix integer
        timestamp (specification FR38, Section 11)."""
        collector = application.metrics.MetricsCollector()
        snapshot = collector.snapshot()

        assert isinstance(snapshot["service_started_at"], str)
        assert _ISO_8601_UTC_TIMESTAMP_PATTERN.match(snapshot["service_started_at"]), (
            f"service_started_at value '{snapshot['service_started_at']}' does "
            f"not match the expected ISO 8601 UTC format"
        )

    def test_collected_at_reflects_current_time(self):
        """The ``collected_at`` value must be generated at the moment the
        snapshot is taken, not cached from a previous invocation."""
        collector = application.metrics.MetricsCollector()

        time_before_snapshot = datetime.datetime.now(datetime.UTC)
        snapshot = collector.snapshot()
        time_after_snapshot = datetime.datetime.now(datetime.UTC)

        collected_at_timestamp = datetime.datetime.fromisoformat(snapshot["collected_at"].replace("Z", "+00:00"))

        assert time_before_snapshot <= collected_at_timestamp <= time_after_snapshot

    def test_service_started_at_remains_constant_across_snapshots(self):
        """The ``service_started_at`` value must not change between
        successive snapshots — it reflects the moment the collector was
        created, not the moment the snapshot was taken."""
        collector = application.metrics.MetricsCollector()
        first_snapshot = collector.snapshot()
        second_snapshot = collector.snapshot()

        assert first_snapshot["service_started_at"] == second_snapshot["service_started_at"]

    def test_collected_at_in_later_snapshot_is_chronologically_later(self):
        """The ``collected_at`` value in a later snapshot must be
        chronologically later than (or equal to) the value in an earlier
        snapshot, as required by the specification's temporal semantics."""
        collector = application.metrics.MetricsCollector()
        first_snapshot = collector.snapshot()
        second_snapshot = collector.snapshot()

        first_timestamp = datetime.datetime.fromisoformat(first_snapshot["collected_at"].replace("Z", "+00:00"))
        second_timestamp = datetime.datetime.fromisoformat(second_snapshot["collected_at"].replace("Z", "+00:00"))

        assert second_timestamp >= first_timestamp


class TestMetricsCollectorRequestCounts:
    """Tests for request count accumulation."""

    def test_initial_snapshot_has_empty_request_counts(self):
        """A freshly created collector must have no recorded request counts."""
        collector = application.metrics.MetricsCollector()
        snapshot = collector.snapshot()

        assert snapshot["request_counts"] == {}

    def test_records_single_request_count(self):
        """A single recorded request must appear with a count of 1."""
        collector = application.metrics.MetricsCollector()
        collector.record_request("GET", "/health", 200, 5.0)

        snapshot = collector.snapshot()
        assert snapshot["request_counts"]["GET /health 200"] == 1

    def test_accumulates_multiple_requests_for_same_endpoint(self):
        """Multiple requests to the same endpoint with the same status
        code must be accumulated into a single count."""
        collector = application.metrics.MetricsCollector()
        collector.record_request("GET", "/health", 200, 5.0)
        collector.record_request("GET", "/health", 200, 3.0)

        snapshot = collector.snapshot()
        assert snapshot["request_counts"]["GET /health 200"] == 2

    def test_records_different_status_codes_separately(self):
        """Requests to the same endpoint with different status codes must
        be recorded as separate count entries."""
        collector = application.metrics.MetricsCollector()
        collector.record_request("POST", "/v1/prompts/enhance", 200, 10.0)
        collector.record_request("POST", "/v1/prompts/enhance", 400, 1.0)

        snapshot = collector.snapshot()
        assert snapshot["request_counts"]["POST /v1/prompts/enhance 200"] == 1
        assert snapshot["request_counts"]["POST /v1/prompts/enhance 400"] == 1


class TestMetricsCollectorLatencyStatistics:
    """Tests for latency observation recording and statistical computation."""

    def test_initial_snapshot_has_empty_request_latencies(self):
        """A freshly created collector must have no recorded latencies."""
        collector = application.metrics.MetricsCollector()
        snapshot = collector.snapshot()

        assert snapshot["request_latencies"] == {}

    def test_computes_latency_statistics_for_multiple_observations(self):
        """Latency statistics must be correctly computed from multiple
        observations: count, minimum, maximum, average, and 95th percentile."""
        collector = application.metrics.MetricsCollector()
        collector.record_request("GET", "/health", 200, 5.0)
        collector.record_request("GET", "/health", 200, 10.0)
        collector.record_request("GET", "/health", 200, 15.0)

        snapshot = collector.snapshot()
        latency_statistics = snapshot["request_latencies"]["GET /health"]

        assert latency_statistics["count"] == 3
        assert latency_statistics["minimum_milliseconds"] == 5.0
        assert latency_statistics["maximum_milliseconds"] == 15.0
        assert latency_statistics["average_milliseconds"] == 10.0

    def test_single_observation_produces_identical_statistics(self):
        """When only one observation exists, all statistical measures
        (minimum, maximum, average, 95th percentile) must equal that
        single observation value."""
        collector = application.metrics.MetricsCollector()
        collector.record_request("POST", "/v1/images/generations", 200, 42.5)

        snapshot = collector.snapshot()
        latency_statistics = snapshot["request_latencies"]["POST /v1/images/generations"]

        assert latency_statistics["count"] == 1
        assert latency_statistics["minimum_milliseconds"] == 42.5
        assert latency_statistics["maximum_milliseconds"] == 42.5
        assert latency_statistics["ninety_fifth_percentile_milliseconds"] == 42.5

    def test_latency_aggregates_across_status_codes(self):
        """Latency statistics must aggregate across all status codes for
        the same method and path combination, as prescribed by the v5.0.0
        specification."""
        collector = application.metrics.MetricsCollector()
        collector.record_request("POST", "/v1/prompts/enhance", 200, 100.0)
        collector.record_request("POST", "/v1/prompts/enhance", 502, 50.0)

        snapshot = collector.snapshot()
        latency_statistics = snapshot["request_latencies"]["POST /v1/prompts/enhance"]

        assert latency_statistics["count"] == 2
        assert latency_statistics["minimum_milliseconds"] == 50.0
        assert latency_statistics["maximum_milliseconds"] == 100.0
        assert latency_statistics["average_milliseconds"] == 75.0


class TestMetricsCollectorBoundedRetention:
    """Tests for the bounded observation retention mechanism.

    The MetricsCollector enforces a configurable maximum number of latency
    observations per endpoint to prevent unbounded memory growth under
    sustained production load (audit finding P-1).  When the limit is
    reached, the oldest observations are evicted via a sliding-window
    strategy implemented using ``collections.deque(maxlen=...)``.
    """

    def test_evicts_oldest_observations_when_limit_reached(self):
        """When the number of observations exceeds the configured maximum,
        the oldest observations must be evicted so that only the most
        recent observations are retained."""
        maximum_observations = 5
        collector = application.metrics.MetricsCollector(
            maximum_observations_per_endpoint=maximum_observations,
        )

        # Record more observations than the maximum allows.  Observations
        # have values 1.0 through 8.0; after eviction, only 4.0 through
        # 8.0 should remain (the 5 most recent).
        for observation_index in range(8):
            collector.record_request("GET", "/health", 200, float(observation_index + 1))

        snapshot = collector.snapshot()
        latency_statistics = snapshot["request_latencies"]["GET /health"]

        # The oldest 3 observations (1.0, 2.0, 3.0) should have been
        # evicted, leaving observations 4.0, 5.0, 6.0, 7.0, 8.0.
        assert latency_statistics["count"] == maximum_observations
        assert latency_statistics["minimum_milliseconds"] == 4.0
        assert latency_statistics["maximum_milliseconds"] == 8.0

    def test_request_counts_are_not_bounded(self):
        """Request counts must accumulate without eviction, even when
        the latency observation limit is reached.  Counts are simple
        integer counters and do not consume significant memory."""
        maximum_observations = 3
        collector = application.metrics.MetricsCollector(
            maximum_observations_per_endpoint=maximum_observations,
        )

        for _ in range(10):
            collector.record_request("GET", "/health", 200, 5.0)

        snapshot = collector.snapshot()

        # All 10 requests should be counted, even though only the last 3
        # latency observations are retained.
        assert snapshot["request_counts"]["GET /health 200"] == 10

    def test_default_maximum_observations_matches_specification(self):
        """The default maximum observation count must be 10,000, matching
        the v5.0.0 specification's expected evaluation scope."""
        assert application.metrics.DEFAULT_MAXIMUM_OBSERVATIONS_PER_ENDPOINT == 10_000

    def test_separate_endpoints_have_independent_observation_limits(self):
        """Each endpoint must have its own independent observation limit.
        Reaching the limit on one endpoint must not affect observations
        recorded for other endpoints."""
        maximum_observations = 3
        collector = application.metrics.MetricsCollector(
            maximum_observations_per_endpoint=maximum_observations,
        )

        # Fill up the /health endpoint's observation window.
        for observation_index in range(5):
            collector.record_request("GET", "/health", 200, float(observation_index + 1))

        # Record a single observation for a different endpoint.
        collector.record_request("POST", "/v1/prompts/enhance", 200, 100.0)

        snapshot = collector.snapshot()

        # /health should have its oldest observations evicted.
        assert snapshot["request_latencies"]["GET /health"]["count"] == 3

        # /v1/prompts/enhance should be unaffected.
        assert snapshot["request_latencies"]["POST /v1/prompts/enhance"]["count"] == 1
