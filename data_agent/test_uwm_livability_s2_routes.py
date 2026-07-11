import json
from pathlib import Path

import pytest
from starlette.requests import Request

from data_agent.api import uwm_livability_s2_routes as routes
from data_agent.test_uwm_livability_s2_scenario import _product_dir


def _methods(items, path):
    for route in items:
        if route.path == path:
            return set(route.methods or [])
    return set()


def _request(path, method="GET", payload=None, path_params=None):
    body = json.dumps(payload or {}).encode()
    sent = False
    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}
    scope = {"type":"http","method":method,"path":path,"headers":[(b"content-type",b"application/json")],"query_string":b"","path_params":path_params or {}}
    return Request(scope, receive)


def _auth(monkeypatch, username="planner-1"):
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: {"id": username})
    monkeypatch.setattr(routes, "_set_user_context", lambda user: (username, "analyst"))


def test_s2_routes_registered_in_frontend_api():
    from data_agent.frontend_api import get_frontend_api_routes
    own = routes.get_uwm_livability_s2_routes()
    mounted = get_frontend_api_routes()
    for path, method in [
        ("/api/uwm/livability/s2/catalog","GET"),
        ("/api/uwm/livability/s2/parcels","GET"),
        ("/api/uwm/livability/s2/parcels/{parcel_id}","GET"),
        ("/api/uwm/livability/s2/validate-action","POST"),
        ("/api/uwm/livability/s2/rollout","POST"),
        ("/api/uwm/livability/s2/runs/{run_id}","GET"),
    ]:
        assert method in _methods(own, path)
        assert method in _methods(mounted, path)


@pytest.mark.asyncio
async def test_catalog_requires_auth_and_returns_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("UWM_LIVABILITY_S2_PATH", str(_product_dir(tmp_path, monkeypatch)))
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: None)
    response = await routes.uwm_livability_s2_catalog(_request("/api/uwm/livability/s2/catalog"))
    assert response.status_code == 401
    _auth(monkeypatch)
    routes._reset_service_cache()
    response = await routes.uwm_livability_s2_catalog(_request("/api/uwm/livability/s2/catalog"))
    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["ready"] is True
    assert payload["online_raw_vector_access"] is False


@pytest.mark.asyncio
async def test_validate_and_rollout_override_actor_and_map_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("UWM_LIVABILITY_S2_PATH", str(_product_dir(tmp_path, monkeypatch)))
    _auth(monkeypatch, "authenticated-planner")
    routes._reset_service_cache()
    service = routes._service()
    parcel = service.list_parcels()["features"][0]
    catalog = service.catalog()
    current = parcel["properties"]["current_land_use_class"]
    target = next(v for v in catalog["land_use_classes"] if v != current)
    body = {"parcel_id":parcel["id"],"from_land_use_class":current,"to_land_use_class":target,"snapshot_digest":catalog["snapshot_digest"],"rationale":"test","requested_at":"2026-07-11T08:00:00Z","actor_id":"spoofed"}
    response = await routes.uwm_livability_s2_validate_action(_request("/api/uwm/livability/s2/validate-action","POST",body))
    assert response.status_code == 200
    assert json.loads(response.body)["action"]["actor_id"] == "authenticated-planner"
    response = await routes.uwm_livability_s2_rollout(_request("/api/uwm/livability/s2/rollout","POST",body))
    run = json.loads(response.body)
    assert response.status_code == 200
    assert run["actor_id"] == "authenticated-planner"
    stale = dict(body, snapshot_digest="stale")
    response = await routes.uwm_livability_s2_rollout(_request("/api/uwm/livability/s2/rollout","POST",stale))
    assert response.status_code == 409
    response = await routes.uwm_livability_s2_run(_request("/x", path_params={"run_id":"missing"}))
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_missing_or_tampered_product_maps_to_503(tmp_path, monkeypatch):
    monkeypatch.setenv("UWM_LIVABILITY_S2_PATH", str(tmp_path / "missing"))
    _auth(monkeypatch)
    routes._reset_service_cache()
    response = await routes.uwm_livability_s2_catalog(_request("/api/uwm/livability/s2/catalog"))
    assert response.status_code == 503
