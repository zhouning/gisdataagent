"""
A2A Agent Server — expose GIS Data Agent as an A2A-compatible service (v11.0.4).

Uses a2a-sdk to create an A2A server that external agents can discover
and invoke via the Agent-to-Agent protocol.

Controlled by A2A_ENABLED env var (default: false).
"""
import json
import os
import time
from typing import Optional

try:
    from .observability import get_logger
    logger = get_logger("a2a_server")
except Exception:
    import logging
    logger = logging.getLogger("a2a_server")


A2A_ENABLED = os.environ.get("A2A_ENABLED", "false").lower() == "true"
A2A_DEFAULT_ROLE = os.environ.get("A2A_DEFAULT_ROLE", "analyst")


# ---------------------------------------------------------------------------
# Agent Card
# ---------------------------------------------------------------------------

def build_agent_card(base_url: str = "http://localhost:8000") -> dict:
    """Build the A2A Agent Card describing this agent's capabilities."""
    return {
        "name": "GIS Data Agent",
        "description": "AI-powered geospatial analysis platform with semantic routing, "
                       "multi-pipeline architecture, and 121+ spatial analysis tools.",
        "url": base_url,
        "version": "11.0",
        "protocol_version": "0.2",
        "capabilities": {
            "streaming": True,
            "push_notifications": False,
        },
        "skills": [
            {
                "id": "spatial-analysis",
                "name": "Spatial Analysis",
                "description": "Spatial statistics (Moran's I, LISA, hotspot), clustering (DBSCAN), "
                               "interpolation (IDW, Kriging), GWR, buffer, overlay, zonal stats.",
            },
            {
                "id": "data-governance",
                "name": "Data Governance",
                "description": "Topological audit (overlaps, self-intersections, gaps), "
                               "schema compliance (GB/T 21010), quality reports.",
            },
            {
                "id": "land-optimization",
                "name": "Land Use Optimization",
                "description": "Deep Reinforcement Learning (MaskablePPO) for land-use layout "
                               "optimization with paired farmland/forest swaps.",
            },
            {
                "id": "visualization",
                "name": "GIS Visualization",
                "description": "Interactive maps (choropleth, heatmap, 3D extrusion), "
                               "categorized layers, legend, basemap switching.",
            },
            {
                "id": "data-fusion",
                "name": "Multi-Source Data Fusion",
                "description": "10 fusion strategies (spatial join, overlay, zonal stats, etc.), "
                               "5 data modalities, LLM-driven strategy routing.",
            },
        ],
        "default_input_modes": ["text"],
        "default_output_modes": ["text"],
    }


# ---------------------------------------------------------------------------
# A2A Executor
# ---------------------------------------------------------------------------

async def execute_a2a_task(message_text: str, caller_id: str = "a2a_client") -> dict:
    """Execute an A2A task by routing through the pipeline runner.

    Args:
        message_text: The user/agent message text.
        caller_id: The calling agent's identifier.

    Returns:
        dict with status, result_text, files, tokens.
    """
    try:
        from .user_context import current_user_id, current_user_role
        from .pipeline_runner import run_pipeline_headless
        from google.adk.sessions import InMemorySessionService

        # Set user context for the A2A caller
        a2a_user = f"a2a_{caller_id}"
        current_user_id.set(a2a_user)
        current_user_role.set(A2A_DEFAULT_ROLE)

        # Classify intent
        try:
            from .app import classify_intent
            intent_result = classify_intent(message_text)
            pipeline_type = intent_result.get("pipeline", "general") if isinstance(intent_result, dict) else "general"
        except Exception:
            pipeline_type = "general"

        # Get agent
        from .task_queue import _get_pipeline_agent
        agent = _get_pipeline_agent(pipeline_type)
        if not agent:
            return {"status": "error", "message": "No agent available for pipeline type"}

        session_service = InMemorySessionService()
        session_id = f"a2a_{int(time.time())}"

        result = await run_pipeline_headless(
            agent=agent,
            session_service=session_service,
            user_id=a2a_user,
            session_id=session_id,
            prompt=message_text,
            pipeline_type=pipeline_type,
            role=A2A_DEFAULT_ROLE,
        )

        return {
            "status": "completed" if not result.error else "failed",
            "result_text": result.report_text or "",
            "files": result.generated_files or [],
            "error": result.error,
            "input_tokens": result.total_input_tokens,
            "output_tokens": result.total_output_tokens,
            "duration": result.duration_seconds,
            "pipeline_type": pipeline_type,
        }

    except Exception as e:
        logger.warning("A2A task execution failed: %s", e)
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# A2A Server Status
# ---------------------------------------------------------------------------

