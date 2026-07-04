from __future__ import annotations

import hashlib
from typing import Any


RUNTIME_OBSERVATION_SCHEMA = "territory_world_model.runtime_observation.v1"
TARGET_COLUMNS = {
    "next_state_score",
    "constraint_risk_delta",
    "planning_utility_delta",
    "outcome",
}
ACTION_MASK_LABEL_COLUMNS = {
    "action_mask_allowed",
    "action_mask_required_reviews",
    "action_mask_hard_blocks",
    "action_mask_policy",
}
EXCLUDED_SIMULATOR_INPUT_COLUMNS = TARGET_COLUMNS | ACTION_MASK_LABEL_COLUMNS


def build_runtime_observation(measurements: dict[str, Any], dataset_snapshot_hash: str) -> dict[str, Any]:
    """Build a canonical TWM observation contract for simulator consumption."""

    trajectory_columns = set(measurements.get("trajectory_columns") or [])
    excluded_target_columns = sorted(trajectory_columns.intersection(EXCLUDED_SIMULATOR_INPUT_COLUMNS))
    input_feature_columns = sorted(trajectory_columns.difference(EXCLUDED_SIMULATOR_INPUT_COLUMNS))
    observation_seed = {
        "schema": RUNTIME_OBSERVATION_SCHEMA,
        "dataset_snapshot_hash": dataset_snapshot_hash,
        "dataset_id": measurements.get("dataset_id"),
        "object_count": measurements.get("object_count"),
        "relation_count": measurements.get("relation_count"),
        "trajectory_columns": sorted(trajectory_columns),
    }
    observation_id = hashlib.sha256(repr(observation_seed).encode("utf-8")).hexdigest()
    return {
        "schema": RUNTIME_OBSERVATION_SCHEMA,
        "observation_id": observation_id,
        "dataset_snapshot_hash": dataset_snapshot_hash,
        "dataset_id": measurements.get("dataset_id"),
        "boundary": {
            "synthetic": "True" in set(measurements.get("synthetic_flags") or []),
            "not_for_production": bool(measurements.get("not_for_production_boundary_preserved")),
            "production_claim": "not_supported",
        },
        "object_summary": {
            "object_count": int(measurements.get("object_count") or 0),
            "project_count": int(measurements.get("project_count") or 0),
            "layer_counts": dict(measurements.get("layer_counts") or {}),
        },
        "relation_summary": {
            "relation_count": int(measurements.get("relation_count") or 0),
        },
        "rule_context": {
            "rule_evaluation_count": int(measurements.get("rule_evaluation_count") or 0),
        },
        "support_material_context": {
            "support_material_count": int(measurements.get("support_material_count") or 0),
            "legacy_source_name": "multimodal_evidence_index",
        },
        "review_context": {
            "review_task_count": int(measurements.get("review_task_count") or 0),
        },
        "trajectory_context": {
            "row_count": int(measurements.get("synthetic_experiment_rows") or 0),
            "counterfactual_pairs": int(measurements.get("counterfactual_pairs") or 0),
            "split_counts": dict(measurements.get("split_counts") or {}),
            "action_types": list(measurements.get("action_types") or []),
            "allowed_rows": int(measurements.get("allowed_rows") or 0),
            "blocked_rows": int(measurements.get("blocked_rows") or 0),
        },
        "feature_vector_contract": {
            "schema": "territory_world_model.runtime_feature_vector_contract.v1",
            "input_feature_columns": input_feature_columns,
            "excluded_target_columns": excluded_target_columns,
            "target_columns": sorted(EXCLUDED_SIMULATOR_INPUT_COLUMNS),
            "future_outcome_columns": sorted(TARGET_COLUMNS),
            "label_explanation_columns": sorted(ACTION_MASK_LABEL_COLUMNS),
            "target_columns_excluded_from_input": set(excluded_target_columns).isdisjoint(input_feature_columns),
            "raw_source_may_contain_targets": bool(excluded_target_columns),
        },
        "simulator_input": {
            "consumable": True,
            "encoding": "tabular_state_action_context",
            "required_contexts": [
                "object_summary",
                "relation_summary",
                "rule_context",
                "support_material_context",
                "review_context",
                "trajectory_context",
                "feature_vector_contract",
            ],
            "state_feature_groups": [
                "object_summary",
                "relation_summary",
                "rule_context",
                "support_material_context",
                "review_context",
            ],
            "action_fields": ["action_type"],
            "label_fields_excluded": sorted(ACTION_MASK_LABEL_COLUMNS),
            "target_fields_excluded": excluded_target_columns,
        },
    }
