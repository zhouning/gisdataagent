import csv
import json
from pathlib import Path

from data_agent.uwm.production_governance_data_adapter import (
    UWM_PRODUCTION_GOVERNANCE_DATA_ADAPTER_READINESS_SCHEMA,
    build_uwm_production_governance_data_adapter_readiness,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
ARTIFACT_PATH = (
    DATA_ROOT
    / "production_governance_data_adapter_readiness_2026_07_08/uwm_production_governance_data_adapter_readiness.json"
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_readiness(input_dir: Path | None = None) -> dict:
    return build_uwm_production_governance_data_adapter_readiness(
        audit_id="uwm-production-governance-data-adapter-readiness-test",
        created_at="2026-07-08T23:58:00Z",
        governance_data_contract=_read_json(
            DATA_ROOT
            / "production_governance_data_contract_2026_07_08/uwm_production_governance_data_contract.json"
        ),
        expected_input_dir=input_dir
        or DATA_ROOT / "authoritative_governance_inputs_2026_07_08",
    )


def test_governance_data_adapter_reports_missing_authoritative_tables_without_fake_rows():
    readiness = _build_readiness()

    assert (
        readiness["schema"]
        == UWM_PRODUCTION_GOVERNANCE_DATA_ADAPTER_READINESS_SCHEMA
    )
    assert readiness["experiment_scope"] == "full_admin_graph"
    assert readiness["adapter_contract_ready"] is True
    assert readiness["all_required_tables_ready"] is False
    assert readiness["planner_governance_binding_ready"] is False
    assert readiness["production_readiness_claim"] is False
    assert readiness["observed_policy_outcome_superiority_claim"] is False
    assert readiness["empirical_superiority_claim"] is False

    summary = readiness["summary"]
    assert summary["expected_table_count"] == 5
    assert summary["ready_table_count"] == 0
    assert summary["missing_source_table_count"] == 5
    assert summary["schema_invalid_table_count"] == 0
    assert summary["total_row_count"] == 0
    assert summary["accepted_authoritative_row_count"] == 0
    assert summary["rejected_row_count"] == 0

    tables = {table["table_id"]: table for table in readiness["table_readiness"]}
    assert set(tables) == {
        "policy_project_history",
        "action_constraint_cost_model",
        "observed_outcome_validation_panel",
        "causal_effect_calibration_panel",
        "human_governance_review_log",
    }
    assert tables["policy_project_history"]["source_exists"] is False
    assert tables["policy_project_history"]["ready"] is False
    assert tables["policy_project_history"]["missing_fields"] == []
    assert tables["policy_project_history"]["accepted_authoritative_row_count"] == 0

    assert "require_all_five_governance_tables_ready" in readiness[
        "planner_binding_gates"
    ]
    assert "reject_sample_or_synthetic_rows" in readiness["planner_binding_gates"]
    assert readiness["claim_boundary"]["max_claim_level"] == (
        "adapter_readiness_audit_only"
    )


def test_governance_data_adapter_rejects_sample_policy_rows(tmp_path):
    table_path = tmp_path / "policy_project_history.csv"
    fields = [
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
    with table_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(
            {
                "project_id": "sample-project-001",
                "action_type": "add_community_service",
                "target_geometry": "sample-geometry",
                "start_date": "2025-01-01",
                "end_date": "2025-12-31",
                "implementation_status": "sample",
                "budget_cost": "100",
                "responsible_department": "sample_department",
                "approval_status": "sample",
                "source_document_id": "sample_doc",
                "synthetic_status": "planning_sample",
                "quality_flag": "sample",
            }
        )

    readiness = _build_readiness(tmp_path)
    policy = {
        table["table_id"]: table for table in readiness["table_readiness"]
    }["policy_project_history"]

    assert policy["source_exists"] is True
    assert policy["schema_valid"] is True
    assert policy["row_count"] == 1
    assert policy["accepted_authoritative_row_count"] == 0
    assert policy["rejected_row_count"] == 1
    assert policy["rejection_reason_counts"] == {
        "non_authoritative_synthetic_status": 1,
        "non_authoritative_quality_flag": 1,
    }
    assert policy["ready"] is False
    assert readiness["summary"]["ready_table_count"] == 0
    assert readiness["planner_governance_binding_ready"] is False


def test_governance_data_adapter_rejects_authoritative_rows_with_invalid_business_values(tmp_path):
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
            "project_id": "",
            "action_type": "unsupported_action",
            "target_geometry": "",
            "start_date": "2026-12-31",
            "end_date": "2026-01-01",
            "implementation_status": "maybe",
            "budget_cost": "-100",
            "responsible_department": "",
            "approval_status": "unknown",
            "source_document_id": "",
            "synthetic_status": "real",
            "quality_flag": "verified",
        },
    )

    readiness = _build_readiness(tmp_path)
    policy = {
        table["table_id"]: table for table in readiness["table_readiness"]
    }["policy_project_history"]

    assert policy["source_exists"] is True
    assert policy["schema_valid"] is True
    assert policy["row_count"] == 1
    assert policy["accepted_authoritative_row_count"] == 0
    assert policy["rejected_row_count"] == 1
    assert policy["rejection_reason_counts"] == {
        "missing_project_id": 1,
        "unsupported_action_type": 1,
        "missing_target_geometry": 1,
        "invalid_date_order": 1,
        "invalid_implementation_status": 1,
        "negative_budget_cost": 1,
        "missing_responsible_department": 1,
        "invalid_approval_status": 1,
        "missing_source_document_id": 1,
    }
    assert policy["ready"] is False
    assert readiness["summary"]["ready_table_count"] == 0
    assert readiness["summary"]["rejected_row_count"] == 1
    assert readiness["planner_governance_binding_ready"] is False


def test_governance_data_adapter_readiness_artifact_is_currently_not_ready():
    readiness = _read_json(ARTIFACT_PATH)

    assert (
        readiness["schema"]
        == UWM_PRODUCTION_GOVERNANCE_DATA_ADAPTER_READINESS_SCHEMA
    )
    assert readiness["summary"]["expected_table_count"] == 5
    assert readiness["summary"]["ready_table_count"] == 0
    assert readiness["summary"]["missing_source_table_count"] == 5
    assert readiness["planner_governance_binding_ready"] is False
    assert readiness["observed_policy_outcome_superiority_claim"] is False


def _write_table(path: Path, fields: list[str], row: dict[str, str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)
