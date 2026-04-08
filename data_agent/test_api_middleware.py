"""Tests for API security middleware (v22.0)."""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse

from data_agent.api_middleware import RateLimitMiddleware, CircuitBreakerMiddleware


# ---------------------------------------------------------------------------
# Test app fixture
# ---------------------------------------------------------------------------

async def _ok_endpoint(request):
    return JSONResponse({"status": "ok"})

async def _error_endpoint(request):
    return JSONResponse({"error": "fail"}, status_code=500)

async def _non_api(request):
    return JSONResponse({"page": "home"})


def _make_app(middleware_cls, **kwargs):
    app = Starlette(routes=[
        Route("/api/test", _ok_endpoint),
        Route("/api/error", _error_endpoint),
        Route("/health", _non_api),
    ])
    app.add_middleware(middleware_cls, **kwargs)
    return app


# ---------------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------------


def test_rate_limit_allows_normal_traffic():
    app = _make_app(RateLimitMiddleware, per_minute=10, per_hour=100)
    client = TestClient(app)
    resp = client.get("/api/test")
    assert resp.status_code == 200


def test_rate_limit_blocks_excess():
    app = _make_app(RateLimitMiddleware, per_minute=100, per_hour=3)
    client = TestClient(app)
    for _ in range(3):
        resp = client.get("/api/test")
        assert resp.status_code == 200
    # 4th request exceeds per-IP hour limit
    resp = client.get("/api/test")
    assert resp.status_code == 429
    assert "rate_limit" in resp.json()["error"]


def test_rate_limit_skips_non_api():
    app = _make_app(RateLimitMiddleware, per_minute=1, per_hour=1)
    client = TestClient(app)
    # Non-API routes are not rate limited
    client.get("/api/test")  # consume the 1 allowed
    resp = client.get("/health")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------


def test_circuit_breaker_closed_normal():
    app = _make_app(CircuitBreakerMiddleware, failure_threshold=3, cooldown_seconds=1)
    client = TestClient(app)
    resp = client.get("/api/test")
    assert resp.status_code == 200


def test_circuit_breaker_opens_after_failures():
    app = _make_app(CircuitBreakerMiddleware, failure_threshold=3, cooldown_seconds=60)
    client = TestClient(app)
    # Trigger 3 failures (500 responses)
    for _ in range(3):
        client.get("/api/error")
    # Circuit should be open now — fast fail
    resp = client.get("/api/test")
    assert resp.status_code == 503
    assert resp.json()["circuit"] == "open"


def test_circuit_breaker_half_open_after_cooldown():
    app = _make_app(CircuitBreakerMiddleware, failure_threshold=2, cooldown_seconds=0)
    client = TestClient(app)
    # Trigger failures
    client.get("/api/error")
    client.get("/api/error")
    # Cooldown = 0, so immediately half-open
    time.sleep(0.01)
    resp = client.get("/api/test")
    # Should succeed (half-open probe) and close circuit
    assert resp.status_code == 200


def test_circuit_breaker_skips_non_api():
    app = _make_app(CircuitBreakerMiddleware, failure_threshold=1, cooldown_seconds=60)
    client = TestClient(app)
    client.get("/api/error")  # open circuit
    # Non-API should still work
    resp = client.get("/health")
    assert resp.status_code == 200


def test_circuit_breaker_state():
    from data_agent.api_middleware import CircuitBreakerMiddleware
    mw = CircuitBreakerMiddleware(app=MagicMock())
    state = mw.state
    assert state["state"] == "closed"
    assert state["failure_count"] == 0
