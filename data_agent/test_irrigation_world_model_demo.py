from __future__ import annotations

from starlette.applications import Starlette
from starlette.testclient import TestClient

from data_agent.api import irrigation_world_model_routes as routes
from data_agent.irrigation_world_model_demo import (
    InMemoryIrrigationRunRepository,
    IrrigationWorldModelConflict,
    IrrigationWorldModelDemoService,
    IrrigationWorldModelError,
    calculate_scenario,
)
from data_agent.irrigation_world_model_repository import IrrigationPersistenceError


def test_deterministic_kernel_conserves_water_and_compares_three_candidates():
    parameters = {
        "supply_drop_percent": 20,
        "west_shift_hours": 6,
        "candidate_east_ratio_percent": 45,
        "horizon_hours": 24,
    }
    results = [
        calculate_scenario(mode, parameters) for mode in ("baseline", "candidateA", "candidateB")
    ]
    assert all(abs(result["residual"]) < 0.001 for result in results)
    assert all(len(result["timeline"]) == 5 for result in results)
    assert all(result["numerical"]["timestep_count"] > 0 for result in results)
    assert results[2]["reaches"][2]["final_storage_m3"] != results[0]["reaches"][2]["final_storage_m3"]


def test_service_versions_runs_and_enforces_proposal_state_machine():
    service = IrrigationWorldModelDemoService(InMemoryIrrigationRunRepository())
    bootstrap = service.bootstrap("alice")
    assert bootstrap["service"]["mode"] == "backend_authoritative"
    assert len(bootstrap["objects"]) == 10
    assert len(bootstrap["links"]) == 12
    first = bootstrap["run"]
    assert first["version"] == 1
    assert first["proposal"]["execution_allowed"] is False
    assert first["planner"]["planner_id"] == "bounded-candidate-enumeration"
    assert first["planner"]["ranking"]

    reviewed = service.review_proposal(
        first["proposal"]["proposal_id"],
        {"decision": "approved", "note": "模型条件已核对；不执行设备动作。"},
        "alice",
    )
    assert reviewed["proposal"]["status"] == "approved"
    assert reviewed["proposal"]["execution_allowed"] is False
    try:
        service.review_proposal(
            first["proposal"]["proposal_id"],
            {"decision": "returned", "note": "再次修改"},
            "alice",
        )
    except IrrigationWorldModelConflict:
        pass
    else:
        raise AssertionError("reviewed Proposal must not be reviewed twice")

    second = service.run({**first["parameters"], "horizon_hours": 12}, "alice")
    assert second["version"] == 2
    assert second["proposal"]["status"] == "pending"


def test_bootstrap_reconstructs_planner_for_legacy_persisted_run():
    repository = InMemoryIrrigationRunRepository()
    service = IrrigationWorldModelDemoService(repository)
    first = service.bootstrap("alice")["run"]
    del repository._runs[first["run_id"]]["planner"]

    restored = service.bootstrap("alice")["run"]

    assert restored["run_id"] == first["run_id"]
    assert restored["planner"]["planner_id"] == "bounded-candidate-enumeration"
    assert restored["planner"]["selected_mode"] == first["proposal"]["candidate_mode"]
    assert restored["planner"]["evidence_origin"] == "legacy_run_reconstruction"


def test_service_rejects_invalid_scenario_parameters():
    service = IrrigationWorldModelDemoService(InMemoryIrrigationRunRepository())
    for payload in (
        {"supply_drop_percent": 60},
        {"west_shift_hours": 3},
        {"candidate_east_ratio_percent": 75},
        {"horizon_hours": 18},
    ):
        try:
            service.run(payload, "alice")
        except IrrigationWorldModelError:
            pass
        else:
            raise AssertionError(f"invalid payload accepted: {payload}")


def _client(monkeypatch, *, authenticated=True):
    service = IrrigationWorldModelDemoService(InMemoryIrrigationRunRepository())
    monkeypatch.setattr(routes, "get_irrigation_world_model_service", lambda: service)
    monkeypatch.setattr(
        routes, "_get_user_from_request", lambda request: object() if authenticated else None
    )
    monkeypatch.setattr(routes, "_set_user_context", lambda user: ("alice", "analyst"))
    routes.current_tenant_id.set("local-dev")
    monkeypatch.setattr(routes, "_audit", lambda *args, **kwargs: None)
    return TestClient(Starlette(routes=routes.get_irrigation_world_model_routes()))


def test_api_workflow_is_authenticated_and_backend_authoritative(monkeypatch):
    client = _client(monkeypatch)
    bootstrap = client.get("/api/irrigation-world-model/bootstrap")
    assert bootstrap.status_code == 200
    assert (
        bootstrap.json()["run"]["model"]["model_class"]
        == "deterministic_physics_based_state_transition"
    )

    response = client.post(
        "/api/irrigation-world-model/run",
        json={
            "supply_drop_percent": 25,
            "west_shift_hours": 8,
            "candidate_east_ratio_percent": 45,
            "horizon_hours": 12,
        },
    )
    assert response.status_code == 201
    run = response.json()["run"]
    assert run["parameters"]["horizon_hours"] == 12
    assert len(run["results"][0]["timeline"]) == 3

    review = client.post(
        f"/api/irrigation-world-model/proposals/{run['proposal']['proposal_id']}/review",
        json={"decision": "returned", "note": "补充设备状态后重新运行"},
    )
    assert review.status_code == 200
    assert review.json()["run"]["proposal"]["status"] == "returned"
    assert review.json()["run"]["proposal"]["execution_allowed"] is False


def test_api_requires_authentication(monkeypatch):
    monkeypatch.delenv("GDA_ODIWM_LOCAL_DEMO", raising=False)
    client = _client(monkeypatch, authenticated=False)
    assert client.get("/api/irrigation-world-model/bootstrap").status_code == 401


def test_api_fails_closed_with_503_when_postgres_is_unavailable(monkeypatch):
    class UnavailableRepository:
        def latest(self, actor, tenant_id):
            raise IrrigationPersistenceError("PostgreSQL unavailable")

    service = IrrigationWorldModelDemoService(UnavailableRepository())
    monkeypatch.setattr(routes, "get_irrigation_world_model_service", lambda: service)
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: object())
    monkeypatch.setattr(routes, "_set_user_context", lambda user: ("alice", "analyst"))
    routes.current_tenant_id.set("local-dev")
    client = TestClient(Starlette(routes=routes.get_irrigation_world_model_routes()))
    response = client.get("/api/irrigation-world-model/bootstrap")
    assert response.status_code == 503
    assert response.json()["error"] == "PostgreSQL unavailable"


def test_api_rejects_cross_site_writes(monkeypatch):
    client = _client(monkeypatch)
    response = client.post(
        "/api/irrigation-world-model/run",
        json={"horizon_hours": 6},
        headers={"sec-fetch-site": "cross-site"},
    )
    assert response.status_code == 403


def test_routes_are_mounted_in_frontend_api():
    from data_agent.frontend_api import get_frontend_api_routes

    paths = {route.path for route in get_frontend_api_routes() if hasattr(route, "path")}
    assert "/api/irrigation-world-model/bootstrap" in paths
    assert "/api/irrigation-world-model/run" in paths
    assert "/api/irrigation-world-model/proposals/{proposal_id}/review" in paths
