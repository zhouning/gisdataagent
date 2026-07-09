import csv
import json
from pathlib import Path

from data_agent.uwm.production_governance_linkage_audit import (
    UWM_PRODUCTION_GOVERNANCE_LINKAGE_AUDIT_SCHEMA,
    build_uwm_production_governance_linkage_audit,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
ARTIFACT_PATH = (
    DATA_ROOT
    / "production_governance_linkage_audit_2026_07_08/uwm_production_governance_linkage_audit.json"
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_audit(input_dir: Path | None = None) -> dict:
    return build_uwm_production_governance_linkage_audit(
        audit_id="uwm-production-governance-linkage-audit-test",
        created_at="2026-07-08T23:59:30Z",
        adapter_readiness=_read_json(
            DATA_ROOT
            / "production_governance_data_adapter_readiness_2026_07_08/uwm_production_governance_data_adapter_readiness.json"
        ),
        governance_input_dir=input_dir
        or DATA_ROOT / "authoritative_governance_inputs_2026_07_08",
    )


def test_governance_linkage_audit_is_not_ready_without_authoritative_tables():
    audit = _build_audit()

    assert audit["schema"] == UWM_PRODUCTION_GOVERNANCE_LINKAGE_AUDIT_SCHEMA
    assert audit["experiment_scope"] == "full_admin_graph"
    assert audit["linkage_audit_ready"] is True
    assert audit["all_required_tables_present"] is False
    assert audit["governance_linkage_ready"] is False
    assert audit["planner_governance_binding_ready"] is False
    assert audit["production_readiness_claim"] is False
    assert audit["observed_policy_outcome_superiority_claim"] is False

    summary = audit["summary"]
    assert summary["expected_table_count"] == 5
    assert summary["present_table_count"] == 0
    assert summary["missing_table_count"] == 5
    assert summary["policy_project_count"] == 0
    assert summary["linked_project_count"] == 0
    assert summary["unlinked_project_count"] == 0
    assert summary["project_with_constraint_count"] == 0
    assert summary["project_with_observed_outcome_count"] == 0
    assert summary["project_with_causal_effect_count"] == 0
    assert summary["project_with_human_review_count"] == 0

    assert audit["missing_tables"] == [
        "policy_project_history",
        "action_constraint_cost_model",
        "observed_outcome_validation_panel",
        "causal_effect_calibration_panel",
        "human_governance_review_log",
    ]
    assert audit["claim_boundary"]["max_claim_level"] == (
        "governance_linkage_audit_only"
    )


def test_governance_linkage_audit_passes_for_complete_authoritative_fixture(tmp_path):
    _write_table(
        tmp_path / "policy_project_history.csv",
        [
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
        ],
        {
            "project_id": "project-001",
            "action_type": "add_community_service",
            "target_geometry": "POLYGON-A",
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "implementation_status": "implemented",
            "budget_cost": "1000000",
            "responsible_department": "civil_affairs",
            "approval_status": "approved",
            "source_document_id": "doc-001",
            "synthetic_status": "real",
            "quality_flag": "verified",
        },
    )
    _write_table(
        tmp_path / "action_constraint_cost_model.csv",
        [
            "constraint_id",
            "action_type",
            "target_geometry",
            "legal_feasibility",
            "land_constraint",
            "budget_cost",
            "implementation_time",
            "maintenance_cost",
            "responsible_department",
            "approval_rule_id",
            "constraint_source_id",
            "quality_flag",
        ],
        {
            "constraint_id": "constraint-001",
            "action_type": "add_community_service",
            "target_geometry": "POLYGON-A",
            "legal_feasibility": "allowed",
            "land_constraint": "available",
            "budget_cost": "1000000",
            "implementation_time": "12",
            "maintenance_cost": "100000",
            "responsible_department": "civil_affairs",
            "approval_rule_id": "rule-001",
            "constraint_source_id": "constraint-doc-001",
            "quality_flag": "verified",
        },
    )
    _write_table(
        tmp_path / "observed_outcome_validation_panel.csv",
        [
            "outcome_id",
            "project_id",
            "target_geometry",
            "outcome_variable",
            "pre_outcome_value",
            "post_outcome_value",
            "observation_time",
            "observation_source_id",
            "measurement_method",
            "quality_flag",
        ],
        {
            "outcome_id": "outcome-001",
            "project_id": "project-001",
            "target_geometry": "POLYGON-A",
            "outcome_variable": "service_accessibility",
            "pre_outcome_value": "0.3",
            "post_outcome_value": "0.5",
            "observation_time": "2026-01-01",
            "observation_source_id": "obs-001",
            "measurement_method": "authoritative_panel",
            "quality_flag": "verified",
        },
    )
    _write_table(
        tmp_path / "causal_effect_calibration_panel.csv",
        [
            "effect_id",
            "project_id",
            "action_type",
            "treatment_geometry",
            "control_geometry",
            "estimator",
            "effect_size",
            "confidence_interval",
            "placebo_result",
            "negative_control_result",
            "spatial_autocorrelation_diagnostic",
            "quality_flag",
        ],
        {
            "effect_id": "effect-001",
            "project_id": "project-001",
            "action_type": "add_community_service",
            "treatment_geometry": "POLYGON-A",
            "control_geometry": "POLYGON-B",
            "estimator": "did_matched_control",
            "effect_size": "0.2",
            "confidence_interval": "[0.1,0.3]",
            "placebo_result": "passed",
            "negative_control_result": "passed",
            "spatial_autocorrelation_diagnostic": "passed",
            "quality_flag": "verified",
        },
    )
    _write_table(
        tmp_path / "human_governance_review_log.csv",
        [
            "review_id",
            "project_id",
            "reviewer_department",
            "review_decision",
            "decision_reason",
            "review_time",
            "review_document_id",
            "quality_flag",
        ],
        {
            "review_id": "review-001",
            "project_id": "project-001",
            "reviewer_department": "planning",
            "review_decision": "approved",
            "decision_reason": "complete evidence",
            "review_time": "2026-01-15T00:00:00Z",
            "review_document_id": "review-doc-001",
            "quality_flag": "verified",
        },
    )

    audit = _build_audit(tmp_path)

    assert audit["all_required_tables_present"] is True
    assert audit["governance_linkage_ready"] is True
    assert audit["planner_governance_binding_ready"] is False
    assert audit["summary"]["policy_project_count"] == 1
    assert audit["summary"]["linked_project_count"] == 1
    assert audit["summary"]["unlinked_project_count"] == 0
    assert audit["project_linkage"][0]["project_id"] == "project-001"
    assert audit["project_linkage"][0]["complete_linkage"] is True


def test_governance_linkage_audit_artifact_is_currently_not_ready():
    audit = _read_json(ARTIFACT_PATH)

    assert audit["schema"] == UWM_PRODUCTION_GOVERNANCE_LINKAGE_AUDIT_SCHEMA
    assert audit["summary"]["expected_table_count"] == 5
    assert audit["summary"]["present_table_count"] == 0
    assert audit["summary"]["missing_table_count"] == 5
    assert audit["governance_linkage_ready"] is False
    assert audit["planner_governance_binding_ready"] is False


def _write_table(path: Path, fields: list[str], row: dict[str, str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)
