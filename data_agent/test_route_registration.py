"""Tests for custom route registration around Chainlit's frontend fallback."""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.routing import Route

from data_agent.route_registration import (
    insert_routes_before_frontend_fallback,
    is_frontend_fallback_route,
)


async def _endpoint(request):
    return None


class _IncludedRouter:
    pass


@pytest.mark.parametrize(
    "fallback",
    [Route("/{full_path:path}", _endpoint), _IncludedRouter()],
)
def test_inserts_routes_before_chainlit_fallback_in_declared_order(fallback):
    existing = Route("/existing", _endpoint)
    health = Route("/health", _endpoint)
    ready = Route("/ready", _endpoint)
    router = SimpleNamespace(routes=[existing, fallback])

    insert_at = insert_routes_before_frontend_fallback(router, [health, ready])

    assert insert_at == 1
    assert router.routes == [existing, health, ready, fallback]


def test_app_health_and_audit_groups_use_fallback_aware_registration():
    app_path = Path(__file__).with_name("app.py")
    tree = ast.parse(app_path.read_text(encoding="utf-8"))
    registered_groups = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "_insert_routes_before_frontend_fallback":
            continue
        route_arg = node.args[1]
        registered_groups.append(
            {
                element.id
                for element in route_arg.elts
                if isinstance(element, ast.Name)
            }
        )

    assert {
        "_audit_page_route",
        "_audit_api_route",
        "_audit_stats_route",
    } in registered_groups
    assert {
        "_health_route",
        "_ready_route",
        "_sysinfo_route",
        "_metrics_route",
    } in registered_groups


def test_detects_only_supported_frontend_fallback_shapes():
    assert is_frontend_fallback_route(Route("/{full_path:path}", _endpoint))
    assert is_frontend_fallback_route(_IncludedRouter())
    assert not is_frontend_fallback_route(Route("/health", _endpoint))
