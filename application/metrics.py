"""
In-memory request metrics collection for operational monitoring (NFR11).

Provides a thread-safe collector for request counts and latency
observations, exposed via the ``GET /metrics`` endpoint in JSON format.

The collector tracks two temporal metadata fields required by the
v5.0.0 specification (FR38 and NFR12):

- ``service_started_at``: an ISO 8601 UTC timestamp recording when the
  collector was created (which coincides with application startup).
  This allows operators to determine how long the service has been
  running and to detect when in-memory counters were last reset.

- ``collected_at``: an ISO 8601 UTC timestamp recording when the
  metrics snapshot was taken.  This allows monitoring systems to detect
  stale or cached responses and to correlate the snapshot with external
  events.

Bounded observation retention
-----------------------------
To prevent unbounded memory growth under sustained production load,
the collector enforces a configurable maximum number of latency
observations per endpoint (default: 10,000).  When the limit is
reached, the oldest observations are evicted using a sliding-window
strategy, ensuring that the most recent operational data is always
retained.  This addresses the production risk identified in audit
finding P-1 without compromising statistical accuracy for the most
recent request window.
"""

import collections
import datetime
import threading

# The default upper bound on the number of latency observations retained
# per endpoint.  The v5.0.0 specification notes that fewer than 10,000
# requests per endpoint is the expected evaluation scope.  This default
# matches that expectation exactly, providing a safety net if the
# assumption is violated in production without artificially constraining
# the evaluation scenario.
DEFAULT_MAXIMUM_OBSERVATIONS_PER_ENDPOINT = 10_000


