import csv
import json
from pathlib import Path

from data_agent.uwm.production_governance_input_templates import (
    UWM_PRODUCTION_GOVERNANCE_INPUT_TEMPLATES_SCHEMA,
    build_uwm_production_governance_input_templates,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "production_governance_input_templates_2026_07_08"
ARTIFACT_PATH = OUTPUT_DIR / "uwm_production_governance_input_templates.json"
TEMPLATE_DIR = OUTPUT_DIR / "templates"
ADAPTER_READINESS_PATH = (
    DATA_ROOT
    / "production_governance_data_adapter_readiness_2026_07_08/uwm_production_governance_data_adapter_readiness.json"
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_templates() -> dict:
    return build_uwm_production_governance_input_templates(
        template_pack_id="uwm-production-governance-input-templates-test",
        created_at="2026-07-08T23:59:00Z",
        governance_data_contract=_read_json(
            DATA_ROOT
            / "production_governance_data_contract_2026_07_08/uwm_production_governance_data_contract.json"
        ),
        adapter_readiness=_read_json(ADAPTER_READINESS_PATH),
        output_dir=OUTPUT_DIR,
    )


def test_governance_input_templates_define_headers_without_authoritative_claims():
    templates = _build_templates()

    assert templates["schema"] == UWM_PRODUCTION_GOVERNANCE_INPUT_TEMPLATES_SCHEMA
    assert templates["experiment_scope"] == "full_admin_graph"
    assert templates["template_pack_ready"] is True
    assert templates["authoritative_input_claim"] is False
    assert templates["production_readiness_claim"] is False
    assert templates["observed_policy_outcome_superiority_claim"] is False

    summary = templates["summary"]
    assert summary["required_table_count"] == 5
    assert summary["template_count"] == 5
    assert summary["required_field_count"] == 54
    assert summary["adapter_ready_table_count"] == 0
    assert summary["adapter_missing_source_table_count"] == 5
    assert summary["template_dir_is_adapter_input_dir"] is False

    assert templates["template_dir"].endswith(
        "production_governance_input_templates_2026_07_08/templates"
    )
    assert templates["adapter_expected_input_dir"].endswith(
        "authoritative_governance_inputs_2026_07_08"
    )
    assert templates["template_dir"] != templates["adapter_expected_input_dir"]

    table_templates = {
        item["table_id"]: item for item in templates["table_templates"]
    }
    assert set(table_templates) == {
        "policy_project_history",
        "action_constraint_cost_model",
        "observed_outcome_validation_panel",
        "causal_effect_calibration_panel",
        "human_governance_review_log",
    }
    assert table_templates["policy_project_history"]["header_fields"] == [
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
    assert table_templates["policy_project_history"]["template_row_count"] == 0
    assert table_templates["policy_project_history"]["authoritative_data"] is False
    assert table_templates["policy_project_history"]["field_mapping_template"][0] == {
        "canonical_field": "project_id",
        "source_field": "",
        "required": True,
        "data_type": "string",
    }
    policy_rules = table_templates["policy_project_history"][
        "business_validation_rules"
    ]
    assert "project_id_required" in policy_rules
    assert "action_type_must_match_production_action_catalog" in policy_rules
    assert "start_date_must_be_on_or_before_end_date" in policy_rules
    assert "budget_cost_must_be_nonnegative_number" in policy_rules
    assert table_templates["policy_project_history"]["allowed_values"][
        "implementation_status"
    ] == [
        "cancelled",
        "completed",
        "implemented",
        "in_progress",
        "operational",
        "paused",
        "planned",
    ]
    assert "add_community_service" in templates["allowed_action_types"]
    assert "increase_green_infrastructure" in templates["allowed_action_types"]
    assert templates["summary"]["allowed_action_type_count"] == 57
    assert templates["claim_boundary"]["max_claim_level"] == (
        "input_template_contract_only"
    )


def test_governance_input_template_artifact_writes_empty_csv_headers_only():
    templates = _read_json(ARTIFACT_PATH)

    assert templates["schema"] == UWM_PRODUCTION_GOVERNANCE_INPUT_TEMPLATES_SCHEMA
    assert templates["summary"]["template_count"] == 5
    assert templates["summary"]["template_dir_is_adapter_input_dir"] is False
    assert templates["authoritative_input_claim"] is False

    for table in templates["table_templates"]:
        path = ROOT / table["template_relative_path"]
        assert path.exists()
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            rows = list(reader)
        assert rows == [table["header_fields"]]

    readiness = _read_json(ADAPTER_READINESS_PATH)
    assert readiness["summary"]["missing_source_table_count"] == 5
    assert readiness["summary"]["ready_table_count"] == 0
