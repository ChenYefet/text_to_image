"""
Request logging middleware.

The ``RequestLoggingMiddleware`` emits structured log events for every
HTTP request entering and leaving the service:

- ``http_request_received`` on entry (including the declared
  ``Content-Length`` from the request headers).
- ``http_request_completed`` on exit (including the response status
  code, duration in milliseconds, and response payload size in bytes).

It also records per-request metrics via the optional
``MetricsCollector`` so that the ``/metrics`` endpoint can expose
request counts and latency distributions.

This middleware must be registered *inside* (after)
``CorrelationIdMiddleware`` so that the structlog context already
contains the correlation ID when these events are emitted.
"""

import time

import starlette.types
import structlog

import application.api.middleware.correlation_identifier
import application.metrics
import application.prometheus_metrics

logger = structlog.get_logger()


class RequestLoggingMiddleware:
    """
    Emit structured log events and record metrics for every HTTP request.

    Tracks the response status code and body size via a ``send`` wrapper
    so that the ``http_request_completed`` event includes the full
    picture even for streaming responses with multiple body chunks.
    """

    def __init__(
        self,
        app: starlette.types.ASGIApp,
        metrics_collector: application.metrics.MetricsCollector | None = None,
    ) -> None:
        self._asgi_application = app
        self._metrics_collector = metrics_collector

    async def __call__(
        self,
        scope: starlette.types.Scope,
        receive: starlette.types.Receive,
        send: starlette.types.Send,
    ) -> None:
        if scope["type"] != "http":
            await self._asgi_application(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")
        start_time = time.monotonic()
        response_status = 0
        number_of_bytes_of_response_payload = 0

        # Extract the declared request payload size from the Content-Length
        # header (if present) for inclusion in the http_request_received
        # log event, as recommended by the v5.8.0 specification's 46-event
        # logging taxonomy.
        number_of_bytes_of_request_payload = (
            application.api.middleware.correlation_identifier.extract_content_length_from_headers(
                scope.get("headers", []),
            )
        )

        logger.info(
            "http_request_received",
            method=method,
            path=path,
            number_of_bytes_of_request_payload=number_of_bytes_of_request_payload,
        )

        async def send_with_status_and_size_tracking(
            message: starlette.types.Message,
        ) -> None:
            nonlocal response_status, number_of_bytes_of_response_payload
            if message["type"] == "http.response.start":
                response_status = message.get("status", 0)
            elif message["type"] == "http.response.body":
                # Accumulate the response body size for inclusion in the
                # http_request_completed log event.  Streaming responses
                # may send multiple body chunks; we track the total.
                body_chunk = message.get("body", b"")
                number_of_bytes_of_response_payload += len(body_chunk)
            await send(message)

        try:
            await self._asgi_application(
                scope,
                receive,
                send_with_status_and_size_tracking,
            )
        except Exception:
            # The exception will propagate to the outer
            # CorrelationIdMiddleware which sends the 500 response.
            # Record status 500 so the completion log reflects it.
            response_status = 500
            raise
        finally:
            duration_in_milliseconds = (time.monotonic() - start_time) * 1000
            logger.info(
                "http_request_completed",
                method=method,
                path=path,
                status=response_status,
                duration_in_milliseconds=round(duration_in_milliseconds, 1),
                number_of_bytes_of_response_payload=number_of_bytes_of_response_payload,
            )
            if self._metrics_collector is not None:
                self._metrics_collector.record_request(
                    method=method,
                    path=path,
                    status=response_status,
                    duration_in_milliseconds=round(duration_in_milliseconds, 1),
                )
            application.prometheus_metrics.counter_of_http_requests_received.labels(
                method=method,
                path=path,
                status_code=str(response_status),
            ).inc()
            application.prometheus_metrics.histogram_of_duration_of_http_requests_in_seconds.labels(
                method=method,
                path=path,
            ).observe(duration_in_milliseconds / 1000.0)
