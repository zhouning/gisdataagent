#!/usr/bin/env python3
"""Compile Stage 23 public downstream-reach hydraulic-state gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import (
    public_reach_hydraulic_measurements as hydraulics,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/stage23_usgs_channel_measurements_03424860"
)
DEFAULT_MEASUREMENT_OUTPUT = (
    DEFAULT_DATA_ROOT / "public_reach_hydraulic_measurements.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "stage23_public_reach_hydraulic_gates.json"
)
SCHEMA = "gwm.geotransport.stage23_public_reach_hydraulic_gates.v1"

FROZEN_STAGE22_HASHES = {
    (
        "scripts/compile_geotransport_stage22_public_roughness_ensemble_gates.py"
    ): "4a9d2bad6d46834828753454746da0f279bbccf449b7b8d9356a324a9ce4d1be",
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "public_confluence_roughness_ensemble.py"
    ): "41033fda6a7894cff08d5db46721a308383b65b0439be958498ad618555a7aa2",
    (
        "data_agent/test_geospatial_kernel_public_confluence_roughness_ensemble.py"
    ): "4fa14a99a39f2179711d91442826b61fb4f113015df87428100bfae8db370bf2",
    (
        "data/geotransport_v0_1/stage22_center_hill_roughness_ensemble/"
        "roughness_ensemble.json"
    ): "0f6609bd3c62fe2eec682c6655f6727ec44e62a864696b8d945f2bd63a234292",
    (
        "data/geotransport_v0_1/stage22_center_hill_roughness_ensemble/"
        "friction_propagation.json"
    ): "aac4aa4c22d5c388bcc686de0a82d20cee309893f35ce2ec452d208b119effb6",
    (
        "benchmarks/geotransport_v0_1/"
        "stage22_public_roughness_ensemble_gates.json"
    ): "8c8791b95842330c47106300a0c2c9c0d54f17707b81e750e519feb127f54a47",
    (
        "docs/architecture-decisions/"
        "adr-063-public-roughness-support-uncertainty-ensemble.md"
    ): "c510a28b8ecbc4ad0d796a08dd9d2784270b1dcf68d75b6c96f2a888f8e0b6db",
}

FROZEN_USGS_SOURCE_HASHES = {
    (
        "data/geotransport_v0_1/"
        "stage23_usgs_channel_measurements_03424860/raw/"
        "channel_measurements_queryables.json"
    ): "fdd11da8be0ec9e54a8c45e1912cf916fdbf13a3c97ea64b2a045929e8de8027",
    (
        "data/geotransport_v0_1/"
        "stage23_usgs_channel_measurements_03424860/raw/"
        "channel_measurements_03424860.json"
    ): "71b5edf3df2190bf31308f6af1b167d22e197c0c19cf7d7350f48548ef4589b1",
    (
        "data/geotransport_v0_1/"
        "stage23_usgs_channel_measurements_03424860/raw/"
        "field_measurements_03424860.json"
    ): "1a60512bad9a6f717e9c17fe46f768911a88e65a99c88a9020eb91b6266c0b92",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--measurement-output", type=Path, default=DEFAULT_MEASUREMENT_OUTPUT
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    compiled = hydraulics.compile_public_reach_hydraulic_measurements()
    measurement_artifact = _write_artifact(
        args.measurement_output, compiled.as_dict()
    )
    report = compile_report(
        compiled=compiled, measurement_artifact=measurement_artifact
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_json_bytes(report))
    print(args.output)
    print(f"status={report['status']}")
    print(f"gates={sum(report['gates'].values())}/{len(report['gates'])}")
    return 0 if report["all_gates_passed"] else 1


def compile_report(
    *, compiled=None, measurement_artifact: dict[str, object] | None = None
) -> dict[str, Any]:
    if compiled is None:
        compiled = hydraulics.compile_public_reach_hydraulic_measurements()
    compiled_dict = compiled.as_dict()
    if measurement_artifact is None:
        measurement_artifact = _memory_artifact(
            DEFAULT_MEASUREMENT_OUTPUT, compiled_dict
        )

    frozen_stage22 = _frozen_hash_report(FROZEN_STAGE22_HASHES)
    frozen_usgs = _frozen_hash_report(FROZEN_USGS_SOURCE_HASHES)
    source_hashes = {
        str(value["path"]): str(value["sha256"])
        for value in compiled.source_artifacts
    }
    expected_source_hashes = {
        path: digest for path, digest in FROZEN_USGS_SOURCE_HASHES.items()
    }
    states = [value.dynamic_wave_state for value in compiled.measurements]
    closures = [
        value.flow_closure_relative_error for value in compiled.measurements
    ]
    froude = [value.froude_number for value in compiled.measurements]
    characteristic_speeds = [
        value.characteristic_speeds_mps for value in compiled.measurements
    ]
    equivalent_geometry_errors = [
        max(
            abs(
                value.equivalent_section.area_m2(
                    value.equivalent_mean_depth_m
                )
                - value.flow_area_m2
            ),
            abs(
                value.equivalent_section.top_width_m(value.flow_area_m2)
                - value.top_width_m
            ),
        )
        for value in compiled.measurements
    ]
    refusals = _geometry_refusal_control(compiled)
    finite_positive = all(
        all(
            math.isfinite(item) and item > 0.0
            for item in (
                value.flow_m3s,
                value.top_width_m,
                value.flow_area_m2,
                value.reported_mean_velocity_mps,
                value.gage_height_m,
            )
        )
        and (
            value.channel_location_distance_m is None
            or (
                math.isfinite(value.channel_location_distance_m)
                and value.channel_location_distance_m >= 0.0
            )
        )
        for value in compiled.measurements
    )
    unnumbered = [
        value
        for value in compiled.measurements
        if value.measurement_number == ""
    ]

    gates = {
        "stage22_artifacts_hash_frozen": all(
            value["matches"] for value in frozen_stage22.values()
        ),
        "three_public_usgs_source_objects_hash_frozen": (
            all(value["matches"] for value in frozen_usgs.values())
            and source_hashes == expected_source_hashes
            and all(
                value["identity_matches"]
                for value in compiled.source_artifacts
            )
        ),
        "all_110_measurements_compiled": len(compiled.measurements) == 110,
        "all_source_measurement_uuids_are_unique": (
            len({value.measurement_id for value in compiled.measurements}) == 110
        ),
        "all_field_visits_join_a_mean_gage_height": (
            len([value.gage_height_m for value in compiled.measurements]) == 110
            and all(
                value.gage_height_approval_status
                for value in compiled.measurements
            )
        ),
        "all_hydraulic_values_are_normalized_positive_and_finite": finite_positive,
        "flow_area_velocity_identity_closes_within_two_percent": (
            max(closures) <= hydraulics.FLOW_CLOSURE_TOLERANCE
        ),
        "all_dynamic_wave_states_are_positive_and_finite": all(
            math.isfinite(value.area_m2)
            and value.area_m2 > 0.0
            and math.isfinite(value.discharge_m3s)
            and value.discharge_m3s > 0.0
            for value in states
        ),
        "equivalent_rectangles_recover_observed_area_and_width": (
            max(equivalent_geometry_errors) <= 1e-12
        ),
        "all_observed_states_are_subcritical": all(
            math.isfinite(value) and value < 1.0 for value in froude
        ),
        "all_characteristic_speeds_straddle_zero": all(
            lower < 0.0 < upper for lower, upper in characteristic_speeds
        ),
        "field_and_instrument_method_diversity_is_retained": (
            compiled_dict["method_counts"].get("BridgeDownstreamSide") == 81
            and compiled_dict["method_counts"].get("Wading") == 25
            and compiled_dict["channel_measurement_type_counts"].get("adcp")
            == 82
            and compiled_dict["channel_measurement_type_counts"].get(
                "point_velocity"
            )
            == 28
        ),
        "measurement_coordinates_match_the_gauge_location": all(
            value.coordinate_wgs84 == compiled.gauge_coordinate_wgs84
            for value in compiled.measurements
        ),
        "gauge_is_same_reach_but_not_the_junction_patch": (
            compiled.reach_id == "18421703"
            and compiled.gauge_distance_from_junction_m > 900.0
            and compiled_dict["claim_boundary"][
                "measurement_location_is_junction_patch"
            ]
            is False
        ),
        "gage_height_is_not_treated_as_bed_referenced_depth": (
            compiled_dict["claim_boundary"][
                "gage_height_treated_as_bed_referenced_depth"
            ]
            is False
            and all(
                value.as_dict()["field_context"][
                    "gage_height_is_bed_referenced_depth"
                ]
                is False
                for value in compiled.measurements
            )
        ),
        "unnumbered_source_record_is_retained_by_uuid": (
            len(unnumbered) == 1
            and unnumbered[0].measurement_id
            == "cedaf1eb-8de6-4829-8c65-304423fe0af9"
        ),
        "fixed_geometry_and_patch_bathymetry_fail_closed": all(
            refusals.values()
        ),
        "candidate_operator_remains_unadmitted": (
            compiled_dict["claim_boundary"]["operator_admitted"] is False
        ),
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "public_downstream_reach_hydraulic_states_compiled_"
            "fixed_geometry_and_operator_admission_pending"
        ),
        "measurement_artifact": measurement_artifact,
        "frozen_stage22_hashes": frozen_stage22,
        "frozen_usgs_source_hashes": frozen_usgs,
        "source_artifacts": list(compiled.source_artifacts),
        "site_and_reach": {
            "monitoring_location_id": compiled.monitoring_location_id,
            "reach_id": compiled.reach_id,
            "gauge_coordinate_wgs84": list(compiled.gauge_coordinate_wgs84),
            "gauge_distance_from_junction_m": (
                compiled.gauge_distance_from_junction_m
            ),
        },
        "observation_summary": {
            "measurement_count": len(compiled.measurements),
            "time_range": compiled_dict["time_range"],
            "maximum_flow_closure_relative_error": max(closures),
            "maximum_froude_number": max(froude),
            "maximum_equivalent_geometry_error": max(
                equivalent_geometry_errors
            ),
            "subcritical_observation_count": sum(value < 1.0 for value in froude),
            "method_counts": compiled_dict["method_counts"],
            "channel_measurement_type_counts": compiled_dict[
                "channel_measurement_type_counts"
            ],
            "observed_ranges_and_quantiles": compiled_dict[
                "observed_ranges_and_quantiles"
            ],
        },
        "typed_refusals": refusals,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "claim_boundary": {
            "public_downstream_reach_hydraulic_states_compiled": True,
            "state_conditioned_equivalent_sections_compiled": True,
            "fixed_reach_geometry_admitted": False,
            "measurement_location_is_junction_patch": False,
            "gage_height_treated_as_bed_referenced_depth": False,
            "confluence_bathymetry_completed": False,
            "operator_admitted": False,
        },
    }


def _geometry_refusal_control(compiled) -> dict[str, bool]:
    results = {}
    try:
        compiled.require_fixed_reach_geometry()
    except ValueError as exc:
        results["fixed_reach_geometry"] = str(exc) == (
            "public_reach_measurements_state_conditioned_not_fixed_geometry"
        )
    else:
        results["fixed_reach_geometry"] = False
    try:
        compiled.require_confluence_patch_bathymetry()
    except ValueError as exc:
        results["confluence_patch_bathymetry"] = str(exc) == (
            "public_reach_measurement_not_confluence_patch_bathymetry"
        )
    else:
        results["confluence_patch_bathymetry"] = False
    return results


def _frozen_hash_report(
    expected: dict[str, str],
) -> dict[str, dict[str, object]]:
    return {
        relative: {
            "expected_sha256": digest,
            "actual_sha256": _sha256(REPO_ROOT / relative),
            "matches": digest == _sha256(REPO_ROOT / relative),
        }
        for relative, digest in expected.items()
    }


def _write_artifact(path: Path, value: dict[str, Any]) -> dict[str, object]:
    body = _json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return {
        "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
        "size_bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def _memory_artifact(path: Path, value: dict[str, Any]) -> dict[str, object]:
    body = _json_bytes(value)
    return {
        "path": path.relative_to(REPO_ROOT).as_posix(),
        "size_bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
