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
