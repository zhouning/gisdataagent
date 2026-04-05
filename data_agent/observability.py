"""
Observability module — structured logging + Prometheus metrics + HTTP middleware + Alert Engine (v15.6).

Provides:
- setup_logging(): configures root logger with text or JSON format
- get_logger(name): returns child logger under "data_agent" namespace
- 25+ Prometheus counters/histograms/gauges across 6 layers (LLM/Tool/Pipeline/Cache/HTTP/CB)
- ObservabilityMiddleware: ASGI middleware for HTTP request metrics
- record_*() convenience functions for metric recording
- generate_latest / CONTENT_TYPE_LATEST for /metrics endpoint
- AlertEngine: configurable threshold-based alerts with push channels (v15.6)
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

# --- Database Connection Pool Layer (v18.0) ---
db_pool_size = _safe_gauge(
    "agent_db_pool_size", "Configured connection pool size", ["engine"],
)
db_pool_checkedin = _safe_gauge(
    "agent_db_pool_checkedin", "Idle connections in pool", ["engine"],
)
db_pool_checkedout = _safe_gauge(
    "agent_db_pool_checkedout", "Active connections in use", ["engine"],
)
db_pool_overflow = _safe_gauge(
    "agent_db_pool_overflow", "Overflow connections beyond pool_size", ["engine"],
)
db_query_duration = _safe_histogram(
    "agent_db_query_duration_seconds", "Database query latency",
    ["operation"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)


def collect_db_pool_metrics():
    """Scrape SQLAlchemy connection pool stats into Prometheus gauges.

    Call this periodically (e.g. from /metrics endpoint or middleware).
    """
    try:
        from .db_engine import get_pool_status
        status = get_pool_status()
        if status:
            db_pool_size.labels(engine="primary").set(status["pool_size"])
            db_pool_checkedin.labels(engine="primary").set(status["checkedin"])
            db_pool_checkedout.labels(engine="primary").set(status["checkedout"])
            db_pool_overflow.labels(engine="primary").set(status["overflow"])
    except Exception:
        pass


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


# ---------------------------------------------------------------------------
# Alert Rule Engine (v15.6)
# ---------------------------------------------------------------------------

_alert_logger = logging.getLogger("data_agent.alerts")

_CONDITION_OPS = {
    "gt": lambda v, t: v > t,
    "gte": lambda v, t: v >= t,
    "lt": lambda v, t: v < t,
    "lte": lambda v, t: v <= t,
    "eq": lambda v, t: v == t,
    "neq": lambda v, t: v != t,
}


class AlertEngine:
    """Configurable threshold-based alert engine.

    Rules are stored in agent_alert_rules table. When a metric value
    is checked against rules, violations trigger alerts stored in
    agent_alert_history and optionally pushed via webhook/websocket.
    """

    _TABLE_RULES = "agent_alert_rules"
    _TABLE_HISTORY = "agent_alert_history"
    _last_fired: dict = {}  # rule_id -> timestamp (cooldown tracking)

    @classmethod
    def add_rule(cls, name: str, metric_name: str, condition: str, threshold: float,
                 severity: str = "warning", channel: str = "webhook",
                 channel_config: dict = None, cooldown_seconds: int = 300) -> int | None:
        """Create an alert rule. Returns rule ID."""
        from .db_engine import get_engine
        engine = get_engine()
        if not engine:
            return None
        try:
            from sqlalchemy import text
            from .user_context import current_user_id
            username = current_user_id.get() or "system"
            with engine.connect() as conn:
                result = conn.execute(text(f"""
                    INSERT INTO {cls._TABLE_RULES}
                        (name, metric_name, condition, threshold, severity,
                         channel, channel_config, cooldown_seconds, owner_username)
                    VALUES (:name, :metric, :cond, :thresh, :sev,
                            :chan, :cc::jsonb, :cool, :user)
                    RETURNING id
                """), {
                    "name": name, "metric": metric_name, "cond": condition,
                    "thresh": threshold, "sev": severity, "chan": channel,
                    "cc": json.dumps(channel_config or {}), "cool": cooldown_seconds,
                    "user": username,
                })
                row = result.fetchone()
                conn.commit()
                return row[0] if row else None
        except Exception as e:
            _alert_logger.error("Failed to add alert rule: %s", e)
            return None

    @classmethod
    def list_rules(cls, metric_name: str = None, enabled_only: bool = True) -> list[dict]:
        """List alert rules."""
        from .db_engine import get_engine
        engine = get_engine()
        if not engine:
            return []
        try:
            from sqlalchemy import text
            conditions = []
            params = {}
            if enabled_only:
                conditions.append("enabled = TRUE")
            if metric_name:
                conditions.append("metric_name = :metric")
                params["metric"] = metric_name
            where = " WHERE " + " AND ".join(conditions) if conditions else ""
            with engine.connect() as conn:
                rows = conn.execute(
                    text(f"SELECT * FROM {cls._TABLE_RULES}{where} ORDER BY id"),
                    params,
                ).mappings().all()
                return [dict(r) for r in rows]
        except Exception:
            return []

    @classmethod
    def check_metric(cls, metric_name: str, value: float) -> list[dict]:
        """Check a metric value against all matching rules.

        Returns list of triggered alerts (empty if no violations).
        """
        rules = cls.list_rules(metric_name=metric_name)
        triggered = []

        for rule in rules:
            cond_fn = _CONDITION_OPS.get(rule.get("condition", "gt"))
            if not cond_fn:
                continue
            threshold = rule.get("threshold", 0)
            if not cond_fn(value, threshold):
                continue

            # Cooldown check
            rule_id = rule["id"]
            cooldown = rule.get("cooldown_seconds", 300)
            last = cls._last_fired.get(rule_id, 0)
            now = time.time()
            if now - last < cooldown:
                continue

            cls._last_fired[rule_id] = now

            alert = {
                "rule_id": rule_id,
                "rule_name": rule.get("name", ""),
                "metric_name": metric_name,
                "metric_value": value,
                "threshold": threshold,
                "condition": rule.get("condition"),
                "severity": rule.get("severity", "warning"),
                "message": f"[{rule.get('severity', 'warning').upper()}] {rule.get('name', '')}: "
                           f"{metric_name}={value} {rule.get('condition')} {threshold}",
            }
            triggered.append(alert)

            # Record to history
            cls._record_alert(alert)

            # Push notification
            channel = rule.get("channel", "webhook")
            channel_config = rule.get("channel_config", {})
            if channel == "webhook" and channel_config.get("url"):
                cls._push_webhook(channel_config["url"], alert)

        return triggered

    @classmethod
    def _record_alert(cls, alert: dict):
        """Save alert to history table."""
        from .db_engine import get_engine
        engine = get_engine()
        if not engine:
            return
        try:
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text(f"""
                    INSERT INTO {cls._TABLE_HISTORY}
                        (rule_id, metric_name, metric_value, threshold, severity, message)
                    VALUES (:rid, :mn, :mv, :th, :sev, :msg)
                """), {
                    "rid": alert["rule_id"], "mn": alert["metric_name"],
                    "mv": alert["metric_value"], "th": alert["threshold"],
                    "sev": alert["severity"], "msg": alert["message"],
                })
                conn.commit()
        except Exception:
            pass

    @classmethod
    def _push_webhook(cls, url: str, alert: dict):
        """Push alert via webhook (fire-and-forget)."""
        try:
            import httpx
            httpx.post(url, json=alert, timeout=5)
        except Exception as e:
            _alert_logger.warning("Webhook push failed for %s: %s", url, e)

    @classmethod
    def get_history(cls, rule_id: int = None, limit: int = 50) -> list[dict]:
        """Get alert history."""
        from .db_engine import get_engine
        engine = get_engine()
        if not engine:
            return []
        try:
            from sqlalchemy import text
            sql = f"SELECT * FROM {cls._TABLE_HISTORY}"
            params = {"lim": limit}
            if rule_id:
                sql += " WHERE rule_id = :rid"
                params["rid"] = rule_id
            sql += " ORDER BY created_at DESC LIMIT :lim"
            with engine.connect() as conn:
                rows = conn.execute(text(sql), params).mappings().all()
                return [dict(r) for r in rows]
        except Exception:
            return []

    @classmethod
    def delete_rule(cls, rule_id: int) -> bool:
        """Delete an alert rule."""
        from .db_engine import get_engine
        engine = get_engine()
        if not engine:
            return False
        try:
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text(f"DELETE FROM {cls._TABLE_RULES} WHERE id = :id"), {"id": rule_id})
                conn.commit()
                return True
        except Exception:
            return False
