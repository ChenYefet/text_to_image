"""
Structured logging configuration for the application.

Configures the root logger to emit JSON-formatted log records, making
logs machine-parseable for log aggregation systems (ELK, CloudWatch, etc.).
"""

import json
import logging
import sys


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def configure_logging(log_level: str = "INFO") -> None:
    """
    Configure the root logger with structured JSON output to stderr.

    Should be called once during application startup, before any log
    messages are emitted.
    """
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
