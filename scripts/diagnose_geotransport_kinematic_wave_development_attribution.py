#!/usr/bin/env python3
"""Attribute kinematic-wave phase error on an outcome-visible public window."""

from __future__ import annotations

import argparse
import csv
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Iterator, Mapping

import numpy as np

from data_agent.uwm.geospatial_kernel_v2.contracts import TemporalSupport
from data_agent.uwm.geospatial_kernel_v2.manning_path_response import (
    MANNING_PATH_RESPONSE_SCHEMA,
    ManningPathResponseDiagnostic,
)
from data_agent.uwm.geospatial_kernel_v2.phase_alignment import (
    TemporalAlignmentSeries,
    TemporalPhaseAlignmentAuditor,
)

if __package__:
    import scripts.run_geotransport_kinematic_wave_holdout_v1_outcome_free as base
    from scripts.run_geotransport_kinematic_wave_holdout_v2_outcome_free import (
        _TwoUlpNumpyProxy,
    )
else:
    import run_geotransport_kinematic_wave_holdout_v1_outcome_free as base
    from run_geotransport_kinematic_wave_holdout_v2_outcome_free import (
        _TwoUlpNumpyProxy,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geotransport_v2_blind_validation_protocol.json"
)
INPUT_REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geotransport_v2_blind_validation_inputs_report.json"
)
OUTCOME_REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geotransport_v2_blind_validation_outcomes_report.json"
)
OUTPUT_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/kinematic_wave_development_attribution/predictions"
)
REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_development_attribution_report.json"
)
START = datetime(2022, 3, 31, 1, tzinfo=timezone.utc)
END = datetime(2022, 4, 28, 1, tzinfo=timezone.utc)
HOUR_COUNT = 672
SYSTEM_IDS = ("center_hill", "j_percy_priest")
TIMESTEP_SECONDS = 3600.0
TARGET_CELL_LENGTH_M = 1000.0
CFL_NUMBER = 0.8
MAXIMUM_PHASE_SHIFT_STEPS = 48
MINIMUM_PHASE_PAIRS = 500
SCHEMA = "gwm.geotransport.kinematic_wave_development_attribution.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace only this script's existing development artifacts.",
    )
    return parser.parse_args()


def compile_attribution() -> tuple[dict[str, bytes], dict[str, Any]]:
    protocol_body, protocol = _load_json(PROTOCOL_PATH)
    inputs_body, inputs = _load_json(INPUT_REPORT_PATH)
    outcomes_body, outcomes = _load_json(OUTCOME_REPORT_PATH)
    _validate_sources(protocol, inputs, outcomes)

    predictions: dict[str, bytes] = {}
    systems: dict[str, dict[str, Any]] = {}
    with _rollout_context():
        for system_id in SYSTEM_IDS:
            output_path = OUTPUT_ROOT / f"{system_id}.csv"
            body, execution = base._run_system(
                system_id=system_id,
                lock=protocol["systems"][system_id],
                inputs=inputs["systems"][system_id],
                output_path=output_path,
            )
            _rename_two_ulp_invariant(execution)
            predictions[system_id] = body
            systems[system_id] = _diagnose_system(
                system_id=system_id,
                prediction_body=body,
                execution=execution,
                lock=protocol["systems"][system_id],
                inputs=inputs["systems"][system_id],
                outcome_descriptor=outcomes["systems"][system_id][
                    "outcome_values"
                ],
            )

    return predictions, {
        "schema": SCHEMA,
        "status": "outcome_visible_development_attribution_complete",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "start_inclusive": _iso(START),
            "end_exclusive": _iso(END),
            "hour_count": HOUR_COUNT,
            "role": "posthoc_development_only",
            "former_role": "completed_blind_validation_window",
        },
        "source_artifacts": {
            "protocol": _artifact(PROTOCOL_PATH, protocol_body),
            "inputs": _artifact(INPUT_REPORT_PATH, inputs_body),
            "outcomes": _artifact(OUTCOME_REPORT_PATH, outcomes_body),
        },
        "systems": systems,
        "interpretation_boundary": {
            "outcomes_visible_before_this_diagnostic_was_defined": True,
            "statistical_phase_is_physical_travel_time": False,
            "statistical_phase_deployed_as_prediction_shift": False,
            "physical_prior_outcome_calibrated": False,
            "physical_prior_admitted_as_flood_wave_lag": False,
            "new_confirmatory_validation_claim": False,
            "operator_form_admitted": False,
            "geospatial_kernel_validated": False,
        },
    }


