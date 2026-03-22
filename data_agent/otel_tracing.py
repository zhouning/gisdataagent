"""
OpenTelemetry distributed tracing for GIS Data Agent (v15.0).

Provides context managers for creating nested spans across pipeline execution:
Pipeline → Agent → LLM Call / Tool Call.

Graceful degradation: if opentelemetry is not installed, all context managers
are no-ops. Set OTEL_EXPORTER_OTLP_ENDPOINT to enable OTLP export.
"""

import contextlib
import logging
import os
import time

logger = logging.getLogger(__name__)

_tracer = None
_initialized = False

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def setup_otel_tracing():
    """Initialize OpenTelemetry TracerProvider. Call once at app startup."""
    global _tracer, _initialized
    if _initialized:
        return
    _initialized = True

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider()

        otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        if otlp_endpoint:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info("[OTel] OTLP exporter → %s", otlp_endpoint)
        elif os.environ.get("OTEL_CONSOLE", "").lower() in ("1", "true"):
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
            logger.info("[OTel] Console exporter enabled")
        else:
            logger.info("[OTel] No exporter configured (metrics-only mode)")

        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("gis_data_agent", "15.0")
        logger.info("[OTel] TracerProvider initialized")
    except ImportError:
        logger.debug("[OTel] opentelemetry not installed — tracing disabled")
    except Exception as e:
        logger.warning("[OTel] Setup failed: %s", e)


def get_tracer():
    """Return the global tracer, or None if not initialized."""
    return _tracer


# ---------------------------------------------------------------------------
# Context managers for span creation
# ---------------------------------------------------------------------------

@contextlib.asynccontextmanager
async def trace_pipeline_run(pipeline_type: str, intent: str = "", trace_id: str = ""):
    """Root span for a pipeline execution."""
    tracer = get_tracer()
    if not tracer:
        yield {}
        return

    from opentelemetry import trace
    from data_agent.user_context import current_user_id, current_session_id

    with tracer.start_as_current_span(
        f"pipeline:{pipeline_type}",
        attributes={
            "pipeline.type": pipeline_type,
            "pipeline.intent": intent,
            "user.id": current_user_id.get(""),
            "session.id": current_session_id.get(""),
            "trace.correlation_id": trace_id,
        },
    ) as span:
        ctx = {"span": span, "start_time": time.monotonic()}
        try:
            yield ctx
        finally:
            duration = time.monotonic() - ctx["start_time"]
            span.set_attribute("pipeline.duration_ms", round(duration * 1000, 1))


@contextlib.asynccontextmanager
async def trace_agent_run(agent_name: str, pipeline_type: str = ""):
    """Child span for an agent execution within a pipeline."""
    tracer = get_tracer()
    if not tracer:
        yield {}
        return

    with tracer.start_as_current_span(
        f"agent:{agent_name}",
        attributes={
            "agent.name": agent_name,
            "agent.pipeline_type": pipeline_type,
        },
    ) as span:
        ctx = {"span": span, "start_time": time.monotonic()}
        try:
            yield ctx
        finally:
            duration = time.monotonic() - ctx["start_time"]
            span.set_attribute("agent.duration_ms", round(duration * 1000, 1))


@contextlib.asynccontextmanager
async def trace_tool_call(tool_name: str, agent_name: str = "", args_keys: list = None):
    """Child span for a tool invocation."""
    tracer = get_tracer()
    if not tracer:
        yield {}
        return

    with tracer.start_as_current_span(
        f"tool:{tool_name}",
        attributes={
            "tool.name": tool_name,
            "tool.agent": agent_name,
            "tool.args_keys": ",".join(args_keys or []),
        },
    ) as span:
        ctx = {"span": span, "start_time": time.monotonic()}
        try:
            yield ctx
        finally:
            duration = time.monotonic() - ctx["start_time"]
            span.set_attribute("tool.duration_ms", round(duration * 1000, 1))


@contextlib.asynccontextmanager
async def trace_llm_call(agent_name: str, model_name: str = ""):
    """Child span for an LLM invocation."""
    tracer = get_tracer()
    if not tracer:
        yield {}
        return

    with tracer.start_as_current_span(
        f"llm:{model_name or 'unknown'}",
        attributes={
            "llm.model": model_name,
            "llm.agent": agent_name,
            "llm.provider": "google",
        },
    ) as span:
        ctx = {"span": span, "start_time": time.monotonic()}
        try:
            yield ctx
        finally:
            duration = time.monotonic() - ctx["start_time"]
            span.set_attribute("llm.duration_ms", round(duration * 1000, 1))
