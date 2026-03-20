"""
Pipeline Helpers — Pure utility functions for pipeline execution.

Extracted from app.py (S-1 refactoring). Contains tool explanation formatting,
step summaries, error classification, progress rendering, and OBS sync logic.
No Chainlit dependency — reusable by CLI/API/Bot channels.
"""
import os
import time
import logging
from contextvars import ContextVar

logger = logging.getLogger("data_agent.pipeline_helpers")

# Pipeline run context — set by app.py at pipeline start, read by sync_tool_output_to_obs
current_pipeline_run_id: ContextVar[str] = ContextVar("current_pipeline_run_id", default="")

# Lazy imports to avoid circular dependencies
_user_context_imported = False


def _get_current_user_id():
    global _user_context_imported
    if not _user_context_imported:
        _user_context_imported = True
    from data_agent.user_context import current_user_id
    return current_user_id.get()


# ---------------------------------------------------------------------------
# Tool Explanation Formatting
# ---------------------------------------------------------------------------

def format_tool_explanation(tool_name: str, args: dict,
                           tool_descriptions: dict) -> str:
    """Format tool args into human-readable Chinese explanation."""
    desc = tool_descriptions.get(tool_name)
    if not desc:
        args_str = str(args)
        return args_str[:500] + "..." if len(args_str) > 500 else args_str

    lines = [f"**{desc['method']}**"]
    param_labels = desc.get("params", {})
    for key, value in (args or {}).items():
        label = param_labels.get(key, key)
        display_val = value
        if isinstance(value, str) and (os.sep in value or '/' in value):
            display_val = os.path.basename(value)
        display_str = str(display_val)
        if len(display_str) > 120:
            display_str = display_str[:120] + "..."
        lines.append(f"- {label}: `{display_str}`")
    return "\n".join(lines)


def build_step_summary(step: dict, step_idx: int,
                       tool_descriptions: dict, tool_labels: dict) -> str:
    """Build a one-line summary of a tool execution step."""
    from data_agent.i18n import t
    tool_name = step.get("tool_name", "")
    desc = tool_descriptions.get(tool_name, {})
    method = desc.get("method", tool_labels.get(tool_name, tool_name))
    status = t("steps.status_failed") if step.get("is_error") else t("steps.status_success")
    duration = step.get("duration", 0)
    out = step.get("output_path")
    out_str = f" -> `{os.path.basename(out)}`" if out else ""
    return t("steps.summary", idx=step_idx, method=method, status=status,
             duration=f"{duration:.1f}", output=out_str)


# ---------------------------------------------------------------------------
# Source Path Extraction (for data lineage)
# ---------------------------------------------------------------------------

NON_RERUNNABLE_TOOLS = {
    "save_memory", "recall_memories", "list_memories", "delete_memory",
    "get_usage_summary", "query_audit_log", "share_table",
}

_SOURCE_PATH_KEYS = {
    "file_path", "input_path", "shp_path", "raster_path", "polygon_path",
    "csv_path", "table_name", "data_path", "input_file", "boundary_path",
    "vector_path", "raster_file", "input_raster",
}


def extract_source_paths(args: dict) -> list:
    """Extract source file/table references from tool arguments for data lineage."""
    sources = []
    for key, val in args.items():
        if not isinstance(val, str) or not val:
            continue
        if key in _SOURCE_PATH_KEYS:
            sources.append(val)
        elif key.endswith("_path") or key.endswith("_file"):
            sources.append(val)
    return sources


# ---------------------------------------------------------------------------
# OBS Sync
# ---------------------------------------------------------------------------

def sync_tool_output_to_obs(resp_data, tool_name: str = "", tool_args: dict = None) -> None:
    """Detect file paths in tool response, sync to OBS, and register in data catalog."""
    paths = []
    if isinstance(resp_data, str) and os.path.exists(resp_data):
        paths.append(resp_data)
    elif isinstance(resp_data, dict):
        for v in resp_data.values():
            if isinstance(v, str) and os.path.exists(v):
                paths.append(v)

    uid = _get_current_user_id()
    source_paths = extract_source_paths(tool_args or {})

    # Register in data catalog (always, even without cloud)
    try:
        from data_agent.data_catalog import register_tool_output
        run_id = current_pipeline_run_id.get("")
        for p in paths:
            register_tool_output(p, tool_name or "unknown", tool_params=tool_args,
                                 source_paths=source_paths, pipeline_run_id=run_id or None)
    except Exception:
        pass

    # Sync to cloud storage
    try:
        from data_agent.obs_storage import is_obs_configured, upload_file_smart
        if not is_obs_configured():
            return
        for p in paths:
            try:
                keys = upload_file_smart(p, uid)
                if keys:
                    try:
                        from data_agent.data_catalog import auto_register_from_path
                        auto_register_from_path(
                            p, creation_tool=tool_name or "unknown",
                            storage_backend="cloud", cloud_key=keys[0],
                        )
                    except Exception:
                        pass
            except Exception:
                pass
    except ImportError:
        pass


# ---------------------------------------------------------------------------
# Pipeline Stage Definitions
# ---------------------------------------------------------------------------

PIPELINE_STAGES = {
    "optimization": [
        "DataIngestion", "DataAnalysis", "DataVisualization", "DataSummary",
    ],
    "governance": ["GovExploration", "GovProcessing", "GovernanceReporter"],
    "general": ["GeneralProcessing", "GeneralViz", "GeneralSummary"],
}


# ---------------------------------------------------------------------------
# Progress Rendering
# ---------------------------------------------------------------------------

def render_bar(completed: int, total: int) -> str:
    """Render a text progress bar, e.g. '▓▓░░ 2/4'."""
    if total == 0:
        return ""
    return "▓" * completed + "░" * (total - completed) + f" {completed}/{total}"


