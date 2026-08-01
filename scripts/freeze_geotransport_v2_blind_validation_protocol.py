#!/usr/bin/env python3
"""Freeze a two-system blind validation before dynamic value access."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlencode

from data_agent.uwm.geospatial_kernel_v2 import load_nwm_zarr_schema, nwm_chunk_url


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
    "geotransport_v2_blind_validation_protocol.json"
)
SCHEMA = "gwm.geotransport.v2_blind_validation_protocol.v1"
INITIAL_STATE_AT = datetime(2022, 3, 31, 0, tzinfo=timezone.utc)
START = datetime(2022, 3, 31, 1, tzinfo=timezone.utc)
END = datetime(2022, 4, 28, 1, tzinfo=timezone.utc)
HOUR_COUNT = 672
INITIAL_TIME_CHUNK = 562
ROLLOUT_TIME_CHUNK = 563
TIMESTEP_SECONDS = 3600
SUBSTEP_SECONDS = 300
CORE_CODE_PATHS = (
    "data_agent/uwm/geospatial_kernel_v2/branching_network.py",
    "data_agent/uwm/geospatial_kernel_v2/contracts.py",
    "scripts/compile_geotransport_center_hill_v2_d5_full_subnetwork.py",
    "scripts/compile_geotransport_j_percy_priest_v1_full_subnetwork.py",
)
FORBIDDEN_PREEXISTING_PATHS = (
    "data/geotransport_v0_1/geotransport_v2_blind_validation/outcomes",
    "benchmarks/geotransport_v0_1/geotransport_v2_blind_validation_score.json",
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
            raise ValueError(f"blind_validation_outcome_already_exists:{relative}")
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
    center_support_fraction = _center_terminal_fraction(center_support)
    jpp_network = _read_verified(jpp["artifacts"]["full_subnetwork"])
    jpp_terminal_fraction = _terminal_length_fraction(
        json.loads(jpp_network)["network"]
    )
    systems = {
        "center_hill": _system_lock(
            topology=center,
            topology_path=center_topology_path,
            topology_body=center_body,
            action_series="CETT1-CENTER_HILL.Flow.Ave.1Hour.1Hour.man-rev",
            action_feature_id=18_434_265,
            outcome_site_id="03424860",
            terminal_support_fraction=center_support_fraction,
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
            terminal_support_fraction=jpp_terminal_fraction,
            terminal_support_method=(
                "outcome_free_uniform_lateral_inflow_per_linear_reach_length"
            ),
            feature_chunks=(63,),
        ),
    }
    return {
        "schema": SCHEMA,
        "status": "frozen_before_dynamic_input_and_outcome_access",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "scientific_role": (
            "first outcome-inaccessible temporal replication of the D5 kernel "
            "on Center Hill and an independent second river system"
        ),
        "development_boundary": {
            "d3_window": "public_structural_development_and_falsification_only",
            "d3_outcomes_may_not_select_or_modify_this_protocol": True,
            "d5_configuration_origin": "sealed_before_D3_posthoc_scoring",
            "no_parameter_or_topology_change_from_d3_score": True,
        },
        "window": {
            "initial_state_valid_at": _iso(INITIAL_STATE_AT),
            "start_inclusive": _iso(START),
            "end_exclusive": _iso(END),
            "hour_count": HOUR_COUNT,
            "time_step": "PT1H",
            "warmup_hours": 0,
            "state_lead_time_to_window_seconds": 3600,
            "initial_state_time_chunk_index": INITIAL_TIME_CHUNK,
            "forcing_time_chunk_index": ROLLOUT_TIME_CHUNK,
        },
        "systems": systems,
        "shared_operator_lock": {
            "operator": "BranchingManningNetworkTransportOperator",
            "schema": "gwm.geospatial_kernel.branching_manning_network_storage.v1",
            "network_mode": "complete_incremental_tributary_DAG",
            "timestep_seconds": TIMESTEP_SECONDS,
            "integration_substep_seconds": SUBSTEP_SECONDS,
            "action_boundary": "one_predeclared_entry_reach",
            "initial_state": (
                "NWM_v3_retrospective_streamflow_times_velocity_times_"
                "trapezoid_cross_section_area_times_effective_reach_length"
            ),
            "initial_state_modeled": True,
            "initial_state_ground_truth": False,
            "initial_state_possible_nudging": True,
            "forcing": "NWM_v3_retrospective_q_lateral_per_reach",
            "forcing_modeled": True,
            "forcing_ground_truth": False,
            "route_parameters": "official_NWM_v3_RouteLink_without_substitution",
            "modeled_tributary_boundary_forbidden": True,
            "parameter_fitting": False,
            "velocity_or_flow_scaling": False,
            "topology_revision": False,
        },
        "negative_control_lock": {
            "branch_silent": (
                "set all off-mainstem initial stocks and q_lateral to zero; "
                "retain mainstem state, mainstem q_lateral, and action"
            ),
            "zero_identity": "zero stock plus zero action plus zero forcing",
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
            "baseline_definitions_changeable_after_outcome_access": False,
        },
        "scoring_lock": {
            "primary_metric": "rmse_m3s",
            "secondary_metrics": ["mae_m3s", "bias_m3s", "nse"],
            "minimum_scored_hours_per_system": 600,
            "common_complete_case_mask_per_system": True,
            "missing_outcome_policy": "omit_without_imputation",
            "per_system_accuracy_gate": (
                "kernel_RMSE_strictly_below_observed_persistence_RMSE"
            ),
            "per_system_mass_gate": "every_step_within_numeric_tolerance",
            "multi_system_validation_gate": (
                "both systems pass accuracy and mass gates without compensation"
            ),
            "score_once": True,
        },
        "outcome_isolation_lock": {
            "input_acquisition_may_access_outcomes": False,
            "rollout_executor_accepts_outcome_paths": False,
            "both_predictions_must_be_sealed_before_any_outcome_request": True,
            "outcome_source": "USGS Water Services IV parameter 00060",
            "outcome_request_margin": (
                "one hour before start through one hour after end for support and "
                "persistence alignment"
            ),
        },
        "frozen_code": {
            path: _artifact(REPO_ROOT / path) for path in CORE_CODE_PATHS
        },
        "fixed_evidence": {
            "center_hill_topology": _artifact(
                center_topology_path, center_body
            ),
            "j_percy_priest_topology": _artifact(jpp_topology_path, jpp_body),
            "center_hill_terminal_support": _artifact(
                center_support_path, center_support_body
            ),
            "nwm_time_schema": _artifact(
                metadata_root / "nwm-time-zarray.json",
                (metadata_root / "nwm-time-zarray.json").read_bytes(),
            ),
            "nwm_time_attributes": _artifact(
                metadata_root / "nwm-time-zattrs.json",
                (metadata_root / "nwm-time-zattrs.json").read_bytes(),
            ),
        },
        "forbidden_after_freeze": [
            "change_window_or_systems",
            "change_topology_or_linear_reference",
            "change_route_parameters",
            "change_terminal_forcing_support",
            "fit_action_forcing_state_or_prediction_scalars",
            "select_lag_smoothing_or_initial_state_from_outcomes",
            "change_baseline_metric_mask_or_gate",
            "inspect_one_system_outcome_before_both_predictions_are_sealed",
            "rerun_predictions_after_any_outcome_access",
        ],
        "data_isolation_at_freeze": {
            "initial_state_chunk_562_loaded_for_this_protocol": False,
            "forcing_chunk_563_loaded_for_this_protocol": False,
            "center_hill_action_values_loaded_for_this_window": False,
            "j_percy_priest_action_values_loaded_for_this_window": False,
            "center_hill_outcome_values_loaded_for_this_window": False,
            "j_percy_priest_outcome_values_loaded_for_this_window": False,
            "outcome_artifacts_present": False,
        },
        "claim_boundary_before_execution": {
            "two_system_topology_and_parameters_compiled": True,
            "protocol_frozen": True,
            "dynamic_inputs_acquired": False,
            "outcome_free_predictions_sealed": False,
            "outcomes_acquired": False,
            "scored": False,
            "predictive_validation_complete": False,
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
    action_query = urlencode(
        {
            "name": action_series,
            "office": "LRN",
            "begin": _iso(START),
            "end": _iso(END),
            "unit": "cms",
            "page-size": "50000",
        }
    )
    raw = topology["domain"]
    return {
        "system_id": system_id,
        "topology_report": _artifact(topology_path, topology_body),
        "feature_count": int(raw["feature_count"]),
        "mainstem_feature_count": int(raw["active_mainstem_feature_count"]),
        "branch_feature_count": int(raw["incremental_branch_feature_count"]),
        "action_entry_feature_id": action_feature_id,
        "outlet_feature_id": int(raw["outlet_feature_id"]),
        "feature_chunk_indices": list(feature_chunks),
        "initial_state_objects": [
            nwm_chunk_url(variable, f"{INITIAL_TIME_CHUNK}.{chunk}")
            for variable in ("streamflow", "velocity")
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
            "url": f"https://cwms-data.usace.army.mil/cwms-data/timeseries?{action_query}",
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
        chunk_hours != 672
        or origin + timedelta(hours=INITIAL_TIME_CHUNK * chunk_hours)
        != datetime(2022, 3, 3, 1, tzinfo=timezone.utc)
        or origin + timedelta(hours=ROLLOUT_TIME_CHUNK * chunk_hours) != START
        or START + timedelta(hours=HOUR_COUNT) != END
    ):
        raise ValueError("blind_validation_nwm_time_contract_mismatch")


def _validate_topology_report(
    payload: Mapping[str, Any], *, expected_schema: str, expected_system: str
) -> None:
    domain = payload.get("domain") or {}
    gates = payload.get("gates") or {}
    if (
        payload.get("schema") != expected_schema
        or payload.get("status") != "pass_full_incremental_subnetwork_compiled"
        or not domain.get("feature_count")
        or gates.get("all_upstream_ancestors_compiled") is not True
        or gates.get("route_link_parameter_coverage_complete") is not True
        or gates.get("nwm_retrospective_feature_coverage_complete") is not True
        or (payload.get("data_isolation") or {}).get(
            "outcome_artifacts_read",
            (payload.get("data_isolation") or {}).get("d3_outcome_artifacts_read"),
        )
        is not False
    ):
        raise ValueError(f"blind_validation_{expected_system}_topology_invalid")


def _center_terminal_fraction(payload: Mapping[str, Any]) -> float:
    fractions = payload.get("coverage_fractions") or []
    feature_ids = payload.get("feature_ids") or []
    uncertainty = payload.get("coverage_uncertainty") or {}
    if (
        payload.get("schema")
        != "gwm.geospatial_kernel.reach_forcing_spatial_support.v1"
        or payload.get("admitted_as_spatial_support") is not True
        or len(fractions) != len(feature_ids)
        or not fractions
        or int(feature_ids[-1]) != 18_421_703
    ):
        raise ValueError("blind_validation_center_support_contract_invalid")
    value = float(fractions[-1])
    if value != float(uncertainty.get("central_fraction")):
        raise ValueError("blind_validation_center_support_central_mismatch")
    if not 0.0 < value <= 1.0:
        raise ValueError("blind_validation_center_support_fraction_invalid")
    return value


def _terminal_length_fraction(network: Mapping[str, Any]) -> float:
    outlet = int(network["outlet_feature_id"])
    index = tuple(int(value) for value in network["feature_ids"]).index(outlet)
    full = float(network["full_lengths_m"][index])
    effective = float(network["effective_lengths_m"][index])
    value = effective / full
    if not 0.0 < value <= 1.0:
        raise ValueError("blind_validation_terminal_length_fraction_invalid")
    return value


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = REPO_ROOT / str(descriptor["path"])
    body = path.read_bytes()
    if (
        len(body) != int(descriptor["size_bytes"])
        or hashlib.sha256(body).hexdigest() != descriptor["sha256"]
    ):
        raise ValueError("blind_validation_fixed_artifact_identity_mismatch")
    return body


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    return body, json.loads(body)


def _artifact(path: Path, body: bytes | None = None) -> dict[str, Any]:
    resolved = path.resolve()
    value = resolved.read_bytes() if body is None else body
    try:
        display = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise ValueError("blind_validation_artifact_outside_repository") from exc
    return {
        "path": display,
        "sha256": hashlib.sha256(value).hexdigest(),
        "size_bytes": len(value),
    }


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise ValueError("blind_validation_protocol_already_frozen")
    payload = compile_protocol(
        metadata_root=args.metadata_root,
        center_topology_path=args.center_topology,
        jpp_topology_path=args.jpp_topology,
        center_support_path=args.center_support,
    )
    _write_json(args.output, payload)
    print(args.output)
    print(f"protocol_sha256={hashlib.sha256(args.output.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
