#!/usr/bin/env python3
"""Run the bounded Center Hill 672-hour reach-transport development rollout."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from data_agent.uwm.geospatial_kernel_v2 import (
    ActionBoundaryFlux,
    ForcingFlux,
    ReachHydraulicState,
    ReachTransportConfig,
    StateDependentReachTransportOperator,
)

if __package__:
    from scripts.build_geotransport_center_hill_reach_transport_smoke import (
        _artifact,
        _artifact_from_descriptor,
        _display,
        _encode_csv,
        _linear_path,
        _read_reach_values,
        _read_verified_artifact,
        _summary,
    )
else:
    from build_geotransport_center_hill_reach_transport_smoke import (
        _artifact,
        _artifact_from_descriptor,
        _display,
        _encode_csv,
        _linear_path,
        _read_reach_values,
        _read_verified_artifact,
        _summary,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRAVEL_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_travel_time_prior_report.json"
)
DEFAULT_PANEL_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_672h_development_panel_report.json"
)
DEFAULT_Q_MANIFEST = (
    REPO_ROOT
    / "data/geotransport_v0_1/nwm_q_lateral_672h/extraction_manifest.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "data/geotransport_v0_1/diagnostics/center_hill_reach_transport_672h_development.csv"
)
DEFAULT_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_672h_reach_transport_rollout_report.json"
)
SCHEMA = "gwm.geotransport.center_hill_672h_reach_transport_rollout.v1"
START = "2021-12-09T01:00:00Z"
END = "2022-01-06T01:00:00Z"
HOUR_COUNT = 672
WARMUP_HOURS = 168
RESIDENCE_CROSS_ARTIFACT_TOLERANCE_SECONDS = 1e-4


@dataclass(frozen=True)
class CompiledReachTransportRollout:
    csv_body: bytes
    report: dict[str, Any]
    final_stock_values_m3: tuple[float, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--travel-report", type=Path, default=DEFAULT_TRAVEL_REPORT)
    parser.add_argument("--panel-report", type=Path, default=DEFAULT_PANEL_REPORT)
    parser.add_argument("--q-manifest", type=Path, default=DEFAULT_Q_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_rollout(
    *,
    travel_report_path: Path = DEFAULT_TRAVEL_REPORT,
    panel_report_path: Path = DEFAULT_PANEL_REPORT,
    q_manifest_path: Path = DEFAULT_Q_MANIFEST,
    output_path: Path = DEFAULT_OUTPUT,
) -> CompiledReachTransportRollout:
    travel_body = travel_report_path.read_bytes()
    travel = json.loads(travel_body)
    panel_report_body = panel_report_path.read_bytes()
    panel_report = json.loads(panel_report_body)
    q_manifest_body = q_manifest_path.read_bytes()
    q_manifest = json.loads(q_manifest_body)
    _validate_source_reports(
        travel=travel,
        panel=panel_report,
        q_manifest=q_manifest,
        travel_body=travel_body,
        travel_path=travel_report_path,
        q_manifest_body=q_manifest_body,
        q_manifest_path=q_manifest_path,
    )

    path = _linear_path(travel["linear_referenced_path"])
    operator = StateDependentReachTransportOperator(
        path,
        ReachTransportConfig(
            timestep_seconds=3600.0,
            allow_unadmitted_components_for_diagnostics=True,
        ),
    )
    active_ids = operator.active_feature_ids
    panel_descriptor = panel_report["panel_artifact"]
    panel_body = _read_verified_artifact(panel_descriptor)
    panel_rows = list(csv.DictReader(io.StringIO(panel_body.decode("utf-8"))))
    _validate_panel_rows(panel_rows)

    q_descriptor = (q_manifest.get("value_artifacts") or [None])[0]
    q_body = _read_verified_artifact(q_descriptor)
    q_values = _read_reach_values(
        q_body,
        value_column="q_lateral_m3s",
        role_column="source_role",
        expected_role="modeled_forcing",
    )
    velocity_descriptor = travel["source_artifacts"]["selected_velocity"]
    velocity_body = _read_verified_artifact(velocity_descriptor)
    velocity_values = _read_reach_values(
        velocity_body,
        value_column="velocity_ms",
        role_column="source_role",
        expected_role="modeled_state_context",
        target_start=START,
        target_end=END,
    )

    state = operator.zero_state(provenance_id="center_hill:cold_start:zero_storage")
    output_rows: list[dict[str, Any]] = []
    step_residuals: list[float] = []
    step_numeric_tolerances: list[float] = []
    phase_inputs = {"warmup": 0.0, "development": 0.0}
    phase_outlets = {"warmup": 0.0, "development": 0.0}
    phase_numeric_tolerances = {"warmup": 0.0, "development": 0.0}
    phase_outlet_flows: dict[str, list[float]] = {"warmup": [], "development": []}
    residence_sums: list[float] = []
    residence_cross_artifact_differences: list[float] = []
    warmup_end_storage: float | None = None

    for index, row in enumerate(panel_rows):
        support_start = row["support_start_utc"]
        support_end = row["support_end_utc"]
        split_role = row["split_role"]
        if row["nwm_valid_time_utc"] != support_start:
            raise ValueError("reach_transport_rollout_nwm_time_contract_mismatch")
        q_by_id = q_values.get(support_start)
        velocity_by_id = velocity_values.get(support_start)
        if q_by_id is None or velocity_by_id is None:
            raise ValueError("reach_transport_rollout_hourly_reach_values_missing")
        if set(q_by_id) != set(path.feature_ids) or set(velocity_by_id) != set(
            path.feature_ids
        ):
            raise ValueError("reach_transport_rollout_feature_membership_mismatch")
        q_active = tuple(q_by_id[feature_id] for feature_id in active_ids)
        velocity_active = tuple(velocity_by_id[feature_id] for feature_id in active_ids)
        q_sum = float(sum(q_active))
        if not np.isclose(
            q_sum,
            float(row["nwm_q_lateral_active_reach_sum_m3s"]),
            rtol=0.0,
            atol=1e-8,
        ):
            raise ValueError("reach_transport_rollout_panel_q_lateral_mismatch")

        action_rate = float(row["action_release_m3s"])
        result = operator.step(
            state,
            ReachHydraulicState(
                feature_ids=active_ids,
                propagation_speed_mps=velocity_active,
                quantity="river_velocity_proxy",
                provenance_id=f"nwm:velocity:{support_start}",
                evidence_level="candidate",
                admitted_as_flood_wave_celerity=False,
            ),
            action=ActionBoundaryFlux(
                values=(action_rate,) + (0.0,) * (len(active_ids) - 1),
                unit="m3 s-1",
                provenance_id=f"cwms:eop:{support_end}",
            ),
            forcing=ForcingFlux(
                values=q_active,
                unit="m3 s-1",
                provenance_id=f"nwm:q_lateral:{support_start}",
                modeled=True,
            ),
        )
        residence_sum = float(sum(result.reach_residence_time_seconds))
        residence_difference = residence_sum - float(
            row["nwm_velocity_proxy_residence_time_seconds"]
        )
        if not np.isclose(
            residence_difference,
            0.0,
            rtol=0.0,
            atol=RESIDENCE_CROSS_ARTIFACT_TOLERANCE_SECONDS,
        ):
            raise ValueError("reach_transport_rollout_panel_residence_time_mismatch")
        phase_inputs[split_role] += result.input_volume_m3
        phase_outlets[split_role] += result.outlet_volume_m3
        phase_outlet_flows[split_role].append(result.outlet_mean_flow_m3s)
        numeric_scale = max(
            1.0,
            float(sum(state.values)),
            result.input_volume_m3,
        )
        numeric_tolerance = (
            operator.config.absolute_mass_tolerance_m3
            + np.finfo(float).eps * 1_000.0 * numeric_scale
        )
        phase_numeric_tolerances[split_role] += numeric_tolerance
        step_residuals.append(result.global_mass_balance_residual_m3)
        step_numeric_tolerances.append(numeric_tolerance)
        residence_sums.append(residence_sum)
        residence_cross_artifact_differences.append(residence_difference)
        output_rows.append(
            {
                "support_start_utc": support_start,
                "support_end_utc": support_end,
                "split_role": split_role,
                "action_release_m3s": action_rate,
                "q_lateral_active_reach_sum_m3s": q_sum,
                "velocity_proxy_min_mps": float(min(velocity_active)),
                "velocity_proxy_median_mps": float(np.median(velocity_active)),
                "velocity_proxy_max_mps": float(max(velocity_active)),
                "proxy_residence_time_sum_seconds": residence_sum,
                "diagnostic_outlet_mean_flow_m3s": result.outlet_mean_flow_m3s,
                "reach_storage_end_m3": float(sum(result.next_stock.values)),
                "step_input_volume_m3": result.input_volume_m3,
                "step_outlet_volume_m3": result.outlet_volume_m3,
                "step_mass_balance_residual_m3": (
                    result.global_mass_balance_residual_m3
                ),
            }
        )
        state = result.next_stock
        if index == WARMUP_HOURS - 1:
            warmup_end_storage = float(sum(state.values))

    if warmup_end_storage is None:
        raise RuntimeError("reach_transport_rollout_warmup_boundary_missing")
    final_storage = float(sum(state.values))
    warmup_residual = (
        warmup_end_storage
        + phase_outlets["warmup"]
        - phase_inputs["warmup"]
    )
    development_residual = (
        final_storage
        + phase_outlets["development"]
        - warmup_end_storage
        - phase_inputs["development"]
    )
    cumulative_input = float(sum(phase_inputs.values()))
    cumulative_outlet = float(sum(phase_outlets.values()))
    horizon_residual = final_storage + cumulative_outlet - cumulative_input
    absolute_tolerance = operator.config.absolute_mass_tolerance_m3
    horizon_tolerance = float(sum(step_numeric_tolerances))
    maximum_step_residual = max(abs(value) for value in step_residuals)
    if (
        any(
            abs(residual) > tolerance
            for residual, tolerance in zip(
                step_residuals, step_numeric_tolerances, strict=True
            )
        )
        or abs(warmup_residual) > phase_numeric_tolerances["warmup"]
        or abs(development_residual)
        > phase_numeric_tolerances["development"]
        or abs(horizon_residual) > horizon_tolerance
    ):
        raise RuntimeError(
            "reach_transport_rollout_mass_balance_gate_failed:"
            f"step={maximum_step_residual}:warmup={warmup_residual}:"
            f"development={development_residual}:horizon={horizon_residual}"
        )

    csv_body = _encode_csv(output_rows)
    report = {
        "schema": SCHEMA,
        "status": "development_diagnostic_completed_not_scientifically_admitted",
        "source_artifacts": {
            "travel_time_prior_report": _artifact(travel_report_path, travel_body),
            "development_panel_report": _artifact(
                panel_report_path, panel_report_body
            ),
            "development_panel": _artifact_from_descriptor(panel_descriptor),
            "q_lateral_extraction_manifest": _artifact(
                q_manifest_path, q_manifest_body
            ),
            "q_lateral_selected_values": _artifact_from_descriptor(q_descriptor),
            "velocity_selected_values": _artifact_from_descriptor(
                velocity_descriptor
            ),
        },
        "operator": {
            "schema": "gwm.geospatial_kernel.state_dependent_reach_transport.v1",
            "method": "ordered_first_order_reach_storage_cascade_exact_matrix_exponential",
            "timestep_seconds": 3600.0,
            "propagation_relation": "K_i=effective_length_i/river_velocity_proxy_i",
            "initial_condition": "zero_reach_storage_before_warmup",
            "warmup_state_transition": "state_carried_without_reset_into_development",
            "path_admitted": False,
            "operator_form_admitted": False,
        },
        "spatial_support": {
            "path_id": path.path_id,
            "full_feature_count": len(path.feature_ids),
            "active_feature_count": len(active_ids),
            "active_feature_ids": list(active_ids),
            "excluded_zero_length_feature_ids": list(
                operator.excluded_zero_length_feature_ids
            ),
            "effective_path_length_m": sum(operator.effective_lengths_m),
            "partial_gauge_reach_q_lateral_remains_full_reach_approximation": True,
        },
        "window": {
            "start_inclusive": START,
            "end_exclusive": END,
            "time_step": "PT1H",
            "step_count": HOUR_COUNT,
            "warmup_hours": WARMUP_HOURS,
            "development_hours": HOUR_COUNT - WARMUP_HOURS,
            "evaluation_hours": 0,
        },
        "output_artifact": {
            "path": _display(output_path),
            "sha256": hashlib.sha256(csv_body).hexdigest(),
            "size_bytes": len(csv_body),
        },
        "diagnostics": {
            "cumulative_input_volume_m3": cumulative_input,
            "cumulative_outlet_volume_m3": cumulative_outlet,
            "final_reach_storage_m3": final_storage,
            "horizon_mass_balance_residual_m3": horizon_residual,
            "maximum_absolute_step_mass_balance_residual_m3": float(
                maximum_step_residual
            ),
            "absolute_mass_tolerance_base_m3": absolute_tolerance,
            "maximum_step_numeric_mass_tolerance_m3": max(
                step_numeric_tolerances
            ),
            "cumulative_step_numeric_mass_tolerance_m3": horizon_tolerance,
            "proxy_residence_time_sum_seconds": _summary(residence_sums),
            "residence_cross_artifact_rounding_tolerance_seconds": (
                RESIDENCE_CROSS_ARTIFACT_TOLERANCE_SECONDS
            ),
            "maximum_absolute_residence_cross_artifact_difference_seconds": max(
                abs(value) for value in residence_cross_artifact_differences
            ),
            "warmup": {
                "step_count": WARMUP_HOURS,
                "initial_reach_storage_m3": 0.0,
                "input_volume_m3": phase_inputs["warmup"],
                "outlet_volume_m3": phase_outlets["warmup"],
                "final_reach_storage_m3": warmup_end_storage,
                "mass_balance_residual_m3": warmup_residual,
                "cumulative_step_numeric_mass_tolerance_m3": (
                    phase_numeric_tolerances["warmup"]
                ),
                "diagnostic_outlet_mean_flow_m3s": _summary(
                    phase_outlet_flows["warmup"]
                ),
            },
            "development": {
                "step_count": HOUR_COUNT - WARMUP_HOURS,
                "initial_reach_storage_m3": warmup_end_storage,
                "input_volume_m3": phase_inputs["development"],
                "outlet_volume_m3": phase_outlets["development"],
                "final_reach_storage_m3": final_storage,
                "mass_balance_residual_m3": development_residual,
                "cumulative_step_numeric_mass_tolerance_m3": (
                    phase_numeric_tolerances["development"]
                ),
                "diagnostic_outlet_mean_flow_m3s": _summary(
                    phase_outlet_flows["development"]
                ),
            },
        },
        "checks": {
            "action_enters_only_first_active_reach": True,
            "zero_effective_length_action_reach_excluded": True,
            "state_specific_velocity_proxy_used_each_hour": True,
            "exact_matrix_exponential_used": True,
            "first_168_hours_used_only_for_warmup": True,
            "warmup_state_carried_into_development_without_reset": True,
            "input_channels_complete_for_all_steps": True,
            "residence_cross_artifact_difference_within_rounding_tolerance": True,
            "source_observation_gap_preserved_without_imputation": True,
            "all_step_mass_balance_residuals_within_tolerance": True,
            "warmup_mass_balance_residual_within_tolerance": True,
            "development_mass_balance_residual_within_tolerance": True,
            "horizon_mass_balance_residual_within_tolerance": True,
            "outcome_values_used": False,
            "outcome_values_used_for_calibration": False,
            "outcome_values_scored": False,
        },
        "claim_boundary": {
            "real_boundary_action_used": True,
            "real_modeled_q_lateral_used": True,
            "real_nwm_river_velocity_proxy_used": True,
            "bounded_672h_rollout_completed": True,
            "warmup_completed": True,
            "development_diagnostic_completed": True,
            "river_velocity_admitted_as_flood_wave_celerity": False,
            "linear_reservoir_cascade_hydrodynamically_validated": False,
            "flood_wave_transport_admitted": False,
            "outcome_calibrated": False,
            "training_or_evaluation_panel_ready": False,
            "benchmark_validated": False,
            "geospatial_kernel_validated": False,
        },
    }
    return CompiledReachTransportRollout(
        csv_body=csv_body,
        report=report,
        final_stock_values_m3=tuple(float(value) for value in state.values),
    )


def _validate_source_reports(
    *,
    travel: Mapping[str, Any],
    panel: Mapping[str, Any],
    q_manifest: Mapping[str, Any],
    travel_body: bytes,
    travel_path: Path,
    q_manifest_body: bytes,
    q_manifest_path: Path,
) -> None:
    if (
        travel.get("schema")
        != "gwm.geotransport.center_hill_travel_time_prior.v1"
        or (travel.get("velocity_window") or {}).get("time_count") != HOUR_COUNT
        or (travel.get("claim_boundary") or {}).get(
            "flood_wave_travel_time_admitted"
        )
        is not False
    ):
        raise ValueError("reach_transport_rollout_travel_prior_contract_invalid")
    quality = panel.get("quality_summary") or {}
    window = panel.get("window") or {}
    claims = panel.get("claim_boundary") or {}
    if (
        panel.get("schema")
        != "gwm.geotransport.center_hill_672h_development_panel.v1"
        or window.get("row_count") != HOUR_COUNT
        or window.get("warmup_hours") != WARMUP_HOURS
        or window.get("development_hours") != HOUR_COUNT - WARMUP_HOURS
        or window.get("evaluation_hours") != 0
        or quality.get("input_channel_missing_value_count") != 0
        or quality.get("outcome_missing_hour_count") != 3
        or quality.get("outcome_imputed_hour_count") != 0
        or claims.get("training_or_evaluation_panel_ready") is not False
        or claims.get("flood_wave_transport_admitted") is not False
    ):
        raise ValueError("reach_transport_rollout_panel_contract_invalid")
    if (
        q_manifest.get("schema") != "gwm.geotransport.nwm_q_lateral_extract.v1"
        or (q_manifest.get("results") or [{}])[0].get("time_count") != HOUR_COUNT
        or (q_manifest.get("results") or [{}])[0].get("fill_value_count") != 0
        or (q_manifest.get("source_semantics") or {}).get("ground_truth")
        is not False
        or (q_manifest.get("claim_boundary") or {}).get(
            "raw_chunks_reused_without_download"
        )
        is not True
    ):
        raise ValueError("reach_transport_rollout_q_lateral_contract_invalid")
    source_manifests = panel.get("source_manifests") or {}
    if source_manifests.get("travel_time_prior") != _artifact(
        travel_path, travel_body
    ) or source_manifests.get("nwm_q_lateral_672h") != _artifact(
        q_manifest_path, q_manifest_body
    ):
        raise ValueError("reach_transport_rollout_source_lineage_mismatch")


def _validate_panel_rows(rows: list[dict[str, str]]) -> None:
    if len(rows) != HOUR_COUNT:
        raise ValueError("reach_transport_rollout_requires_672_rows")
    if rows[0]["support_start_utc"] != START or rows[-1]["support_end_utc"] != END:
        raise ValueError("reach_transport_rollout_target_window_mismatch")
    if any(
        row["split_role"] != ("warmup" if index < WARMUP_HOURS else "development")
        for index, row in enumerate(rows)
    ):
        raise ValueError("reach_transport_rollout_split_contract_mismatch")
    required = (
        "action_release_m3s",
        "nwm_q_lateral_active_reach_sum_m3s",
        "nwm_velocity_proxy_residence_time_seconds",
    )
    if any(row[key] == "" for row in rows for key in required):
        raise ValueError("reach_transport_rollout_input_channel_missing")


def main() -> int:
    args = parse_args()
    compiled = compile_rollout(
        travel_report_path=args.travel_report,
        panel_report_path=args.panel_report,
        q_manifest_path=args.q_manifest,
        output_path=args.output,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(compiled.csv_body)
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
