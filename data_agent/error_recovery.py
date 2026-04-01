"""
Error Recovery Engine — automatic recovery from pipeline/DAG failures.

Five strategies in priority order:
1. Retry        — transient errors (timeout, rate-limit)
2. Alternative  — swap to fallback tool
3. Simplify     — reduce scope (sample, lower resolution)
4. Skip         — non-critical step, continue pipeline
5. Escalate     — generate human intervention request

ErrorRecoveryEngine chains strategies: first match wins.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .pipeline_helpers import classify_error
from .observability import get_logger

logger = get_logger("error_recovery")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RecoveryAction:
    """Outcome of a recovery attempt."""
    strategy_name: str
    action: str  # "retry" | "substitute" | "skip" | "simplify" | "escalate"
    modified_kwargs: dict = field(default_factory=dict)
    reason: str = ""
    success: bool = False  # set True after execution confirms recovery worked

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy_name,
            "action": self.action,
            "reason": self.reason,
            "success": self.success,
            "modified_kwargs": self.modified_kwargs,
        }


@dataclass
class RecoveryContext:
    """Context passed to recovery strategies."""
    step_id: str = ""
    step_label: str = ""
    pipeline_type: str = ""
    prompt: str = ""
    error_message: str = ""
    error_category: str = ""  # from classify_error
    is_retryable: bool = False
    attempt_count: int = 0  # how many times this step has been tried
    is_critical: bool = True  # can this step be skipped?
    tool_name: str = ""  # if failure was from a specific tool
    node_outputs: dict = field(default_factory=dict)  # upstream results


# ---------------------------------------------------------------------------
# Tool alternatives mapping
# ---------------------------------------------------------------------------

TOOL_ALTERNATIVES: dict[str, list[str]] = {
    "arcpy_extract_watershed": ["extract_watershed"],
    "arcpy_clip_analysis": ["pairwise_clip"],
    "arcpy_buffer_analysis": ["create_buffer"],
    "kriging_interpolation": ["idw_interpolation"],
    "drl_model": ["drl_multi_objective"],
    "batch_geocode": ["reverse_geocode"],
    "generate_heatmap": ["visualize_interactive_map"],
    "generate_choropleth": ["visualize_interactive_map"],
    "spatial_autocorrelation": ["hotspot_analysis"],
}

# Steps that can be safely skipped without breaking the pipeline
SKIPPABLE_STEP_LABELS = frozenset({
    "可视化", "visualization", "report", "报告",
    "export", "导出", "summary", "总结",
    "quality_check", "质量检查",
})


# ---------------------------------------------------------------------------
# Strategy ABC
# ---------------------------------------------------------------------------

class ErrorRecoveryStrategy(ABC):
    """Base class for recovery strategies."""

    name: str = ""
    priority: int = 0  # lower = tried first

    @abstractmethod
    def can_handle(self, ctx: RecoveryContext) -> bool:
        """Return True if this strategy can attempt recovery."""

    @abstractmethod
    def recover(self, ctx: RecoveryContext) -> RecoveryAction:
        """Produce a recovery action. Does NOT execute — just plans."""


# ---------------------------------------------------------------------------
# Concrete strategies
# ---------------------------------------------------------------------------

class RetryStrategy(ErrorRecoveryStrategy):
    """Retry transient errors with exponential backoff."""
    name = "retry"
    priority = 10
    MAX_RETRIES = 2

    def can_handle(self, ctx: RecoveryContext) -> bool:
        return ctx.is_retryable and ctx.attempt_count <= self.MAX_RETRIES

    def recover(self, ctx: RecoveryContext) -> RecoveryAction:
        delay = min(2 ** ctx.attempt_count, 8)
        return RecoveryAction(
            strategy_name=self.name,
            action="retry",
            reason=f"Transient error ({ctx.error_category}), retry #{ctx.attempt_count + 1} after {delay}s",
            modified_kwargs={"_retry_delay": delay},
        )


class AlternativeToolStrategy(ErrorRecoveryStrategy):
    """Substitute a failed tool with a fallback alternative."""
    name = "alternative_tool"
    priority = 20

    def can_handle(self, ctx: RecoveryContext) -> bool:
        if not ctx.tool_name:
            return False
        return ctx.tool_name in TOOL_ALTERNATIVES and len(TOOL_ALTERNATIVES[ctx.tool_name]) > 0

    def recover(self, ctx: RecoveryContext) -> RecoveryAction:
        alternatives = TOOL_ALTERNATIVES[ctx.tool_name]
        fallback = alternatives[0]
        return RecoveryAction(
            strategy_name=self.name,
            action="substitute",
            reason=f"Tool '{ctx.tool_name}' failed, substituting with '{fallback}'",
            modified_kwargs={"_substitute_tool": fallback, "_original_tool": ctx.tool_name},
        )


class SimplifyStrategy(ErrorRecoveryStrategy):
    """Simplify the task when data is too large or complex."""
    name = "simplify"
    priority = 30

    _SIMPLIFY_KEYWORDS = frozenset({
        "memory", "oom", "out of memory", "too large", "exceeded",
        "resource", "killed", "cannot allocate", "内存不足", "数据过大",
    })

    def can_handle(self, ctx: RecoveryContext) -> bool:
        msg = ctx.error_message.lower()
        return any(kw in msg for kw in self._SIMPLIFY_KEYWORDS)

    def recover(self, ctx: RecoveryContext) -> RecoveryAction:
        return RecoveryAction(
            strategy_name=self.name,
            action="simplify",
            reason="Data too large or complex, simplifying (sample/reduce resolution)",
            modified_kwargs={
                "_simplify": True,
                "_sample_ratio": 0.5,
                "_add_prompt_suffix": "注意：因资源限制，请对数据采样处理（取前50%行）后再分析。",
            },
        )


class SkipAndContinueStrategy(ErrorRecoveryStrategy):
    """Skip non-critical steps and continue the pipeline."""
    name = "skip"
    priority = 40

    def can_handle(self, ctx: RecoveryContext) -> bool:
        if ctx.is_critical:
            return False
        label_lower = ctx.step_label.lower()
        return any(kw in label_lower for kw in SKIPPABLE_STEP_LABELS)

    def recover(self, ctx: RecoveryContext) -> RecoveryAction:
        return RecoveryAction(
            strategy_name=self.name,
            action="skip",
            reason=f"Non-critical step '{ctx.step_label}' failed, skipping to continue pipeline",
        )


class HumanInterventionStrategy(ErrorRecoveryStrategy):
    """Last resort — escalate to human for manual resolution."""
    name = "escalate"
    priority = 100  # always last

    def can_handle(self, ctx: RecoveryContext) -> bool:
        return True  # catch-all

    def recover(self, ctx: RecoveryContext) -> RecoveryAction:
        return RecoveryAction(
            strategy_name=self.name,
            action="escalate",
            reason=f"Cannot auto-recover step '{ctx.step_label}': {ctx.error_message[:200]}",
        )


# ---------------------------------------------------------------------------
# Recovery Engine
# ---------------------------------------------------------------------------

class ErrorRecoveryEngine:
    """Chains recovery strategies by priority. First match wins."""

    def __init__(self):
        self.strategies: list[ErrorRecoveryStrategy] = sorted([
            RetryStrategy(),
            AlternativeToolStrategy(),
            SimplifyStrategy(),
            SkipAndContinueStrategy(),
            HumanInterventionStrategy(),
        ], key=lambda s: s.priority)

    def attempt_recovery(self, error: Exception, step: dict,
                         node_outputs: dict | None = None,
                         attempt_count: int = 0) -> RecoveryAction:
        """Try each strategy in priority order. Return first viable action."""
        is_retryable, error_category = classify_error(error)

        # Extract tool name from error or step
        tool_name = ""
        error_msg = str(error)
        if "tool_name" in step:
            tool_name = step["tool_name"]

        # Determine if step is critical (default: True)
        is_critical = step.get("critical", True)
        label = step.get("label", step.get("step_id", ""))

        ctx = RecoveryContext(
            step_id=step.get("step_id", ""),
            step_label=label,
            pipeline_type=step.get("pipeline_type", ""),
            prompt=step.get("prompt", ""),
            error_message=error_msg,
            error_category=error_category,
            is_retryable=is_retryable,
            attempt_count=attempt_count,
            is_critical=is_critical,
            tool_name=tool_name,
            node_outputs=node_outputs or {},
        )

        for strategy in self.strategies:
            if strategy.can_handle(ctx):
                action = strategy.recover(ctx)
                logger.info("Recovery: step=%s strategy=%s action=%s reason=%s",
                            ctx.step_id, action.strategy_name, action.action, action.reason)
                return action

        # Should never reach here (HumanInterventionStrategy is catch-all)
        return RecoveryAction(
            strategy_name="none",
            action="escalate",
            reason="No recovery strategy matched",
        )


# Module-level singleton
_engine = ErrorRecoveryEngine()


def attempt_recovery(error: Exception, step: dict,
                     node_outputs: dict | None = None,
                     attempt_count: int = 0) -> RecoveryAction:
    """Convenience function using the singleton engine."""
    return _engine.attempt_recovery(error, step, node_outputs, attempt_count)
