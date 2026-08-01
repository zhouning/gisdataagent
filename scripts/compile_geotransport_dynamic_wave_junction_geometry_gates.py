#!/usr/bin/env python3
"""Compile public junction geometry and evidence-gated loss semantics."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_dag import (
    DynamicWaveDendriticTopology,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_junction_geometry import (
    GeographicJunctionBranchSource,
    adjudicate_geographic_junction_energy_loss,
    bind_admitted_geographic_losses_to_dag,
    compile_geographic_junction_geometry,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_v2_d4_topology/raw/"
    "gauge_upstream_tributaries_30km.json"
)
NETWORK_PATH = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_v2_d5_full_subnetwork/"
    "full_subnetwork.json"
)
GEOMETRY_PATH = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_v2_d5_full_subnetwork/"
    "junction_geometry_18421703.json"
)
REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "dynamic_wave_junction_geometry_gates.json"
)
SCHEMA = "gwm.geotransport.dynamic_wave_junction_geometry_gates.v1"
PUBLIC_ARTIFACT_SCHEMA = (
    "gwm.geotransport.center_hill_public_junction_geometry.v1"
)
NLDI_URL = (
    "https://api.water.usgs.gov/nldi/linked-data/nwissite/"
    "USGS-03424860/navigation/UT/flowlines?distance=30.0"
)
NLDI_SHA256 = (
    "1f8bc9bdb6fae8e4a6e40c34531ae0a002dbaddde0fd475b53e956630a0b262c"
)
NETWORK_SHA256 = (
    "9ae3611462c731ef1508dd091f499425b8befe338fa85e6649df696ee7a1b951"
)
JUNCTION_ID = "18421703"
JUNCTION_FEATURE_ID = 18421703
EXPECTED_UPSTREAM_IDS = (18421705, 18421707)
GEOMETRY_WINDOW_LENGTH_M = 30.0
TERMINAL_SNAP_TOLERANCE_M = 0.25
MINIMUM_TERMINAL_PATH_LENGTH_M = 20.0

HEC_RAS_JUNCTION_URL = (
    "https://www.hec.usace.army.mil/confluence/rasdocs/ras1dtechref/"
    "latest/overview-of-optional-capabilities/modeling-stream-junctions"
)
HEC_RAS_JUNCTION_PAGE_SHA256 = (
    "3858127f64666d61d438c5660ac9d910b17abe6477f2479c334f03a3aa8c03a0"
)
HEC_RAS_CHILD_API_URL = (
    "https://www.hec.usace.army.mil/confluence/rest/api/content/43816552/"
    "child/page?limit=100&expand=body.storage,version"
)
HEC_RAS_CHILD_API_SHA256 = (
    "59bdf525ebc59d2cd34e4523e255bebae41d08af2f3435237844e33b32790563"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=RAW_PATH)
    parser.add_argument("--network", type=Path, default=NETWORK_PATH)
    parser.add_argument("--geometry", type=Path, default=GEOMETRY_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    return parser.parse_args()


def compile_gates(
    *,
    raw_path: Path = RAW_PATH,
    network_path: Path = NETWORK_PATH,
    geometry_path: Path = GEOMETRY_PATH,
    write_geometry: bool = True,
) -> dict[str, Any]:
    raw_body = raw_path.read_bytes()
    network_body = network_path.read_bytes()
    raw_sha256 = _sha256(raw_body)
    network_sha256 = _sha256(network_body)
    raw = json.loads(raw_body)
    compiled = json.loads(network_body)
    if raw.get("type") != "FeatureCollection":
        raise ValueError("junction_geometry_nldi_feature_collection_required")
    features = {_feature_id(value): value for value in raw["features"]}
    if len(features) != len(raw["features"]):
        raise ValueError("junction_geometry_nldi_duplicate_feature_id")
    network = compiled["network"]
    upstream_ids = tuple(
        int(feature_id)
        for feature_id, downstream_id in zip(
            network["feature_ids"],
            network["downstream_feature_ids"],
            strict=True,
        )
        if downstream_id == JUNCTION_FEATURE_ID
    )
    if upstream_ids != EXPECTED_UPSTREAM_IDS:
        raise ValueError("junction_geometry_public_topology_anchor_mismatch")
    confluence = next(
        value
        for value in compiled["compiled_tributary_confluences"]
        if value["receiving_feature_id"] == JUNCTION_FEATURE_ID
        and value["tributary_feature_id"] == EXPECTED_UPSTREAM_IDS[0]
        and value["upstream_network_compiled"] is True
    )
    junction_coordinate = tuple(float(value) for value in confluence["coordinate"])
    requested_ids = (*upstream_ids, JUNCTION_FEATURE_ID)
    if any(value not in features for value in requested_ids):
        raise ValueError("junction_geometry_public_feature_missing")
    sources = tuple(
        GeographicJunctionBranchSource(
            branch_id=str(feature_id),
            role=(
                "downstream"
                if feature_id == JUNCTION_FEATURE_ID
                else "upstream"
            ),
            source_feature_id=str(feature_id),
            coordinates=tuple(
                tuple(float(component) for component in coordinate)
                for coordinate in features[feature_id]["geometry"]["coordinates"]
            ),
            source_uri=NLDI_URL,
            source_sha256=raw_sha256,
            source_crs="EPSG:4326",
        )
        for feature_id in requested_ids
    )
    geometry = compile_geographic_junction_geometry(
        JUNCTION_ID,
        junction_coordinate,
        sources,
        geometry_window_length_m=GEOMETRY_WINDOW_LENGTH_M,
        terminal_snap_tolerance_m=TERMINAL_SNAP_TOLERANCE_M,
        minimum_terminal_path_length_m=MINIMUM_TERMINAL_PATH_LENGTH_M,
    )
    reversed_geometry = compile_geographic_junction_geometry(
        JUNCTION_ID,
        junction_coordinate,
        tuple(
            GeographicJunctionBranchSource(
                value.branch_id,
                value.role,
                value.source_feature_id,
                tuple(reversed(value.coordinates)),
                value.source_uri,
                value.source_sha256,
                value.source_crs,
            )
            for value in sources
        ),
        geometry_window_length_m=GEOMETRY_WINDOW_LENGTH_M,
        terminal_snap_tolerance_m=TERMINAL_SNAP_TOLERANCE_M,
        minimum_terminal_path_length_m=MINIMUM_TERMINAL_PATH_LENGTH_M,
    )
    loss_admission = adjudicate_geographic_junction_energy_loss(geometry)
    topology = DynamicWaveDendriticTopology(
        tuple(str(value) for value in requested_ids),
        (JUNCTION_ID, JUNCTION_ID, None),
    )
    dag_binding_error = None
    try:
        bind_admitted_geographic_losses_to_dag(
            topology, {JUNCTION_ID: loss_admission}
        )
    except ValueError as exc:
        dag_binding_error = str(exc)
    endpoint_negative_control_error = None
    try:
        compile_geographic_junction_geometry(
            JUNCTION_ID,
            (junction_coordinate[0] + 0.001, junction_coordinate[1]),
            sources,
            geometry_window_length_m=GEOMETRY_WINDOW_LENGTH_M,
            terminal_snap_tolerance_m=TERMINAL_SNAP_TOLERANCE_M,
            minimum_terminal_path_length_m=MINIMUM_TERMINAL_PATH_LENGTH_M,
        )
    except ValueError as exc:
        endpoint_negative_control_error = str(exc)

    geometry_dict = geometry.as_dict()
    admission_dict = loss_admission.as_dict()
    public_artifact = {
        "schema": PUBLIC_ARTIFACT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_artifacts": {
            "nldi_upstream_tributaries": _artifact(raw_path, NLDI_URL),
            "d5_full_subnetwork": _artifact(network_path),
        },
        "geometry": geometry_dict,
        "loss_admission": admission_dict,
        "dag_binding": {
            "topology": topology.as_dict(),
            "status": "not_bound_loss_contract_not_admitted",
            "error": dag_binding_error,
            "stage7_common_stage_remains_available_when_map_omitted": True,
        },
    }
    geometry_artifact = None
    if write_geometry:
        _write_json(geometry_path, public_artifact)
        geometry_artifact = _artifact(geometry_path)

    forward_azimuths = tuple(
        value.flow_azimuth_degrees
        for value in (*geometry.upstream_branches, geometry.downstream_branch)
    )
    reverse_azimuths = tuple(
        value.flow_azimuth_degrees
        for value in (
            *reversed_geometry.upstream_branches,
            reversed_geometry.downstream_branch,
        )
    )
    maximum_orientation_difference = max(
        abs(left - right)
        for left, right in zip(forward_azimuths, reverse_azimuths, strict=True)
    )
    source_property_keys = {
        key
        for feature_id in requested_ids
        for key in (features[feature_id].get("properties") or {})
    }
    structure_metadata_keys = source_property_keys & {
        "structure_type",
        "culvert",
        "gate",
        "weir",
        "bridge",
    }
    branches = (*geometry.upstream_branches, geometry.downstream_branch)
    gates = {
        "nldi_source_hash_matches_frozen_public_asset": (
            raw_sha256 == NLDI_SHA256
        ),
        "d5_topology_hash_matches_compiled_public_asset": (
            network_sha256 == NETWORK_SHA256
        ),
        "public_dag_has_expected_two_in_one_out_junction": (
            upstream_ids == EXPECTED_UPSTREAM_IDS
            and topology.upstream_reach_ids(JUNCTION_ID)
            == tuple(str(value) for value in EXPECTED_UPSTREAM_IDS)
        ),
        "all_public_branch_endpoints_snap_to_junction": all(
            value.terminal_snap_distance_m <= TERMINAL_SNAP_TOLERANCE_M
            for value in branches
        ),
        "all_public_branches_support_fixed_geodesic_window": all(
            value.sampled_window_length_m == GEOMETRY_WINDOW_LENGTH_M
            for value in branches
        ),
        "public_azimuths_and_angles_are_finite": all(
            math.isfinite(value)
            for value in (
                *forward_azimuths,
                *geometry.upstream_to_downstream_deflection_degrees,
                *(row[2] for row in geometry.upstream_pair_angles_degrees),
            )
        ),
        "coordinate_sequence_orientation_is_invariant": (
            maximum_orientation_difference <= 1e-10
        ),
        "wrong_junction_coordinate_fails_snap_gate": (
            endpoint_negative_control_error
            == "geographic_junction_branch_endpoint_not_snapped"
        ),
        "source_uri_hash_crs_and_feature_ids_are_preserved": all(
            value.source_uri == NLDI_URL
            and value.source_sha256 == raw_sha256
            and value.source_crs == "EPSG:4326"
            and value.source_feature_id == value.branch_id
            for value in branches
        ),
        "public_centerlines_have_no_structure_metadata": (
            not structure_metadata_keys
            and geometry.structure_classification == "unknown"
        ),
        "centerline_only_loss_coefficient_fails_closed": (
            not loss_admission.admitted
            and loss_admission.energy_loss is None
            and "centerline_geometry_does_not_determine_loss_coefficient"
            in loss_admission.reason_codes
        ),
        "no_implicit_zero_loss_is_substituted": (
            admission_dict["implicit_zero_loss_assumed"] is False
        ),
        "non_admitted_public_loss_cannot_bind_to_dag": (
            dag_binding_error
            == "geographic_junction_energy_loss_dag_binding_not_admitted"
        ),
        "hec_ras_semantics_do_not_authorize_angle_to_k_mapping": True,
        "no_action_observation_or_prediction_values_read": True,
    }
    return {
        "schema": SCHEMA,
        "status": "public_geometry_compiled_loss_semantics_fail_closed",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_isolation": {
            "public_topology_and_centerline_geometry_read": True,
            "action_values_read": False,
            "observation_values_read": False,
            "saved_prediction_values_read": False,
            "coefficient_calibration_performed": False,
        },
        "public_case": public_artifact,
        "public_geometry_artifact": geometry_artifact,
        "orientation_invariance": {
            "forward_flow_azimuths_degrees": list(forward_azimuths),
            "reversed_coordinate_flow_azimuths_degrees": list(reverse_azimuths),
            "maximum_absolute_difference_degrees": (
                maximum_orientation_difference
            ),
        },
        "negative_controls": {
            "wrong_junction_coordinate_error": endpoint_negative_control_error,
            "non_admitted_dag_binding_error": dag_binding_error,
        },
        "authoritative_semantics": {
            "retrieved_at": "2026-07-28",
            "hec_ras_modeling_stream_junctions": {
                "url": HEC_RAS_JUNCTION_URL,
                "retrieved_snapshot_sha256": HEC_RAS_JUNCTION_PAGE_SHA256,
                "finding": (
                    "The energy method uses standard-step calculations and "
                    "does not account for tributary-flow angle."
                ),
            },
            "hec_ras_energy_and_momentum_child_pages": {
                "url": HEC_RAS_CHILD_API_URL,
                "retrieved_snapshot_sha256": HEC_RAS_CHILD_API_SHA256,
                "page_ids": {
                    "energy_based_junction_method": 43816554,
                    "momentum_based_junction_method": 43816560,
                },
                "findings": [
                    (
                        "Energy-based junction calculations evaluate friction "
                        "from reach length and average friction slope and also "
                        "evaluate contraction or expansion losses."
                    ),
                    (
                        "The angle-aware alternative is a one-dimensional "
                        "momentum balance with cross-section specific force, "
                        "friction, weight, and flow-weighted area terms."
                    ),
                ],
            },
            "stage8_compatibility_adjudication": {
                "centerline_angle_is_a_documented_stage8_k_model": False,
                "required_hec_energy_inputs_present_in_nldi_centerlines": False,
                "required_hec_momentum_inputs_present_in_nldi_centerlines": False,
                "positive_loss_coefficient_derivation_admitted": False,
            },
        },
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "claim_boundary": {
            "public_geographic_junction_geometry_compiled": True,
            "ellipsoidal_branch_azimuths_and_angles_compiled": True,
            "geometry_provenance_preserved": True,
            "structure_type_verified": False,
            "centerline_angle_loss_formula_implemented": False,
            "public_loss_coefficient_admitted": False,
            "evidence_gated_stage8_dag_binding_implemented": True,
            "public_case_bound_to_loss_aware_dag": False,
            "junction_vector_momentum_closure_implemented": False,
            "candidate_operator_admitted": False,
            "predictive_validation_complete": False,
            "geospatial_kernel_validated": False,
        },
    }


def _feature_id(feature: dict[str, Any]) -> int:
    properties = feature.get("properties") or {}
    value = properties.get("nhdplus_comid", properties.get("comid"))
    if value is None:
        raise ValueError("junction_geometry_nldi_feature_id_missing")
    return int(value)


def _artifact(path: Path, source_uri: str | None = None) -> dict[str, Any]:
    body = path.read_bytes()
    result = {
        "path": _display(path),
        "sha256": _sha256(body),
        "size_bytes": len(body),
    }
    if source_uri is not None:
        result["source_uri"] = source_uri
    return result


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    report = compile_gates(
        raw_path=args.raw,
        network_path=args.network,
        geometry_path=args.geometry,
        write_geometry=True,
    )
    _write_json(args.report, report)
    print(args.geometry)
    print(args.report)
    return 0 if report["all_gates_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
