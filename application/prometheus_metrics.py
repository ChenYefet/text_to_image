"""
Prometheus metric instruments for HTTP request observability.

This module defines a custom ``CollectorRegistry`` with two instruments:

- ``counter_of_http_requests_received``: A ``Counter`` tracking the total
  number of HTTP requests, labelled by method, path, and status code.
- ``histogram_of_duration_of_http_requests_in_seconds``: A ``Histogram``
  tracking request duration, labelled by method and path.

The custom registry avoids exposing default Python process metrics that
are not specified by the application specification.
"""

import prometheus_client

registry_for_prometheus_metrics = prometheus_client.CollectorRegistry()

counter_of_http_requests_received = prometheus_client.Counter(
    "http_requests_received_total",
    "Total number of HTTP requests received by the service",
    ["method", "path", "status_code"],
    registry=registry_for_prometheus_metrics,
)

histogram_of_duration_of_http_requests_in_seconds = prometheus_client.Histogram(
    "http_request_duration_in_seconds",
    "Duration of HTTP requests in seconds",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 90.0),
    registry=registry_for_prometheus_metrics,
)
