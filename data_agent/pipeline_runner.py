"""
Headless pipeline runner for GIS Data Agent.
Runs ADK pipelines without any Chainlit dependency — reusable by WeChat bot,
API endpoints, or any non-UI channel.
"""
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable, List, Optional

from google.adk.runners import Runner
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.genai import types


# ---------------------------------------------------------------------------
# File path extraction (moved from app.py for reuse)
# ---------------------------------------------------------------------------

def extract_file_paths(text: str) -> list:
    """
    Extract file paths from text.
    Returns list of dicts: [{"path": "...", "type": "png"}, ...].
    """
    artifacts = []
    pattern = r'(?:[a-zA-Z]:\\|/)[^<>:"|?*]+\.(png|html|shp|zip|csv|xlsx|xls|kml|kmz|geojson|gpkg|docx|pdf|tif|tiff)'
    matches = re.finditer(pattern, text, re.IGNORECASE)
    for match in matches:
        path = match.group(0)
        ext = match.group(1).lower()
        if os.path.exists(path):
            artifacts.append({"path": path, "type": ext})
    return artifacts


# ---------------------------------------------------------------------------
# Pipeline result data class
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    """Result of a headless pipeline run."""
    report_text: str = ""
    generated_files: List[str] = field(default_factory=list)
    tool_execution_log: List[dict] = field(default_factory=list)
    provenance_trail: List[dict] = field(default_factory=list)
    pipeline_type: str = ""
    intent: str = ""
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    duration_seconds: float = 0.0
    error: Optional[str] = None


@dataclass
class StreamEvent:
    """A single event emitted during SSE streaming."""
    type: str  # text_chunk, tool_call, agent_transfer, final, error
    data: str = ""
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Headless pipeline runner
# ---------------------------------------------------------------------------

async def run_pipeline_headless(
    agent,
    session_service,
    user_id: str,
    session_id: str,
    prompt: str,
    pipeline_type: str = "general",
    intent: str = "GENERAL",
    router_tokens: int = 0,
    use_dynamic_planner: bool = False,
    role: str = "analyst",
    extra_parts: list = None,
    on_event: Callable[[dict], None] | None = None,
    plugins: list = None,
    memory_service=None,
) -> PipelineResult:
    """
    Run an ADK pipeline without Chainlit UI coupling.

    Args:
        agent:               ADK Agent instance (e.g., planner_agent, general_pipeline).
        session_service:     ADK SessionService (Database or InMemory).
        user_id:             Authenticated username.
        session_id:          ADK session ID.
        prompt:              Full user prompt (including context injections).
        pipeline_type:       'general', 'governance', 'optimization', or 'planner'.
        intent:              Router classification result.
        router_tokens:       Tokens consumed by the intent router.
        use_dynamic_planner: Whether dynamic planner mode is active.
        role:                User role for RBAC context (default: 'analyst').
        on_event:            Optional streaming callback. Called with event dicts:
                             {"type": "agent", "name": str}
                             {"type": "tool_call", "name": str, "args": dict}
                             {"type": "tool_result", "step": int, "name": str, "summary": str}
                             {"type": "text", "content": str}

    Returns:
        PipelineResult with report text, files, token counts, etc.
    """
    # Set ContextVars so tool functions have proper user identity
    from .user_context import current_user_id, current_session_id, current_user_role
    current_user_id.set(user_id)
    current_session_id.set(session_id)
    current_user_role.set(role)

    result = PipelineResult(pipeline_type=pipeline_type, intent=intent)
    start_time = time.time()

    runner_kwargs = dict(
        agent=agent,
        app_name="data_agent_headless",
        session_service=session_service,
        auto_create_session=True,
        plugins=plugins or [],
    )
    if memory_service is not None:
        runner_kwargs["memory_service"] = memory_service
    runner = Runner(**runner_kwargs)
    content = types.Content(role="user", parts=[types.Part(text=prompt)] + (extra_parts or []))

    total_input_tokens = router_tokens
    total_output_tokens = 0
    full_response_text = ""
    tool_execution_log = []
    _tool_step_counter = 0
    _pending_tool_call = None

    try:
        run_config = (
            RunConfig(max_llm_calls=50)
            if use_dynamic_planner and pipeline_type == "planner"
            else None
        )
        events = runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=content,
            run_config=run_config,
        )

        current_agent_name = None

        async for event in events:
            # Token accumulation
            if hasattr(event, "usage_metadata") and event.usage_metadata:
                total_input_tokens += (
                    getattr(event.usage_metadata, "prompt_token_count", 0) or 0
                )
                total_output_tokens += (
                    getattr(event.usage_metadata, "candidates_token_count", 0) or 0
                )

            author = getattr(event, "author", None)
            if author and author != "user":
                current_agent_name = author
                if on_event:
                    on_event({"type": "agent", "name": author})

            if not (event.content and event.content.parts):
                continue

            for part in event.content.parts:

                # --- Tool call tracking ---
                if part.function_call:
                    _pending_tool_call = {
                        "tool_name": part.function_call.name,
                        "args": dict(part.function_call.args) if part.function_call.args else {},
                        "start_time": time.time(),
                        "agent_name": current_agent_name or "",
                    }
                    if on_event:
                        on_event({"type": "tool_call", "name": part.function_call.name,
                                  "args": _pending_tool_call["args"]})

                # --- Tool response tracking ---
                if part.function_response:
                    if _pending_tool_call:
                        _tool_step_counter += 1
                        _resp = part.function_response.response
                        _out_path = None
                        _result_msg = ""
                        _is_err = False
                        if isinstance(_resp, dict):
                            _out_path = _resp.get("output_path")
                            _result_msg = str(
                                _resp.get("message", "")
                            )[:200]
                            _is_err = _resp.get("status") == "error"
                        elif isinstance(_resp, str):
                            _result_msg = _resp[:200]
                        tool_execution_log.append(
                            {
                                "step": _tool_step_counter,
                                "agent_name": _pending_tool_call["agent_name"],
                                "tool_name": _pending_tool_call["tool_name"],
                                "args": _pending_tool_call["args"],
                                "output_path": _out_path,
                                "result_summary": _result_msg,
                                "duration": time.time()
                                - _pending_tool_call["start_time"],
                                "is_error": _is_err,
                            }
                        )
                        _pending_tool_call = None
                    if on_event and tool_execution_log:
                        _last = tool_execution_log[-1]
                        on_event({"type": "tool_result", "step": _last["step"],
                                  "name": _last["tool_name"], "summary": _last["result_summary"]})

                # --- Text accumulation ---
                if part.text:
                    full_response_text += part.text
                    if on_event:
                        on_event({"type": "text", "content": part.text})

        # --- Report extraction from session state ---
        session = await session_service.get_session(
            app_name="data_agent_headless",
            user_id=user_id,
            session_id=session_id,
        )
        report_text = full_response_text
        if session and session.state:
            if pipeline_type == "planner":
                report_text = session.state.get(
                    "final_report",
                    session.state.get("planner_summary", full_response_text),
                )
            elif pipeline_type == "optimization":
                report_text = session.state.get(
                    "final_summary", full_response_text
                )
            elif pipeline_type == "governance":
                report_text = session.state.get(
                    "governance_report", full_response_text
                )

        generated_files = [
            a["path"] for a in extract_file_paths(full_response_text)
        ]

        result.report_text = report_text
        result.generated_files = generated_files
        result.tool_execution_log = tool_execution_log
        result.total_input_tokens = total_input_tokens
        result.total_output_tokens = total_output_tokens

        # Extract provenance trail from session state (if ProvenancePlugin active)
        if session and session.state:
            result.provenance_trail = session.state.get(
                "__provenance_trail__", []
            )

    except Exception as e:
        result.error = str(e)

    result.duration_seconds = time.time() - start_time
    return result


