"""Readiness audit for authoritative governance data adapters."""

from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


UWM_PRODUCTION_GOVERNANCE_DATA_ADAPTER_READINESS_SCHEMA = (
    "uwm.production_governance_data_adapter_readiness.v1"
)

AUTHORITATIVE_SYNTHETIC_STATUSES = {"real", "authoritative"}
AUTHORITATIVE_QUALITY_FLAGS = {
    "authoritative",
    "authoritative_verified",
    "verified",
    "real",
    "passed",
}
NON_AUTHORITATIVE_QUALITY_FLAGS = {
    "",
    "sample",
    "planning_sample",
    "synthetic",
    "template",
    "proxy",
    "public_proxy",
}
POLICY_IMPLEMENTATION_STATUSES = {
    "planned",
    "in_progress",
    "implemented",
    "completed",
    "operational",
    "paused",
    "cancelled",
}
POLICY_APPROVAL_STATUSES = {
    "approved",
    "approved_with_conditions",
    "pending",
    "rejected",
}
LEGAL_FEASIBILITY_STATUSES = {
    "allowed",
    "conditionally_allowed",
    "restricted",
    "prohibited",
}
CAUSAL_DIAGNOSTIC_STATUSES = {
    "passed",
    "failed",
    "not_applicable",
}
HUMAN_REVIEW_DECISIONS = {
    "approved",
    "approved_with_conditions",
    "rejected",
    "revise",
    "pending",
}


def build_uwm_production_governance_data_adapter_readiness(
    *,
    audit_id: str,
    created_at: str,
    governance_data_contract: dict[str, Any],
    expected_input_dir: str | Path,
) -> dict[str, Any]:
    """Audit whether authoritative governance input tables are ready to bind."""

    input_dir = Path(expected_input_dir).expanduser()
    required_tables = [
        table
        for table in governance_data_contract.get("required_tables") or []
        if isinstance(table, dict)
    ]
    allowed_action_types = _allowed_action_types(governance_data_contract)
    table_readiness = [
        _table_readiness(
            table,
            input_dir / f"{table.get('table_id')}.csv",
            allowed_action_types,
        )
        for table in required_tables
    ]
    ready_count = sum(1 for table in table_readiness if table["ready"])
    missing_count = sum(
        1 for table in table_readiness if table["source_exists"] is False
    )
    schema_invalid_count = sum(
        1
        for table in table_readiness
        if table["source_exists"] is True and table["schema_valid"] is False
    )
    total_row_count = sum(table["row_count"] for table in table_readiness)
    accepted_row_count = sum(
        table["accepted_authoritative_row_count"] for table in table_readiness
    )
    rejected_row_count = sum(table["rejected_row_count"] for table in table_readiness)
    all_required_tables_ready = ready_count == len(required_tables) and ready_count > 0
    return {
        "schema": UWM_PRODUCTION_GOVERNANCE_DATA_ADAPTER_READINESS_SCHEMA,
        "audit_id": audit_id,
        "created_at": created_at,
        "experiment_scope": "full_admin_graph",
        "expected_input_dir": str(input_dir),
        "source_contract_schema": governance_data_contract.get("schema"),
        "adapter_contract_ready": True,
        "all_required_tables_ready": all_required_tables_ready,
        "planner_governance_binding_ready": False,
        "summary": {
            "expected_table_count": len(required_tables),
            "ready_table_count": ready_count,
            "missing_source_table_count": missing_count,
            "schema_invalid_table_count": schema_invalid_count,
            "total_row_count": total_row_count,
            "accepted_authoritative_row_count": accepted_row_count,
            "rejected_row_count": rejected_row_count,
        },
        "table_readiness": table_readiness,
        "planner_binding_gates": [
            "require_all_five_governance_tables_ready",
            "require_nonzero_authoritative_rows_per_table",
            "reject_sample_or_synthetic_rows",
            "require_policy_history_constraint_outcome_causal_review_linkage",
            "keep_planner_governance_binding_false_until_authoritative_tables_pass",
        ],
        "supported_claim": (
            "production_governance_data_adapter_readiness_audits_authoritative_table_availability_without_fake_rows"
        ),
        "claim_boundary": {
            "max_claim_level": "adapter_readiness_audit_only",
            "reason": (
                "The adapter readiness audit checks table availability, schema "
                "and row-level authoritative flags. It does not create policy "
                "history rows and does not validate observed outcomes."
            ),
        },
        "production_readiness_claim": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "limitations": [
            "missing_authoritative_governance_tables_keep_planner_binding_false",
            "sample_or_synthetic_rows_are_rejected",
            "adapter_readiness_is_not_policy_outcome_evidence",
        ],
    }


