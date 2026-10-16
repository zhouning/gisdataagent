"""Bounded, content-free step timing for the real product NL2SQL path.

Works without an OpenTelemetry SDK/exporter. SQL, question text, parameters,
credentials and exception messages are deliberately excluded from summaries.
"""
from __future__ import annotations

import contextlib
import functools
import inspect
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

logger = logging.getLogger(__name__)
_active: ContextVar = ContextVar("nl2sql_timing_run", default=None)
_stack: ContextVar[tuple] = ContextVar("nl2sql_timing_stack", default=())
_sink_lock = threading.Lock()
_sink_path = None
_sink_handler = None
_MAX_STEPS = 512
_ATTRIBUTES = frozenset({
    "purpose", "provider", "model", "actual_model", "route", "attempt",
    "candidate_count", "field_count", "metric_count", "result_rows", "truncated",
    "dispatched", "prompt_tokens", "completion_tokens", "total_tokens",
    "error_code", "fallback_reason", "catalog_sha256", "version",
})


def _attributes(values):
    return {key: value[:160] if isinstance(value, str) else value
            for key, value in values.items() if key in _ATTRIBUTES
            and (value is None or type(value) in (str, int, bool))}


@dataclass
class Step:
    stage: str
    parent_id: str | None
    start_ns: int
    step_id: str = field(default_factory=lambda: uuid4().hex[:16])
    end_ns: int | None = None
    status: str = "ok"
    attributes: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    child_timings_incomplete: bool = False
    otel_span: object = None

    def annotate(self, **attributes):
        cleaned = _attributes(attributes)
        self.attributes.update(cleaned)
        if self.otel_span is not None:
            try:
                for key, value in cleaned.items():
                    if value is not None:
                        self.otel_span.set_attribute("nl2sql." + key, value)
            except Exception:
                pass


@dataclass
class Run:
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    correlation_id: str = ""
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    steps: list = field(default_factory=list)
    occurrences: dict = field(default_factory=dict)
    dropped_steps: int = 0
    otel_recording: bool = False
    route: str = "unknown"
    fallback: bool = False
    degraded: bool = False


def current_run():
    return _active.get()


def annotate_stage(**attributes):
    stack = _stack.get()
    if stack:
        stack[-1].annotate(**attributes)


def record_route(route: str, *, fallback: bool = False):
    run = _active.get()
    if run is not None:
        run.route = route if route in {"sql", "registered_ir", "candidates"} else "unknown"
        run.fallback = run.fallback or fallback
    annotate_stage(route=route)


@contextlib.contextmanager
def stage(name: str, **attributes):
    run = _active.get()
    if run is None:
        yield None
        return
    parents = _stack.get()
    item = Step(name, parents[-1].step_id if parents else None, time.perf_counter_ns())
    run.occurrences[name] = run.occurrences.get(name, 0) + 1
    if name == "llm.request":
        for parent in reversed(parents):
            if "purpose" in parent.attributes:
                item.annotate(purpose=parent.attributes["purpose"])
                break
    item.annotate(**{"attempt": run.occurrences[name], **attributes})
    if parents:
        # Keep child intervals even when the serialized trace hits its cap.
        if len(parents[-1].children) < _MAX_STEPS:
            parents[-1].children.append(item)
        else:
            parents[-1].child_timings_incomplete = True
    if len(run.steps) < _MAX_STEPS:
        run.steps.append(item)
    else:
        run.dropped_steps += 1
    token = _stack.set((*parents, item))
    otel_context = None
    try:
        from .otel_tracing import get_tracer
        tracer = get_tracer()
        if tracer is not None:
            # OTel's automatic exception event includes exception messages.
            # Record only a controlled class/code below instead.
            otel_context = tracer.start_as_current_span(
                name, record_exception=False, set_status_on_exception=False)
            item.otel_span = otel_context.__enter__()
            if item.otel_span.is_recording():
                run.otel_recording = True
            if not parents:
                sc = item.otel_span.get_span_context()
                if sc.is_valid:
                    run.trace_id = format(sc.trace_id, "032x")
            item.annotate(**item.attributes)
    except Exception:
        run.degraded = True
    try:
        yield item
    except BaseException as exc:
        item.status = ("cancelled" if type(exc).__name__ == "CancelledError" else
                       "interrupted" if not isinstance(exc, Exception) else "error")
        item.annotate(error_code=type(exc).__name__)
        raise
    finally:
        item.end_ns = time.perf_counter_ns()
        _stack.reset(token)
        if item.otel_span is not None:
            try:
                from opentelemetry.trace import Status, StatusCode
                item.otel_span.set_attribute("nl2sql.status", item.status)
                if item.status not in {"ok", "skipped"}:
                    item.otel_span.set_status(Status(StatusCode.ERROR))
            except Exception:
                run.degraded = True
        if otel_context is not None:
            try:
                otel_context.__exit__(None, None, None)
            except Exception:
                run.degraded = True


def _returned_status(result):
    if isinstance(result, str) and result.lstrip().startswith("{"):
        try:
            result = json.loads(result)
        except (ValueError, TypeError):
            return "ok"
    if isinstance(result, dict):
        status = result.get("status")
        if status in {"unsupported", "rejected", "error", "cancelled", "interrupted"}:
            return status
        if result.get("error"):
            return "error"
    if getattr(result, "rejected", False):
        return "rejected"
    return "ok"


def observe_stage(name, *, rejected_when=None):
    """Instrument sync/async boundaries without reading arguments or content."""
    def decorate(fn):
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapped(*args, **kwargs):
                with stage(name) as item:
                    result = await fn(*args, **kwargs)
                    if item is not None:
                        item.status = "rejected" if rejected_when and rejected_when(result) else _returned_status(result)
                    return result
            return async_wrapped

        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            with stage(name) as item:
                result = fn(*args, **kwargs)
                if item is not None:
                    item.status = "rejected" if rejected_when and rejected_when(result) else _returned_status(result)
                return result
        return wrapped
    return decorate


