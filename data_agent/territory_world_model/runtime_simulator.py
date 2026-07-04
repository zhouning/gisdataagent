from __future__ import annotations

import hashlib
from typing import Any


SIMULATOR_TRACE_SCHEMA = "territory_world_model.simulator_trace.v1"
CONTRACT_TRACE_BACKEND_TYPE = "contract_trace_only"


def build_simulator_trace(canonical_observation: dict[str, Any], *, suite_id: str) -> dict[str, Any]:
    """Build a simulator trace shell without claiming predictive performance."""

    dataset_hash = str(canonical_observation.get("dataset_snapshot_hash") or "")
    observation_id = str(canonical_observation.get("observation_id") or "")
    split = "test"
    prediction_seed = f"{suite_id}:{dataset_hash}:{observation_id}:{split}:{CONTRACT_TRACE_BACKEND_TYPE}"
    prediction_id = f"twm-runtime-v1-{hashlib.sha256(prediction_seed.encode('utf-8')).hexdigest()[:16]}"
    simulator_input = canonical_observation.get("simulator_input") or {}
    return {
        "schema": SIMULATOR_TRACE_SCHEMA,
        "prediction_id": prediction_id,
        "backend_type": CONTRACT_TRACE_BACKEND_TYPE,
        "model_family": "contract_trace_only",
        "model_version": "0.1",
        "split": split,
        "dataset_snapshot_hash": dataset_hash,
        "observation_id": observation_id,
        "consumed_observation_schema": canonical_observation.get("schema"),
        "consumed_contexts": list(simulator_input.get("required_contexts") or []),
        "predictive_heads": {
            "future_state_delta": "not_implemented",
            "constraint_violation_probability": "not_implemented",
            "planning_utility_delta": "not_implemented",
            "uncertainty": "not_implemented",
            "action_mask_probability": "not_implemented",
        },
        "claim_boundary": {
            "runtime_trace": "present",
            "predictive_performance": "not_evaluated",
            "production_claim": "not_supported",
        },
    }
