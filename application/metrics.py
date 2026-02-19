"""
In-memory request metrics collection (NFR11).

Provides a thread-safe collector for request counts and latencies,
exposed via the GET /metrics endpoint in JSON format.
"""

import collections
import threading

_MAX_LATENCIES_PER_KEY = 1000


class MetricsCollector:
    """
    Thread-safe collector for HTTP request metrics.

    Records request counts (by method, path, and status code) and
    request latencies (by method and path) for operational monitoring.
    Latency lists are capped at ``_MAX_LATENCIES_PER_KEY`` entries to
    prevent unbounded memory growth; older entries are discarded.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._request_counts: dict[str, int] = {}
        self._request_latencies: dict[str, collections.deque[float]] = {}

    def record_request(
        self,
        method: str,
        path: str,
        status: int,
        duration_ms: float,
    ) -> None:
        """Record a completed HTTP request."""
        with self._lock:
            count_key = f"{method} {path} {status}"
            self._request_counts[count_key] = (
                self._request_counts.get(count_key, 0) + 1
            )

            latency_key = f"{method} {path}"
            if latency_key not in self._request_latencies:
                self._request_latencies[latency_key] = collections.deque(
                    maxlen=_MAX_LATENCIES_PER_KEY,
                )
            self._request_latencies[latency_key].append(duration_ms)

    def snapshot(self) -> dict:
        """Return a point-in-time snapshot of all collected metrics."""
        with self._lock:
            result: dict = {
                "request_counts": dict(self._request_counts),
                "request_latencies": {},
            }
            for key, latencies in self._request_latencies.items():
                n = len(latencies)
                sorted_latencies = sorted(latencies)
                p95_index = min(int(n * 0.95), n - 1)
                result["request_latencies"][key] = {
                    "count": n,
                    "min_ms": round(sorted_latencies[0], 1),
                    "max_ms": round(sorted_latencies[-1], 1),
                    "avg_ms": round(sum(sorted_latencies) / n, 1),
                    "p95_ms": round(sorted_latencies[p95_index], 1),
                }
            return result
