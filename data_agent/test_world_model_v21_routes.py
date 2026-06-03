import asyncio
from types import SimpleNamespace

from starlette.requests import Request

from data_agent.api import world_model_v21_routes as routes


class FakeService:
    def status(self):
        return {"status": "ready", "version": "2.1.0"}

    def run_plan(self, body, user_id):
        return {
            "status": "ok",
            "version": "2.1.0",
            "summary": {"total_reward": 1.0},
            "map_config": {"layers": []},
        }


def fake_request(method="GET", body=b"{}"):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {"type": "http", "method": method, "path": "/", "headers": []},
        receive,
    )


def test_status_requires_auth(monkeypatch):
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: None)
    resp = asyncio.run(routes.wm_v21_status(fake_request()))
    assert resp.status_code == 401


def test_status_returns_service_payload(monkeypatch):
    user = SimpleNamespace(identifier="alice", metadata={"role": "analyst"})
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "get_world_model_v21_service", lambda: FakeService())
    resp = asyncio.run(routes.wm_v21_status(fake_request()))
    assert resp.status_code == 200
    assert b'"ready"' in resp.body


def test_plan_queues_map_update(monkeypatch):
    user = SimpleNamespace(identifier="alice", metadata={"role": "analyst"})
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "get_world_model_v21_service", lambda: FakeService())
    pending = {}
    monkeypatch.setattr(
        routes, "_queue_map_update", lambda uid, cfg: pending.setdefault(uid, cfg)
    )
    resp = asyncio.run(
        routes.wm_v21_plan(
            fake_request("POST", b'{"prepared_dir":"x","ensemble_dir":"y"}')
        )
    )
    assert resp.status_code == 200
    assert pending["alice"] == {"layers": []}
