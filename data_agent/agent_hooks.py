"""
Agent Lifecycle Hooks for GIS Data Agent (v9.0.6).

Per-agent before/after callbacks that provide:
- Prometheus metrics (agent invocations, durations)
- Structured logging for agent lifecycle events
- Pipeline progress tracking (ProgressTracker)

Usage::

    from data_agent.agent_hooks import attach_lifecycle_hooks
    attach_lifecycle_hooks(data_pipeline, "optimization")
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from google.genai import types

logger = logging.getLogger("data_agent.agent_hooks")


# ---------------------------------------------------------------------------
# Prometheus metrics (lazy registration to avoid import-time side effects)
# ---------------------------------------------------------------------------

_agent_invocations = None
_agent_duration = None


def _ensure_metrics():
    """Lazily register Prometheus metrics on first use."""
    global _agent_invocations, _agent_duration
    if _agent_invocations is not None:
        return
    from prometheus_client import Counter, Histogram
    _agent_invocations = Counter(
        "agent_invocations_total",
        "Total per-agent invocations",
        ["agent_name", "pipeline_type"],
    )
    _agent_duration = Histogram(
        "agent_duration_seconds",
        "Per-agent execution duration",
        ["agent_name", "pipeline_type"],
        buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 300),
    )


# ---------------------------------------------------------------------------
# ProgressTracker
# ---------------------------------------------------------------------------

class ProgressTracker:
    """Track pipeline execution progress by agent completion.

    Maintains a list of expected agents per pipeline type and reports
    completion percentage as agents complete.
    """

    # Default agent lists per pipeline type
    PIPELINE_AGENTS: dict[str, list[str]] = {
        "optimization": [
            "DataExploration", "DataProcessing",
            "DataAnalysis", "DataVisualization", "DataSummary",
        ],
        "governance": [
            "GovExploration", "GovProcessing", "GovernanceReporter",
        ],
        "general": [
            "GeneralProcessing", "GeneralViz", "GeneralSummary",
        ],
        "planner": [
            "PlannerAgent",
        ],
    }

    def __init__(self, pipeline_type: str):
        self.pipeline_type = pipeline_type
        self.expected = self.PIPELINE_AGENTS.get(pipeline_type, [])
        self.completed: list[str] = []

    def update(self, agent_name: str) -> dict:
        """Record an agent completion and return progress info."""
        if agent_name not in self.completed:
            self.completed.append(agent_name)
        total = max(len(self.expected), len(self.completed))
        return {
            "completed": len(self.completed),
            "total": total,
            "current_agent": agent_name,
            "percent": round(len(self.completed) / total * 100, 1) if total > 0 else 0,
        }


# ---------------------------------------------------------------------------
# Callback functions
# ---------------------------------------------------------------------------

_START_TIME_KEY = "__agent_start_{name}__"
_COMPLETED_KEY = "__completed_agents__"


async def before_pipeline_agent(
    *, agent: Any, callback_context: Any
) -> Optional[types.Content]:
    """Record agent start time and increment Prometheus counter."""
    _ensure_metrics()
    name = agent.name
    pipeline_type = callback_context.state.get("__pipeline_type__", "unknown")

    # Record start time
    key = _START_TIME_KEY.format(name=name)
    callback_context.state[key] = time.time()

    # Prometheus counter
    _agent_invocations.labels(
        agent_name=name, pipeline_type=pipeline_type
    ).inc()

    logger.debug("Agent started: %s (pipeline=%s)", name, pipeline_type)
    return None  # Don't short-circuit


async def after_pipeline_agent(
    *, agent: Any, callback_context: Any
) -> Optional[types.Content]:
    """Record agent duration, update Prometheus histogram and progress."""
    _ensure_metrics()
    name = agent.name
    pipeline_type = callback_context.state.get("__pipeline_type__", "unknown")

    # Compute duration
    key = _START_TIME_KEY.format(name=name)
    start = callback_context.state.get(key, 0)
    duration = time.time() - start if start else 0

    # Prometheus histogram
    _agent_duration.labels(
        agent_name=name, pipeline_type=pipeline_type
    ).observe(duration)

    # Track completed agents
    completed = callback_context.state.get(_COMPLETED_KEY, [])
    completed.append(name)
    callback_context.state[_COMPLETED_KEY] = completed

    logger.debug(
        "Agent completed: %s (pipeline=%s, duration=%.1fs)",
        name, pipeline_type, duration,
    )
    return None  # Don't modify response


# ---------------------------------------------------------------------------
# Hook attachment
# ---------------------------------------------------------------------------

def attach_lifecycle_hooks(agent: Any, pipeline_type: str) -> None:
    """Recursively attach before/after callbacks to all LlmAgents in a tree.

    Only attaches to ``LlmAgent`` instances (not SequentialAgent,
    ParallelAgent, or LoopAgent shell agents) to avoid double-counting.

    Existing callbacks are preserved — hooks are prepended to the list.

    Args:
        agent: The root agent (pipeline) to walk.
        pipeline_type: Pipeline type string stored in session state.
    """
    from google.adk.agents import LlmAgent

    def _walk_and_attach(node: Any) -> None:
        if isinstance(node, LlmAgent):
            # Wrap existing before_agent_callback
            existing_before = getattr(node, "before_agent_callback", None)
            if existing_before and callable(existing_before):
                # Already a single callback — wrap in list
                node.before_agent_callback = [
                    before_pipeline_agent, existing_before,
                ]
            elif isinstance(existing_before, list):
                existing_before.insert(0, before_pipeline_agent)
            else:
                node.before_agent_callback = before_pipeline_agent

            # Wrap existing after_agent_callback
            existing_after = getattr(node, "after_agent_callback", None)
            if existing_after and callable(existing_after):
                node.after_agent_callback = [
                    after_pipeline_agent, existing_after,
                ]
            elif isinstance(existing_after, list):
                existing_after.insert(0, after_pipeline_agent)
            else:
                node.after_agent_callback = after_pipeline_agent

        # Recurse into sub_agents
        sub_agents = getattr(node, "sub_agents", None)
        if sub_agents:
            for sub in sub_agents:
                _walk_and_attach(sub)

    _walk_and_attach(agent)
