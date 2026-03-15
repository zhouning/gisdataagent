"""
Message Handler — pure-logic functions extracted from app.py.

These functions handle the message processing pipeline WITHOUT Chainlit
dependency, making them testable and reusable by CLI/TUI/bot channels.

app.py's @cl.on_message still orchestrates the Chainlit-specific UI flow
but delegates business logic to functions here.
"""
import os
from typing import Optional

try:
    from .observability import get_logger
    logger = get_logger("message_handler")
except Exception:
    import logging
    logger = logging.getLogger("message_handler")


# ---------------------------------------------------------------------------
# File Upload Classification
# ---------------------------------------------------------------------------

SPATIAL_EXTENSIONS = {".shp", ".geojson", ".gpkg", ".kml", ".kmz", ".zip"}
TABULAR_EXTENSIONS = {".csv", ".xlsx", ".xls"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff"}
PDF_EXTENSIONS = {".pdf"}


def classify_upload(filename: str) -> str:
    """Classify an uploaded file by extension.

    Returns: 'spatial', 'tabular', 'image', 'pdf', or 'unknown'.
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext in SPATIAL_EXTENSIONS:
        return "spatial"
    if ext in TABULAR_EXTENSIONS:
        return "tabular"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in PDF_EXTENSIONS:
        return "pdf"
    return "unknown"


# ---------------------------------------------------------------------------
# Context Injection
# ---------------------------------------------------------------------------

def build_context_prompt(user_id: str, user_text: str,
                         memories: list = None,
                         perspective: str = None,
                         semantic_context: str = None,
                         file_descriptions: list = None) -> str:
    """Build the full prompt with injected context.

    Combines user text with memory, perspective, semantic context,
    and file descriptions into a single prompt string.
    """
    parts = []

    # File descriptions
    if file_descriptions:
        parts.append("[上传文件]\n" + "\n".join(file_descriptions))

    # Memories
    if memories:
        mem_text = "\n".join(f"- {m}" for m in memories[:5])
        parts.append(f"[历史分析记忆]\n{mem_text}")

    # Analysis perspective
    if perspective:
        parts.append(f"[分析视角] {perspective}")

    # Semantic context
    if semantic_context:
        parts.append(f"[语义上下文]\n{semantic_context}")

    # User message
    parts.append(user_text)

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Pipeline Selection
# ---------------------------------------------------------------------------

def select_pipeline_agent(intent: str, custom_skill_agent=None,
                          use_dynamic_planner: bool = True):
    """Select the appropriate pipeline agent based on intent and skill match.

    Args:
        intent: Classified intent (GENERAL, GOVERNANCE, OPTIMIZATION).
        custom_skill_agent: Pre-built custom skill agent, if matched.
        use_dynamic_planner: Whether dynamic planner mode is enabled.

    Returns:
        (agent, pipeline_type, pipeline_name) tuple.
    """
    if custom_skill_agent:
        name = getattr(custom_skill_agent, 'name', 'CustomSkill')
        return custom_skill_agent, "general", f"Custom Skill: {name}"

    if intent == "GOVERNANCE":
        from .agent import governance_pipeline
        return governance_pipeline, "governance", "Governance Pipeline"

    if intent == "OPTIMIZATION":
        from .agent import data_pipeline
        return data_pipeline, "optimization", "Optimization Pipeline"

    if use_dynamic_planner:
        from .agent import planner_agent
        return planner_agent, "planner", f"Dynamic Planner (意图: {intent})"

    from .agent import general_pipeline
    return general_pipeline, "general", "General Pipeline"


# ---------------------------------------------------------------------------
# RBAC Check
# ---------------------------------------------------------------------------

def check_rbac(role: str, intent: str) -> Optional[str]:
    """Check if the user role allows the requested intent.

    Returns error message if blocked, None if allowed.
    """
    if role == "viewer" and intent in ("GOVERNANCE", "OPTIMIZATION"):
        return f"您的角色 (viewer) 无权访问 {intent} 管线。请联系管理员升级权限。"
    return None


# ---------------------------------------------------------------------------
# Routing Feedback
# ---------------------------------------------------------------------------

def build_routing_info(intent: str, reason: str, pipeline_name: str,
                       pipeline_type: str) -> dict:
    """Build routing metadata for the UI feedback message."""
    return {
        "intent": intent,
        "pipeline": pipeline_name,
        "pipeline_type": pipeline_type,
        "reason": reason,
    }
