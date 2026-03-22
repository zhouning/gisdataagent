"""
Agent Plugins for GIS Data Agent (v9.0.1).

Three ADK plugins that plug into the Runner lifecycle:

- CostGuardPlugin:  Token budget control (warn/abort thresholds)
- GISToolRetryPlugin: Auto-retry on {"status":"error"} + failure_learning integration
- ProvenancePlugin:  Decision audit trail in session state

Usage::

    from data_agent.plugins import build_plugin_stack
    plugins = build_plugin_stack()
    runner = Runner(..., plugins=plugins)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

from google.adk.plugins.base_plugin import BasePlugin
from google.adk.plugins.reflect_retry_tool_plugin import (
    ReflectAndRetryToolPlugin,
    TrackingScope,
)
from google.genai import types

logger = logging.getLogger("data_agent.plugins")


# ---------------------------------------------------------------------------
# CostGuardPlugin
# ---------------------------------------------------------------------------

class CostGuardPlugin(BasePlugin):
    """Token budget control plugin.

    Tracks cumulative token usage across all LLM calls in a pipeline run.
    Emits a warning when ``warn_threshold`` is reached and aborts the
    pipeline (by returning a stop LlmResponse) when ``abort_threshold``
    is exceeded.

    Thresholds can be set via env vars ``COST_GUARD_WARN`` and
    ``COST_GUARD_ABORT`` (integer token counts).
    """

    STATE_KEY = "__cost_guard_tokens__"

    def __init__(
        self,
        warn_threshold: int = 0,
        abort_threshold: int = 0,
    ):
        super().__init__(name="cost_guard")
        self.warn_threshold = warn_threshold or int(
            os.environ.get("COST_GUARD_WARN", "50000")
        )
        self.abort_threshold = abort_threshold or int(
            os.environ.get("COST_GUARD_ABORT", "200000")
        )
        self._warned = False

    async def before_model_callback(self, *, callback_context, llm_request):
        """Check accumulated tokens before each LLM call."""
        accumulated = callback_context.state.get(self.STATE_KEY, 0)
        if accumulated >= self.abort_threshold:
            logger.warning(
                "CostGuard: budget exceeded (%d >= %d), aborting pipeline",
                accumulated, self.abort_threshold,
            )
            from google.adk.models.llm_response import LlmResponse
            return LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(text=(
                        f"[CostGuard] Token budget exceeded "
                        f"({accumulated:,} >= {self.abort_threshold:,}). "
                        f"Pipeline aborted to prevent excessive cost."
                    ))],
                ),
                turn_complete=True,
            )
        return None

    async def after_model_callback(self, *, callback_context, llm_response):
        """Accumulate token usage after each LLM response."""
        usage = getattr(llm_response, "usage_metadata", None)
        if usage:
            prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
            output_tokens = getattr(usage, "candidates_token_count", 0) or 0
            delta = prompt_tokens + output_tokens
            accumulated = callback_context.state.get(self.STATE_KEY, 0) + delta
            callback_context.state[self.STATE_KEY] = accumulated

            # Record LLM metrics for Prometheus (v14.5)
            try:
                from .observability import record_llm_call
                agent_name = getattr(callback_context, 'agent_name', '') or 'unknown'
                model = getattr(llm_response, 'model', '') or 'unknown'
                record_llm_call(agent_name, model, prompt_tokens, output_tokens)
            except Exception:
                pass

            if not self._warned and accumulated >= self.warn_threshold:
                self._warned = True
                logger.warning(
                    "CostGuard: token usage warning (%d >= %d)",
                    accumulated, self.warn_threshold,
                )
        return None


# ---------------------------------------------------------------------------
# GISToolRetryPlugin
# ---------------------------------------------------------------------------

class GISToolRetryPlugin(ReflectAndRetryToolPlugin):
    """Tool retry plugin with GIS-specific error detection.

    Extends ADK's ReflectAndRetryToolPlugin to:
    1. Detect ``{"status": "error", ...}`` responses (project convention)
    2. Record failures to ``failure_learning`` DB for cross-session learning
    """

    def __init__(
        self,
        max_retries: int = 2,
        throw_exception_if_retry_exceeded: bool = False,
    ):
        super().__init__(
            name="gis_tool_retry",
            max_retries=max_retries,
            throw_exception_if_retry_exceeded=throw_exception_if_retry_exceeded,
            tracking_scope=TrackingScope.INVOCATION,
        )

    async def extract_error_from_result(
        self, *, tool, tool_args, tool_context, result
    ) -> Optional[dict[str, Any]]:
        """Detect error status in tool results (GIS project convention)."""
        if isinstance(result, dict) and result.get("status") == "error":
            return result
        return None

    async def on_tool_error_callback(
        self, *, tool, tool_args, tool_context, error
    ) -> Optional[dict[str, Any]]:
        """Handle tool errors and record to failure_learning DB."""
        self._record_failure(tool.name, str(error))
        return await super().on_tool_error_callback(
            tool=tool, tool_args=tool_args,
            tool_context=tool_context, error=error,
        )

    async def after_tool_callback(
        self, *, tool, tool_args, tool_context, result
    ) -> Optional[dict[str, Any]]:
        """Override to also record soft errors to failure_learning."""
        if isinstance(result, dict) and result.get("status") == "error":
            self._record_failure(
                tool.name,
                str(result.get("message", ""))[:200],
            )
        return await super().after_tool_callback(
            tool=tool, tool_args=tool_args,
            tool_context=tool_context, result=result,
        )

    @staticmethod
    def _record_failure(tool_name: str, error_snippet: str) -> None:
        """Record failure to DB (non-fatal)."""
        try:
            from data_agent.failure_learning import record_failure
            record_failure(tool_name, error_snippet)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# ProvenancePlugin
# ---------------------------------------------------------------------------

class ProvenancePlugin(BasePlugin):
    """Decision audit trail plugin.

    Records which agent invoked which tools, in what order, with what
    outcomes.  The trail is stored in session state under
    ``__provenance_trail__`` and can be extracted from PipelineResult.
    """

    STATE_KEY = "__provenance_trail__"

    def __init__(self):
        super().__init__(name="provenance")

    async def after_agent_callback(self, *, agent, callback_context):
        """Record agent completion."""
        trail = callback_context.state.get(self.STATE_KEY, [])
        trail.append({
            "type": "agent",
            "agent": agent.name,
            "timestamp": time.time(),
        })
        callback_context.state[self.STATE_KEY] = trail
        return None

    async def after_tool_callback(
        self, *, tool, tool_args, tool_context, result
    ):
        """Record tool execution."""
        trail = tool_context.state.get(self.STATE_KEY, [])
        is_error = (
            isinstance(result, dict) and result.get("status") == "error"
        )
        trail.append({
            "type": "tool",
            "tool": tool.name,
            "agent": getattr(tool_context, "agent_name", ""),
            "args_keys": list(tool_args.keys()) if tool_args else [],
            "is_error": is_error,
            "timestamp": time.time(),
        })
        tool_context.state[self.STATE_KEY] = trail
        return None


# ---------------------------------------------------------------------------
# Plugin stack assembly
# ---------------------------------------------------------------------------

def build_plugin_stack() -> list[BasePlugin]:
    """Assemble the plugin stack from environment variables.

    Reads the following env vars (all default to ``"true"``):

    - ``COST_GUARD_ENABLED``
    - ``TOOL_RETRY_ENABLED``
    - ``PROVENANCE_ENABLED``

    The HITL plugin is handled separately in ``app.py`` since it
    requires the Chainlit approval function injection.

    Returns:
        Ordered list of plugins: [CostGuard, ToolRetry, Provenance].
    """
    def _is_enabled(var: str, default: str = "true") -> bool:
        return os.environ.get(var, default).strip().lower() not in (
            "false", "0", "no",
        )

    plugins: list[BasePlugin] = []

    if _is_enabled("COST_GUARD_ENABLED"):
        plugins.append(CostGuardPlugin())

    if _is_enabled("TOOL_RETRY_ENABLED"):
        plugins.append(GISToolRetryPlugin())

    if _is_enabled("PROVENANCE_ENABLED"):
        plugins.append(ProvenancePlugin())

    return plugins
