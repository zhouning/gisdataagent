#!/usr/bin/env python3
"""Freeze the Center Hill temporal-holdout protocol before label acquisition."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from data_agent.uwm.geospatial_kernel_v2 import (
    DEFAULT_REGISTRY_PATH,
    build_nwm_q_lateral_plan,
    load_nwm_zarr_schema,
    load_public_data_registry,
    nwm_chunk_url,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METADATA_ROOT = REPO_ROOT / "data/geotransport_v0_1/metadata"
DEFAULT_DEVELOPMENT_PANEL_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_672h_development_panel_report.json"
)
DEFAULT_DEVELOPMENT_ROLLOUT_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_672h_reach_transport_rollout_report.json"
)
DEFAULT_TRAVEL_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_travel_time_prior_report.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_temporal_holdout_protocol_v1.json"
)
SCHEMA = "gwm.geotransport.center_hill_temporal_holdout_protocol.v1"
ACQUISITION_START = datetime(2022, 1, 6, 1, tzinfo=timezone.utc)
SCORED_START = ACQUISITION_START + timedelta(hours=168)
END = ACQUISITION_START + timedelta(hours=672)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--metadata-root", type=Path, default=DEFAULT_METADATA_ROOT)
    parser.add_argument(
        "--development-panel-report",
        type=Path,
        default=DEFAULT_DEVELOPMENT_PANEL_REPORT,
    )
    parser.add_argument(
        "--development-rollout-report",
        type=Path,
        default=DEFAULT_DEVELOPMENT_ROLLOUT_REPORT,
    )
    parser.add_argument("--travel-report", type=Path, default=DEFAULT_TRAVEL_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_protocol(
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    metadata_root: Path = DEFAULT_METADATA_ROOT,
    development_panel_report_path: Path = DEFAULT_DEVELOPMENT_PANEL_REPORT,
    development_rollout_report_path: Path = DEFAULT_DEVELOPMENT_ROLLOUT_REPORT,
    travel_report_path: Path = DEFAULT_TRAVEL_REPORT,
) -> dict[str, Any]:
    registry = load_public_data_registry(registry_path)
    schema = load_nwm_zarr_schema(metadata_root)
    plan = build_nwm_q_lateral_plan(
        registry,
        schema,
        system_id="center_hill",
        start=_iso(ACQUISITION_START),
        end=_iso(END),
    )
    if (
        plan.time_count != 672
        or plan.time_chunk_indices != (560,)
        or plan.q_chunk_keys != ((560, 63),)
    ):
        raise ValueError("temporal_holdout_nwm_chunk_contract_mismatch")

    panel_body, panel = _load_report(development_panel_report_path)
    rollout_body, rollout = _load_report(development_rollout_report_path)
    travel_body, travel = _load_report(travel_report_path)
    _validate_parent_evidence(panel=panel, rollout=rollout, travel=travel)

    return {
        "schema": SCHEMA,
        "status": "frozen_before_evaluation_outcome_acquisition",
        "frozen_on": "2026-07-26",
        "system_id": "center_hill",
        "registry": _artifact(registry_path, registry_path.read_bytes()),
        "parent_development_evidence": {
            "panel_report": _artifact(development_panel_report_path, panel_body),
            "rollout_report": _artifact(
                development_rollout_report_path, rollout_body
            ),
            "travel_time_prior_report": _artifact(travel_report_path, travel_body),
        },
        "label_access_at_freeze": {
            "evaluation_window_outcome_acquired": False,
            "evaluation_window_outcome_inspected": False,
            "post_freeze_access_permitted": True,
            "required_lineage": "protocol_path_sha256_and_size_in_acquisition_manifest",
        },
        "temporal_split": {
            "acquisition_start_inclusive": _iso(ACQUISITION_START),
            "scored_start_inclusive": _iso(SCORED_START),
            "end_exclusive": _iso(END),
            "time_step": "PT1H",
            "acquisition_hours": 672,
            "evaluation_warmup_hours": 168,
            "maximum_scored_hours": 504,
            "evaluation_warmup_role": "state_update_and_baseline_history_only",
            "scored_role": "external_temporal_holdout",
            "development_rows_reassigned_to_evaluation": False,
        },
        "initial_state": {
            "method": "recompute_and_carry_frozen_development_final_per_reach_state",
            "development_end_exclusive": rollout["window"]["end_exclusive"],
            "state_reset_at_evaluation_boundary": False,
            "outcome_used": False,
        },
        "nwm_acquisition": {
            "source": "noaa_nwm_v3_retrospective",
            "time_chunk_indices": list(plan.time_chunk_indices),
            "feature_chunk_indices": list(plan.feature_chunk_indices),
            "q_lateral_chunk_keys": [list(value) for value in plan.q_chunk_keys],
            "required_urls": {
                "time": nwm_chunk_url("time", "560"),
                "q_lateral": nwm_chunk_url("q_lateral", "560.63"),
                "velocity": nwm_chunk_url("velocity", "560.63"),
            },
            "maximum_object_count": 3,
            "maximum_time_chunk_bytes": 1_000_000,
            "maximum_q_lateral_chunk_bytes": 100_000_000,
            "maximum_velocity_chunk_bytes": 100_000_000,
            "modeled_forcing_is_ground_truth": False,
            "river_velocity_is_flood_wave_celerity": False,
        },
        "companion_acquisition": {
            "request_count": 4,
            "sources": ["usace_cwms", "usgs_water_data"],
            "roles": [
                "boundary_action",
                "stock",
                "context_not_independent_forcing",
                "independent_observation",
            ],
            "bounded_to_acquisition_window_plus_usgs_support_margin": True,
            "accept_provisional_with_qualifier_preserved": True,
        },
        "operator_lock": {
            "schema": "gwm.geospatial_kernel.state_dependent_reach_transport.v1",
            "method": "ordered_first_order_reach_storage_cascade_exact_matrix_exponential",
            "timestep_seconds": 3600.0,
            "propagation_relation": "K_i=effective_length_i/river_velocity_proxy_i",
            "action_boundary": "first_active_reach_only",
            "forcing": "nwm_q_lateral_on_each_active_reach",
            "hydraulic_state": "nwm_river_velocity_proxy_each_hour",
            "parameter_fitting_on_evaluation_outcome": False,
            "missing_outcome_imputation": False,
        },
        "outcome_support_lock": {
            "source": "USGS:03424860:00060:IV",
            "hourly_statistic": "mean_of_exactly_two_half_hour_samples",
            "support": "(support_start_utc,support_end_utc]",
            "required_sample_count": 2,
            "required_qualifier": "A",
            "incomplete_hours": "visible_and_excluded_from_all_compared_series",
            "imputation": "forbidden",
        },
        "baseline_lock": {
            "outcome_persistence": (
                "immediately_previous_complete_hour_observation_only"
            ),
            "direct_release": "same_hour_boundary_action_release_m3s",
            "persistence_missing_predecessor": (
                "exclude_target_hour_from_all_compared_series"
            ),
            "baseline_parameters_fitted": False,
        },
        "mechanism_ablation_lock": {
            "zero_action": "same_operator_with_action_flux_zero_for_full_window",
            "no_forcing": "same_operator_with_q_lateral_zero_for_full_window",
            "reversed_topology": (
                "reverse_active_path_reach_order_and_reach_state_channels"
            ),
            "initial_state_rule": "transform_carried_state_consistently_per_ablation",
        },
        "metric_and_gate_lock": {
            "common_complete_case_mask": True,
            "primary_metric": "rmse_m3s",
            "secondary_metrics": ["mae_m3s", "bias_m3s", "nse"],
            "accuracy_gate": (
                "candidate_rmse_strictly_below_persistence_and_direct_release"
            ),
            "ablation_gate": (
                "each_ablated_rmse_strictly_above_candidate_and_prediction_change_positive"
            ),
            "mass_gate": "every_step_and_horizon_within_operator_numeric_tolerance",
            "aggregation": "non_compensatory_all_registered_gates_must_pass",
            "score_once_without_post_label_operator_revision": True,
        },
        "forbidden_after_label_access": [
            "change_evaluation_dates",
            "change_warmup_length",
            "fit_or_scale_velocity_from_evaluation_outcome",
            "select_lag_or_smoothing_from_evaluation_outcome",
            "impute_incomplete_outcome_hours",
            "drop_finite_rows_based_on_error",
            "change_metric_or_gate_thresholds",
        ],
        "claim_boundary": {
            "protocol_frozen_before_evaluation_outcome_acquisition": True,
            "evaluation_values_acquired": False,
            "evaluation_scored": False,
            "flood_wave_transport_admitted": False,
            "benchmark_validated": False,
            "multi_system_generalization_validated": False,
            "geospatial_kernel_validated": False,
        },
    }


def _validate_parent_evidence(
    *,
    panel: Mapping[str, Any],
    rollout: Mapping[str, Any],
    travel: Mapping[str, Any],
) -> None:
    if (
        panel.get("schema")
        != "gwm.geotransport.center_hill_672h_development_panel.v1"
        or (panel.get("window") or {}).get("evaluation_hours") != 0
        or (panel.get("claim_boundary") or {}).get("benchmark_validated")
        is not False
    ):
        raise ValueError("temporal_holdout_parent_panel_invalid")
    if (
        rollout.get("schema")
        != "gwm.geotransport.center_hill_672h_reach_transport_rollout.v1"
        or (rollout.get("window") or {}).get("end_exclusive")
        != _iso(ACQUISITION_START)
        or (rollout.get("checks") or {}).get("outcome_values_scored") is not False
        or (rollout.get("claim_boundary") or {}).get("outcome_calibrated")
        is not False
    ):
        raise ValueError("temporal_holdout_parent_rollout_invalid")
    if (
        travel.get("schema")
        != "gwm.geotransport.center_hill_travel_time_prior.v1"
        or (travel.get("claim_boundary") or {}).get(
            "flood_wave_travel_time_admitted"
        )
        is not False
    ):
        raise ValueError("temporal_holdout_parent_travel_prior_invalid")


def _load_report(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    return body, json.loads(body)


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": _display(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    args = parse_args()
    protocol = compile_protocol(
        registry_path=args.registry,
        metadata_root=args.metadata_root,
        development_panel_report_path=args.development_panel_report,
        development_rollout_report_path=args.development_rollout_report,
        travel_report_path=args.travel_report,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(protocol, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
