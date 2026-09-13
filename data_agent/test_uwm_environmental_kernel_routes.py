import json

import pytest
from starlette.requests import Request

from data_agent.api import uwm_environmental_kernel_routes as routes
from data_agent.test_uwm_environmental_kernel_service import product_dir


def request(path, method="GET", payload=None):
    body = json.dumps(payload or {}).encode()
    sent = False
    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}
    return Request({"type":"http","method":method,"path":path,"headers":[(b"content-type",b"application/json")],"query_string":b""}, receive)


def auth(monkeypatch, username="planner-1"):
    monkeypatch.setattr(routes, "_get_user_from_request", lambda req: {"id": username})
    monkeypatch.setattr(routes, "_set_user_context", lambda user: (username, "analyst"))


def methods(items, path):
    return next(set(route.methods or []) for route in items if route.path == path)


def test_routes_are_registered_in_frontend_api():
    from data_agent.frontend_api import get_frontend_api_routes
    own = routes.get_uwm_environmental_kernel_routes()
    mounted = get_frontend_api_routes()
    for path, method in [
        ("/api/uwm/livability/environmental-kernel/scene", "GET"),
        ("/api/uwm/livability/environmental-kernel/evidence-gate", "GET"),
        ("/api/uwm/livability/environmental-kernel/rollout", "POST"),
        ("/api/uwm/livability/environmental-kernel/map", "GET"),
    ]:
        assert method in methods(own, path)
        assert method in methods(mounted, path)


@pytest.mark.asyncio
async def test_get_routes_require_auth_and_return_product(tmp_path, monkeypatch):
    monkeypatch.setenv("UWM_ENVIRONMENTAL_KERNEL_PATH", str(product_dir(tmp_path)))
    routes._reset_service_cache()
    monkeypatch.setattr(routes, "_get_user_from_request", lambda req: None)
    response = await routes.environmental_kernel_scene(request("/x"))
    assert response.status_code == 401
    auth(monkeypatch)
    response = await routes.environmental_kernel_scene(request("/x"))
    assert response.status_code == 200
    assert json.loads(response.body)["state"]["schema"] == "uwm.environmental_state.v1"


@pytest.mark.asyncio
async def test_rollout_binds_authenticated_actor_and_returns_conflict(tmp_path, monkeypatch):
    monkeypatch.setenv("UWM_ENVIRONMENTAL_KERNEL_PATH", str(product_dir(tmp_path)))
    routes._reset_service_cache()
    auth(monkeypatch, "authenticated-planner")
    scene = routes._service().scene()
    response = await routes.environmental_kernel_rollout(request("/x", "POST", {
        "action_type": "increase_tree_canopy_proxy",
        "target_node_ids": [scene["state"]["spatial_nodes"][0]["node_id"]],
        "state_snapshot_digest": scene["state"]["snapshot_digest"],
        "actor": "spoofed",
    }))
    payload = json.loads(response.body)
    assert response.status_code == 409
    assert payload["error"] == "environmental_action_response_closed"
    assert payload["actor"] == "authenticated-planner"
