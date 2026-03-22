"""
Observability module — structured logging + Prometheus metrics + HTTP middleware (v14.5).

Provides:
- setup_logging(): configures root logger with text or JSON format
- get_logger(name): returns child logger under "data_agent" namespace
- 25+ Prometheus counters/histograms/gauges across 6 layers (LLM/Tool/Pipeline/Cache/HTTP/CB)
- ObservabilityMiddleware: ASGI middleware for HTTP request metrics
- record_*() convenience functions for metric recording
- generate_latest / CONTENT_TYPE_LATEST for /metrics endpoint
"""
import json
import logging
import os
import re
import time

from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

# =====================================================================
# Structured Logging
# =====================================================================

_ROOT_LOGGER_NAME = "data_agent"
_CONFIGURED = False


class JsonFormatter(logging.Formatter):
    """JSON-lines formatter for production log aggregation (ELK, CloudLogging)."""

    def format(self, record: logging.LogRecord) -> str:
        from data_agent.user_context import current_trace_id, current_user_id
        log_entry = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        trace_id = current_trace_id.get('')
        if trace_id:
            log_entry["trace_id"] = trace_id
        user_id = current_user_id.get('anonymous')
        if user_id != 'anonymous':
            log_entry["user_id"] = user_id
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging() -> logging.Logger:
    """Configure the root 'data_agent' logger.

    Environment variables:
    - LOG_LEVEL: DEBUG, INFO (default), WARNING, ERROR, CRITICAL
    - LOG_FORMAT: "text" (default) or "json"

    Returns the root data_agent logger.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return logging.getLogger(_ROOT_LOGGER_NAME)

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    log_format = os.environ.get("LOG_FORMAT", "text").lower()

    root_logger = logging.getLogger(_ROOT_LOGGER_NAME)
    root_logger.setLevel(level)

    # Avoid duplicate handlers on re-import
    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(level)
        if log_format == "json":
            handler.setFormatter(JsonFormatter())
        else:
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ))
        root_logger.addHandler(handler)

    _CONFIGURED = True
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Get a child logger: data_agent.{name}."""
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{name}")


# =====================================================================
# Prometheus Metrics (guarded against duplicate registration on hot reload)
# =====================================================================

from prometheus_client import CollectorRegistry, REGISTRY

def _safe_counter(name, desc, labels):
    try:
        return Counter(name, desc, labels)
    except ValueError:
        # Already registered — retrieve existing
        for c in REGISTRY.collect():
            if hasattr(c, '_name') and c._name == name.replace('_total', ''):
                return c
        return Counter(name, desc, labels, registry=CollectorRegistry())

def _safe_histogram(name, desc, labels, buckets=None):
    try:
        if buckets:
            return Histogram(name, desc, labels, buckets=buckets)
        return Histogram(name, desc, labels)
    except ValueError:
        for c in REGISTRY.collect():
            if hasattr(c, '_name') and c._name == name:
                return c
        if buckets:
            return Histogram(name, desc, labels, buckets=buckets, registry=CollectorRegistry())
        return Histogram(name, desc, labels, registry=CollectorRegistry())

def _safe_gauge(name, desc, labels):
    try:
        return Gauge(name, desc, labels)
    except ValueError:
        for c in REGISTRY.collect():
            if hasattr(c, '_name') and c._name == name:
                return c
        return Gauge(name, desc, labels, registry=CollectorRegistry())

# Counters
pipeline_runs = _safe_counter(
    "agent_pipeline_runs_total",
    "Total pipeline executions",
    ["pipeline", "status"],
)
tool_calls = _safe_counter(
    "agent_tool_calls_total",
    "Total tool invocations",
    ["tool_name", "status"],
)
auth_events = _safe_counter(
    "agent_auth_events_total",
    "Authentication events",
    ["event_type"],
)

# Histograms
pipeline_duration = _safe_histogram(
    "agent_pipeline_duration_seconds",
    "Pipeline execution latency",
    ["pipeline"],
)

# =====================================================================
# Extended Metrics — 6-Layer Observability (v14.5)
# =====================================================================

