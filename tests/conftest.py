"""Root test configuration — enables auto-mode for pytest-asyncio."""

import pytest
import structlog


@pytest.fixture(autouse=True)
def _reset_structlog_configuration():
    """
    Reset structlog to its default configuration before each test.

    Integration tests call ``configure_logging()``, which sets
    ``cache_logger_on_first_use=True`` and routes structlog through the
    stdlib ``logging`` module.  This cached configuration persists across
    tests and causes two problems:

    1. ``structlog.testing.capture_logs()`` cannot intercept log events
       because the cached loggers bypass structlog's own processing
       pipeline and write directly through the stdlib handler chain.

    2. The stdlib ``StreamHandler`` captures a reference to ``sys.stdout``
       at creation time.  When ``capsys``/``capfd`` subsequently replace
       ``sys.stdout``, the handler still writes to the original file
       descriptor, making captured output assertions fail.

    Calling ``structlog.reset_defaults()`` clears the logger cache and
    restores structlog's default ``PrintLogger`` factory, so that
    ``capture_logs()`` works correctly in unit tests.  Integration tests
    that call ``create_application()`` will reconfigure structlog via
    ``configure_logging()`` during their own setup, which is expected.
    """
    structlog.reset_defaults()
    yield
