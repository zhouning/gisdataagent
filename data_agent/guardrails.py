"""
Agent Guardrails for GIS Data Agent (v9.5.3).

Input/output validation callbacks using ADK before/after_agent_callback.

Guardrails:
- InputLengthGuard: Reject超长输入 (>50k chars)
- SQLInjectionGuard: Detect SQL injection patterns
- OutputSanitizer: Remove sensitive info (API keys, passwords)
- HallucinationGuard: Detect hallucinated URLs/file paths

Usage::

    from data_agent.guardrails import attach_guardrails
    attach_guardrails(data_pipeline)
"""

from __future__ import annotations

import os
import re
import logging
from typing import Any, Optional

from google.genai import types

logger = logging.getLogger("data_agent.guardrails")

# Environment variable to disable guardrails (testing/debugging)
GUARDRAILS_DISABLED = os.getenv("GUARDRAILS_DISABLED", "0") == "1"


# ---------------------------------------------------------------------------
# Input Guardrails (before_agent_callback)
# ---------------------------------------------------------------------------

async def input_length_guard(
    *, agent: Any, callback_context: Any
) -> Optional[types.Content]:
    """Reject inputs exceeding 50k characters."""
    if GUARDRAILS_DISABLED:
        return None

    # Extract text from session events
    events = callback_context.session.events if hasattr(callback_context, "session") else []
    total_chars = sum(
        len(part.text)
        for event in events
        for part in getattr(event.content, "parts", [])
        if hasattr(part, "text") and part.text
    )

    if total_chars > 50_000:
        logger.warning(
            "InputLengthGuard: Rejected input with %d chars (limit: 50k)",
            total_chars,
        )
        return types.Content(
            role="model",
            parts=[types.Part(text=(
                "输入过长（超过 50,000 字符）。请缩短输入或分批处理。"
            ))],
        )
    return None


async def sql_injection_guard(
    *, agent: Any, callback_context: Any
) -> Optional[types.Content]:
    """Detect SQL injection patterns in user input."""
    if GUARDRAILS_DISABLED:
        return None

    # SQL injection patterns (basic heuristics)
    patterns = [
        r"(?i)(union\s+select|drop\s+table|delete\s+from|insert\s+into)",
        r"(?i)(exec\s*\(|execute\s*\(|xp_cmdshell)",
        r"(?i)(--|;--|/\*|\*/)",
        r"(?i)(or\s+1\s*=\s*1|and\s+1\s*=\s*1)",
    ]

    events = callback_context.session.events if hasattr(callback_context, "session") else []
    for event in events:
        for part in getattr(event.content, "parts", []):
            if hasattr(part, "text") and part.text:
                for pattern in patterns:
                    if re.search(pattern, part.text):
                        logger.warning(
                            "SQLInjectionGuard: Detected pattern '%s' in input",
                            pattern,
                        )
                        return types.Content(
                            role="model",
                            parts=[types.Part(text=(
                                "检测到可疑的 SQL 注入模式。请检查输入内容。"
                            ))],
                        )
    return None


# ---------------------------------------------------------------------------
# Output Guardrails (after_agent_callback)
# ---------------------------------------------------------------------------

