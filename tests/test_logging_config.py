"""Tests for application/logging_config.py."""

import json
import logging

import application.logging_config


class TestJsonFormatter:

    def test_format_produces_valid_json(self):
        formatter = application.logging_config.JsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )

        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.logger"
        assert parsed["message"] == "hello world"
        assert "timestamp" in parsed

    def test_format_includes_exception(self):
        formatter = application.logging_config.JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test.logger",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="failed",
            args=(),
            exc_info=exc_info,
        )

        output = formatter.format(record)
        parsed = json.loads(output)

        assert "exception" in parsed
        assert "ValueError: boom" in parsed["exception"]


class TestConfigureLogging:

    def test_sets_log_level(self):
        application.logging_config.configure_logging(log_level="DEBUG")
        root = logging.getLogger()
        assert root.level == logging.DEBUG

        # Reset to avoid side effects
        application.logging_config.configure_logging(log_level="INFO")

    def test_adds_json_handler(self):
        application.logging_config.configure_logging(log_level="INFO")
        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert isinstance(
            root.handlers[0].formatter,
            application.logging_config.JsonFormatter,
        )
