"""Fail-closed land-use transition matrix."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


LAND_USE_TRANSITION_MATRIX_SCHEMA = "uwm.geospatial_kernel.land_use_transition_matrix.v1"
TRANSITION_STATUSES = {
    "allowed",
    "conditionally_allowed",
    "prohibited",
    "unresolved",
}


def build_transition_matrix(
    *, version: str, dictionary_version: str, rules: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build a deterministic versioned matrix from controlled rules."""

    canonical_rules: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw_rule in rules:
        rule = deepcopy(raw_rule)
        source = str(rule.get("from_land_use_class") or "")
        target = str(rule.get("to_land_use_class") or "")
        status = rule.get("status")
        if not source or not target or source == target:
            raise ValueError("invalid_transition_rule_classes")
        if status not in TRANSITION_STATUSES - {"unresolved"}:
            raise ValueError("invalid_transition_rule_status")
        key = (source, target)
        if key in seen:
            raise ValueError("duplicate_transition_rule")
        seen.add(key)
        authority_refs = rule.get("authority_refs") or []
        if not authority_refs:
            raise ValueError("transition_rule_authority_refs_missing")
        canonical_rules.append(
            {
                "from_land_use_class": source,
                "to_land_use_class": target,
                "status": status,
                "authority_refs": sorted(str(value) for value in authority_refs),
                "conditions": sorted(str(value) for value in (rule.get("conditions") or [])),
            }
        )
    canonical_rules.sort(
        key=lambda row: (row["from_land_use_class"], row["to_land_use_class"])
    )
    return {
        "schema": LAND_USE_TRANSITION_MATRIX_SCHEMA,
        "version": str(version),
        "dictionary_version": str(dictionary_version),
        "rules": canonical_rules,
        "default_status": "unresolved",
        "approval_claim": False,
    }


def evaluate_transition(
    matrix: dict[str, Any], *, from_land_use_class: str, to_land_use_class: str
) -> dict[str, Any]:
    """Return a bounded technical transition status, never an approval."""

    if from_land_use_class == to_land_use_class:
        return {
            "status": "no_change",
            "can_enter_rollout": True,
            "human_review_required": False,
            "authority_refs": [],
            "conditions": [],
            "approval_claim": False,
        }
    for rule in matrix.get("rules") or []:
        if (
            rule.get("from_land_use_class") == from_land_use_class
            and rule.get("to_land_use_class") == to_land_use_class
        ):
            status = str(rule.get("status"))
            return {
                "status": status,
                "can_enter_rollout": status != "prohibited",
                "human_review_required": status in {"conditionally_allowed", "unresolved"},
                "authority_refs": list(rule.get("authority_refs") or []),
                "conditions": list(rule.get("conditions") or []),
                "approval_claim": False,
            }
    return {
        "status": "unresolved",
        "can_enter_rollout": True,
        "human_review_required": True,
        "authority_refs": [],
        "conditions": ["authoritative_transition_rule_required"],
        "approval_claim": False,
    }

