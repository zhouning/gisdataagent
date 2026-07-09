"""Input templates for authoritative UWM governance data tables."""

from __future__ import annotations

from pathlib import Path
from typing import Any


UWM_PRODUCTION_GOVERNANCE_INPUT_TEMPLATES_SCHEMA = (
    "uwm.production_governance_input_templates.v1"
)


FIELD_DATA_TYPES = {
    "start_date": "date",
    "end_date": "date",
    "review_time": "datetime",
    "observation_time": "datetime",
    "budget_cost": "number",
    "implementation_time": "number",
    "maintenance_cost": "number",
    "pre_outcome_value": "number",
    "post_outcome_value": "number",
    "effect_size": "number",
}
FIELD_ALLOWED_VALUES = {
    "implementation_status": [
        "cancelled",
        "completed",
        "implemented",
        "in_progress",
        "operational",
        "paused",
        "planned",
    ],
    "approval_status": [
        "approved",
        "approved_with_conditions",
        "pending",
        "rejected",
    ],
    "legal_feasibility": [
        "allowed",
        "conditionally_allowed",
        "prohibited",
        "restricted",
    ],
    "placebo_result": ["failed", "not_applicable", "passed"],
    "negative_control_result": ["failed", "not_applicable", "passed"],
    "spatial_autocorrelation_diagnostic": [
        "failed",
        "not_applicable",
        "passed",
    ],
    "review_decision": [
        "approved",
        "approved_with_conditions",
        "pending",
        "rejected",
        "revise",
    ],
    "synthetic_status": ["authoritative", "real"],
    "quality_flag": [
        "authoritative",
        "authoritative_verified",
        "passed",
        "real",
        "verified",
    ],
}
TABLE_BUSINESS_VALIDATION_RULES = {
    "policy_project_history": [
        "project_id_required",
        "action_type_must_match_production_action_catalog",
        "target_geometry_required",
        "start_date_must_be_on_or_before_end_date",
        "implementation_status_must_use_allowed_values",
        "budget_cost_must_be_nonnegative_number",
        "responsible_department_required",
        "approval_status_must_use_allowed_values",
        "source_document_id_required",
        "synthetic_status_must_be_real_or_authoritative",
        "quality_flag_must_be_verified_or_authoritative",
    ],
    "action_constraint_cost_model": [
        "constraint_id_required",
        "action_type_must_match_production_action_catalog",
        "target_geometry_required",
        "legal_feasibility_must_use_allowed_values",
        "land_constraint_required",
        "budget_cost_must_be_nonnegative_number",
        "implementation_time_must_be_nonnegative_number",
        "maintenance_cost_must_be_nonnegative_number",
        "responsible_department_required",
        "approval_rule_id_required",
        "constraint_source_id_required",
        "quality_flag_must_be_verified_or_authoritative",
    ],
    "observed_outcome_validation_panel": [
        "outcome_id_required",
        "project_id_required",
        "target_geometry_required",
        "outcome_variable_required",
        "pre_outcome_value_must_be_number",
        "post_outcome_value_must_be_number",
        "observation_time_must_be_datetime",
        "observation_source_id_required",
        "measurement_method_required",
        "quality_flag_must_be_verified_or_authoritative",
    ],
    "causal_effect_calibration_panel": [
        "effect_id_required",
        "project_id_required",
        "action_type_must_match_production_action_catalog",
        "treatment_geometry_required",
        "control_geometry_required",
        "estimator_required",
        "effect_size_must_be_number",
        "confidence_interval_required",
        "placebo_result_must_use_allowed_values",
        "negative_control_result_must_use_allowed_values",
        "spatial_autocorrelation_diagnostic_must_use_allowed_values",
        "quality_flag_must_be_verified_or_authoritative",
    ],
    "human_governance_review_log": [
        "review_id_required",
        "project_id_required",
        "reviewer_department_required",
        "review_decision_must_use_allowed_values",
        "decision_reason_required",
        "review_time_must_be_datetime",
        "review_document_id_required",
        "quality_flag_must_be_verified_or_authoritative",
    ],
}


