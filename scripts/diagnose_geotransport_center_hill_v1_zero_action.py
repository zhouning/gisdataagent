#!/usr/bin/env python3
"""Reproduce the frozen v1 zero-action failure without reading outcome data."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from scipy.linalg import expm

from data_agent.uwm.geospatial_kernel_v2 import (
    ForcingFlux,
    ReachHydraulicState,
    ReachTransportConfig,
    StateDependentReachTransportOperator,
    StockState,
)

if __package__:
    from scripts.build_geotransport_center_hill_reach_transport_smoke import (
        _artifact,
        _artifact_from_descriptor,
        _linear_path,
        _read_reach_values,
        _read_verified_artifact,
    )
else:
    from build_geotransport_center_hill_reach_transport_smoke import (
        _artifact,
        _artifact_from_descriptor,
        _linear_path,
        _read_reach_values,
        _read_verified_artifact,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRAVEL_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_travel_time_prior_report.json"
)
DEFAULT_Q_MANIFEST = (
    REPO_ROOT
    / "data/geotransport_v0_1/nwm_q_lateral_672h/extraction_manifest.json"
)
DEFAULT_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_v1_zero_action_numerical_invariant_report.json"
)
SCHEMA = "gwm.geotransport.center_hill_v1_zero_action_numerical_invariant.v1"
START = "2021-12-09T01:00:00Z"
END = "2022-01-06T01:00:00Z"
HOUR_COUNT = 672


@dataclass(frozen=True)
class FrozenCascadeStepAudit:
    raw_next_storage_m3: np.ndarray
    raw_transferred_volume_m3: np.ndarray
    cleaned_next_storage_m3: np.ndarray
    cleaned_transferred_volume_m3: np.ndarray
    residence_time_seconds: np.ndarray
    input_volume_m3: float
    numeric_tolerance_m3: float
    raw_mass_balance_residual_m3: float
    cleaned_mass_balance_residual_m3: float
    cleanup_mass_change_m3: float
    thresholded_storage_count: int
    thresholded_outflow_count: int
    failure: str | None


@dataclass(frozen=True)
class CompiledZeroActionInvariant:
    report: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--travel-report", type=Path, default=DEFAULT_TRAVEL_REPORT)
    parser.add_argument("--q-manifest", type=Path, default=DEFAULT_Q_MANIFEST)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_invariant(
    *,
    travel_report_path: Path = DEFAULT_TRAVEL_REPORT,
    q_manifest_path: Path = DEFAULT_Q_MANIFEST,
) -> CompiledZeroActionInvariant:
    travel_body = travel_report_path.read_bytes()
    travel = json.loads(travel_body)
    q_manifest_body = q_manifest_path.read_bytes()
    q_manifest = json.loads(q_manifest_body)
    _validate_sources(travel=travel, q_manifest=q_manifest)

    path = _linear_path(travel["linear_referenced_path"])
    config = ReachTransportConfig(
        timestep_seconds=3600.0,
        allow_unadmitted_components_for_diagnostics=True,
    )
    operator = StateDependentReachTransportOperator(path, config)
    active_ids = operator.active_feature_ids

    q_descriptor = (q_manifest.get("value_artifacts") or [None])[0]
    q_values = _read_reach_values(
        _read_verified_artifact(q_descriptor),
        value_column="q_lateral_m3s",
        role_column="source_role",
        expected_role="modeled_forcing",
        target_start=START,
        target_end=END,
    )
    velocity_descriptor = travel["source_artifacts"]["selected_velocity"]
    velocity_values = _read_reach_values(
        _read_verified_artifact(velocity_descriptor),
        value_column="velocity_ms",
        role_column="source_role",
        expected_role="modeled_state_context",
        target_start=START,
        target_end=END,
    )
    timestamps = sorted(q_values)
    if (
        len(timestamps) != HOUR_COUNT
        or timestamps != sorted(velocity_values)
        or timestamps[0] != START
        or timestamps[-1] != "2022-01-06T00:00:00Z"
    ):
        raise ValueError("zero_action_invariant_hour_axis_mismatch")

    state = operator.zero_state(
        provenance_id="center_hill:v1_zero_action_invariant:cold_start"
    )
    maximum_raw_residual = 0.0
    maximum_cleaned_residual_before_failure = 0.0
    first_failure: dict[str, Any] | None = None
    completed_steps = 0

    for index, timestamp in enumerate(timestamps):
        q_by_id = q_values[timestamp]
        velocity_by_id = velocity_values[timestamp]
        if set(q_by_id) != set(path.feature_ids) or set(velocity_by_id) != set(
            path.feature_ids
        ):
            raise ValueError("zero_action_invariant_feature_membership_mismatch")
        forcing_values = np.asarray(
            [q_by_id[feature_id] for feature_id in active_ids], dtype=float
        )
        speeds = np.asarray(
            [velocity_by_id[feature_id] for feature_id in active_ids], dtype=float
        )
        audit = _audit_frozen_v1_step(
            initial_storage_m3=np.asarray(state.values, dtype=float),
            forcing_rate_m3s=forcing_values,
            effective_lengths_m=np.asarray(operator.effective_lengths_m, dtype=float),
            propagation_speed_mps=speeds,
            timestep_seconds=config.timestep_seconds,
            absolute_mass_tolerance_m3=config.absolute_mass_tolerance_m3,
        )
        maximum_raw_residual = max(
            maximum_raw_residual, abs(audit.raw_mass_balance_residual_m3)
        )
        if audit.failure is None:
            maximum_cleaned_residual_before_failure = max(
                maximum_cleaned_residual_before_failure,
                abs(audit.cleaned_mass_balance_residual_m3),
            )

        operator_error: str | None = None
        try:
            result = operator.step(
                state,
                ReachHydraulicState(
                    active_ids,
                    tuple(float(value) for value in speeds),
                    "river_velocity_proxy",
                    f"nwm:velocity:{timestamp}:zero_action_invariant",
                    "candidate",
                    False,
                ),
                forcing=ForcingFlux(
                    tuple(float(value) for value in forcing_values),
                    "m3 s-1",
                    f"nwm:q_lateral:{timestamp}:zero_action_invariant",
                    modeled=True,
                ),
            )
        except RuntimeError as exc:
            operator_error = str(exc)

        if audit.failure is not None or operator_error is not None:
            if audit.failure != operator_error:
                raise RuntimeError("zero_action_invariant_audit_operator_disagreement")
            raw_storage_sum = float(audit.raw_next_storage_m3.sum())
            cleaned_storage_sum = float(audit.cleaned_next_storage_m3.sum())
            first_failure = {
                "step_index_zero_based": index,
                "completed_step_count": completed_steps,
                "support_start_utc": timestamp,
                "operator_error": operator_error,
                "failure_stage": _failure_stage(audit),
                "initial_storage_m3": float(sum(state.values)),
                "forcing_rate_sum_m3s": float(forcing_values.sum()),
                "forcing_volume_m3": audit.input_volume_m3,
                "raw_next_storage_sum_m3": raw_storage_sum,
                "cleaned_next_storage_sum_m3": cleaned_storage_sum,
                "raw_outlet_volume_m3": float(
                    audit.raw_transferred_volume_m3[-1]
                ),
                "cleaned_outlet_volume_m3": float(
                    audit.cleaned_transferred_volume_m3[-1]
                ),
                "raw_mass_balance_residual_m3": (
                    audit.raw_mass_balance_residual_m3
                ),
                "cleaned_mass_balance_residual_m3": (
                    audit.cleaned_mass_balance_residual_m3
                ),
                "numeric_tolerance_m3": audit.numeric_tolerance_m3,
                "cleaned_residual_to_tolerance_ratio": abs(
                    audit.cleaned_mass_balance_residual_m3
                )
                / audit.numeric_tolerance_m3,
                "cleanup_mass_change_m3": audit.cleanup_mass_change_m3,
                "thresholded_storage_count": audit.thresholded_storage_count,
                "thresholded_outflow_count": audit.thresholded_outflow_count,
                "minimum_raw_next_storage_m3": float(
                    audit.raw_next_storage_m3.min()
                ),
                "minimum_raw_transferred_volume_m3": float(
                    audit.raw_transferred_volume_m3.min()
                ),
                "minimum_residence_time_seconds": float(
                    audit.residence_time_seconds.min()
                ),
                "maximum_residence_time_seconds": float(
                    audit.residence_time_seconds.max()
                ),
                "residence_time_scale_ratio": float(
                    audit.residence_time_seconds.max()
                    / audit.residence_time_seconds.min()
                ),
                "minimum_effective_reach_length_m": float(
                    min(operator.effective_lengths_m)
                ),
                "maximum_effective_reach_length_m": float(
                    max(operator.effective_lengths_m)
                ),
            }
            break

        if not np.array_equal(
            np.asarray(result.next_stock.values), audit.cleaned_next_storage_m3
        ):
            raise RuntimeError("zero_action_invariant_audit_state_mismatch")
        state = StockState(
            tuple(float(value) for value in audit.cleaned_next_storage_m3),
            "m3",
            f"center_hill:v1_zero_action_invariant:{timestamp}",
        )
        completed_steps += 1

    if first_failure is None:
        raise RuntimeError("zero_action_invariant_expected_frozen_v1_failure_missing")

    report = {
        "schema": SCHEMA,
        "status": "frozen_v1_failure_reproduced",
        "operator_schema": "gwm.geospatial_kernel.state_dependent_reach_transport.v1",
        "scenario": "zero_action_with_public_modeled_lateral_forcing",
        "time_window": {
            "start_inclusive": START,
            "end_exclusive": END,
            "registered_hour_count": HOUR_COUNT,
        },
        "data_isolation": {
            "outcome_values_loaded": False,
            "action_values_loaded": False,
            "panel_artifacts_loaded": False,
            "transition_inputs": [
                "linear_referenced_path",
                "nwm_q_lateral_modeled_forcing",
                "nwm_river_velocity_proxy",
            ],
        },
        "source_artifacts": {
            "travel_report": _artifact(travel_report_path, travel_body),
            "q_lateral_manifest": _artifact(q_manifest_path, q_manifest_body),
            "q_lateral_values": _artifact_from_descriptor(q_descriptor),
            "velocity_values": _artifact_from_descriptor(velocity_descriptor),
        },
        "active_reach_count": len(active_ids),
        "excluded_zero_length_feature_ids": list(
            operator.excluded_zero_length_feature_ids
        ),
        "completed_step_count": completed_steps,
        "first_failure": first_failure,
        "pre_failure_summary": {
            "maximum_absolute_raw_mass_balance_residual_m3": (
                maximum_raw_residual
            ),
            "maximum_absolute_cleaned_mass_balance_residual_m3": (
                maximum_cleaned_residual_before_failure
            ),
        },
        "diagnosis": {
            "physical_state_divergence_observed": False,
            "raw_matrix_exponential_conservation_passed_at_failure": abs(
                float(first_failure["raw_mass_balance_residual_m3"])
            )
            <= float(first_failure["numeric_tolerance_m3"]),
            "componentwise_cleanup_changed_conserved_mass": True,
            "frozen_v1_failure_mechanism": (
                "componentwise near-zero storage cleanup precedes the global "
                "mass-balance gate and can remove more than one global tolerance "
                "when several reaches are cleaned in the same step"
            ),
            "scientific_adjudication_changed": False,
            "v1_operator_modified": False,
        },
        "v2_invariant_lock": {
            "zero_action_must_complete_full_window": True,
            "raw_and_returned_state_must_each_be_globally_conservative": True,
            "componentwise_cleanup_may_not_spend_global_tolerance_per_component": True,
            "outcome_access_permitted": False,
            "failure_is_non_compensatory": True,
        },
        "claim_boundary": {
            "frozen_v1_failure_reproduced": True,
            "frozen_v1_repaired": False,
            "v2_numerical_strategy_admitted": False,
            "hydrodynamic_mechanism_validated": False,
            "geospatial_kernel_validated": False,
        },
    }
    return CompiledZeroActionInvariant(report=report)


def _audit_frozen_v1_step(
    *,
    initial_storage_m3: np.ndarray,
    forcing_rate_m3s: np.ndarray,
    effective_lengths_m: np.ndarray,
    propagation_speed_mps: np.ndarray,
    timestep_seconds: float,
    absolute_mass_tolerance_m3: float,
) -> FrozenCascadeStepAudit:
    count = len(initial_storage_m3)
    residence_time = effective_lengths_m / propagation_speed_mps
    inverse_residence = 1.0 / residence_time
    generator = np.zeros((2 * count + 1, 2 * count + 1), dtype=float)
    constant_index = 2 * count
    state_indices = np.arange(count)
    cumulative_indices = count + state_indices
    generator[state_indices, state_indices] = -inverse_residence
    if count > 1:
        generator[state_indices[1:], state_indices[:-1]] = inverse_residence[:-1]
    generator[state_indices, constant_index] = forcing_rate_m3s
    generator[cumulative_indices, state_indices] = inverse_residence

    initial_augmented = np.zeros(2 * count + 1, dtype=float)
    initial_augmented[:count] = initial_storage_m3
    initial_augmented[constant_index] = 1.0
    advanced = expm(generator * timestep_seconds) @ initial_augmented
    raw_next = advanced[:count]
    raw_transferred = advanced[count : 2 * count]
    input_volume = float(forcing_rate_m3s.sum() * timestep_seconds)
    numeric_scale = max(
        1.0,
        float(initial_storage_m3.sum()),
        input_volume,
    )
    tolerance = (
        absolute_mass_tolerance_m3
        + np.finfo(float).eps * 1_000.0 * numeric_scale
    )
    raw_residual = float(
        raw_next.sum()
        + raw_transferred[-1]
        - initial_storage_m3.sum()
        - input_volume
    )

    cleaned_next = raw_next.copy()
    cleaned_transferred = raw_transferred.copy()
    storage_threshold_mask = np.abs(cleaned_next) <= tolerance
    outflow_threshold_mask = np.abs(cleaned_transferred) <= tolerance
    cleaned_next[storage_threshold_mask] = 0.0
    cleaned_transferred[outflow_threshold_mask] = 0.0
    cleaned_next = np.maximum(cleaned_next, 0.0)
    cleaned_transferred = np.maximum(cleaned_transferred, 0.0)
    cleaned_residual = float(
        cleaned_next.sum()
        + cleaned_transferred[-1]
        - initial_storage_m3.sum()
        - input_volume
    )
    cleanup_mass_change = float(
        cleaned_next.sum()
        + cleaned_transferred[-1]
        - raw_next.sum()
        - raw_transferred[-1]
    )

    failure = None
    if bool((raw_next < -tolerance).any()) or bool(
        (raw_transferred < -tolerance).any()
    ):
        failure = "reach_transport_exponential_produced_negative_volume"
    elif abs(cleaned_residual) > tolerance:
        failure = "reach_transport_global_mass_balance_exceeded"
    return FrozenCascadeStepAudit(
        raw_next_storage_m3=raw_next,
        raw_transferred_volume_m3=raw_transferred,
        cleaned_next_storage_m3=cleaned_next,
        cleaned_transferred_volume_m3=cleaned_transferred,
        residence_time_seconds=residence_time,
        input_volume_m3=input_volume,
        numeric_tolerance_m3=float(tolerance),
        raw_mass_balance_residual_m3=raw_residual,
        cleaned_mass_balance_residual_m3=cleaned_residual,
        cleanup_mass_change_m3=cleanup_mass_change,
        thresholded_storage_count=int(storage_threshold_mask.sum()),
        thresholded_outflow_count=int(outflow_threshold_mask.sum()),
        failure=failure,
    )


def _failure_stage(audit: FrozenCascadeStepAudit) -> str:
    if audit.failure == "reach_transport_exponential_produced_negative_volume":
        return "raw_matrix_exponential_output"
    if (
        abs(audit.raw_mass_balance_residual_m3) <= audit.numeric_tolerance_m3
        and abs(audit.cleaned_mass_balance_residual_m3)
        > audit.numeric_tolerance_m3
    ):
        return "post_componentwise_near_zero_cleanup"
    return "raw_or_cleaned_global_mass_balance"


def _validate_sources(
    *, travel: Mapping[str, Any], q_manifest: Mapping[str, Any]
) -> None:
    if (
        travel.get("schema")
        != "gwm.geotransport.center_hill_travel_time_prior.v1"
        or q_manifest.get("schema")
        != "gwm.geotransport.nwm_q_lateral_extract.v1"
        or (q_manifest.get("source_semantics") or {}).get("role")
        != "modeled_forcing"
        or (q_manifest.get("source_semantics") or {}).get("ground_truth")
        is not False
    ):
        raise ValueError("zero_action_invariant_source_contract_invalid")


def main() -> int:
    args = parse_args()
    compiled = compile_invariant(
        travel_report_path=args.travel_report,
        q_manifest_path=args.q_manifest,
    )
    report = dict(compiled.report)
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
