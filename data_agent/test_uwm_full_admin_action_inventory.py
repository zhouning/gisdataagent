import json
from pathlib import Path

from data_agent.test_uwm_full_admin_energy_regularized_planner import _full_admin_env
from data_agent.uwm.full_admin_action_inventory import (
    UWM_FULL_ADMIN_ACTION_INVENTORY_SCHEMA,
    build_full_admin_action_inventory,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
ARTIFACT_PATH = (
    DATA_ROOT
    / "full_admin_action_inventory_2026_07_08/uwm_full_admin_action_inventory.json"
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_full_admin_action_inventory_enumerates_all_feasible_actions():
    inventory = build_full_admin_action_inventory(
        _full_admin_env(),
        inventory_id="uwm-full-admin-action-inventory-test",
        created_at="2026-07-08T21:00:00Z",
        spatial_causal_question_registry=_read_json(
            DATA_ROOT
            / "spatial_causal_question_registry_2026_07_09/uwm_spatial_causal_question_registry.json"
        ),
    )

    assert inventory["schema"] == UWM_FULL_ADMIN_ACTION_INVENTORY_SCHEMA
    assert inventory["experiment_scope"] == "full_admin_graph"
    assert inventory["full_data_guard"]["passed"] is True
    assert inventory["full_data_guard"]["graph_node_count"] == 1017
    assert inventory["full_data_guard"]["graph_edge_count"] == 7932
    assert inventory["full_data_guard"]["available_action_count"] == 1137
    assert inventory["summary"]["action_type_counts"] == {
        "increase_green_infrastructure": 81,
        "traffic_emission_control": 77,
        "add_community_service": 979,
    }
    assert inventory["summary"]["mask_reason_counts"] == {
        "heat_risk_above_threshold": 81,
        "air_pollution_exposure_above_threshold": 77,
        "service_accessibility_below_threshold": 979,
    }
    assert len(inventory["actions"]) == 1137
    assert inventory["spatial_causal_contract_binding"]["binding_ready"] is True
    assert inventory["spatial_causal_contract_binding"]["feasible_action_count"] == 1137
    assert inventory["spatial_causal_contract_binding"]["attached_action_count"] == 1137
    assert (
        inventory["spatial_causal_contract_binding"][
            "missing_contract_action_count"
        ]
        == 0
    )
    assert (
        inventory["spatial_causal_contract_binding"][
            "underidentified_policy_effect_action_count"
        ]
        == 1137
    )
    assert (
        inventory["spatial_causal_contract_binding"][
            "policy_outcome_claim_allowed_action_count"
        ]
        == 0
    )

    first = inventory["actions"][0]
    assert first["action_index"] == 0
    assert first["action_id"] == "increase_green_infrastructure-涪陵区|蔺市镇|498"
    assert first["target_unit_id"] == "涪陵区|蔺市镇|498"
    assert first["action_type_definition"]["state_trigger"] == "heat_risk >= 0.7"
    assert first["target_features"]["heat_risk"] >= 0.7
    assert first["causal_question_id"] == "uwm-cq-green-heat-livability"
    assert first["causal_query"] == (
        "P(heat_risk, livability | do(increase_green_infrastructure), spatial_context)"
    )
    assert first["primary_outcome"] == "heat_risk"
    assert first["identification_status"] == (
        "underidentified_for_observed_policy_effect"
    )
    assert first["required_authoritative_tables"] == [
        "policy_project_history",
        "action_constraint_cost_model",
        "observed_outcome_validation_panel",
        "causal_effect_calibration_panel",
        "human_governance_review_log",
    ]
    assert first["policy_outcome_claim_allowed"] is False
    assert first["observed_policy_outcome_superiority_claim"] is False

    service_actions = [
        action
        for action in inventory["actions"]
        if action["action_type"] == "add_community_service"
    ]
    assert len(service_actions) == 979
    assert all(
        action["target_features"]["service_accessibility"] <= 0.5
        for action in service_actions
    )
    assert all(
        action["causal_question_id"] == "uwm-cq-service-equity-livability"
        for action in service_actions
    )

    assert inventory["supported_claim"] == (
        "full_admin_graph_feasible_action_inventory_enumerates_real_data_graph_mdp_actions"
    )
    assert inventory["observed_policy_outcome_superiority_claim"] is False
    assert inventory["empirical_superiority_claim"] is False


def test_full_admin_action_inventory_artifact_is_complete():
    inventory = _read_json(ARTIFACT_PATH)

    assert inventory["schema"] == UWM_FULL_ADMIN_ACTION_INVENTORY_SCHEMA
    assert inventory["full_data_guard"]["passed"] is True
    assert inventory["summary"]["available_action_count"] == 1137
    assert len(inventory["actions"]) == 1137
    assert inventory["spatial_causal_contract_binding"]["binding_ready"] is True
    assert inventory["spatial_causal_contract_binding"]["attached_action_count"] == 1137
    assert (
        inventory["spatial_causal_contract_binding"][
            "missing_contract_action_count"
        ]
        == 0
    )
    assert (
        inventory["spatial_causal_contract_binding"][
            "policy_outcome_claim_allowed_action_count"
        ]
        == 0
    )
    assert inventory["summary"]["action_type_counts"]["add_community_service"] == 979
    assert {
        "increase_green_infrastructure-沙坪坝区|覃家岗街道|973",
        "increase_green_infrastructure-沙坪坝区|歌乐山镇|800",
    }.issubset({action["action_id"] for action in inventory["actions"]})
    action_by_id = {action["action_id"]: action for action in inventory["actions"]}
    assert action_by_id[
        "increase_green_infrastructure-沙坪坝区|覃家岗街道|973"
    ]["causal_question_id"] == "uwm-cq-green-heat-livability"
    assert action_by_id[
        "add_community_service-涪陵区|蔺市镇|498"
    ]["causal_question_id"] == "uwm-cq-service-equity-livability"
    assert inventory["observed_policy_outcome_superiority_claim"] is False