# --- LLM Layer ---
llm_calls = _safe_counter(
    "agent_llm_calls_total", "LLM invocations", ["agent_name", "model_name"],
)
llm_duration = _safe_histogram(
    "agent_llm_duration_seconds", "LLM call latency",
    ["agent_name", "model_name"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
llm_input_tokens = _safe_histogram(
    "agent_llm_input_tokens", "LLM input token count",
    ["agent_name", "model_name"],
    buckets=(100, 500, 1000, 2000, 5000, 10000, 50000),
)
llm_output_tokens = _safe_histogram(
    "agent_llm_output_tokens", "LLM output token count",
    ["agent_name", "model_name"],
    buckets=(50, 100, 500, 1000, 2000, 5000),
)

# --- Tool Layer ---
tool_duration = _safe_histogram(
    "agent_tool_duration_seconds", "Tool execution latency",
    ["tool_name", "agent_name"],
    buckets=(0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10, 30, 60, 120),
)
tool_retries = _safe_counter(
    "agent_tool_retries_total", "Tool retry attempts",
    ["tool_name", "error_category"],
)
tool_output_bytes = _safe_histogram(
    "agent_tool_output_bytes", "Tool output size in bytes",
    ["tool_name"],
    buckets=(100, 1000, 10000, 100000, 1000000, 10000000),
)

# --- Pipeline / Intent Layer ---
intent_classification = _safe_counter(
    "agent_intent_classification_total", "Intent routing classification",
    ["intent", "language"],
)
intent_duration = _safe_histogram(
    "agent_intent_duration_seconds", "Intent classification latency",
    [],
    buckets=(0.1, 0.25, 0.5, 1, 2, 5),
)
pipeline_steps = _safe_counter(
    "agent_pipeline_steps_total", "Pipeline step completions",
    ["pipeline_type", "step_name", "status"],
)

# --- Cache Layer ---
cache_operations = _safe_counter(
    "agent_cache_operations_total", "Cache hit/miss/invalidate",
    ["cache_name", "operation"],
)

# --- Circuit Breaker Layer ---
cb_state = _safe_gauge(
    "agent_circuit_breaker_state", "Circuit breaker state (0=closed, 1=open, 2=half_open)",
    ["tool_name"],
)
cb_trips = _safe_counter(
    "agent_circuit_breaker_trips_total", "Circuit breaker trip events",
    ["tool_name"],
)

# --- HTTP API Layer ---
http_requests = _safe_counter(
    "http_requests_total", "HTTP request count",
    ["method", "path", "status_code"],
)
http_duration = _safe_histogram(
    "http_request_duration_seconds", "HTTP request latency",
    ["method", "path", "status_code"],
    buckets=(0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)


# =====================================================================
# Convenience Recording Functions
# =====================================================================

def record_llm_call(agent_name: str, model_name: str,
                    input_tok: int = 0, output_tok: int = 0, duration_s: float = 0):
    """Record a single LLM invocation across all LLM metrics."""
    try:
        llm_calls.labels(agent_name=agent_name, model_name=model_name).inc()
        if duration_s > 0:
            llm_duration.labels(agent_name=agent_name, model_name=model_name).observe(duration_s)
        if input_tok > 0:
            llm_input_tokens.labels(agent_name=agent_name, model_name=model_name).observe(input_tok)
        if output_tok > 0:
            llm_output_tokens.labels(agent_name=agent_name, model_name=model_name).observe(output_tok)
    except Exception:
        pass


def record_tool_execution(tool_name: str, agent_name: str = "",
                          duration_s: float = 0, output_size: int = 0, status: str = "success"):
    """Record a tool execution with timing and output size."""
    try:
        tool_calls.labels(tool_name=tool_name, status=status).inc()
        if duration_s > 0:
            tool_duration.labels(tool_name=tool_name, agent_name=agent_name).observe(duration_s)
        if output_size > 0:
            tool_output_bytes.labels(tool_name=tool_name).observe(output_size)
    except Exception:
        pass


def record_intent(intent: str, language: str, duration_s: float = 0):
    """Record intent classification result."""
    try:
        intent_classification.labels(intent=intent, language=language).inc()
        if duration_s > 0:
            intent_duration.observe(duration_s)
    except Exception:
        pass


def record_cache_op(cache_name: str, operation: str):
    """Record cache hit/miss/invalidate. operation: 'hit' | 'miss' | 'invalidate'."""
    try:
        cache_operations.labels(cache_name=cache_name, operation=operation).inc()
    except Exception:
        pass


def record_circuit_breaker(tool_name: str, state: str, tripped: bool = False):
    """Record circuit breaker state change. state: 'closed' | 'open' | 'half_open'."""
    try:
        state_val = {"closed": 0, "open": 1, "half_open": 2}.get(state, 0)
        cb_state.labels(tool_name=tool_name).set(state_val)
        if tripped:
            cb_trips.labels(tool_name=tool_name).inc()
    except Exception:
        pass


# =====================================================================
# HTTP Observability Middleware (ASGI)
# =====================================================================

# Path normalization to prevent cardinality explosion
_PATH_ID_PATTERNS = [
    (re.compile(r'/(\d+)(/|$)'), r'/{id}\2'),       # /api/skills/123 → /api/skills/{id}
    (re.compile(r'/([0-9a-f-]{36})(/|$)'), r'/{uuid}\2'),  # UUID paths
]


def _normalize_path(path: str) -> str:
    """Normalize URL path by replacing numeric/UUID segments with placeholders."""
    for pattern, replacement in _PATH_ID_PATTERNS:
        path = pattern.sub(replacement, path)
    return path


class ObservabilityMiddleware:
    """Starlette-compatible ASGI middleware for HTTP request metrics."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "/")
        # Skip metrics endpoint and static files
        if path == "/metrics" or path.startswith("/assets/") or not path.startswith("/api/"):
            return await self.app(scope, receive, send)

        method = scope.get("method", "GET")
        normalized_path = _normalize_path(path)
        start = time.monotonic()
        status_code = "500"

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = str(message.get("status", 500))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.monotonic() - start
            try:
                http_requests.labels(method=method, path=normalized_path, status_code=status_code).inc()
                http_duration.labels(method=method, path=normalized_path, status_code=status_code).observe(duration)
            except Exception:
                pass
