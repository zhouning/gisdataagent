#!/usr/bin/env python3
"""Freeze Center Hill v2 D3 before loading chunk 561 or holdout outcomes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_v2_d3_protocol.json"
)
SCHEMA = "gwm.geotransport.center_hill_v2_d3_protocol.v1"
FROZEN_AT = "2026-07-27T03:26:28Z"
CODE_PATHS = (
    "data_agent/uwm/geospatial_kernel_v2/nonlinear_reach_transport.py",
    "data_agent/uwm/geospatial_kernel_v2/troute_muskingum_cunge.py",
    "data_agent/uwm/geospatial_kernel_v2/holdout_rollout.py",
    "data_agent/uwm/geospatial_kernel_v2/holdout_scoring.py",
    "scripts/acquire_geotransport_center_hill_v2_d3_inputs.py",
    "scripts/run_geotransport_center_hill_v2_outcome_free.py",
    "scripts/score_geotransport_center_hill_v2_holdout.py",
)
SOURCE_PATHS = {
    "initial_state_manifest": (
        "data/geotransport_v0_1/center_hill_initial_state_nwm_v3/"
        "acquisition_manifest.json"
    ),
    "forcing_support": (
        "data/geotransport_v0_1/center_hill_terminal_forcing_support_nhdplus_v21/"
        "forcing_support.json"
    ),
    "forcing_support_report": (
        "benchmarks/geotransport_v0_1/center_hill_terminal_forcing_support_report.json"
    ),
    "route_link_manifest": (
        "data/geotransport_v0_1/route_link_nwm_v3_center_hill/"
        "acquisition_manifest.json"
    ),
    "route_link_subset": (
        "data/geotransport_v0_1/route_link_nwm_v3_center_hill/"
        "RouteLink_CONUS_NWMv3_CenterHill.nc"
    ),
    "linear_referenced_path": (
        "benchmarks/geotransport_v0_1/center_hill_travel_time_prior_report.json"
    ),
    "t_route_build_manifest": (
        "data/geotransport_v0_1/t_route_mc_runtime/build_manifest.json"
    ),
    "t_route_shared_library": (
        "data/geotransport_v0_1/t_route_mc_runtime/"
        "libtroute_mc_12a8eae.so"
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_protocol() -> dict[str, Any]:
    code = {name: _artifact(REPO_ROOT / name) for name in CODE_PATHS}
    sources = {
        name: _artifact(REPO_ROOT / path) for name, path in SOURCE_PATHS.items()
    }
    return {
        "schema": SCHEMA,
        "status": "frozen_before_d3_value_access",
        "frozen_at": FROZEN_AT,
        "system": {
            "system_id": "center_hill",
            "action_node": "USACE-CWMS:CETT1-CENTER_HILL",
            "outcome_node": "USGS-03424860",
            "terminal_feature_id": 18421703,
            "active_feature_count": 26,
        },
        "window": {
            "initial_state_valid_at": "2022-02-03T00:00:00Z",
            "start_inclusive": "2022-02-03T01:00:00Z",
            "end_exclusive": "2022-03-03T01:00:00Z",
            "time_step": "PT1H",
            "hour_count": 672,
            "warmup_hours": 0,
            "state_lead_time_to_window_seconds": 3600,
        },
        "fixed_sources": sources,
        "frozen_code": code,
        "input_acquisition": {
            "action": {
                "source": "USACE CWMS Data API",
                "variable_role": "boundary_action",
                "timeseries": "CETT1-CENTER_HILL.Flow.Ave.1Hour.1Hour.man-rev",
                "office": "LRN",
                "unit": "cms",
                "timestamp_position": "end",
                "support_kind": "interval_mean",
                "url": (
                    "https://cwms-data.usace.army.mil/cwms-data/timeseries?"
                    "name=CETT1-CENTER_HILL.Flow.Ave.1Hour.1Hour.man-rev&"
                    "office=LRN&begin=2022-02-03T01%3A00%3A00Z&"
                    "end=2022-03-03T01%3A00%3A00Z&unit=cms&page-size=50000"
                ),
                "normalized_manifest_schema": (
                    "gwm.geotransport.center_hill_v2_action_input.v1"
                ),
                "outcome_included": False,
            },
            "modeled_forcing": {
                "source": "NOAA NWM retrospective v3.0 Zarr",
                "variable_role": "modeled_forcing",
                "ground_truth": False,
                "variable": "q_lateral",
                "time_chunk_indices": [561],
                "feature_chunk_indices": [63],
                "object_key": "q_lateral/561.63",
                "url": (
                    "https://noaa-nwm-retrospective-3-0-pds.s3.amazonaws.com/"
                    "CONUS/zarr/chrtout.zarr/q_lateral/561.63"
                ),
                "normalized_manifest_schema": (
                    "gwm.geotransport.center_hill_v2_nwm_input.v1"
                ),
            },
            "outcome": {
                "source": "USGS Water Services IV",
                "variable_role": "independent_observation",
                "site_id": "03424860",
                "parameter_code": "00060",
                "unit_conversion": "ft3 s-1 multiplied by 0.028316846592",
                "support_kind": "interval_sample_mean",
                "request_start": "2022-02-03T00:00:00Z",
                "request_end": "2022-03-03T02:00:00Z",
                "normalized_manifest_schema": (
                    "gwm.geotransport.center_hill_v2_outcome_input.v1"
                ),
                "access_phase": "only_after_protocol_and_predictions_are_sealed",
            },
        },
        "scenarios": {
            "preselected_candidate": "nonlinear_central",
            "support_uncertainty_report_only": [
                "nonlinear_support_lower",
                "nonlinear_support_upper",
            ],
            "causal_ablations": [
                "zero_action",
                "no_forcing",
                "state_only",
                "reversed_topology",
            ],
            "domain_baseline": "t_route_mc",
            "diagnostic_baseline": "direct_release",
            "outcome_only_baseline": "persistence",
        },
        "operator_configuration": {
            "nonlinear_timestep_seconds": 3600,
            "nonlinear_integration_substep_seconds": 300,
            "t_route_commit": "12a8eae0cdfed437143c590659fa7077605a5e70",
            "t_route_entrypoint": "c_muskingcungenwm",
            "t_route_substep_seconds": 300,
            "t_route_substeps_per_hour": 12,
            "t_route_hourly_prediction": (
                "arithmetic mean of 12 end-of-substep discharge values"
            ),
            "t_route_hourly_action": (
                "piecewise constant interval mean; previous=current at every substep"
            ),
            "t_route_hourly_q_lateral": "piecewise constant reach inflow rate",
            "t_route_segment_lengths": (
                "NLDI effective path lengths; all other parameters from official "
                "NWM v3 RouteLink"
            ),
            "terminal_forcing_central_fraction": 0.8429738154993436,
            "terminal_forcing_lower_fraction": 0.8272045786997515,
            "terminal_forcing_upper_fraction": 0.9366451910995578,
        },
        "scoring": {
            "primary_metric": "rmse_m3s",
            "secondary_metrics": ["mae_m3s", "bias_m3s", "nse"],
            "minimum_scored_hours": 600,
            "missing_outcome_policy": "omit_without_imputation",
            "persistence_after_missing_outcome": (
                "next hour is unscored because the previous observation is unavailable"
            ),
            "strict_comparison": True,
            "no_parameter_fitting": True,
            "no_scenario_selection_after_outcome_access": True,
        },
        "gates": {
            "central_beats_persistence_rmse": True,
            "central_beats_t_route_mc_rmse": True,
            "state_only_is_worse_rmse": True,
            "zero_action_degrades_rmse": True,
            "no_forcing_degrades_rmse": True,
            "reversed_topology_degrades_rmse": True,
            "all_nonlinear_scenarios_conserve_mass": True,
            "all_registered_gates_passed": True,
        },
        "data_isolation_at_freeze": {
            "compile_protocol_reads_d0_d1_d2_only": True,
            "chunk_561_loaded": False,
            "q_lateral_561_63_values_loaded": False,
            "d3_action_values_loaded": False,
            "d3_outcome_values_loaded": False,
            "old_v1_prediction_or_score_loaded": False,
        },
        "claim_boundary_before_execution": {
            "d0_geometry_parameters_passed": True,
            "d1_retrospective_modeled_initial_state_passed": True,
            "d2_action_forcing_spatial_support_passed": True,
            "d3_protocol_frozen": True,
            "d3_inputs_acquired": False,
            "d3_predictions_executed": False,
            "d3_scored": False,
            "single_system_validated": False,
            "multi_system_geospatial_kernel_validated": False,
        },
    }


def _artifact(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        display = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise ValueError("center_hill_v2_protocol_artifact_outside_repository") from exc
    body = resolved.read_bytes()
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main() -> int:
    args = parse_args()
    payload = compile_protocol()
    _write_json(args.output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
