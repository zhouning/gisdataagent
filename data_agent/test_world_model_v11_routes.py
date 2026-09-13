import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from starlette.requests import Request

from data_agent.api import world_model_v11_routes as routes


def fake_request(method="GET", body=b"{}"):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {"type": "http", "method": method, "path": "/", "headers": []},
        receive,
    )


def fake_summary(path):
    return {
        "schema": "territory_world_model.paper58_external_benchmark.v1",
        "status": "supporting_evidence" if path else "missing",
        "provided": bool(path),
        "claim_scope": "external_benchmark_support_only",
        "runtime_dependency": "none",
        "geofm_runtime_allowed": False,
        "twm_generator_role": "not_a_runtime_generator",
        "primary_twm_route": "twm_native_generation_and_planning",
        "blocks_validation": False,
        "can_promote_claim_ladder": False,
        "metric_summary": {
            "best_paper58_method": "paper58_semantic_keep_loo_selector",
            "baseline_method": "geosos_flus_console",
            "paper58_vs_baseline_wins": 4,
            "area_count": 43,
        },
        "source_files": {"paper58_benchmark_dir": str(path)} if path else {},
        "missing": [] if path else ["paper58_benchmark_dir_not_provided"],
        "claim_boundary": "Paper58 is external benchmark support only.",
    }


def test_status_requires_auth(monkeypatch):
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: None)
    resp = asyncio.run(routes.twm_paper58_benchmark(fake_request()))
    payload = json.loads(resp.body)
    assert resp.status_code == 401
    assert payload == {"error": "Unauthorized"}


def test_status_uses_only_server_configured_dir(monkeypatch):
    user = SimpleNamespace(identifier="alice", metadata={"role": "analyst"})
    calls = []
    contexts = []

    monkeypatch.setenv("TWM_PAPER58_BENCHMARK_DIR", " /safe/paper58 ")
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "_set_user_context", lambda user: contexts.append(user))
    monkeypatch.setattr(
        routes,
        "build_paper58_external_benchmark",
        lambda path: calls.append(path) or fake_summary(path),
    )

    resp = asyncio.run(routes.twm_paper58_benchmark(fake_request()))
    payload = json.loads(resp.body)

    assert resp.status_code == 200
    assert contexts == [user]
    assert calls == [Path("/safe/paper58")]
    assert payload["status"] == "supporting_evidence"
    assert payload["claim_scope"] == "external_benchmark_support_only"
    assert payload["runtime_dependency"] == "none"
    assert payload["geofm_runtime_allowed"] is False
    assert payload["twm_generator_role"] == "not_a_runtime_generator"
    assert payload["can_promote_claim_ladder"] is False


def test_missing_config_returns_non_blocking_missing_evidence(monkeypatch):
    user = SimpleNamespace(identifier="alice", metadata={"role": "analyst"})
    calls = []

    monkeypatch.delenv("TWM_PAPER58_BENCHMARK_DIR", raising=False)
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "_set_user_context", lambda user: None)
    monkeypatch.setattr(
        routes,
        "build_paper58_external_benchmark",
        lambda path: calls.append(path) or fake_summary(path),
    )

    resp = asyncio.run(routes.twm_paper58_benchmark(fake_request()))
    payload = json.loads(resp.body)

    assert resp.status_code == 200
    assert calls == [None]
    assert payload["status"] == "missing"
    assert payload["provided"] is False
    assert payload["blocks_validation"] is False
    assert payload["missing"] == ["paper58_benchmark_dir_not_provided"]


def test_refresh_does_not_accept_frontend_path(monkeypatch):
    user = SimpleNamespace(identifier="alice", metadata={"role": "analyst"})
    calls = []

    monkeypatch.setenv("TWM_PAPER58_BENCHMARK_DIR", "/configured/paper58")
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "_set_user_context", lambda user: None)
    monkeypatch.setattr(
        routes,
        "build_paper58_external_benchmark",
        lambda path: calls.append(path) or fake_summary(path),
    )

    resp = asyncio.run(
        routes.twm_paper58_benchmark_refresh(
            fake_request("POST", b'{"paper58_benchmark_dir":"/unsafe/frontend"}')
        )
    )
    payload = json.loads(resp.body)

    assert resp.status_code == 200
    assert calls == [Path("/configured/paper58")]
    assert payload["source_files"]["paper58_benchmark_dir"] == "/configured/paper58"


def test_helper_exception_returns_json_500(monkeypatch):
    user = SimpleNamespace(identifier="alice", metadata={"role": "analyst"})

    def raise_helper_error(path):
        raise RuntimeError("paper58 helper failed")

    monkeypatch.setenv("TWM_PAPER58_BENCHMARK_DIR", "/configured/paper58")
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "_set_user_context", lambda user: None)
    monkeypatch.setattr(routes, "build_paper58_external_benchmark", raise_helper_error)

    resp = asyncio.run(routes.twm_paper58_benchmark(fake_request()))
    payload = json.loads(resp.body)

    assert resp.status_code == 500
    assert payload == {"error": "paper58 helper failed"}


def test_status_runs_helper_in_thread(monkeypatch):
    user = SimpleNamespace(identifier="alice", metadata={"role": "analyst"})
    to_thread_calls = []

    def helper(path):
        return fake_summary(path)

    async def fake_to_thread(func, *args):
        to_thread_calls.append((func, args))
        return func(*args)

    monkeypatch.setenv("TWM_PAPER58_BENCHMARK_DIR", "/safe/paper58")
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "_set_user_context", lambda user: None)
    monkeypatch.setattr(routes, "build_paper58_external_benchmark", helper)
    monkeypatch.setattr(routes.asyncio, "to_thread", fake_to_thread)

    resp = asyncio.run(routes.twm_paper58_benchmark(fake_request()))

    assert resp.status_code == 200
    assert to_thread_calls == [(helper, (Path("/safe/paper58"),))]


def _route_methods(route_list, path):
    for route in route_list:
        if route.path == path:
            return set(route.methods or [])
    return set()


def test_routes_are_registered():
    from data_agent.frontend_api import get_frontend_api_routes

    route_list = routes.get_world_model_v11_routes()
    frontend_route_list = get_frontend_api_routes()

    assert "GET" in _route_methods(route_list, "/api/twm/paper58-benchmark")
    assert "POST" in _route_methods(route_list, "/api/twm/paper58-benchmark/refresh")
    assert "GET" in _route_methods(frontend_route_list, "/api/twm/paper58-benchmark")
    assert "POST" in _route_methods(
        frontend_route_list, "/api/twm/paper58-benchmark/refresh"
    )
