#!/usr/bin/env python3
"""Compile Stage 21 real public-confluence spatial fixture gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.public_confluence_fixture import (
    DEFAULT_SOURCE_ROOT,
    LAND_COVER_ROUGHNESS_PRIORS,
    OPENING_ALIGNMENT_TOLERANCE_DEGREES,
    compile_public_confluence_fixture,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "stage21_public_confluence_fixture_gates.json"
)
DEFAULT_FIXTURE_OUTPUT = DEFAULT_SOURCE_ROOT / "public_confluence_fixture.json"
SCHEMA = "gwm.geotransport.stage21_public_confluence_fixture_gates.v1"

FROZEN_STAGE20_HASHES = {
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "coupled_junction_patch_reach_patch_friction.py"
    ): "87d1a38bf5fbe0521a90ae21f307e5ec0c8dee18c813cdd777636d280680298f",
    (
        "data_agent/"
        "test_geospatial_kernel_coupled_junction_patch_reach_patch_friction.py"
    ): "1ac5d64f6e9cc20ef75b83ca19b927096bb32e542f5a7926a77c8bdc0e974bfc",
    (
        "scripts/compile_geotransport_stage20_patch_friction_source_split_gates.py"
    ): "b0f5d9c3aaf93fd204b140ec76fdefb002ceb4e6d59ce26a8c1ed1d01677e3dd",
    (
        "benchmarks/geotransport_v0_1/"
        "stage20_patch_friction_source_split_gates.json"
    ): "cc7e5b04232b2ad45530ba299990fe34294a9a346ee0c1c85057c44172ca63b6",
    (
        "docs/architecture-decisions/"
        "adr-061-spatially-supported-patch-manning-friction.md"
    ): "928d3b7428dde887ac0edee66b74b54f2cb2b5dbad248449939e516aa7508c69",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--fixture-output", type=Path, default=DEFAULT_FIXTURE_OUTPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    fixture = compile_public_confluence_fixture(Path(args.source_root))
    fixture_value = fixture.as_dict()
    fixture_body = _json_bytes(fixture_value)
    args.fixture_output.parent.mkdir(parents=True, exist_ok=True)
    args.fixture_output.write_bytes(fixture_body)
    fixture_artifact = {
        "path": args.fixture_output.resolve().relative_to(REPO_ROOT).as_posix(),
        "size_bytes": len(fixture_body),
        "sha256": hashlib.sha256(fixture_body).hexdigest(),
    }
    report = compile_report(
        fixture=fixture,
        fixture_value=fixture_value,
        fixture_artifact=fixture_artifact,
        source_root=Path(args.source_root),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_json_bytes(report))
    print(args.output)
    print(f"status={report['status']}")
    print(f"gates={sum(report['gates'].values())}/{len(report['gates'])}")
    return 0 if report["all_gates_passed"] else 1


def compile_report(
    *,
    fixture=None,
    fixture_value: dict[str, Any] | None = None,
    fixture_artifact: dict[str, object] | None = None,
    source_root: Path = DEFAULT_SOURCE_ROOT,
) -> dict[str, Any]:
    if fixture is None:
        fixture = compile_public_confluence_fixture(source_root)
    if fixture_value is None:
        fixture_value = fixture.as_dict()
    if fixture_artifact is None:
        body = _json_bytes(fixture_value)
        fixture_artifact = {
            "path": DEFAULT_FIXTURE_OUTPUT.relative_to(REPO_ROOT).as_posix(),
            "size_bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        }
    manifest = json.loads(
        (source_root / "acquisition_manifest.json").read_text(encoding="utf-8")
    )
    geometry = fixture.diagnostic_horizontal_geometry
    roughness = fixture.roughness_prior_field
    alignment = fixture_value["computational_patch_support"][
        "opening_alignment"
    ]
    cell_evidence = fixture.cell_evidence
    source_artifacts = fixture.source_artifacts
    frozen_hashes = {
        relative: {
            "expected_sha256": expected,
            "actual_sha256": _sha256(REPO_ROOT / relative),
        }
        for relative, expected in FROZEN_STAGE20_HASHES.items()
    }
    runtime_refusal = False
    try:
        fixture.require_runtime_hydraulic_geometry()
    except ValueError as exc:
        runtime_refusal = str(exc) == (
            "public_confluence_bathymetry_and_cross_sections_missing"
        )
    class_codes = sorted(
        {
            code
            for value in cell_evidence
            for code, _ in value.land_cover_counts
        }
    )
    maximum_radius = max(
        math.hypot(value.east_m, value.north_m)
        for value in geometry.vertices
    )
    gauge = fixture.gauge
    gates = {
        "stage20_artifacts_hash_frozen": all(
            value["expected_sha256"] == value["actual_sha256"]
            for value in frozen_hashes.values()
        ),
        "acquisition_is_public_bounded_and_sends_no_workspace_data": (
            manifest["request_boundary"]["workspace_or_private_data_sent"]
            is False
            and manifest["request_boundary"]["nldi_navigation_distance_km"]
            == 2.0
            and manifest["total_downloaded_bytes"] <= 1_000_000
        ),
        "all_source_and_derived_artifacts_are_hash_bound": (
            len(source_artifacts) == 9
            and all(value["identity_matches"] for value in source_artifacts)
        ),
        "real_three_branch_single_outlet_topology_is_bound": (
            geometry.upstream_branch_ids == ("18421705", "18421707")
            and geometry.downstream_branch_id == "18421703"
        ),
        "all_branch_terminals_snap_to_one_real_junction": all(
            value.terminal_snap_distance_m <= 0.5
            for value in fixture.branches
        ),
        "branch_directions_use_thirty_meter_centerline_support": all(
            abs(value.sampled_reference_distance_m - 30.0) <= 1e-6
            for value in fixture.branches
        ),
        "six_cell_three_opening_patch_is_kernel_conforming": (
            len(geometry.cells) == 6
            and len(geometry.branch_faces) == 3
            and len(
                [
                    value
                    for value in geometry.faces
                    if value.boundary_type == "solid_wall"
                ]
            )
            == 3
            and geometry.total_plan_area_m2 > 0.0
        ),
        "opening_normals_match_public_centerline_directions": max(
            value["absolute_error_degrees"] for value in alignment
        )
        <= OPENING_ALIGNMENT_TOLERANCE_DEGREES,
        "computational_patch_is_explicitly_local_and_bounded": (
            maximum_radius < 100.0
            and fixture_value["computational_patch_support"]["construction"][
                "computational_support_only"
            ]
            is True
        ),
        "every_cell_has_public_terrain_support": all(
            value.terrain_sample_count > 0 for value in cell_evidence
        ),
        "terrain_is_not_misrepresented_as_bathymetry": (
            fixture_value["claim_boundary"][
                "terrain_treated_as_channel_bathymetry"
            ]
            is False
        ),
        "every_land_cover_class_has_an_explicit_prior_mapping": all(
            value in LAND_COVER_ROUGHNESS_PRIORS for value in class_codes
        ),
        "roughness_prior_has_exact_cell_area_binding": all(
            abs(
                prior.support_area_m2
                - geometry.cell_areas_m2[prior.cell_id]
            )
            <= 1e-9
            for prior in roughness.cells
        ),
        "roughness_prior_is_not_misrepresented_as_calibration": (
            roughness.as_dict()["roughness_is_calibrated"] is False
            and fixture_value["claim_boundary"]["roughness_calibrated"]
            is False
        ),
        "public_gauge_is_bound_as_scalar_discharge": (
            gauge.site_id == "03424860"
            and gauge.observed_parameter_code == "00060"
            and gauge.observed_quantity == "scalar_stream_discharge"
            and gauge.observation_count > 24
        ),
        "gauge_is_not_misrepresented_as_vector_momentum": (
            fixture_value["claim_boundary"][
                "gauge_treated_as_vector_momentum"
            ]
            is False
        ),
        "runtime_binding_fails_closed_without_hydraulic_geometry": (
            runtime_refusal
        ),
        "public_vector_momentum_validation_remains_incomplete": (
            fixture_value["claim_boundary"][
                "public_vector_momentum_validation_completed"
            ]
            is False
        ),
        "candidate_operator_remains_unadmitted": (
            fixture_value["claim_boundary"]["operator_admitted"] is False
        ),
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "real_public_confluence_spatial_fixture_compiled_"
            "hydraulic_geometry_calibration_and_vector_validation_pending"
        ),
        "fixture_artifact": fixture_artifact,
        "frozen_stage20_hashes": frozen_hashes,
        "source_summary": {
            "downloaded_bytes": manifest["total_downloaded_bytes"],
            "downloaded_artifact_count": manifest["artifact_count"],
            "verified_artifact_count_including_derived_and_reused": len(
                source_artifacts
            ),
            "workspace_or_private_data_sent": False,
            "sources": [
                "USGS NLDI/NHDPlus",
                "USGS NWIS",
                "USGS 3DEP",
                "USDA NASS CDL 2024",
            ],
        },
        "spatial_summary": {
            "junction_id": fixture.junction_id,
            "junction_coordinate_wgs84": list(
                fixture.junction_coordinate_wgs84
            ),
            "upstream_feature_ids": list(geometry.upstream_branch_ids),
            "downstream_feature_id": geometry.downstream_branch_id,
            "patch_cell_count": len(geometry.cells),
            "patch_plan_area_m2": geometry.total_plan_area_m2,
            "maximum_patch_radius_m": maximum_radius,
            "maximum_opening_alignment_error_degrees": max(
                value["absolute_error_degrees"] for value in alignment
            ),
            "terrain_elevation_range_m": [
                min(value.terrain_minimum_m for value in cell_evidence),
                max(value.terrain_maximum_m for value in cell_evidence),
            ],
            "land_cover_class_codes": class_codes,
            "manning_n_prior_range": [
                min(value.manning_n_prior for value in cell_evidence),
                max(value.manning_n_prior for value in cell_evidence),
            ],
            "gauge_distance_from_junction_m": gauge.distance_from_junction_m,
        },
        "kernel_boundary": fixture_value["kernel_binding"],
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "claim_boundary": fixture_value["claim_boundary"],
    }


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
