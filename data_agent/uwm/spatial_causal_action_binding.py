"""Bind UWM action records to spatial causal question contracts."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .spatial_causal_question_registry import (
    validate_uwm_spatial_causal_question_registry,
)


def causal_contracts_by_action_type(
    spatial_causal_question_registry: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Index spatial causal question contracts by action type."""

    return {
        str(contract.get("action_type")): contract
        for contract in spatial_causal_question_registry.get(
            "causal_question_contracts"
        )
        or []
        if isinstance(contract, dict) and contract.get("action_type")
    }


def action_with_spatial_causal_contract(
    action: dict[str, Any],
    causal_contracts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Attach the minimal claim-safe causal contract fields to one action."""

    enriched = dict(action)
    action_type = str(action.get("action_type") or "")
    contract = causal_contracts.get(action_type)
    if not contract:
        enriched.update(
            {
                "causal_question_id": None,
                "causal_query": None,
                "primary_outcome": None,
                "identification_status": "missing_spatial_causal_contract",
                "required_authoritative_tables": [],
                "policy_outcome_claim_allowed": False,
                "observed_policy_outcome_superiority_claim": False,
                "empirical_superiority_claim": False,
            }
        )
        return enriched

    outcomes = contract.get("outcomes") or {}
    identification = contract.get("identification") or {}
    enriched.update(
        {
            "causal_question_id": contract.get("question_id"),
            "causal_query": contract.get("causal_query"),
            "primary_outcome": outcomes.get("primary_outcome"),
            "identification_status": identification.get("status"),
            "allowed_current_query_level": identification.get(
                "allowed_current_query_level"
            ),
            "causal_blocked_reason": identification.get("blocked_reason"),
            "required_authoritative_tables": list(
                contract.get("required_authoritative_tables") or []
            ),
            "policy_outcome_claim_allowed": bool(
                contract.get("policy_outcome_claim_allowed")
            ),
            "causal_claim_level": contract.get("claim_level"),
            "observed_policy_outcome_superiority_claim": False,
            "empirical_superiority_claim": False,
        }
    )
    return enriched


def spatial_causal_action_binding_summary(
    *,
    spatial_causal_question_registry: dict[str, Any],
    actions: list[dict[str, Any]],
    total_action_count_key: str,
) -> dict[str, Any]:
    """Summarize whether a collection of actions is causally contract-bound."""

    validation = validate_uwm_spatial_causal_question_registry(
        spatial_causal_question_registry
    )
    summary = spatial_causal_question_registry.get("summary") or {}
    registry_ready = (
        spatial_causal_question_registry.get("registry_ready") is True
        and validation.get("valid") is True
    )
    contracts = causal_contracts_by_action_type(spatial_causal_question_registry)
    missing_actions = [
        action
        for action in actions
        if not action.get("causal_question_id")
        or not action.get("causal_query")
        or not action.get("primary_outcome")
        or not action.get("identification_status")
        or not action.get("required_authoritative_tables")
    ]
    policy_outcome_allowed = [
        action for action in actions if action.get("policy_outcome_claim_allowed")
    ]
    action_type_counts = dict(Counter(str(action.get("action_type")) for action in actions))
    result = {
        "binding_ready": (
            registry_ready
            and bool(actions)
            and not missing_actions
            and not policy_outcome_allowed
        ),
        "schema": spatial_causal_question_registry.get("schema"),
        "registry_ready": registry_ready,
        "validation_errors": validation.get("errors") or [],
        "active_causal_question_count": _int(
            summary.get("active_causal_question_count")
        ),
        "active_action_types": sorted(contracts),
        total_action_count_key: len(actions),
        "attached_action_count": len(actions) - len(missing_actions),
        "missing_contract_action_count": len(missing_actions),
        "missing_contract_action_types": sorted(
            {
                str(action.get("action_type") or "unknown_action")
                for action in missing_actions
            }
        ),
        "action_type_counts": action_type_counts,
        "underidentified_policy_effect_action_count": sum(
            1
            for action in actions
            if action.get("identification_status")
            == "underidentified_for_observed_policy_effect"
        ),
        "identified_policy_effect_action_count": sum(
            1
            for action in actions
            if action.get("identification_status") == "identified"
        ),
        "policy_outcome_claim_allowed_action_count": len(policy_outcome_allowed),
        "required_authoritative_tables": list(
            next(iter(contracts.values()), {}).get("required_authoritative_tables")
            or []
        ),
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }
    return result


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default