import threading

_a2a_started_at: Optional[float] = None
_a2a_lock = threading.Lock()


def get_a2a_status() -> dict:
    """Get A2A server status."""
    return {
        "enabled": A2A_ENABLED,
        "started_at": _a2a_started_at,
        "uptime_seconds": round(time.time() - _a2a_started_at, 1) if _a2a_started_at else 0,
        "default_role": A2A_DEFAULT_ROLE,
    }


def mark_started():
    """Mark the A2A server as started (thread-safe)."""
    global _a2a_started_at
    with _a2a_lock:
        _a2a_started_at = time.time()


# ---------------------------------------------------------------------------
# A2A Task Lifecycle (v14.3 — Google A2A spec)
# ---------------------------------------------------------------------------

import uuid as _uuid

_tasks: dict[str, dict] = {}  # task_id → task state


def create_task(message_text: str, caller_id: str = "a2a_client") -> dict:
    """Create a new A2A task (submitted state). Returns task handle."""
    task_id = _uuid.uuid4().hex[:12]
    _tasks[task_id] = {
        "task_id": task_id,
        "status": "submitted",
        "caller_id": caller_id,
        "message": message_text,
        "result": None,
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    return {"task_id": task_id, "status": "submitted"}


async def execute_task(task_id: str) -> dict:
    """Execute a submitted task (transitions: submitted → working → completed/failed)."""
    task = _tasks.get(task_id)
    if not task:
        return {"status": "error", "message": f"Task {task_id} not found"}
    if task["status"] != "submitted":
        return {"status": "error", "message": f"Task {task_id} is {task['status']}, not submitted"}

    task["status"] = "working"
    task["updated_at"] = time.time()

    result = await execute_a2a_task(task["message"], task["caller_id"])

    task["status"] = result.get("status", "failed")
    task["result"] = result
    task["updated_at"] = time.time()

    # Prune old tasks (keep last 100)
    if len(_tasks) > 100:
        oldest = sorted(_tasks.keys(), key=lambda k: _tasks[k]["created_at"])
        for k in oldest[:len(_tasks) - 100]:
            _tasks.pop(k, None)

    return result


def get_task_status(task_id: str) -> dict | None:
    """Get current task status and result."""
    return _tasks.get(task_id)


def list_tasks(limit: int = 20) -> list[dict]:
    """List recent tasks."""
    sorted_tasks = sorted(_tasks.values(), key=lambda t: t["created_at"], reverse=True)
    return [
        {
            "task_id": t["task_id"],
            "status": t["status"],
            "caller_id": t["caller_id"],
            "message": t["message"][:100],
            "created_at": t["created_at"],
        }
        for t in sorted_tasks[:limit]
    ]


# ---------------------------------------------------------------------------
# Federation Config (v14.3)
# ---------------------------------------------------------------------------

def get_federation_config() -> dict:
    """Return federation configuration for multi-instance deployment."""
    from .agent_registry import discover_agents
    peers = discover_agents()
    return {
        "local_agent_id": os.environ.get("AGENT_ID", "gis-data-agent-local"),
        "federation_enabled": os.environ.get("FEDERATION_ENABLED", "false").lower() == "true",
        "peer_agents": peers,
        "peer_count": len(peers),
        "capabilities": [
            "spatial-analysis", "data-governance", "land-optimization",
            "visualization", "data-fusion", "virtual-sources",
        ],
    }