def _child_union_ns(item, end_ns):
    intervals = sorted((max(item.start_ns, child.start_ns), min(end_ns, child.end_ns))
                       for child in item.children if child.end_ns is not None)
    total = 0
    right = item.start_ns
    for left, end in intervals:
        total += max(0, end - max(left, right))
        right = max(right, end)
    return total


def summarize(run):
    root = run.steps[0]
    records = []
    for item in run.steps:
        end = item.end_ns if item.end_ns is not None else time.perf_counter_ns()
        duration_ns = end - item.start_ns
        records.append({
            "step_id": item.step_id, "parent_id": item.parent_id, "stage": item.stage,
            "start_ms": round((item.start_ns - root.start_ns) / 1e6, 3),
            "duration_ms": round(duration_ns / 1e6, 3),
            "self_ms": (None if item.child_timings_incomplete or item.end_ns is None else
                        round(max(0, duration_ns - _child_union_ns(item, end)) / 1e6, 3)),
            "status": item.status if item.end_ns is not None else "incomplete",
            "attributes": dict(item.attributes),
        })
    measured = [item for item in records[1:] if item["parent_id"] == root.step_id]
    failures = [item for item in records[1:] if item["status"] not in {"ok", "skipped"}]
    failed = min(failures, key=lambda s: (s["start_ms"] + s["duration_ms"], -s["start_ms"]), default=None)
    return {
        "version": "nl2sql-step-timing-v1", "trace_id": run.trace_id,
        "correlation_id": run.correlation_id, "started_at": run.started_at,
        "status": root.status, "route": run.route, "fallback": run.fallback,
        "total_ms": records[0]["duration_ms"], "steps": records,
        "slowest_top_level_stage": max(measured, key=lambda s: s["duration_ms"])["stage"] if measured else None,
        "first_failed_stage": failed["stage"] if failed else None,
        "otel_recording": run.otel_recording, "observability_degraded": run.degraded,
        "dropped_steps": run.dropped_steps,
        "timing_scope": "product_function; excludes HTTP authentication, Agent queue and browser rendering",
    }


def _persist_summary(summary):
    """Rotated local fallback, with no question, SQL, values or user identity."""
    global _sink_path, _sink_handler
    path = Path(os.environ.get("GDA_NL2SQL_TRACE_SUMMARY_PATH") or
                Path(__file__).resolve().parents[1] / "logs" / "nl2sql_steps.jsonl").expanduser()
    with _sink_lock:
        if _sink_path != path or _sink_handler is None:
            if _sink_handler is not None:
                _sink_handler.close()
                _sink_handler = None
            _sink_path = None
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(path, maxBytes=10 * 1024 * 1024, backupCount=3,
                                          encoding="utf-8", delay=False)
            handler.setFormatter(logging.Formatter("%(message)s"))
            _sink_handler = handler
            _sink_path = path
        record = logging.LogRecord(__name__, logging.INFO, "", 0,
                                   json.dumps(summary, ensure_ascii=False), (), None)
        # Handler.emit normally swallows I/O errors, masking telemetry failure.
        if _sink_handler.shouldRollover(record):
            _sink_handler.doRollover()
        _sink_handler.stream.write(_sink_handler.format(record) + "\n")
        _sink_handler.flush()


def _finish(run):
    try:
        summary = summarize(run)
    except Exception:
        # A broken exporter/summary must not turn a completed query into an
        # error or mask the original product exception. Keep a minimal marker.
        summary = {
            "version": "nl2sql-step-timing-v1", "trace_id": run.trace_id,
            "status": run.steps[0].status if run.steps else "unknown",
            "route": run.route, "observability_degraded": True,
            "summary_persisted": False, "steps": [],
        }
    try:
        from .observability import record_nl2sql_timing
        record_nl2sql_timing(summary)
    except Exception:
        summary["observability_degraded"] = True
    try:
        summary["summary_persisted"] = True
        _persist_summary(summary)
    except Exception:
        summary["summary_persisted"] = False
        summary["observability_degraded"] = True
        # Do not log a path/exception that might contain an embedded credential.
        try:
            logger.warning("nl2sql trace summary persistence failed; trace_id=%s", run.trace_id)
        except Exception:
            pass
    try:
        logger.info("nl2sql_run_summary %s", json.dumps(summary, ensure_ascii=False))
    except Exception:
        summary["observability_degraded"] = True
    return summary


def observe_request(fn):
    """Keep every early rejection/exception visible; do not change business status."""
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        if _active.get() is not None:
            with stage("candidate.attempt") as item:
                result = fn(*args, **kwargs)
                item.status = _returned_status(result)
                return result
        from .user_context import current_trace_id
        run = Run(correlation_id=current_trace_id.get("")[:160])
        run_token = _active.set(run)
        stack_token = _stack.set(())
        trace_token = None
        try:
            with stage("gda.nl2sql.request") as root:
                trace_token = current_trace_id.set(run.trace_id)
                result = fn(*args, **kwargs)
                root.status = _returned_status(result)
            summary = _finish(run)
            if isinstance(result, str):
                try:
                    payload = json.loads(result)
                except (ValueError, TypeError):
                    return result
                if isinstance(payload, dict):
                    payload["observability"] = summary
                    return json.dumps(payload, ensure_ascii=False)
            return result
        except BaseException:
            _finish(run)
            raise
        finally:
            if trace_token is not None:
                current_trace_id.reset(trace_token)
            _stack.reset(stack_token)
            _active.reset(run_token)
    return wrapped
