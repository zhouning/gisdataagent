"""
Pipeline Helpers — Pure utility functions for pipeline execution.

Extracted from app.py (S-1 refactoring). Contains tool explanation formatting,
step summaries, error classification, progress rendering, and OBS sync logic.
No Chainlit dependency — reusable by CLI/API/Bot channels.
"""
import os
import time
import json
import logging
import ast
import re
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


def extract_map_update_from_tool_response(value):
    """Extract a frontend map_update config from ADK tool response payloads.

    Tool responses may arrive as a plain dict, a JSON string, or nested under
    wrapper keys such as {"result": "...json..."}. The frontend only needs the
    map_update object with a layers list.
    """
    if value is None:
        return None

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return _extract_map_update_from_html_text(value)
        return extract_map_update_from_tool_response(parsed)

    if isinstance(value, dict):
        map_update = value.get("map_update")
        if isinstance(map_update, dict) and isinstance(map_update.get("layers"), list):
            return map_update

        for key in ("plan_result", "result", "output", "response", "content"):
            if key not in value:
                continue
            nested = extract_map_update_from_tool_response(value[key])
            if nested:
                return nested

    return None


def extract_workspace_update_from_tool_response(value):
    """Extract a bounded data-workbench navigation request from tool output."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(value, dict):
        return None

    update = value.get("workspace_update")
    if isinstance(update, dict) and update.get("tab") in {"ontology", "ontology_demo"}:
        allowed = {
            "tab", "concept_id", "relation_path", "view", "scenario_id", "auto_run",
        }
        return {key: item for key, item in update.items() if key in allowed}
    for key in ("plan_result", "result", "output", "response", "content"):
        if key in value:
            nested = extract_workspace_update_from_tool_response(value[key])
            if nested:
                return nested
    return None


def _extract_map_update_from_html_text(text: str):
    """Load map_update from an HTML path mentioned in a plain tool response."""
    pattern = r'(?:[a-zA-Z]:\\|/)[^<>:"|?*]+\.html'
    for match in re.finditer(pattern, text or "", re.IGNORECASE):
        html_path = match.group(0)
        cfg_path = html_path.replace(".html", ".mapconfig.json")
        if not os.path.exists(cfg_path):
            continue
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if isinstance(cfg, dict) and isinstance(cfg.get("layers"), list):
                return cfg
        except Exception:
            continue
    return None


def _parse_maybe_json_or_literal(value):
    """Parse common ADK wrapper payloads without raising."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    for parser in (json.loads, ast.literal_eval):
        try:
            return parser(text)
        except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
            continue
    return value


def normalize_drl_tool_response(value) -> dict | None:
    """Normalize drl_model output from ADK wrappers into one canonical dict.

    The ADK runtime can return tool payloads directly, nested under keys such as
    ``result``/``output``/``response``, or serialized as JSON/Python literals.
    The final presentation and map fallback must not depend on one wrapper
    shape; otherwise metrics disappear even when the tool succeeded.
    """
    if value is None:
        return None

    parsed = _parse_maybe_json_or_literal(value)

    if isinstance(parsed, dict):
        candidate = dict(parsed)
        summary = candidate.get("summary")
        has_drl_fields = any(
            candidate.get(key)
            for key in ("optimized_data_path", "output_path", "summary")
        )
        if isinstance(summary, str) and "Optimization Complete" in summary:
            has_drl_fields = True
        if has_drl_fields:
            _fill_drl_paths_from_summary(candidate)
            return candidate

        for key in (
            "result", "output", "response", "content", "data",
            "tool_response", "function_response",
        ):
            if key not in candidate:
                continue
            nested = normalize_drl_tool_response(candidate[key])
            if nested:
                return nested
        return None

    if isinstance(parsed, str):
        summary = parsed.strip()
        if not summary:
            return None
        if (
            "Optimization Complete" not in summary
            and "Conversions:" not in summary
            and "Result SHP:" not in summary
        ):
            return None
        result = {"summary": summary}
        _fill_drl_paths_from_summary(result)
        return result

    return None


