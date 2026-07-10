from data_agent.api import uwm_traditional_livability_routes as routes
import json

import pytest


def _route_methods(route_list, path):
    for route in route_list:
        if route.path == path:
            return set(route.methods or [])
    return set()


def test_traditional_livability_routes_are_registered_in_frontend_api():
    from data_agent.frontend_api import get_frontend_api_routes

    route_list = routes.get_uwm_traditional_livability_routes()
    frontend_route_list = get_frontend_api_routes()

    assert "GET" in _route_methods(route_list, "/api/uwm/traditional-livability")
    assert "POST" in _route_methods(route_list, "/api/uwm/traditional-livability/map")
    assert "GET" in _route_methods(
        frontend_route_list, "/api/uwm/traditional-livability"
    )
    assert "POST" in _route_methods(
        frontend_route_list, "/api/uwm/traditional-livability/map"
    )
    assert "GET" in _route_methods(
        route_list, "/api/uwm/traditional-livability/s1"
    )
    assert "GET" in _route_methods(
        frontend_route_list, "/api/uwm/traditional-livability/s1"
    )


def test_s1_snapshot_loader_validates_schema(tmp_path, monkeypatch):
    path = tmp_path / "s1.json"
    path.write_text(json.dumps({"schema": "uwm.traditional_livability.s1_assessment.v1", "assessment_id": "s1"}), encoding="utf-8")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S1_PATH", str(path))

    assert routes._load_s1_snapshot()["assessment_id"] == "s1"


def test_s1_snapshot_loader_fails_closed_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S1_PATH", str(tmp_path / "missing.json"))

    with pytest.raises(routes.S1SnapshotUnavailable) as error:
        routes._load_s1_snapshot()

    assert error.value.payload["ready"] is False
    assert "s1_snapshot_missing" in error.value.payload["blockers"]
