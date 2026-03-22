"""
API package — domain-organized route handlers (S-4 refactoring).

Shared auth helpers and domain-specific route modules.
"""
from .helpers import _get_user_from_request, _set_user_context, _require_admin
from .bundle_routes import get_bundle_routes
from .mcp_routes import get_mcp_routes
from .workflow_routes import get_workflow_routes
from .skills_routes import get_skills_routes
