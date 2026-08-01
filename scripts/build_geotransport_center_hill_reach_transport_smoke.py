#!/usr/bin/env python3
"""Run a cold-start Center Hill reach-transport operator smoke diagnostic."""

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
    LinearReferencedPath,
    ReachHydraulicState,
    ReachTransportConfig,
    StateDependentReachTransportOperator,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRAVEL_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_travel_time_prior_report.json"
)
DEFAULT_PANEL_REPORT = (
    REPO_ROOT / "benchmarks/geotransport_v0_1/center_hill_smoke_panel_report.json"
)
DEFAULT_Q_MANIFEST = (
    REPO_ROOT / "data/geotransport_v0_1/nwm_q_lateral/extraction_manifest.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "data/geotransport_v0_1/diagnostics/center_hill_reach_transport_cold_start_20220101.csv"
)
DEFAULT_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_reach_transport_smoke_report.json"
)
SCHEMA = "gwm.geotransport.center_hill_reach_transport_smoke.v1"
START = "2022-01-01T00:00:00Z"
END = "2022-01-02T00:00:00Z"


@dataclass(frozen=True)
class CompiledReachTransportSmoke:
    csv_body: bytes
    report: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--travel-report", type=Path, default=DEFAULT_TRAVEL_REPORT)
    parser.add_argument("--panel-report", type=Path, default=DEFAULT_PANEL_REPORT)
    parser.add_argument("--q-manifest", type=Path, default=DEFAULT_Q_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_smoke(
    *,
    travel_report_path: Path = DEFAULT_TRAVEL_REPORT,
    panel_report_path: Path = DEFAULT_PANEL_REPORT,
    q_manifest_path: Path = DEFAULT_Q_MANIFEST,
    output_path: Path = DEFAULT_OUTPUT,
) -> CompiledReachTransportSmoke:
    travel_body = travel_report_path.read_bytes()
    travel = json.loads(travel_body)
    panel_report_body = panel_report_path.read_bytes()
    panel_report = json.loads(panel_report_body)
    q_manifest_body = q_manifest_path.read_bytes()
    q_manifest = json.loads(q_manifest_body)
    _validate_source_reports(travel, panel_report, q_manifest)

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
    if len(panel_rows) != 24:
        raise ValueError("reach_transport_panel_requires_24_rows")

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
    cumulative_input = 0.0
    cumulative_outlet = 0.0
    step_residuals: list[float] = []
    residence_sums: list[float] = []
    for row in panel_rows:
        support_start = row["support_start_utc"]
        support_end = row["support_end_utc"]
        if row["nwm_valid_time_utc"] != support_start:
            raise ValueError("reach_transport_panel_nwm_time_contract_mismatch")
        q_by_id = q_values.get(support_start)
        velocity_by_id = velocity_values.get(support_start)
        if q_by_id is None or velocity_by_id is None:
            raise ValueError("reach_transport_hourly_reach_values_missing")
        if set(q_by_id) != set(path.feature_ids) or set(velocity_by_id) != set(
            path.feature_ids
        ):
            raise ValueError("reach_transport_feature_membership_mismatch")
        q_active = tuple(q_by_id[feature_id] for feature_id in active_ids)
        velocity_active = tuple(velocity_by_id[feature_id] for feature_id in active_ids)
        action_rate = float(row["action_release_m3s"])
        action = ActionBoundaryFlux(
            values=(action_rate,) + (0.0,) * (len(active_ids) - 1),
            unit="m3 s-1",
            provenance_id=f"cwms:eop:{support_end}",
        )
        forcing = ForcingFlux(
            values=q_active,
            unit="m3 s-1",
            provenance_id=f"nwm:q_lateral:{support_start}",
            modeled=True,
        )
        hydraulics = ReachHydraulicState(
            feature_ids=active_ids,
            propagation_speed_mps=velocity_active,
            quantity="river_velocity_proxy",
            provenance_id=f"nwm:velocity:{support_start}",
            evidence_level="candidate",
            admitted_as_flood_wave_celerity=False,
        )
        result = operator.step(
            state,
            hydraulics,
            action=action,
            forcing=forcing,
        )
        cumulative_input += result.input_volume_m3
        cumulative_outlet += result.outlet_volume_m3
        step_residuals.append(result.global_mass_balance_residual_m3)
        residence_sum = float(sum(result.reach_residence_time_seconds))
        residence_sums.append(residence_sum)
        output_rows.append(
            {
                "support_start_utc": support_start,
                "support_end_utc": support_end,
                "action_release_m3s": action_rate,
                "q_lateral_active_reach_sum_m3s": float(sum(q_active)),
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

    if output_rows[0]["support_start_utc"] != START or output_rows[-1][
        "support_end_utc"
    ] != END:
        raise ValueError("reach_transport_target_window_mismatch")
    horizon_residual = float(
        sum(state.values) + cumulative_outlet - cumulative_input
    )
    step_mass_tolerance = operator.config.absolute_mass_tolerance_m3
    horizon_mass_tolerance = len(output_rows) * step_mass_tolerance
    maximum_step_residual = max(abs(value) for value in step_residuals)
    if (
        maximum_step_residual > step_mass_tolerance
        or abs(horizon_residual) > horizon_mass_tolerance
    ):
        raise RuntimeError("reach_transport_smoke_mass_balance_gate_failed")
    csv_body = _encode_csv(output_rows)
    report = {
        "schema": SCHEMA,
        "status": "operator_smoke_passed_not_scientifically_admitted",
        "source_artifacts": {
            "travel_time_prior_report": _artifact(travel_report_path, travel_body),
            "panel_report": _artifact(panel_report_path, panel_report_body),
            "panel": _artifact_from_descriptor(panel_descriptor),
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
            "constant_input_support": "[support_start_utc,support_end_utc]",
            "initial_condition": "zero_reach_storage_cold_start",
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
            "step_count": len(output_rows),
        },
        "output_artifact": {
            "path": _display(output_path),
            "sha256": hashlib.sha256(csv_body).hexdigest(),
            "size_bytes": len(csv_body),
        },
        "diagnostics": {
            "cumulative_input_volume_m3": cumulative_input,
            "cumulative_outlet_volume_m3": cumulative_outlet,
            "final_reach_storage_m3": float(sum(state.values)),
            "horizon_mass_balance_residual_m3": horizon_residual,
            "step_mass_tolerance_m3": step_mass_tolerance,
            "horizon_mass_tolerance_m3": horizon_mass_tolerance,
            "maximum_absolute_step_mass_balance_residual_m3": float(
                maximum_step_residual
            ),
            "proxy_residence_time_sum_seconds": _summary(residence_sums),
            "diagnostic_outlet_mean_flow_m3s": _summary(
                [
                    float(row["diagnostic_outlet_mean_flow_m3s"])
                    for row in output_rows
                ]
            ),
        },
        "checks": {
            "action_enters_only_first_active_reach": True,
            "zero_effective_length_action_reach_excluded": True,
            "state_specific_velocity_proxy_used_each_hour": True,
            "exact_matrix_exponential_used": True,
            "all_step_mass_balance_residuals_within_tolerance": (
                maximum_step_residual <= step_mass_tolerance
            ),
            "horizon_mass_balance_residual_within_tolerance": (
                abs(horizon_residual) <= horizon_mass_tolerance
            ),
            "outcome_values_used": False,
        },
        "claim_boundary": {
            "real_boundary_action_used": True,
            "real_modeled_q_lateral_used": True,
            "real_nwm_river_velocity_proxy_used": True,
            "cold_start_operator_smoke_completed": True,
            "river_velocity_admitted_as_flood_wave_celerity": False,
            "linear_reservoir_cascade_hydrodynamically_validated": False,
            "flood_wave_transport_admitted": False,
            "outcome_calibrated": False,
            "training_or_evaluation_panel_ready": False,
            "benchmark_validated": False,
            "geospatial_kernel_validated": False,
        },
    }
    return CompiledReachTransportSmoke(csv_body=csv_body, report=report)


def _validate_source_reports(
    travel: Mapping[str, Any],
    panel: Mapping[str, Any],
    q_manifest: Mapping[str, Any],
) -> None:
    if (
        travel.get("schema")
        != "gwm.geotransport.center_hill_travel_time_prior.v1"
        or (travel.get("claim_boundary") or {}).get(
            "flood_wave_travel_time_admitted"
        )
        is not False
    ):
        raise ValueError("reach_transport_travel_prior_contract_invalid")
    if (
        panel.get("schema") != "gwm.geotransport.center_hill_smoke_panel.v2"
        or (panel.get("claim_boundary") or {}).get(
            "cwms_interval_timestamp_semantics_admitted"
        )
        is not True
        or (panel.get("claim_boundary") or {}).get(
            "training_or_evaluation_panel_ready"
        )
        is not False
    ):
        raise ValueError("reach_transport_panel_contract_invalid")
    if (
        q_manifest.get("schema") != "gwm.geotransport.nwm_q_lateral_extract.v1"
        or (q_manifest.get("source_semantics") or {}).get("ground_truth")
        is not False
    ):
        raise ValueError("reach_transport_q_lateral_contract_invalid")


def _linear_path(payload: Mapping[str, Any]) -> LinearReferencedPath:
    return LinearReferencedPath(
        path_id=str(payload["path_id"]),
        feature_ids=tuple(int(value) for value in payload["feature_ids"]),
        full_lengths_m=tuple(float(value) for value in payload["full_lengths_m"]),
        entry_offsets_m=tuple(
            float(value) for value in payload["entry_offsets_m"]
        ),
        exit_offsets_m=tuple(float(value) for value in payload["exit_offsets_m"]),
        provenance_id=str(payload["provenance_id"]),
        evidence_level=str(payload["evidence_level"]),
    )


def _read_reach_values(
    body: bytes,
    *,
    value_column: str,
    role_column: str,
    expected_role: str,
    target_start: str | None = None,
    target_end: str | None = None,
) -> dict[str, dict[int, float]]:
    result: dict[str, dict[int, float]] = {}
    for row in csv.DictReader(io.StringIO(body.decode("utf-8"))):
        timestamp = row["timestamp_utc"]
        if target_start is not None and not target_start <= timestamp < str(target_end):
            continue
        if row[role_column] != expected_role or row[value_column] == "":
            raise ValueError("reach_transport_reach_value_semantics_invalid")
        result.setdefault(timestamp, {})[int(row["feature_id"])] = float(
            row[value_column]
        )
    return result


def _encode_csv(rows: list[dict[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                key: format(value, ".12g") if isinstance(value, float) else value
                for key, value in row.items()
            }
        )
    return output.getvalue().encode("utf-8")


def _summary(values: list[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=float)
    return {
        "minimum": float(array.min()),
        "maximum": float(array.max()),
        "mean": float(array.mean()),
    }


def _read_verified_artifact(descriptor: Mapping[str, Any] | None) -> bytes:
    if not isinstance(descriptor, Mapping):
        raise ValueError("reach_transport_artifact_descriptor_required")
    path = (REPO_ROOT / str(descriptor.get("path"))).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("reach_transport_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError(f"reach_transport_artifact_identity_mismatch:{path}")
    return body


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": _display(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _artifact_from_descriptor(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    body = _read_verified_artifact(descriptor)
    return _artifact(REPO_ROOT / str(descriptor["path"]), body)


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def main() -> int:
    args = parse_args()
    compiled = compile_smoke(
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
