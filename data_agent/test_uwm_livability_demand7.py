import json
from pathlib import Path
from urllib.parse import urlencode

import pytest
from starlette.requests import Request

from data_agent.api import uwm_livability_demand7_routes as routes
from data_agent.uwm.livability_demand7.service import Demand7Service


ROOT = Path(__file__).resolve().parents[1]
TARGET_UNIT = "涪陵区|蔺市镇|498"


def _service() -> Demand7Service:
    return Demand7Service(routes.DEFAULT_PANEL, routes.DEFAULT_PLANNER, routes.DEFAULT_GEOMETRY)


def _request(path, method="GET", payload=None, path_params=None, query_string=b""):
    body = json.dumps(payload or {}).encode()
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [(b"content-type", b"application/json")],
        "query_string": query_string,
        "path_params": path_params or {},
    }
    return Request(scope, receive)


def _auth(monkeypatch):
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: {"id": "planner-7"})
    monkeypatch.setattr(routes, "_set_user_context", lambda user: ("planner-7", "analyst"))


def test_real_product_overview_and_target_unit():
    service = _service()
    overview = service.overview()
    assert overview["counts"] == {
        "state_nodes": 1017,
        "spatial_edges": 7932,
        "available_actions": 1137,
        "stored_replay_transitions": 6817,
    }
    detail = service.unit_detail(TARGET_UNIT)
    assert detail["available_action_count"] == 3
    assert detail["current_state"] == {
        "heat_risk": 0.807424,
        "air_pollution_exposure": 0.683015,
        "service_accessibility": 0.222003,
        "equity": 0.832,
        "livability": 0.168,
    }
    assert detail["geometry_available"] is True


def test_real_replay_deltas_and_profile_ranking():
    service = _service()
    plan = service.plan(TARGET_UNIT, "community_service", "simulator_step")
    recommended = plan["recommended_action"]
    assert recommended["action_type"] == "add_community_service"
    assert recommended["target_unit_delta"]["service_accessibility"] == pytest.approx(0.221413)
    assert recommended["target_unit_delta"]["equity"] == pytest.approx(0.0761563)
    assert recommended["target_unit_delta"]["livability"] == pytest.approx(0.066776695)
    assert recommended["affected_unit_count"] > 1
    assert len(plan["map_payload"]["layers"][0]["geojsonData"]["features"]) == 1
    assert len(plan["map_payload"]["layers"][1]["geojsonData"]["features"]) > 0
    assert len(plan["map_payload"]["layers"][2]["geojsonData"]["features"]) > 0
    assert plan["map_payload"]["metadata"]["underserved_unit_count"] > 0
    assert plan["map_payload"]["metadata"]["underserved_map_scope"].startswith("涪陵区_")
    assert len(plan["map_payload"]["center"]) == 2
    assert plan["evidence"]["not_observed_policy_outcome"] is True
    environmental = service.plan(TARGET_UNIT, "environmental_comfort", "simulator_step")
    assert environmental["recommended_action"]["action_type"] == "increase_green_infrastructure"


@pytest.mark.parametrize("horizon", ["24_month", "five_year"])
def test_calendar_horizons_fail_closed(horizon):
    result = _service().plan(TARGET_UNIT, "balanced", horizon)
    assert result["status"] == "blocked"
    assert result["reason"] == "calendar_horizon_calibration_missing"
    assert "模型步不等于24个月或5年" in result["claim_boundary"]


@pytest.mark.asyncio
async def test_routes_are_authenticated_and_mounted(monkeypatch):
    from data_agent.frontend_api import get_frontend_api_routes

    route_index = {(route.path, method) for route in get_frontend_api_routes() for method in (getattr(route, "methods", None) or [])}
    assert ("/api/uwm/livability/demand7/overview", "GET") in route_index
    assert ("/api/uwm/livability/demand7/plan", "POST") in route_index
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: None)
    response = await routes.demand7_overview(_request("/api/uwm/livability/demand7/overview"))
    assert response.status_code == 401
    _auth(monkeypatch)
    routes._reset_service_cache()
    response = await routes.demand7_units(
        _request("/api/uwm/livability/demand7/units", query_string=urlencode({"search": "蔺市镇"}).encode())
    )
    payload = json.loads(response.body)
    assert response.status_code == 200
    assert any(row["unit_id"] == TARGET_UNIT for row in payload["units"])
    response = await routes.demand7_plan(
        _request(
            "/api/uwm/livability/demand7/plan",
            "POST",
            {"unit_id": TARGET_UNIT, "target_profile": "community_service", "horizon": "simulator_step"},
        )
    )
    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["recommended_action"]["target_unit_delta"]["service_accessibility"] == pytest.approx(0.221413)
