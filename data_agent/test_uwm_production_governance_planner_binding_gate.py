import json
from pathlib import Path

from data_agent.uwm.production_governance_planner_binding_gate import (
    UWM_PRODUCTION_GOVERNANCE_PLANNER_BINDING_GATE_SCHEMA,
    build_uwm_production_governance_planner_binding_gate,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
ARTIFACT_PATH = (
    DATA_ROOT
    / "production_governance_planner_binding_gate_2026_07_08/uwm_production_governance_planner_binding_gate.json"
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_gate(
    *,
    adapter_readiness: dict | None = None,
    linkage_audit: dict | None = None,
) -> dict:
    return build_uwm_production_governance_planner_binding_gate(
        gate_id="uwm-production-governance-planner-binding-gate-test",
        created_at="2026-07-09T00:08:00Z",
        production_action_catalog=_read_json(
            DATA_ROOT
            / "production_action_catalog_2026_07_08/uwm_production_action_catalog.json"
        ),
        governance_data_contract=_read_json(
            DATA_ROOT
            / "production_governance_data_contract_2026_07_08/uwm_production_governance_data_contract.json"
        ),
        adapter_readiness=adapter_readiness
        or _read_json(
            DATA_ROOT
            / "production_governance_data_adapter_readiness_2026_07_08/uwm_production_governance_data_adapter_readiness.json"
        ),
        linkage_audit=linkage_audit
        or _read_json(
            DATA_ROOT
            / "production_governance_linkage_audit_2026_07_08/uwm_production_governance_linkage_audit.json"
        ),
    )


def test_planner_binding_gate_blocks_current_missing_authoritative_governance_data():
    gate = _build_gate()

    assert gate["schema"] == UWM_PRODUCTION_GOVERNANCE_PLANNER_BINDING_GATE_SCHEMA
    assert gate["experiment_scope"] == "full_admin_graph"
    assert gate["binding_gate_ready"] is True
    assert gate["planner_governance_binding_ready"] is False
    assert gate["authoritative_governance_data_closure_ready"] is False
    assert gate["production_readiness_claim"] is False
    assert gate["observed_policy_outcome_superiority_claim"] is False
    assert gate["empirical_superiority_claim"] is False

    summary = gate["summary"]
    assert summary["required_gate_count"] == 9
    assert summary["passed_gate_count"] == 2
    assert summary["blocking_gate_count"] == 7
    assert summary["expected_table_count"] == 5
    assert summary["ready_table_count"] == 0
    assert summary["missing_table_count"] == 5
    assert summary["accepted_authoritative_row_count"] == 0
    assert summary["linked_project_count"] == 0
    assert summary["currently_bound_feasible_action_count"] == 1137

    gates = {item["gate_id"]: item for item in gate["gate_results"]}
    assert gates["action_catalog_contract_ready"]["passed"] is True
    assert gates["governance_data_contract_ready"]["passed"] is True
    assert gates["adapter_all_required_tables_ready"]["passed"] is False
    assert gates["adapter_authoritative_rows_nonzero_per_table"]["passed"] is False
    assert gates["linkage_all_required_tables_present"]["passed"] is False
    assert gates["linkage_governance_linkage_ready"]["passed"] is False
    assert gates["observed_outcome_panel_authoritative_rows_ready"]["passed"] is False
    assert gates["causal_effect_calibration_authoritative_rows_ready"]["passed"] is False
    assert gates["human_governance_review_authoritative_rows_ready"]["passed"] is False

    assert "adapter_all_required_tables_ready" in gate["blocking_gate_ids"]
    assert "linkage_governance_linkage_ready" in gate["blocking_gate_ids"]
    assert gate["claim_boundary"]["max_claim_level"] == (
        "planner_governance_binding_gate_only"
    )


def test_planner_binding_gate_can_pass_data_closure_without_policy_outcome_claim():
    gate = _build_gate(
        adapter_readiness=_ready_adapter_readiness(),
        linkage_audit=_ready_linkage_audit(),
    )

    assert gate["binding_gate_ready"] is True
    assert gate["authoritative_governance_data_closure_ready"] is True
    assert gate["planner_governance_binding_ready"] is True
    assert gate["summary"]["required_gate_count"] == 9
    assert gate["summary"]["passed_gate_count"] == 9
    assert gate["summary"]["blocking_gate_count"] == 0
    assert gate["summary"]["accepted_authoritative_row_count"] == 5
    assert gate["summary"]["linked_project_count"] == 1
    assert gate["blocking_gate_ids"] == []
    assert gate["production_readiness_claim"] is False
    assert gate["observed_policy_outcome_superiority_claim"] is False
    assert gate["empirical_superiority_claim"] is False


def test_planner_binding_gate_artifact_is_currently_blocked():
    gate = _read_json(ARTIFACT_PATH)

    assert gate["schema"] == UWM_PRODUCTION_GOVERNANCE_PLANNER_BINDING_GATE_SCHEMA
    assert gate["summary"]["required_gate_count"] == 9
    assert gate["summary"]["passed_gate_count"] == 2
    assert gate["summary"]["blocking_gate_count"] == 7
    assert gate["summary"]["missing_table_count"] == 5
    assert gate["summary"]["linked_project_count"] == 0
    assert gate["planner_governance_binding_ready"] is False
    assert gate["observed_policy_outcome_superiority_claim"] is False


def _ready_adapter_readiness() -> dict:
    table_ids = [
        "policy_project_history",
        "action_constraint_cost_model",
        "observed_outcome_validation_panel",
        "causal_effect_calibration_panel",
        "human_governance_review_log",
    ]
    return {
        "schema": "uwm.production_governance_data_adapter_readiness.v1",
        "experiment_scope": "full_admin_graph",
        "adapter_contract_ready": True,
        "all_required_tables_ready": True,
        "planner_governance_binding_ready": False,
        "summary": {
            "expected_table_count": 5,
            "ready_table_count": 5,
            "missing_source_table_count": 0,
            "schema_invalid_table_count": 0,
            "total_row_count": 5,
            "accepted_authoritative_row_count": 5,
            "rejected_row_count": 0,
        },
        "table_readiness": [
            {
                "table_id": table_id,
                "source_exists": True,
                "schema_valid": True,
                "row_count": 1,
                "accepted_authoritative_row_count": 1,
                "rejected_row_count": 0,
                "ready": True,
            }
            for table_id in table_ids
        ],
        "production_readiness_claim": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _ready_linkage_audit() -> dict:
    return {
        "schema": "uwm.production_governance_linkage_audit.v1",
        "experiment_scope": "full_admin_graph",
        "linkage_audit_ready": True,
        "all_required_tables_present": True,
        "governance_linkage_ready": True,
        "planner_governance_binding_ready": False,
        "summary": {
            "expected_table_count": 5,
            "present_table_count": 5,
            "missing_table_count": 0,
            "policy_project_count": 1,
            "linked_project_count": 1,
            "unlinked_project_count": 0,
            "project_with_constraint_count": 1,
            "project_with_observed_outcome_count": 1,
            "project_with_causal_effect_count": 1,
            "project_with_human_review_count": 1,
        },
        "production_readiness_claim": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }
