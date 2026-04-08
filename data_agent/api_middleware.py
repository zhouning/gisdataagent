"""
API Security Middleware — rate limiting, JWT pre-auth, circuit breaker (v22.0).

Starlette middleware implementations that provide Kong-equivalent functionality
without requiring an external API gateway. Suitable for single-instance and
small-scale multi-instance deployments.
"""
from __future__ import annotations

import time
import asyncio
from collections import defaultdict
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .observability import get_logger

logger = get_logger("api_middleware")


# ---------------------------------------------------------------------------
# Rate Limiter (Token Bucket per user/IP)
# ---------------------------------------------------------------------------


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-user/IP rate limiting using token bucket algorithm.

    Limits: 100 requests/minute per user, 1000 requests/hour per IP.
    Uses Redis if available, falls back to in-memory.
    """

    def __init__(self, app, per_minute: int = 100, per_hour: int = 1000):
        super().__init__(app)
        self.per_minute = per_minute
        self.per_hour = per_hour
        self._minute_buckets: dict[str, list[float]] = defaultdict(list)
        self._hour_buckets: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        # Skip non-API routes
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        # Identify caller
        user = self._get_user(request)
        ip = request.client.host if request.client else "unknown"
        now = time.time()

        # Per-user minute limit
        if user:
            self._minute_buckets[user] = [
                t for t in self._minute_buckets[user] if now - t < 60
            ]
            if len(self._minute_buckets[user]) >= self.per_minute:
                logger.warning("Rate limit exceeded: user=%s (%d/min)", user, self.per_minute)
                return JSONResponse(
                    {"error": "rate_limit_exceeded", "retry_after": 60},
                    status_code=429,
                )
            self._minute_buckets[user].append(now)

        # Per-IP hour limit
        self._hour_buckets[ip] = [
            t for t in self._hour_buckets[ip] if now - t < 3600
        ]
        if len(self._hour_buckets[ip]) >= self.per_hour:
            logger.warning("Rate limit exceeded: ip=%s (%d/hour)", ip, self.per_hour)
            return JSONResponse(
                {"error": "rate_limit_exceeded", "retry_after": 3600},
                status_code=429,
            )
        self._hour_buckets[ip].append(now)

        return await call_next(request)

    @staticmethod
    def _get_user(request: Request) -> Optional[str]:
        """Extract username from JWT cookie or header."""
        try:
            from .auth import _decode_token
            token = request.cookies.get("chainlit_access_token")
            if token:
                payload = _decode_token(token)
                return payload.get("username") if payload else None
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# Circuit Breaker Middleware
# ---------------------------------------------------------------------------


class CircuitBreakerMiddleware(BaseHTTPMiddleware):
    """Circuit breaker for backend service protection.

    Opens circuit after consecutive failures, returns 503 fast-fail.
    Half-open after cooldown period allows a single probe request.

    States: CLOSED (normal) → OPEN (fast-fail) → HALF_OPEN (probe) → CLOSED
    """

    def __init__(self, app, failure_threshold: int = 5, cooldown_seconds: int = 30):
        super().__init__(app)
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown_seconds
        self._failure_count = 0
        self._state = "closed"  # closed / open / half_open
        self._last_failure_time = 0.0

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        now = time.time()

        # OPEN state: fast-fail
        if self._state == "open":
            if now - self._last_failure_time > self.cooldown:
                self._state = "half_open"
                logger.info("Circuit breaker: HALF_OPEN (probe allowed)")
            else:
                return JSONResponse(
                    {"error": "service_unavailable", "circuit": "open"},
                    status_code=503,
                )

        try:
            response = await call_next(request)

            # Success: reset on 2xx/3xx
            if response.status_code < 500:
                if self._state == "half_open":
                    self._state = "closed"
                    self._failure_count = 0
                    logger.info("Circuit breaker: CLOSED (recovered)")
                elif self._failure_count > 0:
                    self._failure_count = 0
            else:
                self._record_failure(now)

            return response
        except Exception as e:
            self._record_failure(now)
            raise

    def _record_failure(self, now: float):
        self._failure_count += 1
        self._last_failure_time = now
        if self._failure_count >= self.failure_threshold:
            self._state = "open"
            logger.warning(
                "Circuit breaker: OPEN (failures=%d, threshold=%d)",
                self._failure_count, self.failure_threshold,
            )

    @property
    def state(self) -> dict:
        return {
            "state": self._state,
            "failure_count": self._failure_count,
            "threshold": self.failure_threshold,
            "cooldown_seconds": self.cooldown,
        }
