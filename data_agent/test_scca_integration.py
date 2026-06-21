from __future__ import annotations

import json
from types import SimpleNamespace

from starlette.testclient import TestClient


def _user() -> SimpleNamespace:
    return SimpleNamespace(identifier="analyst", metadata={"role": "analyst"})


def test_scca_service_lists_builtin_cases():
    from data_agent.scca_service import list_scca_cases

    payload = list_scca_cases()

    case_ids = {case["case_id"] for case in payload["cases"]}
    assert {"chongqing_uhi", "county_social_capital"}.issubset(case_ids)


def test_scca_service_runs_chongqing_and_county_workflows(tmp_path):
    from data_agent.scca_service import run_scca_case

    chongqing = run_scca_case("chongqing_uhi", row_limit=80, output_root=tmp_path)
    county = run_scca_case("county_social_capital", row_limit=80, output_root=tmp_path)

    for result in (chongqing, county):
        assert result["row_count"] > 0
        assert result["effect_estimates"]
        assert result["evidence_grade"]
        assert "manifest" in result["files"]
        assert result["user_summary"]["headline"]
        assert result["user_summary"]["map_plain"]


def test_scca_default_run_uses_full_sample_data(tmp_path):
    from data_agent.scca_service import run_scca_case

    chongqing = run_scca_case("chongqing_uhi", output_root=tmp_path)
    county = run_scca_case("county_social_capital", output_root=tmp_path)

    assert chongqing["row_limit"] is None
    assert chongqing["row_count"] > 4900
    assert chongqing["raw_input_count"] == 5000
    assert chongqing["user_summary"]["coverage"]["mapped_features"] == chongqing["row_count"]
    assert county["row_limit"] is None
    assert county["row_count"] > 3000
    assert county["user_summary"]["coverage"]["mapped_features"] > 3000


def test_scca_chongqing_outputs_original_building_polygons(tmp_path):
    from data_agent.scca_service import run_scca_case

    result = run_scca_case("chongqing_uhi", row_limit=80, output_root=tmp_path)

    spatial = result["spatial_outputs"]
    assert spatial["map_kind"] == "building"
    assert spatial["source_geometry"] == "chongqing_buildings_shp"
    assert spatial["match_summary"]["matched_count"] >= 75
    assert spatial["match_summary"]["floor_match_count"] >= 75
    assert result["map_update"]["layers"][0]["type"] == "choropleth"

    with open(spatial["geojson"], encoding="utf-8") as f:
        geojson = json.load(f)
    geometry_types = {feature["geometry"]["type"] for feature in geojson["features"]}
    assert geometry_types <= {"Polygon", "MultiPolygon"}


def test_scca_county_outputs_county_polygons(tmp_path):
    from data_agent.scca_service import run_scca_case

    result = run_scca_case("county_social_capital", row_limit=80, output_root=tmp_path)

    assert result["spatial_outputs"]["map_kind"] == "county"
    assert result["map_update"]["layers"][0]["type"] == "choropleth"
    with open(result["spatial_outputs"]["geojson"], encoding="utf-8") as f:
        geojson = json.load(f)
    geometry_types = {feature["geometry"]["type"] for feature in geojson["features"]}
    assert geometry_types <= {"Polygon", "MultiPolygon"}


def test_scca_routes_are_registered():
    from data_agent.api.causal_routes import get_causal_routes

    paths = {route.path for route in get_causal_routes()}

    assert "/api/causal/scca/cases" in paths
    assert "/api/causal/scca/run" in paths


def test_scca_cases_route_requires_auth(monkeypatch):
    from data_agent.api import causal_routes
    from data_agent.api.causal_routes import get_causal_routes
    from starlette.applications import Starlette

    monkeypatch.setattr(causal_routes, "_get_user_from_request", lambda request: None)
    client = TestClient(Starlette(routes=get_causal_routes()))

    response = client.get("/api/causal/scca/cases")

    assert response.status_code == 401


def test_scca_run_route_executes_builtin_case(monkeypatch, tmp_path):
    from data_agent.api import causal_routes
    from data_agent.api.causal_routes import get_causal_routes
    from data_agent import scca_service
    from starlette.applications import Starlette

    monkeypatch.setattr(causal_routes, "_get_user_from_request", lambda request: _user())

    original_run = scca_service.run_scca_case

    def run_with_tmp(case_id: str, *, row_limit=None, user_id=None):
        return original_run(case_id, row_limit=row_limit, output_root=tmp_path, user_id=user_id)

    monkeypatch.setattr(scca_service, "run_scca_case", run_with_tmp)
    client = TestClient(Starlette(routes=get_causal_routes()))

    response = client.post(
        "/api/causal/scca/run",
        json={"case_id": "chongqing_uhi", "row_limit": 80},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["case_id"] == "chongqing_uhi"
    assert payload["row_count"] > 0
    assert payload["effect_estimates"]
    assert payload["map_update"]["layers"]
    assert payload["map_update_queued"] is True
