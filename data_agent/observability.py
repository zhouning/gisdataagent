"""
Observability module — structured logging + Prometheus metrics.

Provides:
- setup_logging(): configures root logger with text or JSON format
- get_logger(name): returns child logger under "data_agent" namespace
- Prometheus counters/histograms for pipeline runs, tool calls, auth events
- generate_latest / CONTENT_TYPE_LATEST for /metrics endpoint
"""
import json
import logging
import os
import time

from prometheus_client import (
    Counter,
    Histogram,
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
        log_entry = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
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
# Prometheus Metrics
# =====================================================================

# Counters
pipeline_runs = Counter(
    "agent_pipeline_runs_total",
    "Total pipeline executions",
    ["pipeline", "status"],
)
tool_calls = Counter(
    "agent_tool_calls_total",
    "Total tool invocations",
    ["tool_name", "status"],
)
auth_events = Counter(
    "agent_auth_events_total",
    "Authentication events",
    ["event_type"],
)

# Histograms
pipeline_duration = Histogram(
    "agent_pipeline_duration_seconds",
    "Pipeline execution latency",
    ["pipeline"],
)
