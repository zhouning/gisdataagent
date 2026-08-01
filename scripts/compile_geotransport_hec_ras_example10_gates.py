#!/usr/bin/env python3
"""Compile Stage 11 HEC-RAS Example 10 hydraulic conformance gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import h5py

from data_agent.uwm.geospatial_kernel_v2.hec_ras_reference import (
    CFS_TO_CUBIC_METRES_PER_SECOND,
    FEET_TO_METRES,
    HecRasCrossSection,
    HecRasSteadyFlow,
    evaluate_hec_ras_projected_momentum_reference,
    load_hec_ras_example_archive,
    parse_hec_ras_geometry,
    parse_hec_ras_plan,
    parse_hec_ras_steady_flow,
    solve_hec_ras_projected_momentum_reference,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = REPO_ROOT / ".tmp/geotransport/hec_ras_example10"
DEFAULT_ARCHIVE = EVIDENCE_ROOT / "Example 10 - Stream Junction.zip"
DEFAULT_OFFICIAL_TABLE = EVIDENCE_ROOT / "momentum_standard_table_2.png"
DEFAULT_SECONDARY_HDF = EVIDENCE_ROOT / "secondary_JUNCTION.p02.hdf"
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/hec_ras_example10_momentum_gates.json"
)

SCHEMA = "gwm.geotransport.hec_ras_example10_momentum_gates.v1"
OFFICIAL_ARCHIVE_URL = (
    "https://www.hec.usace.army.mil/confluence/download/attachments/"
    "80528340/Example%2010%20-%20Stream%20Junction.zip?version=1&"
    "modificationDate=1642646172667&api=v2"
)
OFFICIAL_TABLE_URL = (
    "https://www.hec.usace.army.mil/confluence/download/attachments/"
    "80528340/worddav48427a90af6fd779f2528e3743d30d6d.png?version=1&"
    "modificationDate=1644264027764&api=v2"
)
SECONDARY_HDF_URL = (
    "https://raw.githubusercontent.com/leixiaohui-1974/HydroClaude/"
    "99f17382ce4dea93055e8d4ecf6732d287be4cc4/reports/"
    "hecras_examples_raw/Applications%20Guide/"
    "Example%2010%20-%20Stream%20Junction/JUNCTION.p02.hdf"
)
ARCHIVE_SHA256 = (
    "c17a7e0e48c9578ce04caa9ffbdb798b979f4f7beb1be027f543b8e45f7f98c2"
)
OFFICIAL_TABLE_SHA256 = (
    "e38d571214ec7c6ba842d90d5ec7368694faead75ff61e17bf61aced48d99624"
)
SECONDARY_HDF_SHA256 = (
    "762b14a079570c2dabd2e4ffdef29bfde561a13cd0fcd09b15353f6de3efa4b6"
)
EXPECTED_SIZES = {
    "archive": 10_838,
    "official_table": 98_515,
    "secondary_hdf": 377_015,
}
FROZEN_STAGE10_HASHES = {
    "data_agent/uwm/geospatial_kernel_v2/__init__.py": (
        "7db7e6459143d2a54e742a732fcd3f85c422a9775559296dc39a985ab632315d"
    ),
    "data_agent/uwm/geospatial_kernel_v2/dynamic_wave_junction_momentum.py": (
        "64cd7ae682784a2d9fc4be48bf6a3a7fc2eb074d5e31bca97fdc5bd6f298a873"
    ),
}

OFFICIAL_PAGE_ID = 80_528_340
OFFICIAL_TABLE_ATTACHMENT_ID = 86_902_570
OFFICIAL_PUBLISHED_STAGE_FT = {
    "common_upstream": 75.50,
    "downstream": 75.04,
}
PUBLISHED_STAGE_ROUNDING_TOLERANCE_FT = 0.005

REFERENCE_KEYS = (
    ("Spring Creek", "Upper Reach", "10.106"),
    ("Spruce Creek", "Spruce Creek", "0.013"),
    ("Spring Creek", "Lower Reach", "10.091"),
)
AREA_TOLERANCE_FT2 = 1e-3
# The secondary HDF stores result arrays as float32; 0.25 cfs is under 2 ppm
# at the largest terminal conveyance while covering its serialization error.
CONVEYANCE_TOLERANCE_CFS = 0.25
BETA_TOLERANCE = 1e-6
FLOW_TOLERANCE_CFS = 1e-3
LENGTH_TOLERANCE_FT = 1e-3

HDF_CROSS_SECTION_ROOT = (
    "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/"
    "Cross Sections"
)
HDF_GEOMETRY_ATTRIBUTES = (
    "Results/Steady/Output/Geometry Info/Cross Section Attributes"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument(
        "--official-table", type=Path, default=DEFAULT_OFFICIAL_TABLE
    )
    parser.add_argument("--secondary-hdf", type=Path, default=DEFAULT_SECONDARY_HDF)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = compile_report(
        archive_path=args.archive,
        official_table_path=args.official_table,
        secondary_hdf_path=args.secondary_hdf,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    return 0


def compile_report(
    *,
    archive_path: Path = DEFAULT_ARCHIVE,
    official_table_path: Path = DEFAULT_OFFICIAL_TABLE,
    secondary_hdf_path: Path = DEFAULT_SECONDARY_HDF,
) -> dict[str, Any]:
    source_paths = {
        "archive": Path(archive_path),
        "official_table": Path(official_table_path),
        "secondary_hdf": Path(secondary_hdf_path),
    }
    expected_hashes = {
        "archive": ARCHIVE_SHA256,
        "official_table": OFFICIAL_TABLE_SHA256,
        "secondary_hdf": SECONDARY_HDF_SHA256,
    }
    source_urls = {
        "archive": OFFICIAL_ARCHIVE_URL,
        "official_table": OFFICIAL_TABLE_URL,
        "secondary_hdf": SECONDARY_HDF_URL,
    }
    source_artifacts: dict[str, dict[str, object]] = {}
    for source_id, path in source_paths.items():
        artifact = _artifact(path)
        if (
            artifact["sha256"] != expected_hashes[source_id]
            or artifact["size_bytes"] != EXPECTED_SIZES[source_id]
        ):
            raise ValueError("hec_ras_example10_compiler_source_identity_mismatch")
        artifact["url"] = source_urls[source_id]
        source_artifacts[source_id] = artifact

    archive = load_hec_ras_example_archive(source_paths["archive"])
    geometry = parse_hec_ras_geometry(archive.geometry_text)
    flow = parse_hec_ras_steady_flow(archive.flow_text)
    plan = parse_hec_ras_plan(archive.plan_text)
    upstream_sections, downstream_section = geometry.junction_terminal_sections()
    terminal_sections = (*upstream_sections, downstream_section)

    hdf_rows, hdf_metadata = _read_secondary_hdf(
        source_paths["secondary_hdf"]
    )
    section_conformance = tuple(
        _compile_section_conformance(section, flow, hdf_rows)
        for section in terminal_sections
    )
    section_hydraulics_conformed = all(
        all(bool(value["within_tolerance"]) for value in row["comparisons"].values())
        for row in section_conformance
    )
    section_geometry_conformed = _category_conformed(
        section_conformance,
        ("area_ft2", "top_width_ft", "wetted_perimeter_ft"),
    )
    conveyance_partition_conformed = _category_conformed(
        section_conformance,
        ("conveyance_cfs", "flow_partition_cfs"),
    )
    beta_conformed = _category_conformed(section_conformance, ("beta",))

    reference_upstream_ft = hdf_rows[REFERENCE_KEYS[0]]["water_surface_ft"]
    second_upstream_ft = hdf_rows[REFERENCE_KEYS[1]]["water_surface_ft"]
    reference_downstream_ft = hdf_rows[REFERENCE_KEYS[2]]["water_surface_ft"]
    if reference_upstream_ft != second_upstream_ft:
        raise ValueError("hec_ras_example10_secondary_upstream_stage_not_common")
    reference_upstream_m = reference_upstream_ft * FEET_TO_METRES
    reference_downstream_m = reference_downstream_ft * FEET_TO_METRES

    reference_balance = evaluate_hec_ras_projected_momentum_reference(
        geometry,
        flow,
        plan,
        common_upstream_water_surface_elevation_m=reference_upstream_m,
        downstream_water_surface_elevation_m=reference_downstream_m,
    )
    solution = solve_hec_ras_projected_momentum_reference(
        geometry,
        flow,
        plan,
        downstream_water_surface_elevation_m=reference_downstream_m,
        reference_upstream_water_surface_elevation_m=reference_upstream_m,
    )
    solution_stage_ft = (
        solution.balance.common_upstream_water_surface_elevation_m / FEET_TO_METRES
    )
    stage_error_ft = solution_stage_ft - reference_upstream_ft
    stage_conformed = abs(stage_error_ft) <= PUBLISHED_STAGE_ROUNDING_TOLERANCE_FT

    frozen_stage10 = {
        path: {
            "expected_sha256": expected,
            "actual_sha256": _sha256_path(REPO_ROOT / path),
        }
        for path, expected in FROZEN_STAGE10_HASHES.items()
    }
    frozen_stage10_unchanged = all(
        value["expected_sha256"] == value["actual_sha256"]
        for value in frozen_stage10.values()
    )
    mass_residual_m3s = sum(
        flow.discharge_for_reach(value.reach_key) for value in upstream_sections
    ) - flow.discharge_for_reach(downstream_section.reach_key)
    rounded_reference_matches_official = (
        round(reference_upstream_ft, 2)
        == OFFICIAL_PUBLISHED_STAGE_FT["common_upstream"]
        and round(reference_downstream_ft, 2)
        == OFFICIAL_PUBLISHED_STAGE_FT["downstream"]
    )

    gates = {
        "all_source_artifact_hashes_and_sizes_match": True,
        "official_archive_parses_without_parameter_substitution": True,
        "official_geometry_has_19_cross_sections": len(geometry.cross_sections) == 19,
        "official_junction_is_expected_two_in_one_out_case": (
            geometry.junction.upstream_reaches
            == (
                ("Spring Creek", "Upper Reach"),
                ("Spruce Creek", "Spruce Creek"),
            )
            and geometry.junction.downstream_reach
            == ("Spring Creek", "Lower Reach")
        ),
        "official_lengths_and_angles_parse_exactly": (
            geometry.junction.reach_lengths_m
            == (80.0 * FEET_TO_METRES, 70.0 * FEET_TO_METRES)
            and geometry.junction.deflection_degrees == (0.0, 45.0)
        ),
        "official_flow_is_mass_conservative": abs(mass_residual_m3s) <= 1e-12,
        "plan_is_subcritical_momentum_with_average_conveyance_friction": (
            plan.subcritical_flow
            and plan.short_identifier == "Momentum"
            and plan.friction_slope_method == 1
        ),
        "secondary_exact_stages_round_to_official_published_table": (
            rounded_reference_matches_official
        ),
        "all_terminal_section_hydraulics_match_secondary_hec_ras_66": (
            section_hydraulics_conformed
        ),
        "reference_stage_projected_momentum_residual_is_exposed": (
            abs(reference_balance.residual_m3) > 1.0
        ),
        "solver_root_satisfies_implemented_momentum_equation": (
            abs(solution.balance.residual_m3) <= 1e-11
        ),
        "solver_root_is_subcritical_on_all_branches": (
            solution.balance.downstream_froude_number < 1.0
            and all(value.froude_number < 1.0 for value in solution.balance.branches)
        ),
        "stage_nonconformance_exceeds_published_rounding_uncertainty": (
            not stage_conformed
            and abs(stage_error_ft) > PUBLISHED_STAGE_ROUNDING_TOLERANCE_FT
        ),
        "no_coefficient_was_calibrated_to_force_stage_agreement": (
            solution.as_dict()["calibrated_to_reference_stage"] is False
        ),
        "frozen_stage10_entrypoints_are_unchanged": frozen_stage10_unchanged,
    }
    expected_gate_count = len(gates)
    passed_gate_count = sum(bool(value) for value in gates.values())

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "partial_conformance_projected_momentum_stage_rejected",
        "source_artifacts": source_artifacts,
        "source_roles": {
            "archive": "USACE authoritative model input",
            "official_table": "USACE authoritative published result table",
            "secondary_hdf": (
                "fixed-commit public HEC-RAS 6.6 recomputation used only for "
                "diagnostic precision; not USACE original output or field truth"
            ),
        },
        "official_publication": {
            "page_id": OFFICIAL_PAGE_ID,
            "table_attachment_id": OFFICIAL_TABLE_ATTACHMENT_ID,
            "page_url": (
                "https://www.hec.usace.army.mil/confluence/rasdocs/"
                "rasappguide/latest/stream-junction-example-10"
            ),
            "published_terminal_stage_ft": OFFICIAL_PUBLISHED_STAGE_FT,
            "display_precision_decimal_places": 2,
        },
        "secondary_recomputation": {
            "repository": "leixiaohui-1974/HydroClaude",
            "commit": "99f17382ce4dea93055e8d4ecf6732d287be4cc4",
            **hdf_metadata,
            "is_official_usace_observation": False,
            "is_independent_field_truth": False,
        },
        "parsed_contract": {
            "geometry": geometry.as_dict(),
            "flow": flow.as_dict(),
            "plan": plan.as_dict(),
            "archive_members": list(archive.members),
        },
        "terminal_section_conformance": list(section_conformance),
        "projected_momentum_diagnostic": {
            "reference_stage_balance": reference_balance.as_dict(),
            "implemented_equation_solution": solution.as_dict(),
            "implemented_solution_stage_ft": solution_stage_ft,
            "secondary_reference_stage_ft": reference_upstream_ft,
            "stage_error_ft": stage_error_ft,
            "published_rounding_tolerance_ft": (
                PUBLISHED_STAGE_ROUNDING_TOLERANCE_FT
            ),
            "stage_conformed": stage_conformed,
            "interpretation": (
                "section geometry, conveyance partition, and beta are not the "
                "source of the remaining stage discrepancy; undocumented HEC-RAS "
                "internal force treatment remains unresolved"
            ),
        },
        "conformance_summary": {
            "irregular_section_geometry_conformed": section_geometry_conformed,
            "conveyance_and_flow_partition_conformed": (
                conveyance_partition_conformed
            ),
            "momentum_coefficient_beta_conformed": beta_conformed,
            "documented_projected_momentum_stage_conformed": stage_conformed,
            "full_reference_conformance": (
                section_hydraulics_conformed and stage_conformed
            ),
            "operator_admitted": False,
        },
        "frozen_stage10": frozen_stage10,
        "gates": gates,
        "gate_summary": {
            "all_expected_behaviors_passed": passed_gate_count == expected_gate_count,
            "passed": passed_gate_count,
            "total": expected_gate_count,
        },
        "claim_boundary": {
            "irregular_section_reference_operator_implemented": True,
            "secondary_hec_ras_66_values_used_as_authoritative_truth": False,
            "coefficient_calibration_performed": False,
            "projected_momentum_operator_admitted": False,
            "predictive_validation_complete": False,
            "geospatial_kernel_validated": False,
        },
    }


def _read_secondary_hdf(
    path: Path,
) -> tuple[dict[tuple[str, str, str], dict[str, Any]], dict[str, str]]:
    dataset_names = {
        "water_surface_ft": "Water Surface",
        "area_ft2": "Additional Variables/Area Flow Total",
        "conveyance_cfs": "Additional Variables/Conveyance Total",
        "beta": "Additional Variables/Beta",
        "flow_left_cfs": "Additional Variables/Flow Left OB",
        "flow_channel_cfs": "Additional Variables/Flow Channel",
        "flow_right_cfs": "Additional Variables/Flow Right OB",
        "top_width_ft": "Additional Variables/Top Width Total",
        "wetted_perimeter_ft": "Additional Variables/Wetted Perimeter Total",
    }
    with h5py.File(path, "r") as handle:
        file_type = _decode(handle.attrs["File Type"])
        file_version = _decode(handle.attrs["File Version"])
        program_name = _decode(
            handle["Results/Steady/Output"].attrs["Program Name"]
        )
        program_version = _decode(
            handle["Results/Steady/Output"].attrs["Program Version"]
        )
        if (
            file_type != "HEC-RAS Results"
            or file_version != "HEC-RAS 6.6 September 2024"
            or program_name != "HEC-RAS - River Analysis System"
            or program_version != file_version
        ):
            raise ValueError("hec_ras_example10_secondary_program_identity_invalid")
        attributes = handle[HDF_GEOMETRY_ATTRIBUTES][:]
        indices = {
            (
                _decode(row["River"]),
                _decode(row["Reach"]),
                _decode(row["Station"]),
            ): index
            for index, row in enumerate(attributes)
        }
        rows: dict[tuple[str, str, str], dict[str, Any]] = {}
        for key in REFERENCE_KEYS:
            if key not in indices:
                raise ValueError("hec_ras_example10_secondary_section_missing")
            index = indices[key]
            row = {
                name: float(handle[f"{HDF_CROSS_SECTION_ROOT}/{dataset}"][0, index])
                for name, dataset in dataset_names.items()
            }
            rows[key] = row
    return rows, {
        "file_type_recorded_in_hdf": file_type,
        "file_version_recorded_in_hdf": file_version,
        "program_name_recorded_in_hdf": program_name,
        "program_version_recorded_in_hdf": program_version,
    }


def _compile_section_conformance(
    section: HecRasCrossSection,
    flow: HecRasSteadyFlow,
    hdf_rows: dict[tuple[str, str, str], dict[str, Any]],
) -> dict[str, Any]:
    key = (*section.reach_key, section.river_station)
    reference = dict(hdf_rows[key])
    reference_partition = tuple(
        _nan_to_zero(reference[name])
        for name in ("flow_left_cfs", "flow_channel_cfs", "flow_right_cfs")
    )
    distribution = section.distribution(
        reference["water_surface_ft"] * FEET_TO_METRES,
        flow.discharge_for_reach(section.reach_key),
    )
    wet = section.section.wet_properties_at_elevation(
        distribution.water_surface_elevation_m
    )
    kernel = {
        "water_surface_ft": (
            distribution.water_surface_elevation_m / FEET_TO_METRES
        ),
        "area_ft2": distribution.total_area_m2 / FEET_TO_METRES**2,
        "conveyance_cfs": (
            distribution.total_conveyance_m3s
            / CFS_TO_CUBIC_METRES_PER_SECOND
        ),
        "beta": distribution.momentum_coefficient_beta,
        "flow_partition_cfs": [
            value.discharge_m3s / CFS_TO_CUBIC_METRES_PER_SECOND
            for value in distribution.subsections
        ],
        "top_width_ft": wet.top_width_m / FEET_TO_METRES,
        "wetted_perimeter_ft": wet.wetted_perimeter_m / FEET_TO_METRES,
    }
    reference_serialized = {
        **reference,
        "flow_left_cfs": reference_partition[0],
        "flow_channel_cfs": reference_partition[1],
        "flow_right_cfs": reference_partition[2],
        "flow_partition_cfs": list(reference_partition),
    }
    comparisons = {
        "area_ft2": _comparison(
            kernel["area_ft2"], reference["area_ft2"], AREA_TOLERANCE_FT2
        ),
        "conveyance_cfs": _comparison(
            kernel["conveyance_cfs"],
            reference["conveyance_cfs"],
            CONVEYANCE_TOLERANCE_CFS,
        ),
        "beta": _comparison(kernel["beta"], reference["beta"], BETA_TOLERANCE),
        "flow_partition_cfs": _vector_comparison(
            kernel["flow_partition_cfs"],
            reference_partition,
            FLOW_TOLERANCE_CFS,
        ),
        "top_width_ft": _comparison(
            kernel["top_width_ft"],
            reference["top_width_ft"],
            LENGTH_TOLERANCE_FT,
        ),
        "wetted_perimeter_ft": _comparison(
            kernel["wetted_perimeter_ft"],
            reference["wetted_perimeter_ft"],
            LENGTH_TOLERANCE_FT,
        ),
    }
    return {
        "reach_key": list(section.reach_key),
        "river_station": section.river_station,
        "reference": reference_serialized,
        "kernel": kernel,
        "comparisons": comparisons,
        "all_within_tolerance": all(
            bool(value["within_tolerance"]) for value in comparisons.values()
        ),
    }


def _category_conformed(
    rows: tuple[dict[str, Any], ...], metrics: tuple[str, ...]
) -> bool:
    return all(
        bool(row["comparisons"][metric]["within_tolerance"])
        for row in rows
        for metric in metrics
    )


def _comparison(actual: float, expected: float, tolerance: float) -> dict[str, Any]:
    error = abs(float(actual) - float(expected))
    return {
        "absolute_error": error,
        "absolute_tolerance": tolerance,
        "within_tolerance": error <= tolerance,
    }


def _vector_comparison(
    actual: list[float], expected: tuple[float, ...], tolerance: float
) -> dict[str, Any]:
    errors = [abs(left - right) for left, right in zip(actual, expected, strict=True)]
    return {
        "absolute_errors": errors,
        "maximum_absolute_error": max(errors),
        "absolute_tolerance": tolerance,
        "within_tolerance": max(errors) <= tolerance,
    }


def _nan_to_zero(value: float) -> float:
    return 0.0 if math.isnan(value) else value


def _decode(value: bytes) -> str:
    return value.decode("ascii").strip()


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ValueError("hec_ras_example10_compiler_source_missing")
    body = path.read_bytes()
    try:
        rendered_path = path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        rendered_path = str(path.resolve())
    return {
        "path": rendered_path,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


if __name__ == "__main__":
    raise SystemExit(main())