async def output_sanitizer(
    *, agent: Any, callback_context: Any
) -> Optional[types.Content]:
    """Remove sensitive information from agent output."""
    if GUARDRAILS_DISABLED:
        return None

    # Patterns for API keys, passwords, tokens
    patterns = [
        (r"(?i)(api[_-]?key|apikey)\s*[:=]\s*['\"]?([a-zA-Z0-9_-]{20,})", "[API_KEY_REDACTED]"),
        (r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]?([^\s'\"]{6,})", "[PASSWORD_REDACTED]"),
        (r"(?i)(token|bearer)\s*[:=]\s*['\"]?([a-zA-Z0-9_-]{20,})", "[TOKEN_REDACTED]"),
        (r"sk-[a-zA-Z0-9]{20,}", "[OPENAI_KEY_REDACTED]"),
    ]

    # Get last agent output from session
    events = callback_context.session.events if hasattr(callback_context, "session") else []
    if not events:
        return None

    last_event = events[-1]
    if not hasattr(last_event, "content") or not last_event.content:
        return None

    modified = False
    new_parts = []
    for part in last_event.content.parts:
        if hasattr(part, "text") and part.text:
            text = part.text
            for pattern, replacement in patterns:
                if re.search(pattern, text):
                    text = re.sub(pattern, replacement, text)
                    modified = True
            new_parts.append(types.Part(text=text))
        else:
            new_parts.append(part)

    if modified:
        logger.warning("OutputSanitizer: Redacted sensitive info from output")
        return types.Content(role="model", parts=new_parts)
    return None


async def hallucination_guard(
    *, agent: Any, callback_context: Any
) -> Optional[types.Content]:
    """Detect hallucinated URLs and file paths in output."""
    if GUARDRAILS_DISABLED:
        return None

    # Patterns for URLs and file paths
    url_pattern = r"https?://[^\s]+"
    file_pattern = r"(?:C:|D:|/[a-z]+)/[^\s]+"

    events = callback_context.session.events if hasattr(callback_context, "session") else []
    if not events:
        return None

    last_event = events[-1]
    if not hasattr(last_event, "content") or not last_event.content:
        return None

    warnings = []
    for part in last_event.content.parts:
        if hasattr(part, "text") and part.text:
            # Check for URLs
            urls = re.findall(url_pattern, part.text)
            if urls:
                # Heuristic: if URL contains "example.com" or "localhost", likely hallucinated
                for url in urls:
                    if "example.com" in url or "localhost" in url:
                        warnings.append(f"可疑 URL: {url}")

            # Check for file paths
            paths = re.findall(file_pattern, part.text)
            if paths:
                # Heuristic: if path doesn't exist, likely hallucinated
                for path in paths:
                    if not os.path.exists(path):
                        warnings.append(f"文件路径可能不存在: {path}")

    if warnings:
        logger.warning("HallucinationGuard: Detected potential hallucinations")
        warning_text = "\n\n⚠️ 警告：检测到可能的幻觉内容：\n" + "\n".join(f"- {w}" for w in warnings)
        # Append warning to last part
        new_parts = list(last_event.content.parts)
        if new_parts and hasattr(new_parts[-1], "text"):
            new_parts[-1] = types.Part(text=new_parts[-1].text + warning_text)
        else:
            new_parts.append(types.Part(text=warning_text))
        return types.Content(role="model", parts=new_parts)

    return None


# ---------------------------------------------------------------------------
# Hook attachment
# ---------------------------------------------------------------------------

def attach_guardrails(agent: Any) -> None:
    """Recursively attach guardrail callbacks to all LlmAgents in a tree.

    Only attaches to ``LlmAgent`` instances (not SequentialAgent,
    ParallelAgent, or LoopAgent shell agents).

    Existing callbacks are preserved — guardrails are prepended to the list.

    Args:
        agent: The root agent (pipeline) to walk.
    """
    if GUARDRAILS_DISABLED:
        logger.info("Guardrails disabled via GUARDRAILS_DISABLED=1")
        return

    from google.adk.agents import LlmAgent

    def _walk_and_attach(node: Any) -> None:
        if isinstance(node, LlmAgent):
            # Attach input guardrails (before_agent_callback)
            existing_before = getattr(node, "before_agent_callback", None)
            input_guards = [input_length_guard, sql_injection_guard]

            if existing_before and callable(existing_before):
                node.before_agent_callback = input_guards + [existing_before]
            elif isinstance(existing_before, list):
                node.before_agent_callback = input_guards + existing_before
            else:
                node.before_agent_callback = input_guards

            # Attach output guardrails (after_agent_callback)
            existing_after = getattr(node, "after_agent_callback", None)
            output_guards = [output_sanitizer, hallucination_guard]

            if existing_after and callable(existing_after):
                node.after_agent_callback = output_guards + [existing_after]
            elif isinstance(existing_after, list):
                node.after_agent_callback = output_guards + existing_after
            else:
                node.after_agent_callback = output_guards

        # Recurse into sub_agents
        sub_agents = getattr(node, "sub_agents", None)
        if sub_agents:
            for sub in sub_agents:
                _walk_and_attach(sub)

    _walk_and_attach(agent)
    logger.info("Guardrails attached to agent tree")


# ===========================================================================
# D-4: Tool-Level Policy Engine (v16.0)
# ===========================================================================

import fnmatch
from dataclasses import dataclass, field

import yaml

_POLICY_PATH = os.path.join(os.path.dirname(__file__), "standards", "guardrail_policies.yaml")


@dataclass
class GuardrailPolicy:
    """A single guardrail policy rule."""
    role: str  # "viewer" | "analyst" | "admin" | "*"
    effect: str  # "deny" | "require_confirmation" | "allow"
    tools: list = field(default_factory=list)  # glob patterns
    reason: str = ""


@dataclass
class GuardrailDecision:
    """Result of policy evaluation."""
    effect: str  # "deny" | "require_confirmation" | "allow"
    policy_role: str = ""
    matched_pattern: str = ""
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "effect": self.effect,
            "policy_role": self.policy_role,
            "matched_pattern": self.matched_pattern,
            "reason": self.reason,
        }


class GuardrailEngine:
    """Evaluates YAML-driven policies against (role, tool_name) pairs."""

    def __init__(self, policy_path: str | None = None):
        self.policies: list[GuardrailPolicy] = []
        self._load(policy_path or _POLICY_PATH)

    def _load(self, path: str) -> None:
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            for p in data.get("policies", []):
                self.policies.append(GuardrailPolicy(
                    role=p.get("role", "*"),
                    effect=p.get("effect", "allow"),
                    tools=p.get("tools", []),
                    reason=p.get("reason", ""),
                ))
            logger.info("Loaded %d guardrail policies from %s", len(self.policies), path)
        except FileNotFoundError:
            logger.warning("Guardrail policy file not found: %s", path)
        except Exception as e:
            logger.warning("Failed to load guardrail policies: %s", e)

    def evaluate(self, role: str, tool_name: str) -> GuardrailDecision:
        """Evaluate policies. Admin explicit allow overrides. Deny > confirm > allow."""
        # Admin bypass
        for p in self.policies:
            if p.role == "admin" and p.effect == "allow" and "*" in p.tools:
                if role == "admin":
                    return GuardrailDecision("allow", "admin", "*", "管理员完全权限")

        best_decision = GuardrailDecision("allow")
        best_weight = -1

        for p in self.policies:
            if p.role != "*" and p.role != role:
                continue
            for pattern in p.tools:
                if fnmatch.fnmatch(tool_name, pattern):
                    specificity = (10 if p.role != "*" else 0) + (5 if pattern == tool_name else 0)
                    effect_priority = {"deny": 100, "require_confirmation": 50, "allow": 0}
                    weight = specificity * 1000 + effect_priority.get(p.effect, 0)
                    if weight > best_weight:
                        best_weight = weight
                        best_decision = GuardrailDecision(
                            effect=p.effect, policy_role=p.role,
                            matched_pattern=pattern, reason=p.reason,
                        )

        return best_decision

    def reload(self, path: str | None = None) -> None:
        self.policies.clear()
        self._load(path or _POLICY_PATH)


class GuardrailsPlugin:
    """ADK plugin: enforces tool-level policies via before_tool_callback."""

    def __init__(self, engine: GuardrailEngine | None = None):
        self.engine = engine or GuardrailEngine()

    async def before_tool_callback(self, *, tool, tool_args, tool_context, **kwargs):
        from .user_context import current_user_role
        role = current_user_role.get("anonymous")
        tool_name = tool.name if hasattr(tool, "name") else str(tool)

        decision = self.engine.evaluate(role, tool_name)

        if decision.effect == "deny":
            logger.warning("GUARDRAIL DENIED: role=%s tool=%s reason=%s",
                           role, tool_name, decision.reason)
            try:
                from .audit_logger import record_audit
                record_audit(
                    username=role, action="guardrail_denied", status="denied",
                    details={"tool": tool_name, "role": role,
                             "reason": decision.reason,
                             "matched_pattern": decision.matched_pattern},
                )
            except Exception:
                pass
            import json
            return json.dumps({
                "status": "blocked", "reason": decision.reason,
                "tool": tool_name, "role": role,
            }, ensure_ascii=False)

        return None  # allow or require_confirmation (HITL handles confirmation)


# Module-level singleton
_policy_engine: GuardrailEngine | None = None


def get_policy_engine() -> GuardrailEngine:
    global _policy_engine
    if _policy_engine is None:
        _policy_engine = GuardrailEngine()
    return _policy_engine


def evaluate_policy(role: str, tool_name: str) -> GuardrailDecision:
    return get_policy_engine().evaluate(role, tool_name)