def _table_readiness(
    table: dict[str, Any],
    path: Path,
    allowed_action_types: set[str],
) -> dict[str, Any]:
    required_fields = [
        str(field) for field in table.get("minimum_required_fields") or []
    ]
    table_id = str(table.get("table_id"))
    source_exists = path.exists()
    if not source_exists:
        return {
            "table_id": table_id,
            "source_path": str(path),
            "source_exists": False,
            "schema_valid": False,
            "minimum_required_fields": required_fields,
            "observed_fields": [],
            "missing_fields": [],
            "row_count": 0,
            "accepted_authoritative_row_count": 0,
            "rejected_row_count": 0,
            "rejection_reason_counts": {},
            "ready": False,
        }
    rows, observed_fields = _read_csv_rows(path)
    missing_fields = [
        field for field in required_fields if field not in set(observed_fields)
    ]
    schema_valid = not missing_fields
    accepted_count = 0
    rejected_count = 0
    rejection_counts: Counter[str] = Counter()
    if schema_valid:
        for row in rows:
            reasons = _row_rejection_reasons(
                row,
                table_id=table_id,
                allowed_action_types=allowed_action_types,
            )
            if reasons:
                rejected_count += 1
                rejection_counts.update(reasons)
            else:
                accepted_count += 1
    ready = schema_valid and accepted_count > 0
    return {
        "table_id": table_id,
        "source_path": str(path),
        "source_exists": True,
        "schema_valid": schema_valid,
        "minimum_required_fields": required_fields,
        "observed_fields": observed_fields,
        "missing_fields": missing_fields,
        "row_count": len(rows),
        "accepted_authoritative_row_count": accepted_count,
        "rejected_row_count": rejected_count,
        "rejection_reason_counts": dict(rejection_counts),
        "ready": ready,
    }


def _read_csv_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
        return rows, list(reader.fieldnames or [])


def _row_rejection_reasons(
    row: dict[str, Any],
    *,
    table_id: str,
    allowed_action_types: set[str],
) -> list[str]:
    authority_reasons = _authority_rejection_reasons(row)
    if authority_reasons:
        return authority_reasons
    return _business_rejection_reasons(
        row,
        table_id=table_id,
        allowed_action_types=allowed_action_types,
    )


def _authority_rejection_reasons(row: dict[str, Any]) -> list[str]:
    reasons = []
    synthetic_status = _normalize(row.get("synthetic_status"))
    if synthetic_status and synthetic_status not in AUTHORITATIVE_SYNTHETIC_STATUSES:
        reasons.append("non_authoritative_synthetic_status")
    quality_flag = _normalize(row.get("quality_flag"))
    if quality_flag in NON_AUTHORITATIVE_QUALITY_FLAGS:
        reasons.append("non_authoritative_quality_flag")
    elif quality_flag and quality_flag not in AUTHORITATIVE_QUALITY_FLAGS:
        reasons.append("unknown_quality_flag")
    return reasons


def _business_rejection_reasons(
    row: dict[str, Any],
    *,
    table_id: str,
    allowed_action_types: set[str],
) -> list[str]:
    if table_id == "policy_project_history":
        return _policy_project_history_rejection_reasons(row, allowed_action_types)
    if table_id == "action_constraint_cost_model":
        return _action_constraint_rejection_reasons(row, allowed_action_types)
    if table_id == "observed_outcome_validation_panel":
        return _observed_outcome_rejection_reasons(row)
    if table_id == "causal_effect_calibration_panel":
        return _causal_effect_rejection_reasons(row, allowed_action_types)
    if table_id == "human_governance_review_log":
        return _human_review_rejection_reasons(row)
    return []


