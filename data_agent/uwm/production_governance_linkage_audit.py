"""Cross-table linkage audit for authoritative governance inputs."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


UWM_PRODUCTION_GOVERNANCE_LINKAGE_AUDIT_SCHEMA = (
    "uwm.production_governance_linkage_audit.v1"
)

EXPECTED_TABLE_IDS = [
    "policy_project_history",
    "action_constraint_cost_model",
    "observed_outcome_validation_panel",
    "causal_effect_calibration_panel",
    "human_governance_review_log",
]


def build_uwm_production_governance_linkage_audit(
    *,
    audit_id: str,
    created_at: str,
    adapter_readiness: dict[str, Any],
    governance_input_dir: str | Path,
) -> dict[str, Any]:
    """Audit project/action/outcome/causal/review linkage across governance tables."""

    input_dir = Path(governance_input_dir).expanduser()
    table_rows = {
        table_id: _read_csv_if_exists(input_dir / f"{table_id}.csv")
        for table_id in EXPECTED_TABLE_IDS
    }
    present_tables = [
        table_id for table_id, rows in table_rows.items() if rows is not None
    ]
    missing_tables = [
        table_id for table_id in EXPECTED_TABLE_IDS if table_id not in present_tables
    ]
    policy_rows = table_rows.get("policy_project_history") or []
    project_linkage = [
        _project_linkage(project, table_rows) for project in policy_rows
    ]
    linked_project_count = sum(
        1 for project in project_linkage if project["complete_linkage"]
    )
    all_required_tables_present = len(missing_tables) == 0
    governance_linkage_ready = (
        all_required_tables_present
        and bool(project_linkage)
        and linked_project_count == len(project_linkage)
    )
    return {
        "schema": UWM_PRODUCTION_GOVERNANCE_LINKAGE_AUDIT_SCHEMA,
        "audit_id": audit_id,
        "created_at": created_at,
        "experiment_scope": "full_admin_graph",
        "governance_input_dir": str(input_dir),
        "source_adapter_readiness_schema": adapter_readiness.get("schema"),
        "linkage_audit_ready": True,
        "all_required_tables_present": all_required_tables_present,
        "governance_linkage_ready": governance_linkage_ready,
        "planner_governance_binding_ready": False,
        "summary": {
            "expected_table_count": len(EXPECTED_TABLE_IDS),
            "present_table_count": len(present_tables),
            "missing_table_count": len(missing_tables),
            "policy_project_count": len(policy_rows),
            "linked_project_count": linked_project_count,
            "unlinked_project_count": max(
                0, len(project_linkage) - linked_project_count
            ),
            "project_with_constraint_count": sum(
                1 for project in project_linkage if project["has_constraint"]
            ),
            "project_with_observed_outcome_count": sum(
                1 for project in project_linkage if project["has_observed_outcome"]
            ),
            "project_with_causal_effect_count": sum(
                1 for project in project_linkage if project["has_causal_effect"]
            ),
            "project_with_human_review_count": sum(
                1 for project in project_linkage if project["has_human_review"]
            ),
        },
        "present_tables": present_tables,
        "missing_tables": missing_tables,
        "project_linkage": project_linkage,
        "planner_binding_gates": [
            "require_all_governance_tables_present",
            "require_each_project_has_constraint_outcome_causal_review",
            "require_adapter_readiness_accepts_authoritative_rows",
            "keep_planner_governance_binding_false_until_policy_outcome_gate",
        ],
        "supported_claim": (
            "production_governance_linkage_audit_checks_cross_table_policy_constraint_outcome_closure"
        ),
        "claim_boundary": {
            "max_claim_level": "governance_linkage_audit_only",
            "reason": (
                "The audit checks whether authoritative governance rows link "
                "across required tables. It does not create governance data and "
                "does not prove observed policy outcome superiority."
            ),
        },
        "production_readiness_claim": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _project_linkage(
    project: dict[str, str],
    table_rows: dict[str, list[dict[str, str]] | None],
) -> dict[str, Any]:
    project_id = str(project.get("project_id") or "")
    action_type = str(project.get("action_type") or "")
    target_geometry = str(project.get("target_geometry") or "")
    has_constraint = any(
        str(row.get("action_type") or "") == action_type
        and str(row.get("target_geometry") or "") == target_geometry
        for row in table_rows.get("action_constraint_cost_model") or []
    )
    has_observed_outcome = any(
        str(row.get("project_id") or "") == project_id
        for row in table_rows.get("observed_outcome_validation_panel") or []
    )
    has_causal_effect = any(
        str(row.get("project_id") or "") == project_id
        and str(row.get("action_type") or "") == action_type
        for row in table_rows.get("causal_effect_calibration_panel") or []
    )
    has_human_review = any(
        str(row.get("project_id") or "") == project_id
        for row in table_rows.get("human_governance_review_log") or []
    )
    complete_linkage = all(
        [
            has_constraint,
            has_observed_outcome,
            has_causal_effect,
            has_human_review,
        ]
    )
    return {
        "project_id": project_id,
        "action_type": action_type,
        "target_geometry": target_geometry,
        "has_constraint": has_constraint,
        "has_observed_outcome": has_observed_outcome,
        "has_causal_effect": has_causal_effect,
        "has_human_review": has_human_review,
        "complete_linkage": complete_linkage,
    }


def _read_csv_if_exists(path: Path) -> list[dict[str, str]] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]
