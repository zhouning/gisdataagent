"""Planner binding gate for authoritative UWM governance data closure."""

from __future__ import annotations

from typing import Any


UWM_PRODUCTION_GOVERNANCE_PLANNER_BINDING_GATE_SCHEMA = (
    "uwm.production_governance_planner_binding_gate.v1"
)

REQUIRED_TABLE_IDS = [
    "policy_project_history",
    "action_constraint_cost_model",
    "observed_outcome_validation_panel",
    "causal_effect_calibration_panel",
    "human_governance_review_log",
]


def build_uwm_production_governance_planner_binding_gate(
    *,
    gate_id: str,
    created_at: str,
    production_action_catalog: dict[str, Any],
    governance_data_contract: dict[str, Any],
    adapter_readiness: dict[str, Any],
    linkage_audit: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate whether governance data may bind production planner search."""

    action_summary = production_action_catalog.get("summary") or {}
    adapter_summary = adapter_readiness.get("summary") or {}
    linkage_summary = linkage_audit.get("summary") or {}
    table_readiness = {
        str(table.get("table_id")): table
        for table in adapter_readiness.get("table_readiness") or []
        if isinstance(table, dict)
    }
    gate_results = [
        _gate_result(
            "action_catalog_contract_ready",
            _action_catalog_ready(production_action_catalog),
            "production_action_catalog_contract_not_ready",
            {
                "schema": production_action_catalog.get("schema"),
                "action_catalog_contract_ready": bool(
                    production_action_catalog.get("action_catalog_contract_ready")
                ),
                "currently_bound_feasible_action_count": _int(
                    action_summary.get("currently_bound_feasible_action_count")
                ),
            },
        ),
        _gate_result(
            "governance_data_contract_ready",
            _governance_contract_ready(governance_data_contract),
            "production_governance_data_contract_not_ready",
            {
                "schema": governance_data_contract.get("schema"),
                "governance_data_contract_ready": bool(
                    governance_data_contract.get("governance_data_contract_ready")
                ),
                "required_governance_table_count": _int(
                    (governance_data_contract.get("summary") or {}).get(
                        "required_governance_table_count"
                    )
                ),
            },
        ),
        _gate_result(
            "adapter_all_required_tables_ready",
            _adapter_all_required_tables_ready(adapter_readiness),
            "authoritative_governance_tables_not_all_ready",
            {
                "schema": adapter_readiness.get("schema"),
                "all_required_tables_ready": bool(
                    adapter_readiness.get("all_required_tables_ready")
                ),
                "expected_table_count": _int(
                    adapter_summary.get("expected_table_count")
                ),
                "ready_table_count": _int(adapter_summary.get("ready_table_count")),
            },
        ),
        _gate_result(
            "adapter_authoritative_rows_nonzero_per_table",
            _adapter_authoritative_rows_nonzero_per_table(table_readiness),
            "nonzero_authoritative_rows_required_for_each_governance_table",
            {
                "accepted_authoritative_row_count": _int(
                    adapter_summary.get("accepted_authoritative_row_count")
                ),
                "per_table_accepted_authoritative_row_counts": {
                    table_id: _int(
                        (table_readiness.get(table_id) or {}).get(
                            "accepted_authoritative_row_count"
                        )
                    )
                    for table_id in REQUIRED_TABLE_IDS
                },
            },
        ),
        _gate_result(
            "linkage_all_required_tables_present",
            bool(linkage_audit.get("all_required_tables_present")),
            "linkage_audit_missing_required_governance_tables",
            {
                "schema": linkage_audit.get("schema"),
                "present_table_count": _int(
                    linkage_summary.get("present_table_count")
                ),
                "missing_table_count": _int(
                    linkage_summary.get("missing_table_count")
                ),
            },
        ),
        _gate_result(
            "linkage_governance_linkage_ready",
            bool(linkage_audit.get("governance_linkage_ready")),
            "project_action_outcome_causal_review_linkage_not_ready",
            {
                "linked_project_count": _int(
                    linkage_summary.get("linked_project_count")
                ),
                "unlinked_project_count": _int(
                    linkage_summary.get("unlinked_project_count")
                ),
            },
        ),
        _gate_result(
            "observed_outcome_panel_authoritative_rows_ready",
            _table_ready(table_readiness, "observed_outcome_validation_panel"),
            "observed_outcome_validation_panel_not_authoritative_or_empty",
            _table_evidence(table_readiness, "observed_outcome_validation_panel"),
        ),
        _gate_result(
            "causal_effect_calibration_authoritative_rows_ready",
            _table_ready(table_readiness, "causal_effect_calibration_panel"),
            "causal_effect_calibration_panel_not_authoritative_or_empty",
            _table_evidence(table_readiness, "causal_effect_calibration_panel"),
        ),
        _gate_result(
            "human_governance_review_authoritative_rows_ready",
            _table_ready(table_readiness, "human_governance_review_log"),
            "human_governance_review_log_not_authoritative_or_empty",
            _table_evidence(table_readiness, "human_governance_review_log"),
        ),
    ]
    blocking_gate_ids = [
        result["gate_id"] for result in gate_results if result["passed"] is False
    ]
    forbidden_source_claims = _forbidden_source_claims(
        production_action_catalog,
        governance_data_contract,
        adapter_readiness,
        linkage_audit,
    )
    data_closure_ready = not blocking_gate_ids and not forbidden_source_claims
    return {
        "schema": UWM_PRODUCTION_GOVERNANCE_PLANNER_BINDING_GATE_SCHEMA,
        "gate_id": gate_id,
        "created_at": created_at,
        "experiment_scope": "full_admin_graph",
        "source_artifacts": {
            "production_action_catalog_schema": production_action_catalog.get(
                "schema"
            ),
            "governance_data_contract_schema": governance_data_contract.get(
                "schema"
            ),
            "adapter_readiness_schema": adapter_readiness.get("schema"),
            "linkage_audit_schema": linkage_audit.get("schema"),
        },
        "binding_gate_ready": True,
        "authoritative_governance_data_closure_ready": data_closure_ready,
        "planner_governance_binding_ready": data_closure_ready,
        "summary": {
            "required_gate_count": len(gate_results),
            "passed_gate_count": sum(1 for result in gate_results if result["passed"]),
            "blocking_gate_count": len(blocking_gate_ids),
            "production_action_type_count": _int(
                action_summary.get("production_action_type_count")
            ),
            "currently_bound_feasible_action_count": _int(
                action_summary.get("currently_bound_feasible_action_count")
            ),
            "expected_table_count": _int(
                adapter_summary.get("expected_table_count")
            )
            or _int(linkage_summary.get("expected_table_count")),
            "ready_table_count": _int(adapter_summary.get("ready_table_count")),
            "missing_table_count": _int(linkage_summary.get("missing_table_count")),
            "accepted_authoritative_row_count": _int(
                adapter_summary.get("accepted_authoritative_row_count")
            ),
            "policy_project_count": _int(
                linkage_summary.get("policy_project_count")
            ),
            "linked_project_count": _int(
                linkage_summary.get("linked_project_count")
            ),
            "unlinked_project_count": _int(
                linkage_summary.get("unlinked_project_count")
            ),
        },
        "gate_results": gate_results,
        "blocking_gate_ids": blocking_gate_ids,
        "forbidden_source_claims": forbidden_source_claims,
        "planner_binding_policy": {
            "allow_planner_governance_binding_only_when_all_gates_pass": True,
            "allow_observed_policy_outcome_superiority_claim": False,
            "allow_production_readiness_claim": False,
            "binding_scope": (
                "authoritative governance data closure for planner input binding, "
                "not production deployment and not observed policy superiority"
            ),
        },
        "supported_claim": (
            "production_governance_planner_binding_gate_blocks_search_until_authoritative_data_closure"
        ),
        "claim_boundary": {
            "max_claim_level": "planner_governance_binding_gate_only",
            "reason": (
                "The gate checks whether production actions may bind to "
                "authoritative governance data before planner search. It does "
                "not create data, deploy policy, or prove observed outcomes."
            ),
        },
        "production_readiness_claim": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _action_catalog_ready(catalog: dict[str, Any]) -> bool:
    summary = catalog.get("summary") or {}
    return (
        catalog.get("schema") == "uwm.production_action_catalog.v1"
        and catalog.get("action_catalog_contract_ready") is True
        and _int(summary.get("currently_bound_feasible_action_count")) > 0
    )


def _governance_contract_ready(contract: dict[str, Any]) -> bool:
    summary = contract.get("summary") or {}
    return (
        contract.get("schema") == "uwm.production_governance_data_contract.v1"
        and contract.get("governance_data_contract_ready") is True
        and _int(summary.get("required_governance_table_count")) == len(
            REQUIRED_TABLE_IDS
        )
    )


def _adapter_all_required_tables_ready(readiness: dict[str, Any]) -> bool:
    summary = readiness.get("summary") or {}
    expected = _int(summary.get("expected_table_count"))
    ready = _int(summary.get("ready_table_count"))
    return (
        readiness.get("schema")
        == "uwm.production_governance_data_adapter_readiness.v1"
        and readiness.get("all_required_tables_ready") is True
        and expected == len(REQUIRED_TABLE_IDS)
        and ready == expected
    )


def _adapter_authoritative_rows_nonzero_per_table(
    table_readiness: dict[str, dict[str, Any]],
) -> bool:
    return all(_table_ready(table_readiness, table_id) for table_id in REQUIRED_TABLE_IDS)


def _table_ready(
    table_readiness: dict[str, dict[str, Any]],
    table_id: str,
) -> bool:
    table = table_readiness.get(table_id) or {}
    return bool(table.get("ready")) and _int(
        table.get("accepted_authoritative_row_count")
    ) > 0


def _table_evidence(
    table_readiness: dict[str, dict[str, Any]],
    table_id: str,
) -> dict[str, Any]:
    table = table_readiness.get(table_id) or {}
    return {
        "table_id": table_id,
        "source_exists": bool(table.get("source_exists")),
        "schema_valid": bool(table.get("schema_valid")),
        "row_count": _int(table.get("row_count")),
        "accepted_authoritative_row_count": _int(
            table.get("accepted_authoritative_row_count")
        ),
        "rejected_row_count": _int(table.get("rejected_row_count")),
        "ready": bool(table.get("ready")),
    }


def _gate_result(
    gate_id: str,
    passed: bool,
    blocking_reason: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "passed": bool(passed),
        "blocking_reason": None if passed else blocking_reason,
        "evidence": evidence,
    }


def _forbidden_source_claims(*artifacts: dict[str, Any]) -> list[str]:
    forbidden = []
    for artifact in artifacts:
        schema = str(artifact.get("schema") or "unknown_schema")
        for claim_key in [
            "production_readiness_claim",
            "observed_policy_outcome_superiority_claim",
            "empirical_superiority_claim",
        ]:
            if artifact.get(claim_key) is True:
                forbidden.append(f"{schema}:{claim_key}")
    return forbidden


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