def _fill_drl_paths_from_summary(result: dict) -> None:
    """Backfill output paths from the drl_model summary text."""
    summary = str(result.get("summary") or "")
    if not summary:
        return
    patterns = {
        "optimized_data_path": r"(?im)^\s*Result SHP:\s*(.+?)\s*$",
        "output_path": r"(?im)^\s*Visualization:\s*(.+?)\s*$",
    }
    for key, pattern in patterns.items():
        if result.get(key):
            continue
        match = re.search(pattern, summary)
        if match:
            result[key] = match.group(1).strip()


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

    if pipeline_type in ("planner", "sub_agent_direct"):
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


# ---------------------------------------------------------------------------
# Context Engine Integration (v19.0)
# ---------------------------------------------------------------------------


def inject_context(query: str, task_type: str, user_context: dict | None = None) -> str:
    """Prepare and format context from the unified ContextEngine.

    Convenience wrapper for agent middleware / pipeline hooks.
    Returns formatted context string ready for prompt injection,
    or empty string on failure.
    """
    try:
        from .context_engine import get_context_engine

        engine = get_context_engine()
        blocks = engine.prepare(query, task_type, user_context or {})
        return engine.format_context(blocks)
    except Exception as e:
        logger.debug("inject_context failed: %s", e)
        return ""


import re as _re

_LEAK_START_RE = _re.compile(
    r"(The user wants|The user specifies|The user provided context|The previous steps|"
    r"The interactive map has been generated|Now I need|Key info to communicate|"
    r"I should use|my task is|I need to|I will call|I will use|Parameters for|"
    r"Title:|Section \d+:|Check against constraints)",
    _re.IGNORECASE,
)

_COT_PATTERNS = _re.compile(
    r"(?:^|\n)"
    r"(?:"
    r"(?:让我|我来|我需要|我应该|我查看|我先|根据规则|根据返回|根据 grounding|不过根据|"
    r"所以我|实际上|用户想要|用户要求|用户想|用户问|用户明确|"
    r"不过，安全|不过，|现在我来|这涉及到|"
    r"The user wants|The user specifies|The user provided context|The previous steps|The status check|"
    r"The interactive map has been generated|Now, I will|Now I need|I will proceed|Key info to communicate|"
    r"I should use|my task is|I need to|I will call|I will use|Parameters for|Ah, I made a typo|"
    r"Corrected parameters|Final Summary Data|"
    r"Step \d+:|Plan:|Call world_model|Provide a summary|Language:)"
    r"[^\n]{0,200}\n?"
    r")+",
    _re.MULTILINE,
)

_COT_PREFIXES = _re.compile(
    r"^(?:好的，|好，|OK，|首先，|接下来，|然后，|最后，)"
    r"(?:让我|我来|我需要|我先)",
)

_FINAL_HEADER_RE = _re.compile(
    r"(?m)^\s*(?:#{1,6}\s+\S|(?:📌\s*)?执行摘要(?:\s|$|[（(])|任务状态(?:\s|$|[:：]))"
)


