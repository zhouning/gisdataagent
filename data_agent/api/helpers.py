"""
Shared API helpers — auth extraction, user context, admin guards.

Used by all domain route modules. Extracted from frontend_api.py (S-4).
"""
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..user_context import current_user_id, current_user_role


def _get_user_from_request(request: Request):
    """Extract authenticated user from JWT in request cookies."""
    try:
        from chainlit.auth.cookie import get_token_from_cookies
        from chainlit.auth.jwt import decode_jwt
    except ImportError:
        return None
    token = get_token_from_cookies(dict(request.cookies))
    if not token:
        return None
    try:
        return decode_jwt(token)
    except Exception:
        return None


def _set_user_context(user):
    """Set ContextVars from a decoded JWT user object."""
    username = user.identifier if hasattr(user, "identifier") else str(user)
    role = "analyst"
    if hasattr(user, "metadata") and isinstance(user.metadata, dict):
        role = user.metadata.get("role", "analyst")
    current_user_id.set(username)
    current_user_role.set(role)
    return username, role


def _require_admin(request: Request):
    """Returns (user, username, role, error_response).

    If error_response is not None, the caller should return it immediately.
    """
    user = _get_user_from_request(request)
    if not user:
        return None, None, None, JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    if role != "admin":
        return user, username, role, JSONResponse({"error": "Admin required"}, status_code=403)
    return user, username, role, None