def build_progress_content(
    pipeline_label: str,
    pipeline_type: str,
    stages: list,
    stage_timings: list,
    agent_labels: dict,
    is_complete: bool = False,
    total_duration: float = 0.0,
    is_error: bool = False,
) -> str:
    """Build Markdown content for the inline progress message.

    Pure function — no side effects, easily testable.
    """
    from data_agent.i18n import t
    timing_map = {st["name"]: st for st in stage_timings}

    if pipeline_type == "planner":
        if is_complete:
            header = t("progress.steps_complete", label=f"**{pipeline_label}**", count=len(stage_timings))
        elif stage_timings:
            header = t("progress.step_n", label=f"**{pipeline_label}**", n=len(stage_timings))
        else:
            header = t("progress.preparing", label=f"**{pipeline_label}**")
        lines = [header, ""]
        for st in stage_timings:
            if is_error and st["end"] is None:
                elapsed = (st.get("_error_time") or time.time()) - st["start"]
                lines.append(f"✗ {st['label']}  {elapsed:.1f}s {t('progress.error_suffix')}")
            elif st["end"] is not None:
                dur = st["end"] - st["start"]
                lines.append(f"✓ {st['label']}  {dur:.1f}s")
            else:
                elapsed = time.time() - st["start"]
                lines.append(f"▶ {st['label']}  {elapsed:.1f}s...")
    else:
        completed_count = sum(1 for st in stage_timings if st["end"] is not None)
        total = len(stages)
        if is_complete:
            header = t("progress.bar_complete", label=f"**{pipeline_label}**", bar=render_bar(total, total))
        else:
            header = f"**{pipeline_label}** {render_bar(completed_count, total)}"
        lines = [header, ""]
        for stage_name in stages:
            label = agent_labels.get(stage_name, stage_name)
            st = timing_map.get(stage_name)
            if st is None:
                lines.append(f"○ {label}")
            elif is_error and st["end"] is None:
                elapsed = (st.get("_error_time") or time.time()) - st["start"]
                lines.append(f"✗ {label}  {elapsed:.1f}s {t('progress.error_suffix')}")
            elif st["end"] is not None:
                dur = st["end"] - st["start"]
                lines.append(f"✓ {label}  {dur:.1f}s")
            else:
                elapsed = time.time() - st["start"]
                lines.append(f"▶ {label}  {elapsed:.1f}s...")

    if is_complete:
        lines.append("")
        if is_error:
            lines.append(t("progress.total_time_error", duration=f"{total_duration:.1f}"))
        else:
            lines.append(t("progress.total_time", duration=f"{total_duration:.1f}"))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Error Classification for Retry Logic
# ---------------------------------------------------------------------------

MAX_PIPELINE_RETRIES = 2

_RETRYABLE_PATTERNS = [
    "timeout", "timed out", "rate limit", "rate_limit",
    "503", "429", "temporarily unavailable", "service unavailable",
    "resource exhausted", "deadline exceeded", "connection reset",
    "connection refused", "network unreachable",
]

_NON_RETRYABLE_PATTERNS = [
    "permission denied", "access denied", "unauthorized",
    "invalid format", "invalid argument", "not found",
    "no such file", "must contain", "must include",
]


def classify_error(exc: Exception) -> tuple:
    """Classify whether a pipeline error is retryable.

    Returns (is_retryable, category) where category is one of:
    "transient", "permission", "data_format", "config", "unknown".
    """
    if isinstance(exc, (TimeoutError, ConnectionError, ConnectionResetError,
                        ConnectionAbortedError, BrokenPipeError, OSError)):
        if isinstance(exc, (PermissionError, FileNotFoundError)):
            return (False, "permission" if isinstance(exc, PermissionError) else "data_format")
        if isinstance(exc, OSError) and not isinstance(exc, (ConnectionError, TimeoutError)):
            pass
        else:
            return (True, "transient")

    if isinstance(exc, (ValueError, KeyError)):
        return (False, "data_format")

    msg = str(exc).lower()

    for pattern in _NON_RETRYABLE_PATTERNS:
        if pattern in msg:
            return (False, "config")

    for pattern in _RETRYABLE_PATTERNS:
        if pattern in msg:
            return (True, "transient")

    return (True, "unknown")


# ---------------------------------------------------------------------------
# Recommended Follow-up Questions (v14.1)
# ---------------------------------------------------------------------------

def generate_followup_questions(report_text: str, user_text: str, pipeline_type: str) -> list[str]:
    """Generate 3 recommended follow-up questions based on analysis results.

    Uses Gemini Flash for low-latency generation. Returns empty list on failure.
    """
    if not report_text or len(report_text) < 50:
        return []
    try:
        from google import genai as genai_client
        from google.genai import types

        client = genai_client.Client()
        prompt = f"""根据以下GIS分析结果，生成3个有价值的后续分析建议。
每个建议应该是一个具体的分析请求（用户可以直接发送给Agent执行）。

用户原始问题：{user_text[:200]}
管线类型：{pipeline_type}
分析结果摘要：{report_text[:1500]}

要求：
- 每行一个建议，不要编号
- 每个建议不超过50字
- 建议应该是递进式或互补的分析方向
- 用中文表述"""

        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                http_options=types.HttpOptions(timeout=10_000),
            ),
        )
        lines = [l.strip() for l in response.text.strip().split('\n') if l.strip()]
        # Clean up: remove numbering if present
        cleaned = []
        for line in lines[:3]:
            for prefix in ("1.", "2.", "3.", "- ", "· "):
                if line.startswith(prefix):
                    line = line[len(prefix):].strip()
            if line:
                cleaned.append(line)
        return cleaned[:3]
    except Exception as e:
        logger.debug("Follow-up generation failed: %s", e)
        return []
