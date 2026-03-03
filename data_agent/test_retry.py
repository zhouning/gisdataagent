"""Tests for error classification and retry logic (v4.1.5).

Tests _classify_error() as a pure function and verifies MAX_PIPELINE_RETRIES.
No Chainlit mocking required.
"""

import pytest


def _get_funcs():
    from data_agent.app import _classify_error, MAX_PIPELINE_RETRIES
    return _classify_error, MAX_PIPELINE_RETRIES


# ===================================================================
# MAX_PIPELINE_RETRIES constant
# ===================================================================

class TestMaxRetries:
    def test_value_is_two(self):
        _, max_retries = _get_funcs()
        assert max_retries == 2


# ===================================================================
# _classify_error — retryable (transient)
# ===================================================================

class TestRetryableErrors:
    """Transient errors that should be retryable."""

    def test_timeout_error(self):
        classify, _ = _get_funcs()
        retryable, category = classify(TimeoutError("request timed out"))
        assert retryable is True
        assert category == "transient"

    def test_connection_error(self):
        classify, _ = _get_funcs()
        retryable, category = classify(ConnectionError("connection refused"))
        assert retryable is True
        assert category == "transient"

    def test_connection_reset_error(self):
        classify, _ = _get_funcs()
        retryable, category = classify(ConnectionResetError("reset by peer"))
        assert retryable is True
        assert category == "transient"

    def test_message_contains_timeout(self):
        classify, _ = _get_funcs()
        retryable, category = classify(RuntimeError("upstream timeout after 30s"))
        assert retryable is True
        assert category == "transient"

    def test_message_contains_rate_limit(self):
        classify, _ = _get_funcs()
        retryable, category = classify(Exception("rate limit exceeded"))
        assert retryable is True
        assert category == "transient"

    def test_message_contains_503(self):
        classify, _ = _get_funcs()
        retryable, category = classify(Exception("503 Service Unavailable"))
        assert retryable is True
        assert category == "transient"

    def test_message_contains_429(self):
        classify, _ = _get_funcs()
        retryable, category = classify(Exception("HTTP 429 Too Many Requests"))
        assert retryable is True
        assert category == "transient"

    def test_message_contains_resource_exhausted(self):
        classify, _ = _get_funcs()
        retryable, category = classify(Exception("RESOURCE EXHAUSTED: quota exceeded"))
        assert retryable is True
        assert category == "transient"


# ===================================================================
# _classify_error — non-retryable
# ===================================================================

class TestNonRetryableErrors:
    """Errors that should NOT be retried."""

    def test_value_error(self):
        classify, _ = _get_funcs()
        retryable, category = classify(ValueError("invalid column"))
        assert retryable is False
        assert category == "data_format"

    def test_key_error(self):
        classify, _ = _get_funcs()
        retryable, category = classify(KeyError("missing_key"))
        assert retryable is False
        assert category == "data_format"

    def test_permission_error(self):
        classify, _ = _get_funcs()
        retryable, category = classify(PermissionError("access denied"))
        assert retryable is False
        assert category == "permission"

    def test_file_not_found_error(self):
        classify, _ = _get_funcs()
        retryable, category = classify(FileNotFoundError("no such file"))
        assert retryable is False
        assert category == "data_format"

    def test_message_contains_permission_denied(self):
        classify, _ = _get_funcs()
        retryable, category = classify(RuntimeError("permission denied for table"))
        assert retryable is False
        assert category == "config"

    def test_message_contains_invalid_format(self):
        classify, _ = _get_funcs()
        retryable, category = classify(Exception("invalid format: expected GeoJSON"))
        assert retryable is False
        assert category == "config"

    def test_message_contains_unauthorized(self):
        classify, _ = _get_funcs()
        retryable, category = classify(Exception("401 Unauthorized"))
        assert retryable is False
        assert category == "config"


# ===================================================================
# _classify_error — unknown (default retryable)
# ===================================================================

class TestUnknownErrors:
    """Unknown errors default to retryable."""

    def test_generic_exception(self):
        classify, _ = _get_funcs()
        retryable, category = classify(Exception("something unexpected"))
        assert retryable is True
        assert category == "unknown"

    def test_runtime_error_no_keywords(self):
        classify, _ = _get_funcs()
        retryable, category = classify(RuntimeError("internal processing failed"))
        assert retryable is True
        assert category == "unknown"