# ---------------------------------------------------------------------------
# SSE Streaming pipeline runner
# ---------------------------------------------------------------------------

async def run_pipeline_streaming(
    agent,
    session_service,
    user_id: str,
    session_id: str,
    prompt: str,
    pipeline_type: str = "general",
    role: str = "analyst",
    plugins: list = None,
    memory_service=None,
) -> AsyncIterator[StreamEvent]:
    """
    Run an ADK pipeline with SSE streaming, yielding StreamEvents.

    Yields:
        StreamEvent objects with type: text_chunk, tool_call, agent_transfer,
        final, or error.
    """
    from .user_context import current_user_id, current_session_id, current_user_role
    current_user_id.set(user_id)
    current_session_id.set(session_id)
    current_user_role.set(role)

    runner_kwargs = dict(
        agent=agent,
        app_name="data_agent_headless",
        session_service=session_service,
        auto_create_session=True,
        plugins=plugins or [],
    )
    if memory_service is not None:
        runner_kwargs["memory_service"] = memory_service
    runner = Runner(**runner_kwargs)

    content = types.Content(role="user", parts=[types.Part(text=prompt)])

    run_config = RunConfig(streaming_mode=StreamingMode.SSE)

    full_text = ""

    try:
        events = runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=content,
            run_config=run_config,
        )

        async for event in events:
            author = getattr(event, "author", None)
            if author and author != "user":
                yield StreamEvent(
                    type="agent_transfer",
                    data=json.dumps({"agent": author}),
                )

            if not (event.content and event.content.parts):
                continue

            for part in event.content.parts:
                if part.function_call:
                    yield StreamEvent(
                        type="tool_call",
                        data=json.dumps({
                            "tool": part.function_call.name,
                            "args": dict(part.function_call.args)
                            if part.function_call.args else {},
                        }),
                    )

                if part.text:
                    full_text += part.text
                    yield StreamEvent(
                        type="text_chunk",
                        data=part.text,
                    )

        yield StreamEvent(
            type="final",
            data=json.dumps({
                "text": full_text,
                "files": [a["path"] for a in extract_file_paths(full_text)],
            }),
        )

    except Exception as e:
        yield StreamEvent(type="error", data=str(e))
