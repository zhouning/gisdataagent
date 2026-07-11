from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Mapping

from .contracts import UNAVAILABLE
from .state import build_environmental_state


TemporalStep = Callable[..., Mapping[str, Any] | None]


def step_environmental_state(
    *,
    state: Mapping[str, Any],
    action: Mapping[str, Any],
    forcing: Mapping[str, Any],
    evidence_gate: Mapping[str, Any],
    temporal_channel_steps: Mapping[str, TemporalStep] | None = None,
) -> dict[str, Any]:
    nodes = {str(row["node_id"]): deepcopy(dict(row)) for row in state.get("spatial_nodes") or []}
    temporal_contributions: dict[str, dict[str, Any]] = {node_id: {} for node_id in nodes}
    direct_contributions: dict[str, dict[str, Any]] = {node_id: {} for node_id in nodes}
    spatial_contributions: dict[str, dict[str, Any]] = {node_id: {} for node_id in nodes}
    temporal_channel_steps = temporal_channel_steps or {}

    for channel, step in temporal_channel_steps.items():
        gate = (evidence_gate.get("temporal_calibration") or {}).get(channel) or {}
        if gate.get("support_level") == UNAVAILABLE:
            continue
        field = _state_field(channel)
        for node_id, node in nodes.items():
            before = node.get(field)
            result = step(node=deepcopy(node), forcing=deepcopy(dict(forcing)), channel_gate=deepcopy(gate))
            if result is None or result.get("value") is None or before is None:
                continue
            after = float(result["value"])
            node[field] = after
            temporal_contributions[node_id][f"{channel}_delta"] = after - float(before)
            temporal_contributions[node_id][f"{channel}_support_level"] = result.get("support_level")
            temporal_contributions[node_id][f"{channel}_coefficient_source"] = result.get("coefficient_source")

    target_ids = set(action.get("target_node_ids") or [])
    action_type = action.get("action_type")
    for node_id in target_ids:
        if node_id not in nodes:
            continue
        if action_type == "no_intervention":
            continue
        vegetation_gate = (evidence_gate.get("direct_action_response") or {}).get("vegetation") or {}
        vegetation_delta = float(action.get("vegetation_fraction_delta") or 0.0)
        if vegetation_gate.get("support_level") != UNAVAILABLE:
            current = nodes[node_id].get("vegetation_fraction")
            if current is not None:
                applied = min(1.0 - float(current), vegetation_delta)
                nodes[node_id]["vegetation_fraction"] = float(current) + applied
                direct_contributions[node_id]["vegetation_fraction_delta"] = applied
                direct_contributions[node_id]["vegetation_support_level"] = vegetation_gate.get("support_level")
        for channel in ("pm25", "temperature"):
            gate = (evidence_gate.get("direct_action_response") or {}).get(channel) or {}
            direct_contributions[node_id][f"{channel}_delta"] = None
            direct_contributions[node_id][f"{channel}_support_level"] = gate.get("support_level", UNAVAILABLE)

    messages: list[dict[str, Any]] = []
    adjacency_edges = [
        edge
        for edge in state.get("spatial_edges") or []
        if edge.get("relation_type") == "grid_adjacent_grid"
    ]
    for edge in adjacency_edges:
        source_id = str(edge.get("source_node_id"))
        target_id = str(edge.get("target_node_id"))
        if source_id not in target_ids and target_id not in target_ids:
            continue
        direct_source = source_id if source_id in target_ids else target_id
        context_target = target_id if source_id in target_ids else source_id
        for channel in ("pm25", "temperature", "vegetation"):
            gate = (evidence_gate.get("spatial_propagation") or {}).get(channel) or {}
            if gate.get("support_level") == UNAVAILABLE:
                continue
            message = {
                "source_node_id": direct_source,
                "target_node_id": context_target,
                "relation_type": "grid_adjacent_grid",
                "effect_channel": channel,
                "raw_weight": 1.0,
                "normalized_weight": 1.0,
                "hop": 1,
                "support_level": gate.get("support_level"),
                "uncertainty": "bounded_by_channel_evidence",
                "coefficient_source": gate.get("coefficient_source"),
                "claim_level": "context_propagation_only",
            }
            messages.append(message)
            spatial_contributions[context_target][f"{channel}_context"] = {
                "support_level": gate.get("support_level"),
                "coefficient_source": gate.get("coefficient_source"),
                "numeric_delta": None,
            }

    next_payload = deepcopy(dict(state))
    next_payload["spatial_nodes"] = list(nodes.values())
    next_payload["external_forcing"] = deepcopy(dict(forcing))
    next_payload.pop("snapshot_digest", None)
    next_state = build_environmental_state(next_payload)
    return {
        "state": next_state,
        "mechanism_contributions": {
            "temporal": temporal_contributions,
            "direct_action": direct_contributions,
            "spatial_propagation": spatial_contributions,
        },
        "propagation_messages": sorted(
            messages,
            key=lambda row: (row["source_node_id"], row["target_node_id"], row["effect_channel"]),
        ),
    }


def _state_field(channel: str) -> str:
    if channel == "pm25":
        return "pm25_ugm3"
    if channel == "temperature":
        return "temperature_c"
    if channel == "vegetation":
        return "vegetation_fraction"
    raise ValueError("unsupported_temporal_channel")
