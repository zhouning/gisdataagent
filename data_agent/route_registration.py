"""Helpers for registering routes ahead of Chainlit's frontend fallback."""

from collections.abc import Sequence
from typing import Any, Protocol


class _Router(Protocol):
    routes: list[Any]


def is_frontend_fallback_route(route: object) -> bool:
    """Recognize the frontend fallback used by old and new Chainlit releases."""
    path = getattr(route, "path", None)
    return path == "/{full_path:path}" or type(route).__name__ == "_IncludedRouter"


def insert_routes_before_frontend_fallback(
    router: _Router,
    routes: Sequence[Any],
) -> int:
    """Insert routes before Chainlit's greedy frontend router, preserving order."""
    insert_at = next(
        (
            index
            for index, route in enumerate(router.routes)
            if is_frontend_fallback_route(route)
        ),
        len(router.routes),
    )
    router.routes[insert_at:insert_at] = routes
    return insert_at


def ensure_chainlit_oauth_openapi_model(security: Any) -> bool:
    """Restore the OpenAPI model omitted by Chainlit's cookie OAuth helper."""
    if getattr(security, "model", None) is not None:
        return False

    token_url = getattr(security, "tokenUrl", None)
    if not isinstance(token_url, str) or not token_url:
        raise ValueError("Chainlit OAuth security dependency is missing tokenUrl")

    from fastapi.security import OAuth2PasswordBearer

    reference = OAuth2PasswordBearer(
        tokenUrl=token_url,
        scheme_name=getattr(security, "scheme_name", None),
        auto_error=bool(getattr(security, "auto_error", True)),
    )
    security.model = reference.model
    return True
