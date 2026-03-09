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
current_user_role: ContextVar[str] = ContextVar('current_user_role', default='analyst')
current_trace_id: ContextVar[str] = ContextVar('current_trace_id', default='')

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
    abs_path = os.path.abspath(path)
    user_dir = os.path.abspath(get_user_upload_dir())
    base_dir = os.path.abspath(_BASE_UPLOAD_DIR)
    # Allow: user's own directory or the shared base (for backward compat)
    return abs_path.startswith(user_dir) or abs_path.startswith(base_dir)
