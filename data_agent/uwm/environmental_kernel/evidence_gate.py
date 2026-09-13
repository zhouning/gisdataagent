from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .contracts import (
    BOUNDED_PROXY,
    ENVIRONMENTAL_EVIDENCE_GATE_SCHEMA,
    OBSERVED_CALIBRATED,
    OBSERVED_CONTEXT,
    UNAVAILABLE,
)


CHANNELS = ("pm25", "temperature", "vegetation")


def build_environmental_evidence_gate(evidence: Mapping[str, Any]) -> dict[str, Any]:
    temporal = {
        channel: _temporal_readiness((evidence.get("temporal_channels") or {}).get(channel) or {})
        for channel in CHANNELS
    }
    action = {
        channel: _mechanism_readiness((evidence.get("action_response_channels") or {}).get(channel) or {})
        for channel in CHANNELS
    }
    spatial = {
        channel: _mechanism_readiness((evidence.get("spatial_channels") or {}).get(channel) or {})
        for channel in CHANNELS
    }
    observation = deepcopy(evidence.get("state_observation") or {})
    forcing = deepcopy(evidence.get("external_forcing") or {})
    blockers: list[str] = []
    if not observation.get("ready"):
        blockers.append("state_observation_not_ready")
    if not forcing.get("scene_aligned"):
        blockers.append("external_forcing_not_scene_aligned")
    for channel, readiness in temporal.items():
        if readiness["support_level"] == UNAVAILABLE:
            blockers.append(f"{channel}_temporal_calibration_unavailable")
    for channel, readiness in action.items():
        if readiness["support_level"] == UNAVAILABLE:
            blockers.append(f"{channel}_action_response_unavailable")
    for channel, readiness in spatial.items():
        if readiness["support_level"] == UNAVAILABLE:
            blockers.append(f"{channel}_spatial_propagation_unavailable")

    counterfactual_ready = bool(observation.get("ready") and forcing.get("scene_aligned"))
    any_bounded_action = any(row["support_level"] == BOUNDED_PROXY for row in action.values())
    any_action = any(row["support_level"] != UNAVAILABLE for row in action.values())
    max_claim_level = (
        "bounded_action_conditioned_environmental_scenario"
        if counterfactual_ready and any_action
        else "observed_environmental_state"
    )
    if any_bounded_action:
        max_claim_level = "bounded_action_conditioned_environmental_scenario"
    return {
        "schema": ENVIRONMENTAL_EVIDENCE_GATE_SCHEMA,
        "state_observation": observation,
        "temporal_calibration": temporal,
        "direct_action_response": action,
        "spatial_propagation": spatial,
        "external_forcing": forcing,
        "counterfactual_comparison": {
            "ready": counterfactual_ready,
            "causal_effect_claim": False,
        },
        "max_claim_level": max_claim_level,
        "production_blockers": sorted(set(blockers)),
    }


def _temporal_readiness(channel: Mapping[str, Any]) -> dict[str, Any]:
    if channel.get("holdout_passed") is True and channel.get("calibration_artifact_id") and channel.get("coefficient_source"):
        return {
            "support_level": OBSERVED_CALIBRATED,
            "calibration_artifact_id": channel.get("calibration_artifact_id"),
            "coefficient_source": channel.get("coefficient_source"),
        }
    return _mechanism_readiness(channel)


def _mechanism_readiness(channel: Mapping[str, Any]) -> dict[str, Any]:
    if channel.get("calibration_artifact_id") and channel.get("coefficient_source"):
        return {
            "support_level": OBSERVED_CALIBRATED,
            "calibration_artifact_id": channel.get("calibration_artifact_id"),
            "coefficient_source": channel.get("coefficient_source"),
        }
    if channel.get("deterministic_state_edit") is True and channel.get("coefficient_source"):
        return {
            "support_level": OBSERVED_CONTEXT,
            "coefficient_source": channel.get("coefficient_source"),
        }
    proxy_bound = channel.get("proxy_bound")
    if (
        isinstance(proxy_bound, list)
        and len(proxy_bound) == 2
        and channel.get("coefficient_source")
    ):
        return {
            "support_level": BOUNDED_PROXY,
            "proxy_bound": deepcopy(proxy_bound),
            "coefficient_source": channel.get("coefficient_source"),
        }
    return {
        "support_level": UNAVAILABLE,
        "coefficient_source": None,
    }
