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
