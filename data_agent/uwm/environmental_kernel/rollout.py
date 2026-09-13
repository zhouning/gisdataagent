from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Mapping

from .actions import bind_environmental_action
from .contracts import ENVIRONMENTAL_ROLLOUT_SCHEMA, validate_rollout_result
from .dynamics import TemporalStep, step_environmental_state


def run_environmental_counterfactual(
    *,
    state: Mapping[str, Any],
    intervention_action: Mapping[str, Any],
    forcing_package: Mapping[str, Any],
    evidence_gate: Mapping[str, Any],
    horizon: int,
    random_seed: int,
    temporal_channel_steps: Mapping[str, TemporalStep] | None = None,
) -> dict[str, Any]:
    if intervention_action.get("state_snapshot_digest") != state.get("snapshot_digest"):
        raise ValueError("intervention_state_mismatch")
    forcing_steps = deepcopy(forcing_package.get("steps") or [])
    if len(forcing_steps) != horizon:
        raise ValueError("forcing_horizon_mismatch")
    if not (evidence_gate.get("counterfactual_comparison") or {}).get("ready"):
        raise ValueError("counterfactual_evidence_gate_not_ready")

    baseline_action = bind_environmental_action(
        {
            "action_type": "no_intervention",
            "target_node_ids": intervention_action.get("target_node_ids") or [],
            "state_snapshot_digest": state.get("snapshot_digest"),
        },
        state,
        actor=str(intervention_action.get("actor") or "system"),
    )
    baseline_states = [deepcopy(dict(state))]
    intervention_states = [deepcopy(dict(state))]
    baseline_mechanisms: list[dict[str, Any]] = []
    intervention_mechanisms: list[dict[str, Any]] = []
    propagation_messages: list[dict[str, Any]] = []

    for step_index, forcing in enumerate(forcing_steps, start=1):
        baseline_step = step_environmental_state(
            state=baseline_states[-1],
            action=baseline_action,
            forcing=forcing,
            evidence_gate=evidence_gate,
            temporal_channel_steps=temporal_channel_steps,
        )
        intervention_step = step_environmental_state(
            state=intervention_states[-1],
            action=intervention_action,
            forcing=forcing,
            evidence_gate=evidence_gate,
            temporal_channel_steps=temporal_channel_steps,
        )
        baseline_states.append(baseline_step["state"])
        intervention_states.append(intervention_step["state"])
        baseline_mechanisms.append(baseline_step["mechanism_contributions"])
        intervention_mechanisms.append(intervention_step["mechanism_contributions"])
        for message in intervention_step["propagation_messages"]:
            row = deepcopy(message)
            row["step"] = step_index
            propagation_messages.append(row)

    deltas = [
        _state_delta(step_index, baseline_states[step_index], intervention_states[step_index])
        for step_index in range(1, horizon + 1)
    ]
    result = {
        "schema": ENVIRONMENTAL_ROLLOUT_SCHEMA,
        "baseline_action": baseline_action,
        "intervention_action": deepcopy(dict(intervention_action)),
        "baseline_trajectory": baseline_states,
        "intervention_trajectory": intervention_states,
        "counterfactual_delta_by_step": deltas,
        "mechanism_contributions": {
            "baseline": baseline_mechanisms,
            "intervention": intervention_mechanisms,
        },
        "propagation_messages": propagation_messages,
        "uncertainty_envelope": {
            "mode": "per_mechanism_support_and_proxy_bounds",
            "numeric_joint_uncertainty": None,
        },
        "evidence_gate": deepcopy(dict(evidence_gate)),
        "production_blockers": deepcopy(evidence_gate.get("production_blockers") or []),
        "comparison_controls": {
            "initial_state_digest": state.get("snapshot_digest"),
            "graph_version": state.get("geography_version"),
            "forcing_digest": forcing_package.get("forcing_digest"),
            "horizon": horizon,
            "random_seed": random_seed,
        },
        "not_a_causal_effect_estimate": True,
    }
    validation = validate_rollout_result(result)
    if not validation["valid"]:
        raise ValueError(";".join(validation["errors"]))
    result["rollout_digest"] = _digest(result)
    return result


def _state_delta(step: int, baseline: Mapping[str, Any], intervention: Mapping[str, Any]) -> dict[str, Any]:
    baseline_nodes = {str(row["node_id"]): row for row in baseline.get("spatial_nodes") or []}
    intervention_nodes = {str(row["node_id"]): row for row in intervention.get("spatial_nodes") or []}
    nodes: dict[str, dict[str, float | None]] = {}
    for node_id in sorted(set(baseline_nodes) & set(intervention_nodes)):
        nodes[node_id] = {
            "pm25_delta": _joint_delta(baseline_nodes[node_id].get("pm25_ugm3"), intervention_nodes[node_id].get("pm25_ugm3")),
            "temperature_delta": _joint_delta(baseline_nodes[node_id].get("temperature_c"), intervention_nodes[node_id].get("temperature_c")),
            "vegetation_fraction_delta": _joint_delta(
                baseline_nodes[node_id].get("vegetation_fraction"),
                intervention_nodes[node_id].get("vegetation_fraction"),
            ),
        }
    return {"step": step, "nodes": nodes}


def _joint_delta(baseline: Any, intervention: Any) -> float | None:
    if baseline is None or intervention is None:
        return None
    return round(float(intervention) - float(baseline), 12)


def _digest(payload: Mapping[str, Any]) -> str:
    canonical = deepcopy(dict(payload))
    canonical.pop("rollout_digest", None)
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
