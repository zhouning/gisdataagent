#!/usr/bin/env python3
"""Freeze a mechanism-level selector replication design without choosing a window."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.horizon_assimilation_policy import (
    HORIZON_ASSIMILATION_MODES,
    HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS,
    HorizonAssimilationPolicy,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DISPOSITION = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_candidate_disposition.json"
)
DEFAULT_POLICY_FREEZE = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_policy_freeze.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_selector_replication_design.json"
)
COMPILER_PATH = Path(__file__).resolve()
SCHEMA = "gwm.geotransport.horizon_selector_replication_design.v1"
DISPOSITION_SCHEMA = (
    "gwm.geotransport.horizon_assimilation_candidate_disposition.v1"
)
POLICY_FREEZE_SCHEMA = "gwm.geotransport.horizon_assimilation_policy_freeze.v1"
DESIGN_ID = "horizon_selector_mechanism_replication_v1"
PRIOR_WINDOW = {
    "start_inclusive_utc": "2022-04-28T01:00:00Z",
    "end_exclusive_utc": "2022-05-26T01:00:00Z",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disposition", type=Path, default=DEFAULT_DISPOSITION)
    parser.add_argument("--policy-freeze", type=Path, default=DEFAULT_POLICY_FREEZE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_replication_design(
    *,
    disposition_path: Path = DEFAULT_DISPOSITION,
    policy_freeze_path: Path = DEFAULT_POLICY_FREEZE,
    frozen_at: datetime | None = None,
) -> dict[str, Any]:
    disposition_body, disposition = _load_json(disposition_path)
    policy_body, policy_freeze = _load_json(policy_freeze_path)
    policy = _validate_inputs(disposition, policy_freeze)
    now = frozen_at or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("horizon_selector_design_frozen_at_must_be_aware")
    selected = policy.as_dict()["selected_mode_by_horizon_hours"]
    if not isinstance(selected, Mapping):
        raise ValueError("horizon_selector_design_policy_mapping_invalid")
    differing_horizons = {
        mode: [
            horizon
            for horizon in HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS
            if selected[str(horizon)] != mode
        ]
        for mode in HORIZON_ASSIMILATION_MODES
    }
    if any(not values for values in differing_horizons.values()):
        raise ValueError("horizon_selector_design_uniform_comparator_identical")

    return {
        "schema": SCHEMA,
        "status": "design_frozen_awaiting_unused_window_adjudication",
        "design_id": DESIGN_ID,
        "frozen_at": now.astimezone(UTC).isoformat(),
        "scientific_question": (
            "Does a predeclared horizon selector improve equal-horizon-weighted "
            "system accuracy over every uniform constituent strategy and causal "
            "issue-observation persistence on a new unused window?"
        ),
        "prior_candidate_boundary": {
            "candidate_id": policy.candidate_id,
            "prior_disposition": "rejected_for_promotion",
            "prior_disposition_final": True,
            "prior_candidate_reopened": False,
            "successful_replication_would_reverse_prior_rejection": False,
            "scientific_role": (
                "mechanism-level replication only; not a replacement score for "
                "the rejected candidate"
            ),
        },
        "frozen_artifacts": {
            "candidate_disposition": _artifact(
                disposition_path, disposition_body
            ),
            "policy_freeze": _artifact(policy_freeze_path, policy_body),
            "rollout_core": dict(
                policy_freeze["implementation_artifacts"][
                    "outcome_free_rollout_core"
                ]
            ),
            "design_compiler": _artifact(
                COMPILER_PATH, COMPILER_PATH.read_bytes()
            ),
        },
        "prediction_lock": {
            "candidate_policy_sha256": policy_freeze["policy_sha256"],
            "candidate_selected_mode_by_horizon_hours": dict(selected),
            "uniform_fixed_strategy_modes": list(HORIZON_ASSIMILATION_MODES),
            "traditional_strategy": "causal_issue_observation_persistence",
            "all_constituent_predictions_sealed_per_issue": True,
            "target_outcome_argument_accepted_by_runner": False,
            "score_or_loss_argument_accepted_by_runner": False,
        },
        "scoring_design": {
            "primary_metric": "rmse_m3s",
            "secondary_metrics": ["mae_m3s", "bias_m3s"],
            "common_complete_case_mask": (
                "per_system_and_horizon_across_target_candidate_all_four_"
                "uniform_modes_and_persistence"
            ),
            "minimum_scored_issues_per_system_and_horizon": 48,
            "horizon_aggregation_within_system": (
                "unweighted_arithmetic_mean_of_1h_3h_6h_12h_RMSE"
            ),
            "cross_horizon_aggregation_within_system_permitted": True,
            "cross_system_compensation_permitted": False,
            "system_gate": (
                "candidate_mean_RMSE_strictly_below_each_of_four_uniform_"
                "strategy_mean_RMSEs_and_persistence_mean_RMSE"
            ),
            "overall_gate": (
                "both_system_gates_and_all_execution_gates_pass"
            ),
            "ties_pass": False,
            "per_horizon_strict_superiority_gate": False,
            "per_horizon_metrics_reported": True,
            "score_once_after_joint_prediction_seal": True,
            "post_score_tuning_or_rescoring_permitted": False,
        },
        "comparison_validity": {
            "candidate_is_not_identical_to_any_uniform_strategy_across_all_horizons": True,
            "candidate_differing_horizons_by_uniform_mode": differing_horizons,
            "constituent_mode_may_tie_candidate_at_selected_horizon": True,
            "selected_horizon_tie_does_not_make_system_level_gate_impossible": True,
            "former_three_hour_self_comparison_removed": True,
        },
        "window_adjudication_requirements": {
            "window_selected": False,
            "window_start_utc": None,
            "window_end_utc": None,
            "nwm_time_chunk_index": None,
            "hour_count": 672,
            "issue_stride_hours": 12,
            "issue_count_per_system": 56,
            "systems": ["center_hill", "j_percy_priest"],
            "horizons_hours": list(
                HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS
            ),
            "must_start_on_full_nwm_time_chunk_boundary": True,
            "initial_state_is_immediately_preceding_hour": True,
            "must_not_overlap_prior_scored_window": dict(PRIOR_WINDOW),
            "repository_value_consumption_audit_required": True,
            "audit_scope": [
                "NWM_initial_state_and_forcing_values",
                "CWMS_action_values",
                "USGS_issue_observation_values",
                "USGS_target_outcome_values",
            ],
            "zero_prior_local_target_outcome_consumption_required": True,
            "external_prior_access_can_be_proven_absent": False,
        },
        "data_access_boundary": {
            "new_window_url_compiled": False,
            "new_window_request_count": 0,
            "new_window_values_requested": False,
            "new_window_values_loaded": False,
            "current_exposed_holdout_used_to_select_new_window": False,
        },
        "forbidden_after_freeze": [
            "change_candidate_policy_or_constituent_modes",
            "change_metrics_aggregation_comparators_masks_or_gates",
            "use_the_exposed_2022_04_28_to_2022_05_26_outcomes_to_retune_rules",
            "select_a_window_after_reading_its_values",
            "score_more_than_once_or_tune_after_score",
            "reinterpret_mechanism_replication_as_reversal_of_prior_rejection",
        ],
        "next_gate": {
            "required_artifact": "unused_window_adjudication_report",
            "network_or_value_access_before_next_gate": False,
            "automatic_execution_authorized": False,
        },
        "claim_boundary": {
            "replication_design_frozen": True,
            "unused_window_adjudicated": False,
            "replication_protocol_frozen": False,
            "replication_predictions_executed": False,
            "replication_scored": False,
            "candidate_promoted": False,
            "runtime_default_enabled": False,
            "geospatial_kernel_validated": False,
        },
    }


def _validate_inputs(
    disposition: Mapping[str, Any], policy_freeze: Mapping[str, Any]
) -> HorizonAssimilationPolicy:
    if (
        disposition.get("schema") != DISPOSITION_SCHEMA
        or disposition.get("status")
        != "candidate_rejected_after_verified_historical_holdout"
        or disposition.get("decision", {}).get("disposition")
        != "rejected_for_promotion"
        or disposition.get("decision", {}).get("final_for_candidate_id")
        is not True
        or disposition.get("claim_boundary", {}).get("candidate_promoted")
        is not False
        or disposition.get("claim_boundary", {}).get("runtime_default_enabled")
        is not False
        or policy_freeze.get("schema") != POLICY_FREEZE_SCHEMA
    ):
        raise ValueError("horizon_selector_design_input_disposition_invalid")
    for descriptor in disposition.get("evidence_chain", {}).values():
        _read_verified(descriptor)
    policy_payload = policy_freeze.get("policy")
    if not isinstance(policy_payload, Mapping):
        raise ValueError("horizon_selector_design_policy_missing")
    policy = HorizonAssimilationPolicy.from_dict(policy_payload)
    if policy.admitted is not False or policy.runtime_default_enabled is not False:
        raise ValueError("horizon_selector_design_policy_not_fail_closed")
    return policy


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor.get("path"))).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("horizon_selector_design_artifact_outside_repo") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("horizon_selector_design_artifact_hash_mismatch")
    return body


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("horizon_selector_design_json_required")
    return body, payload


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        display = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise ValueError("horizon_selector_design_artifact_outside_repo") from exc
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise ValueError("horizon_selector_replication_design_already_exists")
    report = compile_replication_design(
        disposition_path=args.disposition,
        policy_freeze_path=args.policy_freeze,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(f"status={report['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
