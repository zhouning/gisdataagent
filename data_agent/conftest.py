"""
Shared test fixtures for data_agent test suite (v9.5.1).

Provides common mocks, helpers, and event-loop safety to eliminate
duplication across 68+ test files.
"""

import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# Async helper — safe event-loop execution
# ---------------------------------------------------------------------------

def run_async(coro):
    """Run an async coroutine safely, creating a new event loop if needed.

    Prevents cross-contamination from IsolatedAsyncioTestCase which closes
    the default event loop after each test class.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ---------------------------------------------------------------------------
# Event loop safety — ensure clean loop per test function
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _ensure_event_loop():
    """Ensure a fresh, open event loop is available for every test.

    IsolatedAsyncioTestCase and some async fixtures close the running loop,
    which breaks subsequent tests that call asyncio.get_event_loop().
    This fixture runs after each test and resets the loop if needed.
    """
    yield
    # Post-test cleanup: if the loop was closed, install a fresh one
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — check if the default loop is closed
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                asyncio.set_event_loop(asyncio.new_event_loop())
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())


# ---------------------------------------------------------------------------
# Database engine mock
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_engine():
    """Patch data_agent.db_engine.get_engine to return a MagicMock.

    Usage::

        def test_something(mock_engine):
            # get_engine() returns mock_engine throughout the test
            ...
    """
    with patch("data_agent.db_engine.get_engine") as mock_get:
        engine = MagicMock()
        mock_get.return_value = engine
        yield engine


# ---------------------------------------------------------------------------
# Mock Starlette request factory
# ---------------------------------------------------------------------------

def make_mock_request(
    path="/",
    query_params=None,
    cookies=None,
    path_params=None,
    method="GET",
    body=None,
):
    """Create a mock Starlette Request for REST endpoint tests."""
    req = MagicMock()
    req.cookies = cookies or {}
    req.path_params = path_params or {}
    req.method = method
    req.url = MagicMock()
    req.url.path = path

    qp = MagicMock()
    qp_dict = query_params or {}
    qp.get = lambda k, default=None: qp_dict.get(k, default)
    qp.__contains__ = lambda self, k: k in qp_dict
    qp.items = lambda: qp_dict.items()
    req.query_params = qp

    if body is not None:
        req.json = AsyncMock(return_value=body)
        req.body = AsyncMock(return_value=str(body).encode())
    else:
        req.json = AsyncMock(return_value={})
        req.body = AsyncMock(return_value=b"")

    return req


# ---------------------------------------------------------------------------
# Mock callback/tool context factories
# ---------------------------------------------------------------------------

def make_callback_context(state=None):
    """Create a mock ADK CallbackContext with a state dict."""
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    return ctx


def make_tool_context(state=None):
    """Create a mock ADK ToolContext with a state dict."""
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    return ctx


# ---------------------------------------------------------------------------
# LLM mock factory
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm():
    """Provide a reusable AsyncMock for LLM call functions.

    The fixture returns a tuple (mock, set_response) where set_response
    is a helper to configure the mock's return value.
    """
    mock = AsyncMock()
    mock.return_value = ""

    def set_response(text):
        mock.return_value = text

    return mock, set_response
