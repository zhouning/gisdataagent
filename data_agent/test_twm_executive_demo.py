import asyncio
import json
from types import SimpleNamespace

from starlette.requests import Request

from data_agent.api import territory_world_model_routes as routes
from data_agent.territory_world_model import executive_demo


def fake_request(method: str = "GET") -> Request:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request({"type": "http", "method": method, "path": "/api/twm/executive-demo-report", "headers": []}, receive)


def test_executive_demo_report_aggregates_current_evidence_without_promoting_claims():
    report = executive_demo.build_executive_demo_report()

    assert report["schema"] == executive_demo.REPORT_SCHEMA
    assert report["status"] == "controlled_demo_ready"
    assert report["positioning"]["production_claim_supported"] is False

    definition = report["gwm_definition"]
    assert "不是给通用世界模型追加经纬度特征" in definition["not_coordinate_appendage"]
    assert [item["dimension"] for item in definition["fusion_dimensions"]] == ["状态", "关系", "转移", "验证与交付"]

    simulator = report["simulator"]
    assert "组合式状态转移与写回协议" in simulator["definition"]
    assert [item["id"] for item in simulator["pipeline"]] == ["state", "action", "route", "delta", "write_back", "rollout"]
    assert {item["source"] for item in simulator["transition_sources"]} >= {"GIS 确定性计算", "规则 / Action Mask", "Geospatial Kernel / Learned", "Unknown Gate"}
    assert [item["family"] for item in simulator["comparison"]] == ["视觉 / 机器人世界模型", "科学模拟 / 数字孪生", "GeoSOS-FLUS", "GWM Simulator"]
    assert "不自动等于政策因果识别" in simulator["claim_boundary"]
    assert "DAM-GK 建模动态" not in next(item["detail"] for item in report["decision_story"] if item["id"] == "simulate")

    paper9 = report["paper9v2"]
    assert paper9["status"] == "verified_offline_run"
    assert paper9["source_available"] is True
    assert paper9["source_mode"] == "live_offline_artifacts"
    assert len(paper9["cases"]) == 2
    assert {item["id"]: item["label"] for item in paper9["cases"]} == {
        "dongxing": "四川省内江市东兴区",
        "bishan": "重庆市璧山区",
    }
    assert all(item["hard_constraint_passed"] for item in paper9["cases"])
    assert "不等于方案已获业务审批" in paper9["claim_boundary"]

    foundation = report["twm_foundation"]
    assert foundation["record_count"] == 22401
    assert foundation["spatial_feature_count"] == 21603
    assert foundation["production_observed_history_rows"] == 0
    assert foundation["production_policy_history_rows"] == 0

    event = report["natural_resource_event_compilation"]
    assert [item["count"] for item in event["pipeline"]] == [62, 13, 9, 194, 194, 194]
    assert event["training_admission"] is False
    assert event["comparison_design_complete"] is False

    benchmark = report["gwm_benchmark"]
    matrix = {item["id"]: item for item in benchmark["matrix"]}
    assert matrix["full_kernel_passes_existing_core_reference_gate"]["pass_count"] == 0
    assert matrix["full_kernel_beats_no_graph_mean_core_nmae"]["pass_count"] == 10
    assert benchmark["candidate_v03"]["compiled_object_count"] > 0
    assert benchmark["candidate_v03"]["training_input_admitted"] is False


def test_paper9_missing_external_assets_use_labeled_validation_snapshot(tmp_path):
    report = executive_demo.build_executive_demo_report(paper9_root=tmp_path / "missing-paper9")

    paper9 = report["paper9v2"]
    assert paper9["status"] == "verified_offline_run"
    assert paper9["source_available"] is False
    assert paper9["source_mode"] == "embedded_validation_snapshot"
    assert paper9["source_date"] == "2026-06-27"
    assert len(paper9["source_sha256"]) == 64


def test_missing_repo_evidence_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(executive_demo, "REPO_ROOT", tmp_path)
    report = executive_demo.build_executive_demo_report(paper9_root=tmp_path / "missing-paper9")

    assert report["status"] == "review"
    assert report["positioning"]["production_claim_supported"] is False
    assert report["twm_foundation"]["source_available"] is False
    assert report["natural_resource_event_compilation"]["source_available"] is False
    assert report["natural_resource_event_compilation"]["training_admission"] is False
    assert report["gwm_benchmark"]["source_available"] is False
    assert report["gwm_benchmark"]["candidate_v03"]["training_input_admitted"] is False


def test_executive_demo_route_requires_auth(monkeypatch):
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: None)
    response = asyncio.run(routes.twm_executive_demo_report(fake_request()))

    assert response.status_code == 401
    assert json.loads(response.body) == {"error": "Unauthorized"}


def test_executive_demo_route_returns_service_report(monkeypatch):
    payload = {
        "schema": executive_demo.REPORT_SCHEMA,
        "status": "controlled_demo_ready",
        "positioning": {"production_claim_supported": False},
    }
    user = SimpleNamespace(identifier="director-demo", metadata={"role": "analyst"})
    service = SimpleNamespace(executive_demo_report=lambda: payload)
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "_set_user_context", lambda current_user: (current_user.identifier, "analyst"))
    monkeypatch.setattr(routes, "get_territory_world_model_service", lambda: service)

    response = asyncio.run(routes.twm_executive_demo_report(fake_request()))

    assert response.status_code == 200
    assert json.loads(response.body) == payload
    registered_paths = {route.path for route in routes.get_territory_world_model_routes()}
    assert "/api/twm/executive-demo-report" in registered_paths