def _diagnose_system(
    *,
    system_id: str,
    prediction_body: bytes,
    execution: Mapping[str, Any],
    lock: Mapping[str, Any],
    inputs: Mapping[str, Any],
    outcome_descriptor: Mapping[str, Any],
) -> dict[str, Any]:
    prediction_rows = list(
        csv.DictReader(io.StringIO(prediction_body.decode("utf-8")))
    )
    action_body = base._read_verified(inputs["action_values"])
    action_rows = list(csv.DictReader(io.StringIO(action_body.decode("utf-8"))))
    outcome_body = base._read_verified(outcome_descriptor)
    outcome_rows = list(csv.DictReader(io.StringIO(outcome_body.decode("utf-8"))))

    observation = _series(
        timestamps=tuple(_parse_utc(row["support_end_utc"]) for row in outcome_rows),
        values=tuple(
            None
            if row["observed_discharge_m3s"] == ""
            else float(row["observed_discharge_m3s"])
            for row in outcome_rows
        ),
        role="independent_observation",
        provenance_id=str(outcome_descriptor["sha256"]),
        evidence_level="derived",
    )
    action = _series(
        timestamps=tuple(_parse_utc(row["support_end_utc"]) for row in action_rows),
        values=tuple(float(row["action_release_m3s"]) for row in action_rows),
        role="boundary_action",
        provenance_id=str(inputs["action_values"]["sha256"]),
        evidence_level="authoritative",
    )
    prediction = _series(
        timestamps=tuple(
            _parse_utc(row["support_end_utc"]) for row in prediction_rows
        ),
        values=tuple(float(row["kinematic_wave_m3s"]) for row in prediction_rows),
        role="kinematic_wave_prediction",
        provenance_id=hashlib.sha256(prediction_body).hexdigest(),
        evidence_level="derived",
    )
    branch_silent = _series(
        timestamps=prediction.timestamps_utc,
        values=tuple(
            float(row["branch_silent_negative_control_m3s"])
            for row in prediction_rows
        ),
        role="branch_silent_negative_control",
        provenance_id=hashlib.sha256(prediction_body).hexdigest(),
        evidence_level="derived",
    )
    auditor = TemporalPhaseAlignmentAuditor()
    phase = {
        "action_to_observation": _analyze(auditor, observation, action),
        "kinematic_prediction_to_observation": _analyze(
            auditor, observation, prediction
        ),
        "branch_silent_to_observation": _analyze(
            auditor, observation, branch_silent
        ),
    }
    physical = _initial_state_path_prior(
        system_id=system_id,
        lock=lock,
        inputs=inputs,
    )
    return {
        "system_id": system_id,
        "prediction_artifact": _artifact(
            OUTPUT_ROOT / f"{system_id}.csv", prediction_body
        ),
        "source_artifacts": {
            "action": _artifact_from_descriptor(inputs["action_values"]),
            "outcome": _artifact_from_descriptor(outcome_descriptor),
        },
        "execution": execution,
        "phase_alignment": phase,
        "physical_path_diagnostic": physical,
        "attribution_audit": {
            "all_series_normalized_to_support_centers": True,
            "all_timestamp_positions": "end",
            "temporal_label_support_center_offset_seconds": 0.0,
            "branch_effect_zero_shift_rmse_improvement_m3s": (
                phase["branch_silent_to_observation"]["zero_shift"]["rmse"]
                - phase["kinematic_prediction_to_observation"]["zero_shift"][
                    "rmse"
                ]
            ),
            "physical_prior_compared_with_outcomes_but_not_fitted": True,
            "statistical_phase_admitted_as_flood_wave_lag": False,
        },
    }


def _analyze(
    auditor: TemporalPhaseAlignmentAuditor,
    reference: TemporalAlignmentSeries,
    candidate: TemporalAlignmentSeries,
) -> dict[str, Any]:
    return auditor.analyze(
        reference,
        candidate,
        timestep_seconds=TIMESTEP_SECONDS,
        maximum_shift_steps=MAXIMUM_PHASE_SHIFT_STEPS,
        minimum_complete_pairs=MINIMUM_PHASE_PAIRS,
        outcome_visible_diagnostic=True,
    ).as_dict()


def _series(
    *,
    timestamps: tuple[datetime, ...],
    values: tuple[float | None, ...],
    role: str,
    provenance_id: str,
    evidence_level: str,
) -> TemporalAlignmentSeries:
    return TemporalAlignmentSeries(
        timestamps_utc=timestamps,
        values=values,
        temporal_support=TemporalSupport(
            kind="interval_mean",
            duration_seconds=TIMESTEP_SECONDS,
            timestamp_position="end",
            provenance_id=f"{role}:{provenance_id}",
            evidence_level=evidence_level,
        ),
        unit="m3 s-1",
        role=role,
        provenance_id=provenance_id,
    )


