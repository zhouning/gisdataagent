from data_agent.api import uwm_traditional_livability_routes as routes
import json

import pytest
from starlette.requests import Request

from data_agent.test_traditional_livability_s6 import resource_fixture
from data_agent.uwm.traditional_livability_facility_dictionary import (
    unavailable_compatibility_matrix,
    unavailable_facility_dictionary,
)


def _route_methods(route_list, path):
    for route in route_list:
        if route.path == path:
            return set(route.methods or [])
    return set()


def _request(path, *, method="GET", payload=None):
    body = json.dumps(payload or {}).encode("utf-8")
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
        },
        receive,
    )


def _write_s6_snapshots(directory, *, resources=None, dictionary=None, compatibility=None):
    directory.mkdir()
    (directory / "uwm_traditional_livability_s6_resources.json").write_text(
        json.dumps(resources or resource_fixture()), encoding="utf-8"
    )
    (directory / "uwm_traditional_livability_s6_dictionary.json").write_text(
        json.dumps(dictionary or unavailable_facility_dictionary()), encoding="utf-8"
    )
    (directory / "uwm_traditional_livability_s6_compatibility.json").write_text(
        json.dumps(compatibility or unavailable_compatibility_matrix()), encoding="utf-8"
    )
    return directory


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
    assert "GET" in _route_methods(
        route_list, "/api/uwm/traditional-livability/s7"
    )
    assert "GET" in _route_methods(
        frontend_route_list, "/api/uwm/traditional-livability/s7"
    )
    for path, method in (
        ("/api/uwm/traditional-livability/s6/resources", "GET"),
        ("/api/uwm/traditional-livability/s6/dictionary", "GET"),
        ("/api/uwm/traditional-livability/s6/analyze", "POST"),
    ):
        assert method in _route_methods(route_list, path)
        assert method in _route_methods(frontend_route_list, path)


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


def test_s7_snapshot_loader_validates_schema(tmp_path, monkeypatch):
    import json
    path = tmp_path / "s7.json"
    path.write_text(json.dumps({"schema": "uwm.traditional_livability.s7_siting.v1", "siting_id": "s7"}), encoding="utf-8")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S7_PATH", str(path))
    assert routes._load_s7_snapshot()["siting_id"] == "s7"


def test_s7_snapshot_loader_fails_closed_when_missing(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S7_PATH", str(tmp_path / "missing.json"))
    with pytest.raises(routes.S7SnapshotUnavailable) as error:
        routes._load_s7_snapshot()
    assert error.value.payload["ready"] is False
    assert "s7_snapshot_missing" in error.value.payload["blockers"]


def test_s6_path_accepts_controlled_directory_or_resource_json(tmp_path, monkeypatch):
    snapshot_dir = _write_s6_snapshots(tmp_path / "snapshots")
    resource_path = snapshot_dir / "uwm_traditional_livability_s6_resources.json"

    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(snapshot_dir))
    assert routes._resolve_s6_path("resources") == resource_path
    assert routes._resolve_s6_path("dictionary").parent == snapshot_dir

    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(resource_path))
    assert routes._resolve_s6_path("resources") == resource_path
    assert routes._resolve_s6_path("compatibility").parent == snapshot_dir


@pytest.mark.parametrize("failure", ["missing", "unreadable", "invalid_json", "invalid_schema"])
def test_s6_resource_loader_fails_closed(tmp_path, monkeypatch, failure):
    path = tmp_path / "resources.json"
    if failure == "unreadable":
        path.mkdir()
    elif failure == "invalid_json":
        path.write_text("{", encoding="utf-8")
    elif failure == "invalid_schema":
        path.write_text(json.dumps({"schema": "wrong", "ready": True}), encoding="utf-8")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(path))

    with pytest.raises(routes.S6SnapshotUnavailable) as error:
        routes._load_s6_snapshot("resources")

    assert error.value.payload["ready"] is False
    assert error.value.payload["blockers"]


@pytest.mark.asyncio
async def test_s6_resources_endpoint_returns_503_for_invalid_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "resources.json"
    path.write_text(json.dumps({"schema": "wrong"}), encoding="utf-8")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(path))
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: {"id": "user"})
    monkeypatch.setattr(routes, "_set_user_context", lambda user: None)

    response = await routes.uwm_traditional_livability_s6_resources(
        _request("/api/uwm/traditional-livability/s6/resources")
    )

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_s6_dictionary_unavailable_returns_http_200_blocker(tmp_path, monkeypatch):
    _write_s6_snapshots(tmp_path / "snapshots")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(tmp_path / "snapshots"))
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: {"id": "user"})
    monkeypatch.setattr(routes, "_set_user_context", lambda user: None)

    response = await routes.uwm_traditional_livability_s6_dictionary(
        _request("/api/uwm/traditional-livability/s6/dictionary")
    )
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["ready"] is False
    assert payload["blockers"]


@pytest.mark.asyncio
async def test_s6_analyze_uses_server_snapshots_and_rejects_cross_area(tmp_path, monkeypatch):
    snapshot_dir = _write_s6_snapshots(tmp_path / "snapshots")
    monkeypatch.setenv("UWM_TRADITIONAL_LIVABILITY_S6_PATH", str(snapshot_dir))
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: {"id": "user"})
    monkeypatch.setattr(routes, "_set_user_context", lambda user: None)
    calls = []

    def fake_analyze(**kwargs):
        calls.append(kwargs)
        return {"schema": "uwm.traditional_livability.s6_analysis.v1", "status": "insufficient_evidence", "blockers": ["unknown_analysis_area:outside"]}

    monkeypatch.setattr(routes, "analyze_s6_facility_proposal", fake_analyze)
    request_payload = {
        "input_mode": "planning_parcel",
        "analysis_area_id": "outside",
        "planning_resource_id": "parcel-selected",
        "resources": {"schema": "attacker"},
        "dictionary": {"schema": "attacker"},
        "compatibility": {"schema": "attacker"},
        "source_path": str(tmp_path / "Downloads" / "attacker.shp"),
    }

    response = await routes.uwm_traditional_livability_s6_analyze(
        _request("/api/uwm/traditional-livability/s6/analyze", method="POST", payload=request_payload)
    )
    payload = json.loads(response.body)

    assert response.status_code == 400
    assert "unknown_analysis_area:outside" in payload["blockers"]
    assert calls[0]["request"] == request_payload
    assert calls[0]["resources"]["schema"] == "uwm.traditional_livability.s6_fulu_resources.v1"
    assert calls[0]["dictionary"]["schema"] != "attacker"
    assert calls[0]["compatibility"]["schema"] != "attacker"