def _policy_project_history_rejection_reasons(
    row: dict[str, Any],
    allowed_action_types: set[str],
) -> list[str]:
    reasons: list[str] = []
    _require_nonempty(row, "project_id", "missing_project_id", reasons)
    _require_action_type(row, allowed_action_types, reasons)
    _require_nonempty(row, "target_geometry", "missing_target_geometry", reasons)
    _require_date_order(row, "start_date", "end_date", reasons)
    _require_enum(
        row,
        "implementation_status",
        POLICY_IMPLEMENTATION_STATUSES,
        "invalid_implementation_status",
        reasons,
    )
    _require_nonnegative_number(row, "budget_cost", "negative_budget_cost", reasons)
    _require_nonempty(
        row,
        "responsible_department",
        "missing_responsible_department",
        reasons,
    )
    _require_enum(
        row,
        "approval_status",
        POLICY_APPROVAL_STATUSES,
        "invalid_approval_status",
        reasons,
    )
    _require_nonempty(
        row,
        "source_document_id",
        "missing_source_document_id",
        reasons,
    )
    return reasons


def _action_constraint_rejection_reasons(
    row: dict[str, Any],
    allowed_action_types: set[str],
) -> list[str]:
    reasons: list[str] = []
    _require_nonempty(row, "constraint_id", "missing_constraint_id", reasons)
    _require_action_type(row, allowed_action_types, reasons)
    _require_nonempty(row, "target_geometry", "missing_target_geometry", reasons)
    _require_enum(
        row,
        "legal_feasibility",
        LEGAL_FEASIBILITY_STATUSES,
        "invalid_legal_feasibility",
        reasons,
    )
    _require_nonempty(row, "land_constraint", "missing_land_constraint", reasons)
    _require_nonnegative_number(row, "budget_cost", "negative_budget_cost", reasons)
    _require_nonnegative_number(
        row,
        "implementation_time",
        "negative_implementation_time",
        reasons,
    )
    _require_nonnegative_number(
        row,
        "maintenance_cost",
        "negative_maintenance_cost",
        reasons,
    )
    _require_nonempty(
        row,
        "responsible_department",
        "missing_responsible_department",
        reasons,
    )
    _require_nonempty(row, "approval_rule_id", "missing_approval_rule_id", reasons)
    _require_nonempty(
        row,
        "constraint_source_id",
        "missing_constraint_source_id",
        reasons,
    )
    return reasons


def _observed_outcome_rejection_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    _require_nonempty(row, "outcome_id", "missing_outcome_id", reasons)
    _require_nonempty(row, "project_id", "missing_project_id", reasons)
    _require_nonempty(row, "target_geometry", "missing_target_geometry", reasons)
    _require_nonempty(row, "outcome_variable", "missing_outcome_variable", reasons)
    _require_number(row, "pre_outcome_value", "invalid_pre_outcome_value", reasons)
    _require_number(row, "post_outcome_value", "invalid_post_outcome_value", reasons)
    _require_date(row, "observation_time", "invalid_observation_time", reasons)
    _require_nonempty(
        row,
        "observation_source_id",
        "missing_observation_source_id",
        reasons,
    )
    _require_nonempty(row, "measurement_method", "missing_measurement_method", reasons)
    return reasons


