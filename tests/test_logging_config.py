"""Tests for application/logging_config.py."""

import json
import logging

import structlog

import application.logging_config


class TestConfigureLogging:
    def setup_method(self):
        """Reset structlog configuration before each test."""
        structlog.reset_defaults()

    def teardown_method(self):
        """Reset structlog configuration after each test."""
        structlog.reset_defaults()

    def test_sets_log_level(self):
        application.logging_config.configure_logging(log_level="DEBUG")
        root = logging.getLogger()
        assert root.level == logging.DEBUG

        application.logging_config.configure_logging(log_level="INFO")

    def test_adds_handler_with_structlog_formatter(self):
        application.logging_config.configure_logging(log_level="INFO")
        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert isinstance(
            root.handlers[0].formatter,
            structlog.stdlib.ProcessorFormatter,
        )

    def test_native_structlog_produces_valid_json(self, capsys):
        application.logging_config.configure_logging(log_level="INFO")
        test_logger = structlog.get_logger("test")
        test_logger.info("test_event", key="value")

        captured = capsys.readouterr()
        parsed = json.loads(captured.err.strip())

        assert parsed["event"] == "test_event"
        assert parsed["key"] == "value"

    def test_output_contains_mandatory_fields(self, capsys):
        application.logging_config.configure_logging(log_level="INFO")
        test_logger = structlog.get_logger("test")
        test_logger.info("test_event")

        captured = capsys.readouterr()
        parsed = json.loads(captured.err.strip())

        assert "timestamp" in parsed
        assert "level" in parsed
        assert "event" in parsed
        assert "service_name" in parsed

    def test_level_is_uppercase(self, capsys):
        application.logging_config.configure_logging(log_level="INFO")
        test_logger = structlog.get_logger("test")
        test_logger.info("test_event")

        captured = capsys.readouterr()
        parsed = json.loads(captured.err.strip())

        assert parsed["level"] == "INFO"

    def test_service_name_is_set(self, capsys):
        application.logging_config.configure_logging(log_level="INFO")
        test_logger = structlog.get_logger("test")
        test_logger.info("test_event")

        captured = capsys.readouterr()
        parsed = json.loads(captured.err.strip())

        assert parsed["service_name"] == "text-to-image-api"

    def test_timestamp_is_iso_8601_utc(self, capsys):
        application.logging_config.configure_logging(log_level="INFO")
        test_logger = structlog.get_logger("test")
        test_logger.info("test_event")

        captured = capsys.readouterr()
        parsed = json.loads(captured.err.strip())

        timestamp = parsed["timestamp"]
        assert "T" in timestamp
        assert timestamp.endswith("Z") or "+" in timestamp

    def test_contextvars_are_included(self, capsys):
        application.logging_config.configure_logging(log_level="INFO")
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id="test-correlation-id")

        test_logger = structlog.get_logger("test")
        test_logger.info("test_event")

        captured = capsys.readouterr()
        parsed = json.loads(captured.err.strip())

        assert parsed["correlation_id"] == "test-correlation-id"

        structlog.contextvars.clear_contextvars()

    def test_stdlib_loggers_produce_json(self, capsys):
        application.logging_config.configure_logging(log_level="INFO")
        stdlib_logger = logging.getLogger("test.stdlib")
        stdlib_logger.info("stdlib message")

        captured = capsys.readouterr()
        parsed = json.loads(captured.err.strip())

        assert parsed["event"] == "stdlib message"
        assert "service_name" in parsed
        assert "timestamp" in parsed
