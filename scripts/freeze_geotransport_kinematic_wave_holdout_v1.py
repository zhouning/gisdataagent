#!/usr/bin/env python3
"""Freeze a two-system kinematic-wave holdout before dynamic value access."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlencode

from data_agent.uwm.geospatial_kernel_v2 import load_nwm_zarr_schema, nwm_chunk_url

if __package__:
    from scripts.freeze_geotransport_v2_blind_validation_protocol import (
        _center_terminal_fraction,
        _load_json,
        _read_verified,
        _terminal_length_fraction,
        _validate_topology_report,
    )
else:
    from freeze_geotransport_v2_blind_validation_protocol import (
        _center_terminal_fraction,
        _load_json,
        _read_verified,
        _terminal_length_fraction,
        _validate_topology_report,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METADATA_ROOT = REPO_ROOT / "data/geotransport_v0_1/metadata"
DEFAULT_CENTER_TOPOLOGY = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_v2_d5_full_subnetwork_report.json"
)
DEFAULT_JPP_TOPOLOGY = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "j_percy_priest_v1_full_subnetwork_report.json"
)
DEFAULT_CENTER_SUPPORT = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_terminal_forcing_support_nhdplus_v21/"
    "forcing_support.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "kinematic_wave_holdout_v1_protocol.json"
)
SCHEMA = "gwm.geotransport.kinematic_wave_holdout_protocol.v1"
INITIAL_STATE_AT = datetime(2022, 10, 13, 0, tzinfo=timezone.utc)
START = datetime(2022, 10, 13, 1, tzinfo=timezone.utc)
END = datetime(2022, 11, 10, 1, tzinfo=timezone.utc)
HOUR_COUNT = 672
INITIAL_TIME_CHUNK = 569
ROLLOUT_TIME_CHUNK = 570
TIMESTEP_SECONDS = 3600.0
TARGET_CELL_LENGTH_M = 1000.0
CFL_NUMBER = 0.8
SYSTEM_IDS = ("center_hill", "j_percy_priest")
CORE_CODE_PATHS = (
    "data_agent/uwm/geospatial_kernel_v2/__init__.py",
    "data_agent/uwm/geospatial_kernel_v2/contracts.py",
    "data_agent/uwm/geospatial_kernel_v2/branching_network.py",
    "data_agent/uwm/geospatial_kernel_v2/kinematic_wave.py",
    "data_agent/uwm/geospatial_kernel_v2/branching_kinematic_wave.py",
    "data_agent/uwm/geospatial_kernel_v2/nwm_q_lateral.py",
    "data_agent/uwm/geospatial_kernel_v2/public_data.py",
    "scripts/acquire_geotransport_center_hill_v2_d3_inputs.py",
    "scripts/acquire_geotransport_center_hill_v2_d5_subnetwork_inputs.py",
    "scripts/build_geotransport_center_hill_smoke_panel.py",
    "scripts/run_geotransport_center_hill_v2_d5_full_subnetwork_outcome_free.py",
    "scripts/acquire_geotransport_v2_blind_validation_outcomes.py",
    "scripts/acquire_geotransport_kinematic_wave_holdout_v1_inputs.py",
    "scripts/run_geotransport_kinematic_wave_holdout_v1_outcome_free.py",
    "scripts/acquire_geotransport_kinematic_wave_holdout_v1_outcomes.py",
    "scripts/score_geotransport_kinematic_wave_holdout_v1.py",
)
FORBIDDEN_PREEXISTING_PATHS = (
    "data/geotransport_v0_1/kinematic_wave_holdout_v1/outcomes",
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v1_score.json",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata-root", type=Path, default=DEFAULT_METADATA_ROOT)
    parser.add_argument(
        "--center-topology", type=Path, default=DEFAULT_CENTER_TOPOLOGY
    )
    parser.add_argument("--jpp-topology", type=Path, default=DEFAULT_JPP_TOPOLOGY)
    parser.add_argument(
        "--center-support", type=Path, default=DEFAULT_CENTER_SUPPORT
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_protocol(
    *,
    metadata_root: Path = DEFAULT_METADATA_ROOT,
    center_topology_path: Path = DEFAULT_CENTER_TOPOLOGY,
    jpp_topology_path: Path = DEFAULT_JPP_TOPOLOGY,
    center_support_path: Path = DEFAULT_CENTER_SUPPORT,
) -> dict[str, Any]:
    for relative in FORBIDDEN_PREEXISTING_PATHS:
        if (REPO_ROOT / relative).exists():
            raise ValueError(f"kinematic_holdout_outcome_already_exists:{relative}")
    schema = load_nwm_zarr_schema(metadata_root)
    _validate_time_contract(schema)
    center_body, center = _load_json(center_topology_path)
    jpp_body, jpp = _load_json(jpp_topology_path)
    center_support_body, center_support = _load_json(center_support_path)
    _validate_topology_report(
        center,
        expected_schema="gwm.geotransport.center_hill_v2_d5_full_subnetwork.v1",
        expected_system="center_hill",
    )
    _validate_topology_report(
        jpp,
        expected_schema="gwm.geotransport.j_percy_priest_v1_full_subnetwork.v1",
        expected_system="j_percy_priest",
    )
    jpp_network = json.loads(_read_verified(jpp["artifacts"]["full_subnetwork"]))[
        "network"
    ]
    systems = {
        "center_hill": _system_lock(
            topology=center,
            topology_path=center_topology_path,
            topology_body=center_body,
            action_series="CETT1-CENTER_HILL.Flow.Ave.1Hour.1Hour.man-rev",
            action_feature_id=18_434_265,
            outcome_site_id="03424860",
            terminal_support_fraction=_center_terminal_fraction(center_support),
            terminal_support_method=(
                "preexisting_D2_NHDPlus_v2.1_flow_accumulation_spatial_support"
            ),
            feature_chunks=(63, 87),
        ),
        "j_percy_priest": _system_lock(
            topology=jpp,
            topology_path=jpp_topology_path,
            topology_body=jpp_body,
            action_series="JPPT1-J_PERCY_PRIEST.Flow.Ave.1Hour.1Hour.man-rev",
            action_feature_id=18_401_881,
            outcome_site_id="03430200",
            terminal_support_fraction=_terminal_length_fraction(jpp_network),
            terminal_support_method=(
                "outcome_free_uniform_lateral_inflow_per_linear_reach_length"
            ),
            feature_chunks=(63,),
        ),
    }
    code = {path: _artifact(REPO_ROOT / path) for path in CORE_CODE_PATHS}
    return {
        "schema": SCHEMA,
        "status": "frozen_before_dynamic_input_and_outcome_access",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "scientific_role": (
            "first outcome-inaccessible two-system public holdout of the "
            "project-owned branching finite-volume kinematic-wave operator"
        ),
        "window": {
            "initial_state_valid_at": _iso(INITIAL_STATE_AT),
            "start_inclusive": _iso(START),
            "end_exclusive": _iso(END),
            "hour_count": HOUR_COUNT,
            "time_step": "PT1H",
            "initial_state_time_chunk_index": INITIAL_TIME_CHUNK,
            "forcing_time_chunk_index": ROLLOUT_TIME_CHUNK,
        },
        "systems": systems,
        "operator_lock": {
            "operator": "BranchingFiniteVolumeKinematicWaveOperator",
            "schema": (
                "gwm.geospatial_kernel.branching_finite_volume_kinematic_wave.v1"
            ),
            "equation": "dA/dt + dQ(A)/dx = q_lateral",
            "network_mode": "complete_incremental_tributary_DAG",
            "timestep_seconds": TIMESTEP_SECONDS,
            "target_cell_length_m": TARGET_CELL_LENGTH_M,
            "cfl_number": CFL_NUMBER,
            "flux": "simultaneous_downstream_upwind_Manning_discharge",
            "state": "per_cell_physical_water_volume_m3",
            "action_boundary": "one_predeclared_entry_reach_per_system",
            "initial_state": (
                "NWM_v3_retrospective_streamflow_transformed_by_operator_"
                "Manning_Q_to_A_without_velocity_scaling"
            ),
            "initial_state_modeled": True,
            "initial_state_ground_truth": False,
            "initial_state_possible_nudging": True,
            "forcing": "NWM_v3_retrospective_q_lateral_per_reach",
            "forcing_modeled": True,
            "forcing_ground_truth": False,
            "route_parameters": "official_NWM_v3_RouteLink_without_substitution",
            "parameter_fitting": False,
            "closure_or_learned_correction": False,
            "operator_form_admitted_before_holdout": False,
            "diagnostic_only_during_holdout": True,
        },
        "negative_control_lock": {
            "branch_silent": (
                "zero all off-mainstem initial discharge and q_lateral; retain "
                "mainstem initial discharge, mainstem q_lateral, and action"
            ),
            "zero_identity": "zero cell volume plus zero action plus zero forcing",
            "outcome_used": False,
        },
        "baseline_lock": {
            "primary": "one_hour_observed_streamflow_persistence",
            "persistence_definition": (
                "prediction for support end t equals the immediately previous "
                "complete hourly observation"
            ),
            "diagnostic": "same_hour_boundary_action_release",
            "baseline_parameters_fitted": False,
            "changeable_after_outcome_access": False,
        },
        "scoring_lock": {
            "primary_metric": "rmse_m3s",
            "secondary_metrics": ["mae_m3s", "bias_m3s", "nse"],
            "minimum_scored_hours_per_system": 600,
            "common_complete_case_mask_per_system": True,
            "missing_outcome_policy": "omit_without_imputation",
            "native_cadence_rule": (
                "mean of every complete approved native sample on (t-1h,t]"
            ),
            "allowed_native_cadence_seconds": [300, 600, 900, 1200, 1800, 3600],
            "per_system_accuracy_gate": (
                "kinematic_wave_RMSE_strictly_below_observed_persistence_RMSE"
            ),
            "per_system_execution_gates": [
                "every_step_mass_residual_within_numeric_tolerance",
                "every_step_CFL_at_or_below_0.8_plus_one_binary64_ULP",
                "all_cell_volumes_nonnegative_finite",
                "zero_state_zero_input_identity",
            ],
            "multi_system_gate": "both_systems_pass_without_compensation",
            "score_once": True,
        },
        "outcome_isolation_lock": {
            "input_acquisition_may_access_outcomes": False,
            "rollout_executor_accepts_outcome_paths": False,
            "both_predictions_must_be_sealed_before_any_outcome_request": True,
            "outcome_source": "USGS Water Services IV parameter 00060",
            "outcome_request_margin": (
                "one hour before start through one hour after end"
            ),
        },
        "frozen_code": code,
        "fixed_evidence": {
            "center_hill_topology": _artifact(center_topology_path, center_body),
            "j_percy_priest_topology": _artifact(jpp_topology_path, jpp_body),
            "center_hill_terminal_support": _artifact(
                center_support_path, center_support_body
            ),
            "nwm_time_schema": _artifact(
                metadata_root / "nwm-time-zarray.json"
            ),
            "nwm_time_attributes": _artifact(
                metadata_root / "nwm-time-zattrs.json"
            ),
        },
        "forbidden_after_freeze": [
            "change_window_systems_topology_geometry_or_spatial_support",
            "change_cell_length_CFL_initialization_flux_or_forcing_semantics",
            "fit_any_parameter_state_scaling_lag_closure_or_correction",
            "change_metrics_baselines_masks_or_gates",
            "inspect_either_outcome_before_both_predictions_are_sealed",
            "rerun_predictions_after_any_outcome_access",
        ],
        "data_isolation_at_freeze": {
            "initial_state_chunk_569_loaded_for_this_protocol": False,
            "forcing_chunk_570_loaded_for_this_protocol": False,
            "action_values_loaded_for_this_window": False,
            "outcome_values_loaded_for_this_window": False,
            "outcome_artifacts_present": False,
        },
        "claim_boundary_before_execution": {
            "branching_kinematic_operator_implemented": True,
            "two_system_topology_and_parameters_compiled": True,
            "protocol_frozen": True,
            "dynamic_inputs_acquired": False,
            "outcome_free_predictions_sealed": False,
            "outcomes_acquired": False,
            "scored": False,
            "operator_form_admitted": False,
            "geospatial_kernel_validated": False,
        },
    }


def _system_lock(
    *,
    topology: Mapping[str, Any],
    topology_path: Path,
    topology_body: bytes,
    action_series: str,
    action_feature_id: int,
    outcome_site_id: str,
    terminal_support_fraction: float,
    terminal_support_method: str,
    feature_chunks: tuple[int, ...],
) -> dict[str, Any]:
    system_id = "center_hill" if outcome_site_id == "03424860" else "j_percy_priest"
    query = urlencode(
        {
            "name": action_series,
            "office": "LRN",
            "begin": _iso(START),
            "end": _iso(END),
            "unit": "cms",
            "page-size": "50000",
        }
    )
    domain = topology["domain"]
    return {
        "system_id": system_id,
        "topology_report": _artifact(topology_path, topology_body),
        "feature_count": int(domain["feature_count"]),
        "mainstem_feature_count": int(domain["active_mainstem_feature_count"]),
        "branch_feature_count": int(domain["incremental_branch_feature_count"]),
        "action_entry_feature_id": action_feature_id,
        "outlet_feature_id": int(domain["outlet_feature_id"]),
        "feature_chunk_indices": list(feature_chunks),
        "initial_state_objects": [
            nwm_chunk_url("streamflow", f"{INITIAL_TIME_CHUNK}.{chunk}")
            for chunk in feature_chunks
        ],
        "forcing_objects": [
            nwm_chunk_url("q_lateral", f"{ROLLOUT_TIME_CHUNK}.{chunk}")
            for chunk in feature_chunks
        ],
        "time_objects": [
            nwm_chunk_url("time", str(INITIAL_TIME_CHUNK)),
            nwm_chunk_url("time", str(ROLLOUT_TIME_CHUNK)),
        ],
        "action": {
            "source": "USACE CWMS Data API",
            "timeseries": action_series,
            "office": "LRN",
            "unit": "cms",
            "support_kind": "interval_mean",
            "timestamp_position": "end",
            "variable_role": "boundary_action",
            "url": f"https://cwms-data.usace.army.mil/cwms-data/timeseries?{query}",
        },
        "outcome": {
            "source": "USGS Water Services IV",
            "site_id": outcome_site_id,
            "parameter_code": "00060",
            "variable_role": "independent_observation",
            "request_start": _iso(START - timedelta(hours=1)),
            "request_end": _iso(END + timedelta(hours=1)),
            "access_phase": "after_both_predictions_are_sealed",
        },
        "forcing_support": {
            "complete_reach_fraction": 1.0,
            "partial_terminal_reach_fraction": terminal_support_fraction,
            "partial_terminal_reach_method": terminal_support_method,
            "outcome_calibrated": False,
        },
    }


def _validate_time_contract(schema: Any) -> None:
    origin = schema.time_origin
    chunk_hours = schema.time_chunk_size
    if (
        chunk_hours != HOUR_COUNT
        or origin + timedelta(hours=INITIAL_TIME_CHUNK * chunk_hours)
        != datetime(2022, 9, 15, 1, tzinfo=timezone.utc)
        or origin + timedelta(hours=ROLLOUT_TIME_CHUNK * chunk_hours) != START
        or START + timedelta(hours=HOUR_COUNT) != END
        or origin
        + timedelta(hours=(INITIAL_TIME_CHUNK + 1) * chunk_hours - 1)
        != INITIAL_STATE_AT
    ):
        raise ValueError("kinematic_holdout_nwm_time_contract_mismatch")


def _artifact(path: Path, body: bytes | None = None) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        display = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise ValueError("kinematic_holdout_artifact_outside_repository") from exc
    payload = resolved.read_bytes() if body is None else body
    return {
        "path": display,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
    }


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise ValueError("kinematic_holdout_protocol_refuses_overwrite")
    payload = compile_protocol(
        metadata_root=args.metadata_root,
        center_topology_path=args.center_topology,
        jpp_topology_path=args.jpp_topology,
        center_support_path=args.center_support,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(hashlib.sha256(args.output.read_bytes()).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
