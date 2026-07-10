import json
from pathlib import Path

from data_agent.uwm.traditional_livability_analysis import (
    UWM_TRADITIONAL_LIVABILITY_ANALYSIS_SCHEMA,
    build_traditional_livability_analysis,
    queue_traditional_livability_map,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
SCENE_PATH = (
    DATA_ROOT
    / "multisource_livability_scene_2026_07_06/uwm_multisource_livability_scene.json"
)
ADMIN_UNITS_PATH = DATA_ROOT / "admin_units/chongqing_township_admin_units.geojson"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_analysis() -> dict:
    return build_traditional_livability_analysis(
        analysis_id="uwm-traditional-livability-analysis-real-data-test",
        created_at="2026-07-07T16:20:00Z",
        multisource_livability_scene=_read_json(SCENE_PATH),
        top_n=8,
    )


def test_traditional_livability_analysis_is_complete_static_same_data_output():
    analysis = _build_analysis()

    assert analysis["schema"] == UWM_TRADITIONAL_LIVABILITY_ANALYSIS_SCHEMA
    assert analysis["scene_id"] == "uwm-multisource-livability-scene-2026-07-06"
    assert analysis["summary"]["admin_unit_count"] == 36
    assert analysis["summary"]["priority_unit_count"] == 8
    assert 0.0 <= analysis["summary"]["city_livability_score"] <= 1.0
    assert analysis["summary"]["grade"] in {"A", "B", "C", "D", "E"}

    assert analysis["method"]["name"] == "traditional_static_indicator_weighted_analysis"
    assert analysis["method"]["simulator_used"] is False
    assert analysis["method"]["planner_used"] is False
    assert analysis["method"]["counterfactual_output_available"] is False
    assert analysis["method"]["world_model_components_used"] == []

    ownership = analysis["requirement_ownership"]
    assert ownership["primary_route"] == "traditional_livability"
    assert {row["id"] for row in ownership["livability_scenarios"]} == {
        "S1",
        "S4",
        "S6",
        "S7",
    }
    assert {row["id"] for row in ownership["customer_ai_demands"]} == {
        "8",
        "9",
        "10",
        "12",
        "13",
        "14",
        "15",
        "16",
        "21",
    }

    assert analysis["data_basis"]["admin_unit_count"] == 36
    assert "osm_admin_mobility_crosswalk" in analysis["data_basis"]["data_sources_used"]
    assert (
        analysis["data_basis"]["source_coverage"]["service_accessibility"][
            "matched_admin_units"
        ]
        == 36
    )

    weights = {
        item["dimension_id"]: item["weight"]
        for item in analysis["indicator_system"]["dimensions"]
    }
    assert round(sum(weights.values()), 6) == 1.0
    assert set(weights) == {
        "public_service_accessibility",
        "environment_health",
        "mobility_connectivity",
        "population_exposure_equity",
        "urban_intensity_balance",
    }

    ranked = analysis["ranked_admin_units"]
    assert len(ranked) == 36
    assert ranked[0]["admin_unit_id"] == "九龙坡区|九龙镇|77"
    assert ranked[0]["static_rank"] == 1
    assert ranked[0]["traditional_livability_score"] == 0.0
    assert "public_service_accessibility" in ranked[0]["dimension_scores"]
    assert "公共服务可达性短板" in ranked[0]["issue_tags"]
    assert ranked[0]["recommended_static_actions"]

    assert analysis["priority_diagnosis"][0]["admin_unit_id"] == "九龙坡区|九龙镇|77"
    assert analysis["static_action_plan"]["method"] == "rule_based_current_deficit_priority"
    assert analysis["static_action_plan"]["action_count"] >= 3
    assert "公共服务可达性短板" in {
        issue for row in analysis["priority_diagnosis"] for issue in row["issue_tags"]
    }

    serialized = json.dumps(analysis, ensure_ascii=False)
    assert "counterfactual_state_delta" not in serialized
    assert "predicted_delta" not in serialized
    assert "rollout" not in serialized
    assert analysis["method_boundary"]["cannot_output"] == [
        "action_conditioned_future_state",
        "multi_step_policy_sequence",
        "spatial_spillover_effect",
        "risk_adjusted_counterfactual_benefit",
        "empirical_policy_outcome_superiority",
    ]
    assert analysis["method_boundary"]["world_model_transition_claim"] is False
    assert analysis["method_boundary"]["policy_outcome_claim"] is False


def test_traditional_livability_map_uses_real_admin_geojson_static_scores(tmp_path):
    analysis = _build_analysis()

    payload = queue_traditional_livability_map(
        username="alice",
        analysis=analysis,
        admin_units_geojson_path=ADMIN_UNITS_PATH,
        upload_root=tmp_path,
    )

    assert payload["schema"] == "uwm.traditional_livability_map.v1"
    assert payload["map_update_queued"] is True
    assert payload["matched_feature_count"] == 36
    assert payload["map_update"]["layers"][0]["name"] == "城市宜居性分析（传统方法）"
    assert payload["map_update"]["layers"][0]["type"] == "categorized"
    assert payload["map_update"]["layers"][0]["category_column"] == "static_priority_class"

    layer_path = tmp_path / "alice" / payload["map_update"]["layers"][0]["geojson"]
    layer = _read_json(layer_path)
    assert layer["type"] == "FeatureCollection"
    assert len(layer["features"]) == 36
    top = next(
        feature
        for feature in layer["features"]
        if feature["properties"]["admin_unit_id"] == "九龙坡区|九龙镇|77"
    )
    assert top["properties"]["static_rank"] == 1
    assert top["properties"]["traditional_livability_score"] == 0.0
    assert top["properties"]["static_priority_class"] == "高优先级"
