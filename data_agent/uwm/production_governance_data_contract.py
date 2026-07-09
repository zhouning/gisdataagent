"""Governance data contract for production UWM livability actions."""

from __future__ import annotations

from typing import Any


UWM_PRODUCTION_GOVERNANCE_DATA_CONTRACT_SCHEMA = (
    "uwm.production_governance_data_contract.v1"
)

REQUIRED_GOVERNANCE_TABLES = [
    {
        "table_id": "policy_project_history",
        "business_role": "authoritative intervention/project action log",
        "minimum_required_fields": [
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
    },
    {
        "table_id": "action_constraint_cost_model",
        "business_role": "legal, land, budget, timing and feasibility constraints",
        "minimum_required_fields": [
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
    },
    {
        "table_id": "observed_outcome_validation_panel",
        "business_role": "pre/post observed validation outcomes for interventions",
        "minimum_required_fields": [
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
    },
    {
        "table_id": "causal_effect_calibration_panel",
        "business_role": "matched controls, estimators and policy-effect calibration",
        "minimum_required_fields": [
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
    },
    {
        "table_id": "human_governance_review_log",
        "business_role": "planner, department and expert review before production search",
        "minimum_required_fields": [
            "review_id",
            "project_id",
            "reviewer_department",
            "review_decision",
            "decision_reason",
            "review_time",
            "review_document_id",
            "quality_flag",
        ],
    },
]


def build_uwm_production_governance_data_contract(
    *,
    contract_id: str,
    created_at: str,
    production_action_catalog: dict[str, Any],
    data_foundation_evidence_gate: dict[str, Any],
) -> dict[str, Any]:
    """Build claim-safe governance data requirements for production planner use."""

    action_summary = production_action_catalog.get("summary") or {}
    foundation_scope = data_foundation_evidence_gate.get("data_foundation_scope") or {}
    source_type_counts = foundation_scope.get("source_type_counts") or {}
    action_contracts = [
        item
        for item in production_action_catalog.get("action_type_contracts") or []
        if isinstance(item, dict)
    ]
    required_tables = _required_tables()
    action_requirements = _action_type_governance_requirements(action_contracts)
    return {
        "schema": UWM_PRODUCTION_GOVERNANCE_DATA_CONTRACT_SCHEMA,
        "contract_id": contract_id,
        "created_at": created_at,
        "experiment_scope": "full_admin_graph",
        "source_artifacts": {
            "production_action_catalog_schema": production_action_catalog.get(
                "schema"
            ),
            "data_foundation_evidence_gate_schema": data_foundation_evidence_gate.get(
                "schema"
            ),
        },
        "governance_data_contract_ready": True,
        "future_authoritative_data_extension_ready": True,
        "planner_governance_binding_ready": False,
        "policy_project_history_ready": False,
        "constraint_cost_model_ready": False,
        "observed_outcome_panel_ready": False,
        "causal_effect_calibration_ready": False,
        "human_governance_review_ready": False,
        "summary": {
            "production_action_type_count": _int(
                action_summary.get("production_action_type_count")
            ),
            "currently_bound_action_type_count": _int(
                action_summary.get("currently_bound_action_type_count")
            ),
            "currently_bound_feasible_action_count": _int(
                action_summary.get("currently_bound_feasible_action_count")
            ),
            "required_governance_table_count": len(required_tables),
            "ready_governance_table_count": 0,
            "manifest_row_count": _int(foundation_scope.get("manifest_row_count")),
            "planning_sample_source_count": _int(
                source_type_counts.get("planning_sample")
            ),
            "local_planning_sample_is_policy_history": False,
            "authoritative_policy_project_history_row_count": 0,
            "authoritative_constraint_cost_row_count": 0,
            "observed_outcome_validation_row_count": 0,
            "causal_effect_calibration_row_count": 0,
            "human_governance_review_row_count": 0,
        },
        "required_tables": required_tables,
        "action_type_governance_requirements": action_requirements,
        "future_data_ingestion_contract": {
            "schema_evolution_rule": "versioned_additive_no_rewrite",
            "adapter_slots": [
                "policy_project_history_adapter",
                "constraint_cost_model_adapter",
                "observed_outcome_panel_adapter",
                "causal_effect_calibration_adapter",
                "human_governance_review_adapter",
            ],
            "planner_binding_gates": [
                "reject_local_planning_samples_as_policy_history",
                "require_authoritative_policy_project_history",
                "require_constraint_cost_model_for_parameterized_action",
                "reject_planner_production_claim_without_observed_outcome_panel",
                "require_causal_effect_calibration_for_policy_effect_claim",
                "require_human_governance_review_for_production_search",
            ],
        },
        "supported_claim": (
            "production_governance_data_contract_defines_non_smoke_policy_constraint_outcome_requirements"
        ),
        "claim_boundary": {
            "max_claim_level": "governance_data_contract_gap_only",
            "reason": (
                "The contract defines the authoritative policy/project history, "
                "constraint-cost, outcome, causal and review data required before "
                "production planner claims. It does not supply those rows and does "
                "not validate observed policy outcomes."
            ),
        },
        "production_readiness_claim": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "limitations": [
            "local_planning_samples_are_not_policy_project_history",
            "no_authoritative_constraint_cost_rows_available",
            "no_observed_post_intervention_outcome_panel_available",
            "no_production_planner_binding_allowed_from_this_contract_alone",
        ],
    }


def _required_tables() -> list[dict[str, Any]]:
    tables = []
    for table in REQUIRED_GOVERNANCE_TABLES:
        tables.append(
            {
                "table_id": table["table_id"],
                "business_role": table["business_role"],
                "minimum_required_fields": list(table["minimum_required_fields"]),
                "ready": False,
                "authoritative_row_count": 0,
                "synthetic_or_sample_substitution_allowed": False,
            }
        )
    return tables


def _action_type_governance_requirements(
    action_contracts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    requirements = []
    for contract in action_contracts:
        action_binding_status = str(
            contract.get("current_binding_status") or "production_target_unbound"
        )
        has_current_binding = action_binding_status == "implemented_bounded_support"
        requirements.append(
            {
                "action_type": str(contract.get("action_type")),
                "family_id": str(contract.get("family_id")),
                "current_action_binding_status": action_binding_status,
                "current_feasible_action_count": _int(
                    contract.get("current_feasible_action_count")
                ),
                "governance_binding_status": (
                    "current_abstract_binding_only_missing_governance_data"
                    if has_current_binding
                    else "production_target_unbound_missing_governance_data"
                ),
                "required_tables": [
                    table["table_id"] for table in REQUIRED_GOVERNANCE_TABLES
                ],
                "missing_authoritative_inputs": [
                    "authoritative_policy_project_history",
                    "constraint_cost_model",
                    "observed_outcome_validation_panel",
                    "causal_effect_calibration_panel",
                    "human_governance_review",
                ],
                "planner_search_allowed_with_production_claim": False,
                "observed_policy_outcome_claim": False,
            }
        )
    return requirements


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except (TypeError, ValueError):
        return int(default)
