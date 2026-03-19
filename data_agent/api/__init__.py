"""
API package — domain-organized route handlers (S-4 refactoring).

Shared auth helpers and domain-specific route modules.
"""
from .helpers import _get_user_from_request, _set_user_context, _require_admin
