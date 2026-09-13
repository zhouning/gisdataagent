import json
from pathlib import Path

from data_agent.uwm.production_governance_data_contract import (
    UWM_PRODUCTION_GOVERNANCE_DATA_CONTRACT_SCHEMA,
    build_uwm_production_governance_data_contract,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
ARTIFACT_PATH = (
    DATA_ROOT
    / "production_governance_data_contract_2026_07_08/uwm_production_governance_data_contract.json"
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_contract() -> dict:
    return build_uwm_production_governance_data_contract(
        contract_id="uwm-production-governance-data-contract-test",
        created_at="2026-07-08T23:55:00Z",
        production_action_catalog=_read_json(
            DATA_ROOT
            / "production_action_catalog_2026_07_08/uwm_production_action_catalog.json"
        ),
        data_foundation_evidence_gate=_read_json(
            DATA_ROOT
            / "data_foundation_evidence_gate_2026_07_05/uwm_data_foundation_evidence_gate.json"
        ),
    )


def test_production_governance_data_contract_blocks_policy_outcome_shortcuts():
    contract = _build_contract()

    assert (
        contract["schema"] == UWM_PRODUCTION_GOVERNANCE_DATA_CONTRACT_SCHEMA
    )
    assert contract["experiment_scope"] == "full_admin_graph"
    assert contract["governance_data_contract_ready"] is True
    assert contract["future_authoritative_data_extension_ready"] is True
    assert contract["planner_governance_binding_ready"] is False
    assert contract["policy_project_history_ready"] is False
    assert contract["constraint_cost_model_ready"] is False
    assert contract["observed_outcome_panel_ready"] is False
    assert contract["causal_effect_calibration_ready"] is False
    assert contract["human_governance_review_ready"] is False
    assert contract["production_readiness_claim"] is False
    assert contract["observed_policy_outcome_superiority_claim"] is False
    assert contract["empirical_superiority_claim"] is False

    summary = contract["summary"]
    assert summary["production_action_type_count"] == 57
    assert summary["currently_bound_feasible_action_count"] == 1137
    assert summary["required_governance_table_count"] == 5
    assert summary["ready_governance_table_count"] == 0
    assert summary["planning_sample_source_count"] == 15
    assert summary["manifest_row_count"] == 75
    assert summary["local_planning_sample_is_policy_history"] is False
    assert summary["authoritative_policy_project_history_row_count"] == 0
    assert summary["authoritative_constraint_cost_row_count"] == 0
    assert summary["observed_outcome_validation_row_count"] == 0

    tables = {table["table_id"]: table for table in contract["required_tables"]}
    assert set(tables) == {
        "policy_project_history",
        "action_constraint_cost_model",
        "observed_outcome_validation_panel",
        "causal_effect_calibration_panel",
        "human_governance_review_log",
    }
    assert tables["policy_project_history"]["ready"] is False
    assert tables["policy_project_history"]["minimum_required_fields"] == [
        "project_id",
        "action_type",
        "target_geometry",
        "start_date",
        "end_date",
        "implementation_status",
        "budget_cost",
        "responsible_department",
        "approval_status",
        "source_document_id",
        "synthetic_status",
        "quality_flag",
    ]
    assert "legal_feasibility" in tables[
        "action_constraint_cost_model"
    ]["minimum_required_fields"]
    assert "post_outcome_value" in tables[
        "observed_outcome_validation_panel"
    ]["minimum_required_fields"]
    assert "negative_control_result" in tables[
        "causal_effect_calibration_panel"
    ]["minimum_required_fields"]

    action_requirements = {
        item["action_type"]: item
        for item in contract["action_type_governance_requirements"]
    }
    assert len(action_requirements) == 57
    assert action_requirements["increase_green_infrastructure"][
        "current_action_binding_status"
    ] == "implemented_bounded_support"
    assert action_requirements["increase_green_infrastructure"][
        "governance_binding_status"
    ] == "current_abstract_binding_only_missing_governance_data"
    assert action_requirements["increase_green_infrastructure"][
        "planner_search_allowed_with_production_claim"
    ] is False
    assert action_requirements["bus_route_adjustment"][
        "current_action_binding_status"
    ] == "production_target_unbound"
    assert action_requirements["bus_route_adjustment"][
        "governance_binding_status"
    ] == "production_target_unbound_missing_governance_data"

    ingestion = contract["future_data_ingestion_contract"]
    assert ingestion["schema_evolution_rule"] == "versioned_additive_no_rewrite"
    assert "policy_project_history_adapter" in ingestion["adapter_slots"]
    assert "constraint_cost_model_adapter" in ingestion["adapter_slots"]
    assert "reject_planner_production_claim_without_observed_outcome_panel" in ingestion[
        "planner_binding_gates"
    ]
    assert contract["claim_boundary"]["max_claim_level"] == (
        "governance_data_contract_gap_only"
    )


def test_production_governance_data_contract_artifact_is_rebuilt_without_fake_rows():
    contract = _read_json(ARTIFACT_PATH)

    assert contract["schema"] == UWM_PRODUCTION_GOVERNANCE_DATA_CONTRACT_SCHEMA
    assert contract["summary"]["production_action_type_count"] == 57
    assert contract["summary"]["currently_bound_feasible_action_count"] == 1137
    assert contract["summary"]["ready_governance_table_count"] == 0
    assert contract["summary"]["authoritative_policy_project_history_row_count"] == 0
    assert contract["planner_governance_binding_ready"] is False
    assert contract["observed_policy_outcome_superiority_claim"] is False
