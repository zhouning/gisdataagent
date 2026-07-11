"""Counterfactual orchestration for bounded parcel land-use scenarios."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .direct_transition import apply_direct_transition
from .evidence_gate import build_rollout_evidence_gate
from .land_use_action import (
    bind_server_actor,
    build_change_land_use_action,
    build_no_change_action,
    validate_land_use_action,
)
from .spatial_propagation import propagate_spatial_messages


def run_counterfactual_rollout(
    *,
    graph: dict[str, Any],
    intervention_action: dict[str, Any],
    land_use_dictionary: dict[str, Any],
    transition_matrix: dict[str, Any],
    alternative_land_use_class: str | None,
) -> dict[str, Any]:
    """Compare no-action, intervention and optional controlled alternative worlds."""

    parcel = _target_parcel(graph, str(intervention_action.get("parcel_id")))
    intervention_validation = validate_land_use_action(
        intervention_action,
        parcel=parcel,
        actual_snapshot_digest=str(graph.get("snapshot_digest")),
        land_use_dictionary=land_use_dictionary,
        transition_matrix=transition_matrix,
    )
    if not intervention_validation["valid"]:
        raise ValueError("intervention_action_invalid:" + intervention_validation["errors"][0])

    baseline_action = bind_server_actor(
        build_no_change_action(
            parcel_id=str(parcel.get("node_id")),
            current_land_use_class=str(parcel.get("current_land_use_class")),
            rationale="counterfactual_no_change_baseline",
            snapshot_digest=str(graph.get("snapshot_digest")),
            dictionary_version=str(land_use_dictionary.get("version")),
            transition_matrix_version=str(transition_matrix.get("version")),
            requested_at=str(intervention_action.get("requested_at")),
        ),
        actor_id=str(intervention_action.get("actor_id")),
    )
    baseline_validation = validate_land_use_action(
        baseline_action,
        parcel=parcel,
        actual_snapshot_digest=str(graph.get("snapshot_digest")),
        land_use_dictionary=land_use_dictionary,
        transition_matrix=transition_matrix,
    )
    baseline = _trajectory(
        graph=graph,
        action=baseline_action,
        validation=baseline_validation,
    )
    intervention = _trajectory(
        graph=graph,
        action=intervention_action,
        validation=intervention_validation,
    )

    alternative = None
    if alternative_land_use_class is not None:
        alternative_action = bind_server_actor(
            build_change_land_use_action(
                parcel_id=str(parcel.get("node_id")),
                from_land_use_class=str(parcel.get("current_land_use_class")),
                to_land_use_class=str(alternative_land_use_class),
                rationale="controlled_alternative_land_use_counterfactual",
                snapshot_digest=str(graph.get("snapshot_digest")),
                dictionary_version=str(land_use_dictionary.get("version")),
                transition_matrix_version=str(transition_matrix.get("version")),
                requested_at=str(intervention_action.get("requested_at")),
            ),
            actor_id=str(intervention_action.get("actor_id")),
        )
        alternative_validation = validate_land_use_action(
            alternative_action,
            parcel=parcel,
            actual_snapshot_digest=str(graph.get("snapshot_digest")),
            land_use_dictionary=land_use_dictionary,
            transition_matrix=transition_matrix,
        )
        if not alternative_validation["valid"]:
            raise ValueError("alternative_action_invalid:" + alternative_validation["errors"][0])
        alternative = _trajectory(
            graph=graph,
            action=alternative_action,
            validation=alternative_validation,
        )

    evidence_gate = build_rollout_evidence_gate()
    result = {
        "schema": "uwm.geospatial_kernel.counterfactual_rollout.v1",
        "kernel_version": graph.get("kernel_version"),
        "t0_snapshot_digest": graph.get("snapshot_digest"),
        "baseline": baseline,
        "intervention": intervention,
        "alternative": alternative,
        "direct_state_delta": intervention["t1"]["direct_state_delta"],
        "spillover_state_delta": {
            "baseline_message_count": len(baseline["t2"]["messages"]),
            "intervention_message_count": len(intervention["t2"]["messages"]),
            "baseline_message_digest": baseline["t2"]["message_digest"],
            "intervention_message_digest": intervention["t2"]["message_digest"],
            "message_count_delta": len(intervention["t2"]["messages"])
            - len(baseline["t2"]["messages"]),
            **_message_differences(
                baseline["t2"]["messages"], intervention["t2"]["messages"]
            ),
        },
        "constraint_violations": _constraint_violations(intervention_validation),
        "potential_conflicts": _messages_by_priority(
            intervention["t2"]["messages"],
            {"rule_or_potential_conflict", "unmapped_or_unresolved", "unmapped_object"},
        ),
        "opportunity_signals": _messages_by_priority(
            intervention["t2"]["messages"], {"opportunity_signal"}
        ),
        "uncertainty": _uncertainty(intervention["t2"]["messages"]),
        "review_required": bool(
            intervention_validation.get("review_required")
            or _messages_by_priority(
                intervention["t2"]["messages"],
                {"rule_or_potential_conflict", "unmapped_or_unresolved", "unmapped_object"},
            )
        ),
        **evidence_gate,
    }
    result["rollout_digest"] = _rollout_digest(result)
    return result


def _trajectory(
    *, graph: dict[str, Any], action: dict[str, Any], validation: dict[str, Any]
) -> dict[str, Any]:
    t1 = apply_direct_transition(
        graph=graph,
        action=action,
        action_validation=validation,
    )
    propagation = propagate_spatial_messages(
        graph=t1["state_graph"],
        target_parcel_id=str(action.get("parcel_id")),
        from_land_use_class=str(action.get("from_land_use_class")),
        to_land_use_class=str(action.get("to_land_use_class")),
        kernel_version=str(graph.get("kernel_version")),
    )
    t2 = {
        "state_time": "t2_neighborhood_adaptation",
        **propagation,
    }
    return {
        "action": action,
        "action_validation": validation,
        "t0_snapshot_digest": graph.get("snapshot_digest"),
        "t1": t1,
        "t2": t2,
    }


def _target_parcel(graph: dict[str, Any], parcel_id: str) -> dict[str, Any]:
    for node in graph.get("nodes") or []:
        if node.get("node_id") == parcel_id and node.get("node_type") == "parcel":
            return node
    raise ValueError("target_parcel_missing")


def _messages_by_priority(
    messages: list[dict[str, Any]], priorities: set[str]
) -> list[dict[str, Any]]:
    return [message for message in messages if message.get("review_priority") in priorities]


def _constraint_violations(validation: dict[str, Any]) -> list[dict[str, Any]]:
    transition = validation.get("transition") or {}
    if transition.get("status") != "prohibited":
        return []
    return [
        {
            "type": "prohibited_land_use_transition",
            "authority_refs": transition.get("authority_refs") or [],
            "approval_claim": False,
        }
    ]


def _uncertainty(messages: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"none": 0, "bounded": 0, "unresolved": 0}
    for message in messages:
        level = str(message.get("uncertainty") or "unresolved")
        counts[level] = counts.get(level, 0) + 1
    return {
        "message_uncertainty_counts": counts,
        "learned_calibrated_effect_ready": False,
        "observed_intervention_outcome_ready": False,
    }


def _rollout_digest(payload: dict[str, Any]) -> str:
    content = {key: value for key, value in payload.items() if key != "rollout_digest"}
    encoded = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _message_differences(
    baseline: list[dict[str, Any]], intervention: list[dict[str, Any]]
) -> dict[str, Any]:
    baseline_by_id = {str(row.get("message_id")): row for row in baseline}
    intervention_by_id = {str(row.get("message_id")): row for row in intervention}
    changed = []
    for message_id in sorted(set(baseline_by_id) | set(intervention_by_id)):
        before = baseline_by_id.get(message_id)
        after = intervention_by_id.get(message_id)
        if before == after:
            continue
        changed.append(
            {
                "message_id": message_id,
                "target_node_id": (after or before or {}).get("target_node_id"),
                "relation_type": (after or before or {}).get("relation_type"),
                "effect_type": (after or before or {}).get("effect_type"),
                "baseline_raw_evidence": (before or {}).get("raw_evidence"),
                "intervention_raw_evidence": (after or {}).get("raw_evidence"),
            }
        )
    return {"changed_message_count": len(changed), "changed_effects": changed}