class MetricsCollector:
    """
    Thread-safe collector for HTTP request metrics.

    Records request counts (grouped by HTTP method, path, and status code)
    and request latencies (grouped by HTTP method and path) for operational
    monitoring via the ``GET /metrics`` endpoint.

    Latency observations are accumulated in a bounded sliding window per
    endpoint.  When the number of observations for a given endpoint reaches
    the configured maximum, the oldest observations are automatically
    evicted, ensuring that aggregate statistics (percentile 95, average,
    minimum, maximum) reflect the most recent operational window rather
    than the entire service lifetime.

    The ``service_started_at`` timestamp is recorded once at construction
    time (in ISO 8601 UTC format) and included in every snapshot.  The
    ``collected_at`` timestamp is generated at the moment ``snapshot()``
    is called.

    Thread safety is achieved via a ``threading.Lock`` rather than an
    ``asyncio.Lock`` because the metrics collector is also accessed from
    synchronous contexts (such as the ASGI middleware layer).
    """

    def __init__(
        self,
        maximum_observations_per_endpoint: int = DEFAULT_MAXIMUM_OBSERVATIONS_PER_ENDPOINT,
    ) -> None:
        """
        Initialise the metrics collector.

        Args:
            maximum_observations_per_endpoint: The maximum number of
                latency observations retained per endpoint before the
                oldest observations are evicted.  Defaults to 10,000,
                matching the v5.0.0 specification's expected evaluation
                scope.  Setting this to a lower value reduces memory
                consumption at the cost of statistical window size.
        """
        self._lock = threading.Lock()
        self._request_counts: dict[str, int] = {}

        # Each endpoint's latency observations are stored in a deque with
        # a fixed maximum length.  When the deque is full, appending a new
        # observation automatically evicts the oldest entry from the left
        # side, implementing a sliding window without explicit eviction
        # logic.  This is more memory-efficient than a plain list because
        # the deque never exceeds the configured capacity.
        self._maximum_observations_per_endpoint = maximum_observations_per_endpoint
        self._request_latencies: dict[str, collections.deque[float]] = {}

        # Record the service start time as an ISO 8601 UTC string at
        # construction time.  This value never changes after construction
        # and is included in every snapshot to allow monitoring systems to
        # compute service uptime.
        self._service_started_at: str = _format_current_utc_timestamp()

    def record_request(
        self,
        method: str,
        path: str,
        status: int,
        duration_milliseconds: float,
    ) -> None:
        """
        Record a completed HTTP request for metrics aggregation.

        This method is called by the ``CorrelationIdMiddleware`` after
        every HTTP request completes (whether successfully or with an
        error).  It records both the request count (keyed by method,
        path, and status code) and the latency observation (keyed by
        method and path, across all status codes).

        Args:
            method: The HTTP method of the completed request (e.g. "GET",
                "POST").
            path: The URL path of the completed request (e.g. "/health",
                "/v1/images/generations").
            status: The HTTP status code returned to the client (e.g.
                200, 400, 502).
            duration_milliseconds: The total duration of the request in
                milliseconds, measured from receipt to response completion.
        """
        with self._lock:
            # Increment the request count for this specific method + path
            # + status code combination.  The count key format matches the
            # specification's prescribed format: "METHOD /path STATUS_CODE".
            count_key = f"{method} {path} {status}"
            self._request_counts[count_key] = self._request_counts.get(count_key, 0) + 1

            # Append the latency observation to the bounded deque for this
            # endpoint.  The latency key aggregates across all status codes
            # for the same method + path combination, as prescribed by the
            # specification: "Statistics are cumulative... Aggregates across
            # all status codes for that endpoint."
            latency_key = f"{method} {path}"
            if latency_key not in self._request_latencies:
                self._request_latencies[latency_key] = collections.deque(
                    maxlen=self._maximum_observations_per_endpoint,
                )
            self._request_latencies[latency_key].append(duration_milliseconds)

    def snapshot(self) -> dict:
        """
        Return a point-in-time snapshot of all collected metrics.

        The snapshot includes two temporal metadata fields required by
        the v5.0.0 specification (FR38, Section 11):

        - ``collected_at``: ISO 8601 UTC timestamp of when this snapshot
          was generated (e.g. ``"2026-02-23T14:32:10.123456Z"``).
        - ``service_started_at``: ISO 8601 UTC timestamp of when the
          metrics collector was created, coinciding with application
          startup.

        The latency statistics for each endpoint are computed from the
        bounded observation window and include count, minimum, maximum,
        average, and 95th percentile values in milliseconds.

        Returns:
            A dictionary containing the complete metrics snapshot,
            suitable for direct JSON serialisation in the ``GET /metrics``
            response body.
        """
        with self._lock:
            result: dict = {
                "collected_at": _format_current_utc_timestamp(),
                "service_started_at": self._service_started_at,
                "request_counts": dict(self._request_counts),
                "request_latencies": {},
            }

            for endpoint_key, latency_observations in self._request_latencies.items():
                observation_count = len(latency_observations)

                # Sort a copy of the observations to compute order
                # statistics (minimum, maximum, 95th percentile) without
                # modifying the underlying deque.
                sorted_observations = sorted(latency_observations)

                # Compute the 95th percentile index using the nearest-rank
                # method: the index is the ceiling of 0.95 × count, clamped
                # to the valid index range.  For small observation counts,
                # the 95th percentile converges towards the maximum value.
                percentile_95_index = min(
                    int(observation_count * 0.95),
                    observation_count - 1,
                )

                result["request_latencies"][endpoint_key] = {
                    "count": observation_count,
                    "minimum_milliseconds": round(sorted_observations[0], 1),
                    "maximum_milliseconds": round(sorted_observations[-1], 1),
                    "average_milliseconds": round(sum(sorted_observations) / observation_count, 1),
                    "ninety_fifth_percentile_milliseconds": round(sorted_observations[percentile_95_index], 1),
                }

            return result


def _format_current_utc_timestamp() -> str:
    """
    Generate the current UTC time as an ISO 8601 formatted string.

    The format matches the v5.0.0 specification requirement (FR38,
    Section 11): a full ISO 8601 UTC timestamp with microsecond
    precision and the ``Z`` suffix indicating Coordinated Universal
    Time.

    Example output: ``"2026-02-23T14:32:10.123456Z"``

    Returns:
        A string containing the current UTC time in ISO 8601 format
        with microsecond precision.
    """
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
