from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


CLAIM_LADDER_SCHEMA = "territory_world_model.claim_ladder.v1"

CLAIM_LEVEL_ORDER = ["L0", "L1", "L2", "L3", "L4"]

CLAIM_LEVEL_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "L0": {
        "claim_status": "unsupported",
        "claim_scope": "model_output_or_contract_only",
        "required_gates": [],
        "minimum_evidence": "No upgraded model claim is allowed beyond reporting that evidence is insufficient.",
    },
    "L1": {
        "claim_status": "state_prediction_supported",
        "claim_scope": "future_state_prediction",
        "required_gates": ["state_build_pass", "future_state_holdout_pass"],
        "minimum_evidence": "The hierarchical state build and future-state holdout validation both pass.",
    },
    "L2": {
        "claim_status": "counterfactual_supported",
        "claim_scope": "action_conditioned_counterfactual_rollout",
        "depends_on": ["L1"],
        "required_gates": [
            "counterfactual_calibration_pass",
            "spatial_estimator_pass_or_not_applicable",
        ],
        "minimum_evidence": "Counterfactual rollout is calibrated and spatial causal support is passed or explicitly not applicable.",
    },
    "L3": {
        "claim_status": "planning_lift_supported",
        "claim_scope": "planner_consumable_rollout_or_beam",
        "depends_on": ["L2"],
        "required_gates": ["planning_lift_pass", "geofm_gate_decision"],
        "minimum_evidence": "Planning lift or ranking evidence passes, and any GeoFM use has a passed gate decision.",
    },
    "L4": {
        "claim_status": "deployable_gis_supported",
        "claim_scope": "operational_gis_deployment",
        "depends_on": ["L3"],
        "required_gates": ["gis_audit_pass", "human_review_completed"],
        "minimum_evidence": "GIS audit, checksums, rule evidence and human-review closure all pass.",
    },
}

CLAIM_GATE_CATALOG: dict[str, dict[str, str]] = {
    "state_build_pass": {
        "label": "State build",
        "description": "The state is a valid hierarchical GIS object-relation-rule-evidence state.",
    },
    "future_state_holdout_pass": {
        "label": "Future-state holdout",
        "description": "Future-state prediction is validated against holdout or observed temporal labels.",
    },
    "counterfactual_calibration_pass": {
        "label": "Counterfactual calibration",
        "description": "Counterfactual rollout passes evidence and calibration gates.",
    },
    "spatial_estimator_pass_or_not_applicable": {
        "label": "Spatial causal support",
        "description": "Spatial causal estimator support passes, or the claim is explicitly non-causal/not applicable.",
    },
    "planning_lift_pass": {
        "label": "Planning lift",
        "description": "Beam/MPC/ranking or rollout comparison shows positive planning lift under constraints.",
    },
    "geofm_gate_decision": {
        "label": "GeoFM gate",
        "description": "GeoFM is either not used or has passed B0/B1 and downstream gate requirements.",
    },
    "gis_audit_pass": {
        "label": "GIS audit",
        "description": "GIS evidence, checksums and rule/audit artifacts pass deployment checks.",
    },
    "human_review_completed": {
        "label": "Human review",
        "description": "Required human review tasks are completed before deployment claims are upgraded.",
    },
}


def claim_level_requirements() -> dict[str, dict[str, Any]]:
    return deepcopy(CLAIM_LEVEL_REQUIREMENTS)


def claim_gate_catalog() -> dict[str, dict[str, str]]:
    return deepcopy(CLAIM_GATE_CATALOG)


def evaluate_claim_ladder(gate_facts: Mapping[str, Any] | None = None) -> dict[str, Any]:
    facts = {name: _normalize_gate_fact(name, value) for name, value in (gate_facts or {}).items()}
    levels: list[dict[str, Any]] = []
    level_status: dict[str, str] = {}
    current_level = "L0"
    current_claim = CLAIM_LEVEL_REQUIREMENTS["L0"]["claim_status"]

    for level in CLAIM_LEVEL_ORDER:
        spec = CLAIM_LEVEL_REQUIREMENTS[level]
        dependencies = list(spec.get("depends_on") or [])
        required_gates = list(spec.get("required_gates") or [])
        dependency_gaps = [
            dep for dep in dependencies
            if level_status.get(dep) not in {"pass", "not_applicable"}
        ]
        requirement_results = [dict(facts.get(name) or _normalize_gate_fact(name, None)) for name in required_gates]
        blocked = [item["gate"] for item in requirement_results if item["status"] == "blocked"]
        missing = [
            item["gate"] for item in requirement_results
            if not item.get("passed") and item["status"] != "blocked"
        ]
        if dependency_gaps:
            missing.extend(f"depends_on:{dep}" for dep in dependency_gaps)

        if blocked:
            status = "blocked"
        elif missing:
            status = "review"
        else:
            status = "pass"

        if level == "L0":
            status = "pass"
            missing = []
            blocked = []

        level_status[level] = status
        if status == "pass":
            current_level = level
            current_claim = str(spec.get("claim_status") or current_claim)

        levels.append(
            {
                "level": level,
                "claim_status": spec.get("claim_status"),
                "claim_scope": spec.get("claim_scope"),
                "status": status,
                "passed": status == "pass",
                "depends_on": dependencies,
                "required_gates": required_gates,
                "requirements": requirement_results,
                "missing": missing,
                "blocked": blocked,
                "minimum_evidence": spec.get("minimum_evidence", ""),
            }
        )

    return {
        "schema": CLAIM_LADDER_SCHEMA,
        "current_level": current_level,
        "current_claim": current_claim,
        "deployable": current_level == "L4",
        "review_required": current_level != "L4",
        "levels": levels,
        "requirements": claim_level_requirements(),
        "gate_catalog": claim_gate_catalog(),
    }


def _normalize_gate_fact(name: str, value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        if value.get("gate"):
            name = str(value.get("gate"))
        raw_status = value.get("status")
        if raw_status is None:
            raw_status = "pass" if value.get("passed") is True else "blocked" if value.get("blocked") else "review"
        status = _normalize_status(raw_status)
        passed = bool(value.get("passed")) or status in {"pass", "not_applicable"}
        if value.get("blocked"):
            status = "blocked"
            passed = False
        return {
            "gate": name,
            "status": status,
            "passed": passed,
            "evidence": {key: deepcopy(val) for key, val in value.items() if key not in {"gate", "status", "passed", "blocked"}},
        }
    if isinstance(value, bool):
        status = "pass" if value else "review"
        return {"gate": name, "status": status, "passed": value, "evidence": {}}
    if isinstance(value, str):
        status = _normalize_status(value)
        return {
            "gate": name,
            "status": status,
            "passed": status in {"pass", "not_applicable"},
            "evidence": {},
        }
    return {"gate": name, "status": "review", "passed": False, "evidence": {}}


def _normalize_status(value: Any) -> str:
    status = str(value or "review").strip().lower()
    if status in {"passed", "true", "ok", "available"}:
        return "pass"
    if status in {"block", "blocked", "failed", "fail", "false"}:
        return "blocked"
    if status in {"not_applicable", "n/a", "na", "optional_not_used"}:
        return "not_applicable"
    if status == "pass":
        return "pass"
    return "review"