def build_uwm_production_governance_input_templates(
    *,
    template_pack_id: str,
    created_at: str,
    governance_data_contract: dict[str, Any],
    adapter_readiness: dict[str, Any],
    output_dir: str | Path,
) -> dict[str, Any]:
    """Build empty-header input templates without creating authoritative claims."""

    output_path = Path(output_dir).expanduser()
    template_dir = output_path / "templates"
    adapter_input_dir = Path(
        adapter_readiness.get("expected_input_dir") or ""
    ).expanduser()
    required_tables = [
        table
        for table in governance_data_contract.get("required_tables") or []
        if isinstance(table, dict)
    ]
    allowed_action_types = _allowed_action_types(governance_data_contract)
    table_templates = [
        _table_template(table, template_dir, output_path)
        for table in required_tables
    ]
    readiness_summary = adapter_readiness.get("summary") or {}
    return {
        "schema": UWM_PRODUCTION_GOVERNANCE_INPUT_TEMPLATES_SCHEMA,
        "template_pack_id": template_pack_id,
        "created_at": created_at,
        "experiment_scope": "full_admin_graph",
        "source_contract_schema": governance_data_contract.get("schema"),
        "source_adapter_readiness_schema": adapter_readiness.get("schema"),
        "template_pack_ready": True,
        "template_dir": str(template_dir),
        "adapter_expected_input_dir": str(adapter_input_dir),
        "summary": {
            "required_table_count": len(required_tables),
            "template_count": len(table_templates),
            "required_field_count": sum(
                len(table["header_fields"]) for table in table_templates
            ),
            "adapter_ready_table_count": _int(
                readiness_summary.get("ready_table_count")
            ),
            "adapter_missing_source_table_count": _int(
                readiness_summary.get("missing_source_table_count")
            ),
            "template_dir_is_adapter_input_dir": (
                template_dir.resolve() == adapter_input_dir.resolve()
                if str(adapter_input_dir)
                else False
            ),
            "allowed_action_type_count": len(allowed_action_types),
        },
        "allowed_action_types": allowed_action_types,
        "table_templates": table_templates,
        "usage_rules": [
            "templates_are_headers_only_not_authoritative_data",
            "copy_filled_authoritative_tables_to_adapter_expected_input_dir",
            "keep_synthetic_status_real_or_authoritative_for_accepted_rows",
            "keep_quality_flag_verified_or_authoritative_for_accepted_rows",
            "rerun_adapter_readiness_before_planner_binding",
        ],
        "supported_claim": (
            "production_governance_input_templates_define_authoritative_table_headers_without_fake_rows"
        ),
        "claim_boundary": {
            "max_claim_level": "input_template_contract_only",
            "reason": (
                "The template pack provides empty CSV headers and field mapping "
                "contracts. It is not authoritative governance data and does not "
                "change adapter readiness."
            ),
        },
        "authoritative_input_claim": False,
        "production_readiness_claim": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _table_template(
    table: dict[str, Any],
    template_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    table_id = str(table.get("table_id"))
    fields = [str(field) for field in table.get("minimum_required_fields") or []]
    template_path = template_dir / f"{table_id}.csv"
    repo_root = output_dir.parents[3]
    return {
        "table_id": table_id,
        "business_role": table.get("business_role"),
        "template_path": str(template_path),
        "template_relative_path": str(template_path.relative_to(repo_root)),
        "header_fields": fields,
        "template_row_count": 0,
        "authoritative_data": False,
        "field_mapping_template": [
            _field_mapping(field)
            for field in fields
        ],
        "business_validation_rules": TABLE_BUSINESS_VALIDATION_RULES.get(
            table_id,
            [],
        ),
        "allowed_values": {
            field: FIELD_ALLOWED_VALUES[field]
            for field in fields
            if field in FIELD_ALLOWED_VALUES
        },
    }


def _field_mapping(field: str) -> dict[str, Any]:
    mapping: dict[str, Any] = {
        "canonical_field": field,
        "source_field": "",
        "required": True,
        "data_type": FIELD_DATA_TYPES.get(field, "string"),
    }
    allowed_values = FIELD_ALLOWED_VALUES.get(field)
    if allowed_values:
        mapping["allowed_values"] = allowed_values
    return mapping


def _allowed_action_types(governance_data_contract: dict[str, Any]) -> list[str]:
    values = {
        str(item.get("action_type"))
        for item in governance_data_contract.get("action_type_governance_requirements")
        or []
        if isinstance(item, dict) and str(item.get("action_type") or "").strip()
    }
    return sorted(values)


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except (TypeError, ValueError):
        return int(default)