def _initial_state_path_prior(
    *,
    system_id: str,
    lock: Mapping[str, Any],
    inputs: Mapping[str, Any],
) -> dict[str, Any]:
    topology_body = base._read_verified(lock["topology_report"])
    topology = json.loads(topology_body)
    network_body = base._read_verified(topology["artifacts"]["full_subnetwork"])
    network_payload = json.loads(network_body)
    network = base._network(network_payload["network"])
    route_link_descriptor = topology["artifacts"]["route_link_subset"]
    route_link_body = base._read_verified(route_link_descriptor)
    route_link_path = REPO_ROOT / str(route_link_descriptor["path"])
    geometry = base._geometry(route_link_path, network, route_link_body)
    initial_discharge = np.asarray(
        base._read_npy(inputs["decoded_arrays"]["initial_streamflow_m3s"]),
        dtype=float,
    )
    initial_area_proxy = np.asarray(
        base._read_npy(inputs["decoded_arrays"]["initial_cross_section_area_m2"]),
        dtype=float,
    )
    initial_velocity = np.asarray(
        base._read_npy(inputs["decoded_arrays"]["initial_velocity_ms"]),
        dtype=float,
    )
    diagnostic = ManningPathResponseDiagnostic(network, geometry)
    provenance_id = (
        f"{route_link_descriptor['sha256']}|"
        f"{inputs['decoded_arrays']['initial_streamflow_m3s']['sha256']}"
    )
    initial_response = diagnostic.analyze(
        tuple(float(value) for value in initial_discharge),
        start_feature_id=network.action_entry_feature_ids[0],
        end_feature_id=network.outlet_feature_id,
        path_id=f"{system_id}:action-entry-to-outlet",
        provenance_id=provenance_id,
        evidence_level="candidate",
        outcome_calibrated=False,
    )
    if initial_response.total_travel_time_seconds is None:
        raise ValueError(f"{system_id}_initial_manning_celerity_nonpositive")

    reach_rows: list[dict[str, Any]] = []
    index = {feature: offset for offset, feature in enumerate(network.feature_ids)}
    for response in initial_response.reaches:
        feature = response.feature_id
        reach_index = index[feature]
        area_proxy = float(initial_area_proxy[reach_index])
        velocity = float(initial_velocity[reach_index])
        if area_proxy <= 0.0 or velocity <= 0.0:
            raise ValueError(f"{system_id}_initial_nwm_hydraulics_nonpositive")
        reach_rows.append(
            {
                "feature_id": feature,
                "effective_length_m": response.effective_length_m,
                "initial_discharge_m3s": response.discharge_m3s,
                "initial_manning_area_m2": response.manning_area_m2,
                "initial_nwm_q_over_velocity_area_proxy_m2": area_proxy,
                "initial_manning_to_nwm_area_proxy_ratio": (
                    response.manning_area_m2 / area_proxy
                ),
                "initial_nwm_velocity_mps": velocity,
                "initial_manning_dq_da_celerity_mps": (
                    response.manning_dq_da_celerity_mps
                ),
                "travel_time_seconds": response.travel_time_seconds,
            }
        )
    path_length = initial_response.total_effective_length_m
    travel_time_seconds = initial_response.total_travel_time_seconds
    area_ratios = np.asarray(
        [row["initial_manning_to_nwm_area_proxy_ratio"] for row in reach_rows]
    )
    action_rows = csv.DictReader(
        io.StringIO(base._read_verified(inputs["action_values"]).decode("utf-8"))
    )
    action_release = np.asarray(
        [float(row["action_release_m3s"]) for row in action_rows], dtype=float
    )
    positive_action = action_release[action_release > 0.0]
    if not positive_action.size:
        raise ValueError(f"{system_id}_positive_action_required")
    uniform_action_travel_hours = np.asarray(
        [
            diagnostic.analyze(
                (float(discharge),) * len(network.feature_ids),
                start_feature_id=network.action_entry_feature_ids[0],
                end_feature_id=network.outlet_feature_id,
                path_id=f"{system_id}:uniform-action-state",
                provenance_id=provenance_id,
                evidence_level="candidate",
                outcome_calibrated=False,
            )
            .total_travel_time_seconds
            / 3600.0
            for discharge in positive_action
        ],
        dtype=float,
    )
    prior = initial_response.travel_time_prior(
        method=(
            "sum_RouteLink_effective_length_over_initial_state_"
            "Manning_dQ_dA_celerity"
        )
    )
    return {
        "route_link_action_entry_to_outlet_feature_ids": list(
            initial_response.feature_ids
        ),
        "route_link_action_entry_to_outlet_reach_count": len(
            initial_response.feature_ids
        ),
        "route_link_action_entry_to_outlet_effective_length_m": path_length,
        "initial_state_path_effective_celerity_mps": (
            path_length / travel_time_seconds
        ),
        "initial_state_manning_celerity_travel_time_hours": (
            travel_time_seconds / 3600.0
        ),
        "initial_state_geometry_closure": {
            "comparison": "Manning_Q_to_A_over_NWM_streamflow_to_velocity_area_proxy",
            "area_ratio_q05_q50_q95": _quantiles(area_ratios),
            "nwm_area_is_ground_truth": False,
            "material_initial_area_mismatch_detected": bool(
                np.quantile(np.abs(area_ratios - 1.0), 0.95) > 0.25
            ),
        },
        "positive_action_uniform_state_diagnostic": {
            "positive_hour_count": int(positive_action.size),
            "zero_hour_count": int((action_release == 0.0).sum()),
            "action_release_m3s_q05_q50_q95": _quantiles(positive_action),
            "travel_time_hours_q05_q50_q95": _quantiles(
                uniform_action_travel_hours
            ),
            "uniform_discharge_along_path": True,
            "outcome_values_used": False,
            "admitted_as_flood_wave_lag": False,
        },
        "travel_time_prior": prior.as_dict(),
        "reaches": reach_rows,
        "path_response_schema": MANNING_PATH_RESPONSE_SCHEMA,
        "public_typed_path_response_diagnostic_used": True,
    }