def _causal_effect_rejection_reasons(
    row: dict[str, Any],
    allowed_action_types: set[str],
) -> list[str]:
    reasons: list[str] = []
    _require_nonempty(row, "effect_id", "missing_effect_id", reasons)
    _require_nonempty(row, "project_id", "missing_project_id", reasons)
    _require_action_type(row, allowed_action_types, reasons)
    _require_nonempty(
        row,
        "treatment_geometry",
        "missing_treatment_geometry",
        reasons,
    )
    _require_nonempty(row, "control_geometry", "missing_control_geometry", reasons)
    _require_nonempty(row, "estimator", "missing_estimator", reasons)
    _require_number(row, "effect_size", "invalid_effect_size", reasons)
    _require_nonempty(
        row,
        "confidence_interval",
        "missing_confidence_interval",
        reasons,
    )
    _require_enum(
        row,
        "placebo_result",
        CAUSAL_DIAGNOSTIC_STATUSES,
        "invalid_placebo_result",
        reasons,
    )
    _require_enum(
        row,
        "negative_control_result",
        CAUSAL_DIAGNOSTIC_STATUSES,
        "invalid_negative_control_result",
        reasons,
    )
    _require_enum(
        row,
        "spatial_autocorrelation_diagnostic",
        CAUSAL_DIAGNOSTIC_STATUSES,
        "invalid_spatial_autocorrelation_diagnostic",
        reasons,
    )
    return reasons


def _human_review_rejection_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    _require_nonempty(row, "review_id", "missing_review_id", reasons)
    _require_nonempty(row, "project_id", "missing_project_id", reasons)
    _require_nonempty(
        row,
        "reviewer_department",
        "missing_reviewer_department",
        reasons,
    )
    _require_enum(
        row,
        "review_decision",
        HUMAN_REVIEW_DECISIONS,
        "invalid_review_decision",
        reasons,
    )
    _require_nonempty(row, "decision_reason", "missing_decision_reason", reasons)
    _require_date(row, "review_time", "invalid_review_time", reasons)
    _require_nonempty(
        row,
        "review_document_id",
        "missing_review_document_id",
        reasons,
    )
    return reasons


def _allowed_action_types(governance_data_contract: dict[str, Any]) -> set[str]:
    return {
        str(item.get("action_type"))
        for item in governance_data_contract.get("action_type_governance_requirements")
        or []
        if isinstance(item, dict) and str(item.get("action_type") or "").strip()
    }


def _require_action_type(
    row: dict[str, Any],
    allowed_action_types: set[str],
    reasons: list[str],
) -> None:
    action_type = _normalize(row.get("action_type"))
    if not action_type:
        reasons.append("missing_action_type")
    elif allowed_action_types and action_type not in allowed_action_types:
        reasons.append("unsupported_action_type")


def _require_nonempty(
    row: dict[str, Any],
    field: str,
    reason: str,
    reasons: list[str],
) -> None:
    if not str(row.get(field) or "").strip():
        reasons.append(reason)


def _require_enum(
    row: dict[str, Any],
    field: str,
    allowed: set[str],
    reason: str,
    reasons: list[str],
) -> None:
    if _normalize(row.get(field)) not in allowed:
        reasons.append(reason)


def _require_date(
    row: dict[str, Any],
    field: str,
    reason: str,
    reasons: list[str],
) -> None:
    if _parse_datetime(row.get(field)) is None:
        reasons.append(reason)


def _require_date_order(
    row: dict[str, Any],
    start_field: str,
    end_field: str,
    reasons: list[str],
) -> None:
    start = _parse_datetime(row.get(start_field))
    end = _parse_datetime(row.get(end_field))
    if start is None:
        reasons.append(f"invalid_{start_field}")
    if end is None:
        reasons.append(f"invalid_{end_field}")
    if start is not None and end is not None and start > end:
        reasons.append("invalid_date_order")


def _require_number(
    row: dict[str, Any],
    field: str,
    reason: str,
    reasons: list[str],
) -> None:
    if _parse_float(row.get(field)) is None:
        reasons.append(reason)


def _require_nonnegative_number(
    row: dict[str, Any],
    field: str,
    negative_reason: str,
    reasons: list[str],
) -> None:
    value = _parse_float(row.get(field))
    if value is None:
        reasons.append(f"invalid_{field}")
    elif value < 0:
        reasons.append(negative_reason)


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _parse_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _normalize(value: Any) -> str:
    return str(value or "").strip().lower()