def clean_cot_leakage(text: str) -> str:
    """Remove chain-of-thought reasoning leaked into model output."""
    if not text or len(text) < 20:
        return text
    final_markers = (
        "规划已完成",
        "NL2SQL 查询结果",
        "查询成功",
        "已成功结项",
        "已成功完成。",
        "已检索到",
        "已成功将",
        "已保存记忆",
        "找到 ",
        "📌 执行摘要",
    )

    def _find_next_final_marker(search_text: str, start: int = 0) -> int:
        marker_positions = []
        for marker in final_markers:
            pos = search_text.find(marker, start)
            if pos >= start:
                marker_positions.append(pos)
        header_match = _FINAL_HEADER_RE.search(search_text, start)
        if header_match:
            marker_positions.append(header_match.start())
        return min(marker_positions) if marker_positions else -1

    leak_markers = (
        "The user wants",
        "The previous steps",
        "The interactive map has been generated",
        "I should use",
        "my task is",
        "Now I need",
        "Key info to communicate",
        "I will call",
        "I will use",
        "Parameters for",
        "Title:",
        "Section 1:",
        "Check against constraints",
        "Plan:",
        "Step 1:",
        "Ah, I made a typo",
        "Corrected parameters",
    )
    leak_detected = any(marker in text for marker in leak_markers)
    if leak_detected:
        while True:
            leak_match = _LEAK_START_RE.search(text)
            if not leak_match:
                break
            start = leak_match.start()
            end = _find_next_final_marker(text, start + 1)
            if end > start:
                text = (text[:start].rstrip() + "\n" + text[end:].lstrip()).strip()
            else:
                text = text[:start].rstrip()
                break
        final_start = _find_next_final_marker(text, 1)
        if final_start > 0:
            text = text[final_start:]
    cleaned = _COT_PATTERNS.sub("\n", text)
    cleaned = _COT_PREFIXES.sub("", cleaned)
    skip_prefixes = (
        "Check the status",
        "Run a fast MPC",
        "Use default",
        "Parameters:",
        "Parameters for",
        "keyword:",
        "memory_type:",
        "The user provided context",
        "env_kind:",
        "horizon:",
        "top_k:",
        "n_episodes:",
        "continuation:",
        "scoring:",
        "prepared_dir:",
        "ensemble_dir:",
    )
    lines = [
        ln for ln in cleaned.split("\n")
        if ln.strip() and not ln.strip().startswith(skip_prefixes)
    ]
    result = "\n".join(lines)
    if len(result.strip()) < 10 and len(text.strip()) > 10 and not leak_detected:
        return text
    return result


def should_force_drl_optimization(prompt: str) -> bool:
    """Return True for land-use/farmland layout optimization requests."""
    text = prompt or ""
    lower = text.lower()
    has_optimization = "优化" in text or "optimization" in lower
    if not has_optimization:
        return False
    domain_markers = (
        "耕地",
        "农田",
        "土地利用",
        "地类",
        "空间布局",
        "布局优化",
        "land use",
        "farmland",
    )
    return any(marker in lower if marker.isascii() else marker in text for marker in domain_markers)


