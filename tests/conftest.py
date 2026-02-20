"""Root test configuration — enables auto-mode for pytest-asyncio."""

import pytest

import application.rate_limiting


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Reset the rate limiter state before each test to prevent cross-test contamination."""
    application.rate_limiting.configure_rate_limit("1000/minute")
    application.rate_limiting.limiter.reset()
