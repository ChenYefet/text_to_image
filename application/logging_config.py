"""
Structured logging configuration for the application.

Configures structlog to emit JSON-formatted log records to **stdout** with
the mandatory fields required by the specification (NFR9): timestamp
(ISO 8601 UTC), level, event, correlation_id, and service_name.

The log output destination is stdout (not stderr), consistent with the
twelve-factor app methodology (factor XI — Logs) and container logging
best practices as mandated by the v5.0.0 specification (Section 18,
Log Output Destination).

Both structlog-native loggers and standard library loggers (used by
third-party packages such as Uvicorn and httpx) are routed through the
same processing pipeline and produce identical JSON output.
"""

import logging
import sys

import structlog

SERVICE_NAME = "text-to-image-api"


def _add_service_name(
    logger: structlog.types.WrappedLogger,
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Inject the service name into every log entry."""
    event_dict["service_name"] = SERVICE_NAME
    return event_dict


def _uppercase_level(
    logger: structlog.types.WrappedLogger,
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Normalise the log level to uppercase (e.g. INFO, ERROR)."""
    if "level" in event_dict:
        event_dict["level"] = event_dict["level"].upper()
    return event_dict


def configure_logging(log_level: str = "INFO") -> None:
    """
    Configure structlog for structured JSON logging to stdout.

    Both structlog-native loggers and standard library loggers are
    processed through the same pipeline, producing JSON output with
    the mandatory fields: timestamp, level, event, service_name.
    The correlation_id field is injected per-request via contextvars.

    The output stream is stdout (not stderr), consistent with the
    twelve-factor app methodology (factor XI — Logs) as required by
    the v5.0.0 specification (Section 18).

    Should be called once during application startup, before any log
    messages are emitted.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        _add_service_name,
        structlog.stdlib.add_log_level,
        _uppercase_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)