@contextmanager
def _rollout_context() -> Iterator[None]:
    replacements = {
        "START": START,
        "END": END,
        "HOUR_COUNT": HOUR_COUNT,
        "TIMESTEP_SECONDS": TIMESTEP_SECONDS,
        "TARGET_CELL_LENGTH_M": TARGET_CELL_LENGTH_M,
        "CFL_NUMBER": CFL_NUMBER,
        "np": _TwoUlpNumpyProxy(np),
    }
    original = {name: getattr(base, name) for name in replacements}
    for name, value in replacements.items():
        setattr(base, name, value)
    try:
        yield
    finally:
        for name, value in original.items():
            setattr(base, name, value)


def _rename_two_ulp_invariant(execution: dict[str, Any]) -> None:
    invariants = execution["invariants"]
    invariants["cfl_comparison_limit_two_binary64_ulps"] = invariants.pop(
        "cfl_comparison_limit_one_binary64_ulp"
    )
    execution["registered_execution"]["cfl_reporting_comparison"] = (
        "configured_CFL_plus_two_binary64_ULPs"
    )


def _validate_sources(
    protocol: Mapping[str, Any],
    inputs: Mapping[str, Any],
    outcomes: Mapping[str, Any],
) -> None:
    expected_window = {
        "start_inclusive": _iso(START),
        "end_exclusive": _iso(END),
        "hour_count": HOUR_COUNT,
    }
    actual_window = {
        key: inputs["window"][key] for key in expected_window
    }
    if (
        protocol.get("schema")
        != "gwm.geotransport.v2_blind_validation_protocol.v1"
        or inputs.get("status")
        != "pass_outcome_free_two_system_inputs_acquired"
        or outcomes.get("status") != "two_system_outcomes_acquired_after_joint_seal"
        or actual_window != expected_window
        or set(protocol.get("systems", {})) != set(SYSTEM_IDS)
        or set(inputs.get("systems", {})) != set(SYSTEM_IDS)
        or set(outcomes.get("systems", {})) != set(SYSTEM_IDS)
    ):
        raise ValueError("kinematic_development_attribution_sources_invalid")


def _artifact_from_descriptor(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    body = base._read_verified(descriptor)
    return _artifact(REPO_ROOT / str(descriptor["path"]), body)


def _quantiles(values: np.ndarray) -> list[float]:
    return [float(value) for value in np.quantile(values, (0.05, 0.5, 0.95))]


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    return body, json.loads(body)


def _parse_utc(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("kinematic_development_attribution_timezone_required")
    return result.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    args = parse_args()
    prediction_paths = [OUTPUT_ROOT / f"{value}.csv" for value in SYSTEM_IDS]
    if (
        not args.overwrite
        and (REPORT_PATH.exists() or any(path.exists() for path in prediction_paths))
    ):
        raise ValueError("kinematic_development_attribution_refuses_overwrite")
    predictions, report = compile_attribution()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for system_id, body in predictions.items():
        (OUTPUT_ROOT / f"{system_id}.csv").write_bytes(body)
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(REPORT_PATH)
    for system_id in SYSTEM_IDS:
        system = report["systems"][system_id]
        phase_hours = (
            system["phase_alignment"]["kinematic_prediction_to_observation"]
            ["best_rmse"]["candidate_time_shift_seconds"]
            / 3600.0
        )
        travel_hours = system["physical_path_diagnostic"][
            "initial_state_manning_celerity_travel_time_hours"
        ]
        print(
            f"{system_id}_kinematic_phase_hours={phase_hours}"
        )
        print(
            f"{system_id}_initial_manning_travel_time_hours={travel_hours}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
