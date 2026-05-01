"""
User context module for multi-tenant isolation.
Uses contextvars.ContextVar to propagate user identity through async call chains
without modifying tool function signatures.
"""
import os
from contextvars import ContextVar

# Context variables - set in app.py on each request, read by tool functions
current_user_id: ContextVar[str] = ContextVar('current_user_id', default='anonymous')
current_session_id: ContextVar[str] = ContextVar('current_session_id', default='default')
current_user_role: ContextVar[str] = ContextVar('current_user_role', default='anonymous')
current_trace_id: ContextVar[str] = ContextVar('current_trace_id', default='')
current_tool_categories: ContextVar[set] = ContextVar('current_tool_categories', default=set())
current_model_tier: ContextVar[str] = ContextVar('current_model_tier', default='standard')

# NL2SQL grounding cache (Phase 1)
current_nl2sql_schemas: ContextVar[dict] = ContextVar('current_nl2sql_schemas', default={})
current_nl2sql_large_tables: ContextVar[set] = ContextVar('current_nl2sql_large_tables', default=set())
current_nl2sql_question: ContextVar[str] = ContextVar('current_nl2sql_question', default='')

from data_agent.nl2sql_intent import IntentLabel  # noqa: E402

current_nl2sql_intent: ContextVar[IntentLabel] = ContextVar(
    'current_nl2sql_intent', default=IntentLabel.UNKNOWN,
)

# Base uploads directory
_BASE_UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")


def get_user_upload_dir() -> str:
    """Returns the upload directory for the current user, creating it if needed."""
    user_id = current_user_id.get()
    user_dir = os.path.join(_BASE_UPLOAD_DIR, user_id)
    os.makedirs(user_dir, exist_ok=True)
    return user_dir


def is_path_in_sandbox(path: str) -> bool:
    """Check if a resolved path is within the current user's sandbox or the shared uploads dir."""
    real_path = os.path.realpath(path)
    real_user_dir = os.path.realpath(get_user_upload_dir())
    real_base_dir = os.path.realpath(_BASE_UPLOAD_DIR)
    return (
        (real_path.startswith(real_user_dir + os.sep) or real_path == real_user_dir)
        or (real_path.startswith(real_base_dir + os.sep) or real_path == real_base_dir)
    )