def find_drl_optimization_input_path(
    prompt: str,
    response_text: str = "",
    uploaded_files: list | None = None,
) -> str:
    """Find the best source vector dataset for mandatory DRL fallback.

    The LLM may mention only a basename such as ``斑竹村10000.shp`` while the
    real file lives in a nested upload directory. This resolver prefers user-
    requested source datasets over generated analysis outputs such as LISA or
    optimized shapefiles.
    """
    import os
    import re

    try:
        from data_agent.gis_processors import _resolve_path
        from data_agent.user_context import get_user_upload_dir
    except Exception:
        return ""

    spatial_exts = (".shp", ".geojson", ".gpkg")
    generated_prefixes = (
        "optimized_",
        "lisa_",
        "moran_",
        "hotspot_",
        "choropleth_",
        "interactive_",
        "buffer_",
        "clip_",
    )
    haystack = "\n".join([prompt or "", response_text or ""])
    raw_candidates: list[str] = []

    path_pattern = re.compile(
        r"(?P<path>(?:[A-Za-z]:\\|/)?[^\s`'\"<>|?*]+?\.(?:shp|geojson|gpkg))",
        re.IGNORECASE,
    )
    for match in path_pattern.finditer(haystack):
        raw_candidates.append(match.group("path").rstrip("，。；;、)）]】"))

    for item in uploaded_files or []:
        for attr in ("path", "name"):
            val = getattr(item, attr, None)
            if val:
                raw_candidates.append(str(val))

    try:
        user_dir = get_user_upload_dir()
        for root, dirs, files in os.walk(user_dir):
            depth = root[len(user_dir):].count(os.sep)
            if depth >= 4:
                dirs.clear()
            for fname in files:
                if fname.lower().endswith(spatial_exts):
                    raw_candidates.append(os.path.join(root, fname))
    except Exception:
        user_dir = ""

    prompt_tokens = []
    for tok in re.findall(r"[\u4e00-\u9fffA-Za-z0-9_]+", prompt or ""):
        if len(tok) >= 3:
            prompt_tokens.append(tok.lower())

    best_path = ""
    best_score = -10_000
    seen = set()
    for candidate in raw_candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        if not candidate.lower().endswith(spatial_exts):
            continue
        resolved = _resolve_path(candidate)
        if not (resolved and os.path.exists(resolved)):
            continue

        basename = os.path.basename(resolved)
        stem = os.path.splitext(basename)[0]
        comparable = resolved.lower()
        score = 0
        if stem and stem in (prompt or ""):
            score += 120
        if basename and basename in haystack:
            score += 80
        for token in prompt_tokens:
            if token in comparable:
                score += 40
        if user_dir and os.path.realpath(resolved).startswith(os.path.realpath(user_dir) + os.sep):
            score += 20
        if basename.lower().startswith(generated_prefixes):
            score -= 120
        if re.search(r"_[0-9a-f]{8}$", stem, re.IGNORECASE):
            score -= 20
        if score > best_score:
            best_score = score
            best_path = resolved

    return best_path


def format_drl_optimization_result_for_chat(tool_result: dict, artifacts: list[str] | None = None) -> str:
    """Build a factual chat summary from a drl_model tool response."""
    normalized = normalize_drl_tool_response(tool_result)
    if not isinstance(normalized, dict):
        return ""

    summary = str(normalized.get("summary") or "")
    conversions = pairs = net_change = None
    for line in summary.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip().lower()
        value = value.strip()
        if key == "conversions":
            conversions = value
        elif key == "pairs":
            pairs = value
        elif key == "net change":
            net_change = value

    optimized_path = normalized.get("optimized_data_path") or ""
    map_path = normalized.get("output_path") or ""
    html_paths = [
        p for p in (artifacts or [])
        if isinstance(p, str) and p.lower().endswith(".html")
    ]

    lines = [
        "已完成耕地空间布局优化分析。",
        "",
        "### 分析方法",
        "使用 `drl_model` 深度强化学习工具对输入地块进行地类属性优化。该工具在原始地块几何上输出优化后的类型字段，不移动地块边界。",
        "",
        "### DRL 工具实测指标",
    ]
    if conversions is not None:
        lines.append(f"- Conversions: {conversions}")
    if pairs is not None:
        pair_note = "（本次运行未形成成对置换）" if pairs in {"0", "0.0"} else ""
        lines.append(f"- Pairs: {pairs}{pair_note}")
    if net_change is not None:
        net_note = "" if net_change in {"0", "0.0", "+0"} else "（存在地类数量净变化，不代表总量平衡）"
        lines.append(f"- Net Change: {net_change}{net_note}")

    lines.extend([
        "",
        "### 交付物",
    ])
    if optimized_path:
        lines.append(f"- 优化后矢量数据: `{optimized_path}`")
    if map_path:
        lines.append(f"- 优化结果 PNG: `{map_path}`")
    for path in html_paths[:3]:
        lines.append(f"- 交互式地图: `{path}`")

    lines.extend([
        "",
        "### 解读口径",
        "- 如果 `Pairs=0`，只能说明本次运行完成了地类转换，不能按配对交换结果解读。",
        "- 如果 `Net Change` 不为 0，说明地类数量存在净变化，不能按总量平衡结果解读。",
        "- 右侧地图和 PNG 用于查看优化前后地类属性变化。"
    ])
    return "\n".join(lines)
