import asyncio
import json
from types import SimpleNamespace

from starlette.requests import Request

from data_agent.api import world_model_v21_routes as routes


class FakeService:
    def __init__(self):
        self.calls = []

    def status(self):
        return {"status": "ready", "version": "2.1.0"}

    def run_plan(self, body, user_id):
        self.calls.append(("run_plan", body, user_id))
        return {
            "status": "ok",
            "version": "2.1.0",
            "summary": {"total_reward": 1.0},
            "map_config": {"layers": []},
        }

    def run_prepare(self, body, user_id):
        self.calls.append(("run_prepare", body, user_id))
        return {"status": "ok", "mode": "tool1_prepare"}

    def run_sample(self, body, user_id):
        self.calls.append(("run_sample", body, user_id))
        return {"status": "ok", "mode": "tool2_sample"}

    def run_train(self, body, user_id):
        self.calls.append(("run_train", body, user_id))
        return {"status": "ok", "mode": "tool3_train"}

    def run_pipeline(self, body, user_id):
        self.calls.append(("run_pipeline", body, user_id))
        return {
            "status": "ok",
            "mode": "pipeline_a_to_d",
            "steps": [{"step": "prepare", "status": "skipped_reused"}],
            "plan_result": {"status": "ok", "map_config": {"layers": []}},
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
    fake = FakeService()
    monkeypatch.setattr(routes, "get_world_model_v21_service", lambda: fake)
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
    assert fake.calls[0][0] == "run_plan"


def test_prepare_sample_train_and_pipeline_routes_call_service(monkeypatch):
    user = SimpleNamespace(identifier="alice", metadata={"role": "analyst"})
    fake = FakeService()
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "get_world_model_v21_service", lambda: fake)
    pending = {}
    monkeypatch.setattr(
        routes, "_queue_map_update", lambda uid, cfg: pending.setdefault(uid, cfg)
    )

    route_calls = [
        (routes.wm_v21_prepare, "run_prepare"),
        (routes.wm_v21_sample, "run_sample"),
        (routes.wm_v21_train, "run_train"),
        (routes.wm_v21_pipeline, "run_pipeline"),
    ]
    for handler, method_name in route_calls:
        resp = asyncio.run(handler(fake_request("POST", b'{"prepared_dir":"x"}')))
        assert resp.status_code == 200
        assert fake.calls[-1][0] == method_name

    pipeline_payload = json.loads(resp.body)
    assert pipeline_payload["map_update_queued"] is True
    assert pipeline_payload["plan_result"]["map_update_queued"] is True
    assert "map_config" not in pipeline_payload["plan_result"]
    assert pending["alice"] == {"layers": []}
