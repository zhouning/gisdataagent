#!/usr/bin/env python3
"""Compile Stage 12 HEC-RAS force decomposition and refusal gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import h5py

from data_agent.uwm.geospatial_kernel_v2.hec_ras_force_diagnostic import (
    DOCUMENTED_FORCE_VARIANT,
    HEC_RAS_FORCE_VARIANTS,
    evaluate_hec_ras_force_variant,
    solve_hec_ras_force_variant,
)
from data_agent.uwm.geospatial_kernel_v2.hec_ras_reference import (
    FEET_TO_METRES,
    load_hec_ras_example_archive,
    parse_hec_ras_geometry,
    parse_hec_ras_plan,
    parse_hec_ras_steady_flow,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE10_ROOT = REPO_ROOT / ".tmp/geotransport/hec_ras_example10"
STAGE12_ROOT = REPO_ROOT / ".tmp/geotransport/hec_ras_stage12"
DEFAULT_ARCHIVE = EXAMPLE10_ROOT / "Example 10 - Stream Junction.zip"
DEFAULT_SECONDARY_HDF = EXAMPLE10_ROOT / "secondary_JUNCTION.p02.hdf"
DEFAULT_JUNCTION_METHOD = STAGE12_ROOT / "momentum_based_junction_method.json"
DEFAULT_SPECIFIC_FORCE = STAGE12_ROOT / "mixed_flow_specific_force.json"
DEFAULT_JUNCTION_SEARCH = STAGE12_ROOT / "junction_search_snapshot.json"
DEFAULT_TRANSPARENT_SOURCE = STAGE12_ROOT / "rivernetwork_solve_network_mod.f90"
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/"
    "hec_ras_example10_force_decomposition_diagnostic.json"
)

SCHEMA = "gwm.geotransport.hec_ras_stage12_force_diagnostic.v1"
PUBLISHED_STAGE_ROUNDING_TOLERANCE_FT = 0.005
REFERENCE_KEYS = (
    ("Spring Creek", "Upper Reach", "10.106"),
    ("Spruce Creek", "Spruce Creek", "0.013"),
    ("Spring Creek", "Lower Reach", "10.091"),
)
HDF_CROSS_SECTION_ROOT = (
    "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/"
    "Cross Sections"
)
HDF_GEOMETRY_ATTRIBUTES = (
    "Results/Steady/Output/Geometry Info/Cross Section Attributes"
)

SOURCE_IDENTITIES = {
    "archive": (
        DEFAULT_ARCHIVE,
        10_838,
        "c17a7e0e48c9578ce04caa9ffbdb798b979f4f7beb1be027f543b8e45f7f98c2",
    ),
    "secondary_hdf": (
        DEFAULT_SECONDARY_HDF,
        377_015,
        "762b14a079570c2dabd2e4ffdef29bfde561a13cd0fcd09b15353f6de3efa4b6",
    ),
    "junction_method": (
        DEFAULT_JUNCTION_METHOD,
        11_533,
        "c1c8e383101863cf1d88c7eaeebad87ee2dccc0ca8440cfaaf3620ca8a89d7dd",
    ),
    "specific_force": (
        DEFAULT_SPECIFIC_FORCE,
        11_446,
        "fd505acdd8bfd404fa76c227e4e307729106b1920c2e8c46bbf2fc5b826dd539",
    ),
    "transparent_source": (
        DEFAULT_TRANSPARENT_SOURCE,
        100_473,
        "ea4846d397e5b3f2f7bfac7a486f904c671eda3c98338fc636336ee820f74148",
    ),
}
SEARCH_SIZE = 156_673
SEARCH_CANONICAL_SHA256 = (
    "255615d8257d9f721c1a501ce97c5578b7e359c48b535d767beafad139ea4326"
)

FROZEN_STAGE10_AND_STAGE11_HASHES = {
    "data_agent/uwm/geospatial_kernel_v2/__init__.py": (
        "7db7e6459143d2a54e742a732fcd3f85c422a9775559296dc39a985ab632315d"
    ),
    "data_agent/uwm/geospatial_kernel_v2/dynamic_wave_junction_momentum.py": (
        "64cd7ae682784a2d9fc4be48bf6a3a7fc2eb074d5e31bca97fdc5bd6f298a873"
    ),
    "data_agent/uwm/geospatial_kernel_v2/irregular_section.py": (
        "3cde5d5bbdce22738516fed8ff2dd078f9eb50824b66b7155e10849f440e07cd"
    ),
    "data_agent/uwm/geospatial_kernel_v2/hec_ras_reference.py": (
        "9536a02990743a456574a737059be6d0a4134d44bf98a629095d7ce28515b39d"
    ),
    "scripts/acquire_geotransport_hec_ras_example10.py": (
        "f9bcde3128eb8c4eabd536be79b0eb5d79651f6b84869eae8286cad2bece708e"
    ),
    "scripts/compile_geotransport_hec_ras_example10_gates.py": (
        "0eeb5fa702a0dbbe55afcb1f46a74318769d255a4f62771e913d2470098403e3"
    ),
    "benchmarks/geotransport_v0_1/hec_ras_example10_momentum_gates.json": (
        "9b48df0851bdfd93f03e3beda3deb021d877e92e8e598a7cf360d50522e63b17"
    ),
    "docs/architecture-decisions/adr-052-hec-ras-irregular-junction-reference.md": (
        "53fc825a6db189c29707084ebec556db82022e04b7aa8112f49b6d8d1622310d"
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--secondary-hdf", type=Path, default=DEFAULT_SECONDARY_HDF)
    parser.add_argument("--junction-method", type=Path, default=DEFAULT_JUNCTION_METHOD)
    parser.add_argument("--specific-force", type=Path, default=DEFAULT_SPECIFIC_FORCE)
    parser.add_argument("--junction-search", type=Path, default=DEFAULT_JUNCTION_SEARCH)
    parser.add_argument(
        "--transparent-source", type=Path, default=DEFAULT_TRANSPARENT_SOURCE
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = compile_report(
        archive_path=args.archive,
        secondary_hdf_path=args.secondary_hdf,
        junction_method_path=args.junction_method,
        specific_force_path=args.specific_force,
        junction_search_path=args.junction_search,
        transparent_source_path=args.transparent_source,
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
    secondary_hdf_path: Path = DEFAULT_SECONDARY_HDF,
    junction_method_path: Path = DEFAULT_JUNCTION_METHOD,
    specific_force_path: Path = DEFAULT_SPECIFIC_FORCE,
    junction_search_path: Path = DEFAULT_JUNCTION_SEARCH,
    transparent_source_path: Path = DEFAULT_TRANSPARENT_SOURCE,
) -> dict[str, Any]:
    paths = {
        "archive": Path(archive_path),
        "secondary_hdf": Path(secondary_hdf_path),
        "junction_method": Path(junction_method_path),
        "specific_force": Path(specific_force_path),
        "junction_search": Path(junction_search_path),
        "transparent_source": Path(transparent_source_path),
    }
    source_artifacts: dict[str, dict[str, object]] = {}
    for source_id, (default_path, expected_size, expected_hash) in (
        SOURCE_IDENTITIES.items()
    ):
        path = paths[source_id]
        artifact = _artifact(path)
        if (
            artifact["size_bytes"] != expected_size
            or artifact["sha256"] != expected_hash
        ):
            raise ValueError("hec_ras_stage12_source_identity_mismatch")
        source_artifacts[source_id] = artifact
    search_artifact = _artifact(paths["junction_search"])
    search_body = paths["junction_search"].read_bytes()
    search_canonical_hash = _canonical_search_sha256(search_body)
    if (
        search_artifact["size_bytes"] != SEARCH_SIZE
        or search_canonical_hash != SEARCH_CANONICAL_SHA256
    ):
        raise ValueError("hec_ras_stage12_search_identity_mismatch")
    search_artifact["canonical_sha256"] = search_canonical_hash
    search_artifact["canonicalization"] = (
        "remove_dynamic_searchDuration_then_sorted_compact_json"
    )
    source_artifacts["junction_search"] = search_artifact

    archive = load_hec_ras_example_archive(paths["archive"])
    geometry = parse_hec_ras_geometry(archive.geometry_text)
    flow = parse_hec_ras_steady_flow(archive.flow_text)
    plan = parse_hec_ras_plan(archive.plan_text)
    hdf_rows, hdf_metadata = _read_secondary_hdf(paths["secondary_hdf"])
    reference_upstream_ft = hdf_rows[REFERENCE_KEYS[0]]["water_surface_ft"]
    second_upstream_ft = hdf_rows[REFERENCE_KEYS[1]]["water_surface_ft"]
    reference_downstream_ft = hdf_rows[REFERENCE_KEYS[2]]["water_surface_ft"]
    if reference_upstream_ft != second_upstream_ft:
        raise ValueError("hec_ras_stage12_upstream_stage_not_common")
    reference_upstream_m = reference_upstream_ft * FEET_TO_METRES
    reference_downstream_m = reference_downstream_ft * FEET_TO_METRES

    variant_diagnostics: list[dict[str, Any]] = []
    for variant in HEC_RAS_FORCE_VARIANTS:
        reference_balance = evaluate_hec_ras_force_variant(
            geometry,
            flow,
            plan,
            variant,
            common_upstream_water_surface_elevation_m=reference_upstream_m,
            downstream_water_surface_elevation_m=reference_downstream_m,
        )
        try:
            solution = solve_hec_ras_force_variant(
                geometry,
                flow,
                plan,
                variant,
                downstream_water_surface_elevation_m=reference_downstream_m,
                reference_upstream_water_surface_elevation_m=reference_upstream_m,
            )
            root_ft = (
                solution.balance.common_upstream_water_surface_elevation_m
                / FEET_TO_METRES
            )
            stage_error_ft = root_ft - reference_upstream_ft
            root = {
                "status": "root_found",
                "stage_ft": root_ft,
                "stage_error_ft": stage_error_ft,
                "residual_m3": solution.balance.residual_m3,
                "root_bracket_m": list(solution.root_bracket_m),
                "all_sections_subcritical": (
                    solution.balance.downstream_force.froude_number < 1.0
                    and all(
                        value.section_force.froude_number < 1.0
                        for value in solution.balance.branches
                    )
                ),
                "within_published_stage_tolerance": (
                    abs(stage_error_ft)
                    <= PUBLISHED_STAGE_ROUNDING_TOLERANCE_FT
                ),
            }
        except ValueError as exc:
            root = {
                "status": "root_not_found",
                "error": str(exc),
                "within_published_stage_tolerance": False,
            }
        variant_diagnostics.append(
            {
                "variant": variant.as_dict(),
                "reference_stage_balance": reference_balance.as_dict(),
                "root": root,
                "admission_eligible": False,
                "admission_refusal_reason": (
                    "no independently discriminating case; a same-case stage "
                    "match would not validate an altered equation"
                ),
            }
        )

    documented = variant_diagnostics[0]
    documented_balance = documented["reference_stage_balance"]
    documented_root = documented["root"]
    if documented["variant"]["variant_id"] != DOCUMENTED_FORCE_VARIANT.variant_id:
        raise ValueError("hec_ras_stage12_documented_variant_order_invalid")

    junction_document = json.loads(paths["junction_method"].read_text("utf-8"))
    specific_force_document = json.loads(
        paths["specific_force"].read_text("utf-8")
    )
    junction_html = junction_document["body"]["storage"]["value"]
    specific_force_html = specific_force_document["body"]["storage"]["value"]
    documentation_audit = _documentation_audit(
        junction_document,
        junction_html,
        specific_force_document,
        specific_force_html,
    )
    search_value = json.loads(search_body)
    catalog_audit = _catalog_audit(search_value)
    transparent_source_text = paths["transparent_source"].read_text(
        encoding="utf-8"
    )
    transparent_audit = _transparent_source_audit(transparent_source_text)

    ineffective_area_audit = []
    for key in REFERENCE_KEYS:
        row = hdf_rows[key]
        ineffective_area_audit.append(
            {
                "reach_key": list(key[:2]),
                "river_station": key[2],
                "moving_flow_area_ft2": row["moving_flow_area_ft2"],
                "total_area_including_ineffective_ft2": (
                    row["total_area_including_ineffective_ft2"]
                ),
                "difference_ft2": (
                    row["total_area_including_ineffective_ft2"]
                    - row["moving_flow_area_ft2"]
                ),
                "areas_equal_at_terminal_state": abs(
                    row["total_area_including_ineffective_ft2"]
                    - row["moving_flow_area_ft2"]
                )
                <= 1e-6,
            }
        )

    frozen_files = {
        path: {
            "expected_sha256": expected,
            "actual_sha256": _sha256_path(REPO_ROOT / path),
        }
        for path, expected in FROZEN_STAGE10_AND_STAGE11_HASHES.items()
    }
    frozen_unchanged = all(
        value["expected_sha256"] == value["actual_sha256"]
        for value in frozen_files.values()
    )
    variant_roots = [value["root"] for value in variant_diagnostics]
    no_variant_conforms = all(
        not bool(value["within_published_stage_tolerance"])
        for value in variant_roots
    )
    gates = {
        "all_source_artifact_identities_match": True,
        "specific_force_equation_4_3_is_present": documentation_audit[
            "specific_force_equation_4_3_present"
        ],
        "junction_force_equations_4_5_to_4_8_are_present": documentation_audit[
            "core_junction_equations_present"
        ],
        "published_equation_4_7_angle_ambiguity_is_exposed": documentation_audit[
            "equation_4_7_reuses_theta_1"
        ],
        "published_equation_4_9_weight_ambiguity_is_exposed": documentation_audit[
            "equation_4_9_reuses_branch_and_friction_slope"
        ],
        "moving_and_total_areas_are_equal_in_this_case": all(
            value["areas_equal_at_terminal_state"]
            for value in ineffective_area_audit
        ),
        "documented_force_decomposition_matches_stage11_residual": abs(
            float(documented_balance["residual_m3"]) - 5.465593360172079
        )
        <= 1e-12,
        "documented_variant_root_matches_stage11_root": abs(
            float(documented_root["stage_ft"]) - 75.93723881747063
        )
        <= 1e-10,
        "all_variants_are_uncalibrated_and_diagnostic_only": all(
            value["variant"]["calibrated_to_example10"] is False
            and value["variant"]["operator_admitted"] is False
            for value in variant_diagnostics
        ),
        "no_predeclared_variant_matches_reference_stage": no_variant_conforms,
        "no_second_official_combining_junction_case_found": not catalog_audit[
            "independent_same_method_case_found"
        ],
        "transparent_candidate_does_not_implement_momentum_junction": not (
            transparent_audit["momentum_junction_implemented"]
        ),
        "frozen_stage10_and_stage11_evidence_is_unchanged": frozen_unchanged,
        "operator_remains_refused": True,
    }
    passed = sum(bool(value) for value in gates.values())
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "diagnostic_refusal_no_independent_discriminator",
        "source_artifacts": source_artifacts,
        "source_roles": {
            "archive": "USACE authoritative Example 10 model input",
            "secondary_hdf": (
                "fixed-commit HEC-RAS 6.6 recomputation; diagnostic precision "
                "only, not official observation or independent truth"
            ),
            "junction_method": "USACE authoritative equation documentation",
            "specific_force": "USACE authoritative specific-force documentation",
            "junction_search": (
                "official catalog discovery snapshot; absence is not universal "
                "proof that another case does not exist"
            ),
            "transparent_source": (
                "fixed-commit public source candidate audit; not hydraulic truth"
            ),
        },
        "reference_state": {
            "common_upstream_stage_ft": reference_upstream_ft,
            "downstream_stage_ft": reference_downstream_ft,
            "published_rounding_tolerance_ft": (
                PUBLISHED_STAGE_ROUNDING_TOLERANCE_FT
            ),
            "secondary_hdf_metadata": hdf_metadata,
        },
        "documentation_audit": documentation_audit,
        "ineffective_area_semantics_audit": ineffective_area_audit,
        "documented_force_decomposition": documented_balance,
        "equation_variant_diagnostics": variant_diagnostics,
        "independent_evidence_search": {
            "official_catalog": catalog_audit,
            "transparent_source_candidate": transparent_audit,
            "independent_discriminating_case_available": False,
        },
        "selection_decision": {
            "selected_variant_id": None,
            "selection_performed": False,
            "reason": (
                "none of the predeclared variants reproduces the reference stage, "
                "and Example 10 cannot both generate and validate a changed law"
            ),
        },
        "frozen_stage10_and_stage11": frozen_files,
        "gates": gates,
        "gate_summary": {
            "all_expected_behaviors_passed": passed == len(gates),
            "passed": passed,
            "total": len(gates),
        },
        "claim_boundary": {
            "force_terms_decomposed": True,
            "equation_variants_evaluated": True,
            "coefficient_calibration_performed": False,
            "variant_selected_from_example10_fit": False,
            "independent_predictive_validation_complete": False,
            "projected_momentum_operator_admitted": False,
            "geospatial_kernel_validated": False,
        },
    }


def _read_secondary_hdf(
    path: Path,
) -> tuple[dict[tuple[str, str, str], dict[str, float]], dict[str, object]]:
    with h5py.File(path, "r") as handle:
        attributes = handle[HDF_GEOMETRY_ATTRIBUTES][:]
        indices = {
            (
                _decode(row["River"]),
                _decode(row["Reach"]),
                _decode(row["Station"]),
            ): index
            for index, row in enumerate(attributes)
        }
        rows: dict[tuple[str, str, str], dict[str, float]] = {}
        for key in REFERENCE_KEYS:
            if key not in indices:
                raise ValueError("hec_ras_stage12_secondary_section_missing")
            index = indices[key]
            additional = f"{HDF_CROSS_SECTION_ROOT}/Additional Variables"
            rows[key] = {
                "water_surface_ft": float(
                    handle[f"{HDF_CROSS_SECTION_ROOT}/Water Surface"][0, index]
                ),
                "moving_flow_area_ft2": float(
                    handle[f"{additional}/Area Flow Total"][0, index]
                ),
                "total_area_including_ineffective_ft2": float(
                    handle[f"{additional}/Area including Ineffective Total"][
                        0, index
                    ]
                ),
            }
        gravity_ft_s2 = float(handle["Plan Data/Plan Parameters"].attrs["Gravity"])
    return rows, {
        "program_version": "HEC-RAS 6.6 September 2024",
        "gravity_ft_s2": gravity_ft_s2,
        "gravity_m_s2": gravity_ft_s2 * FEET_TO_METRES,
        "is_official_usace_observation": False,
        "is_independent_field_truth": False,
    }


def _documentation_audit(
    junction_document: dict[str, Any],
    junction_html: str,
    specific_force_document: dict[str, Any],
    specific_force_html: str,
) -> dict[str, object]:
    if (
        junction_document.get("id") != "43816560"
        or junction_document.get("title") != "Momentum Based Junction Method"
        or specific_force_document.get("id") != "43816541"
        or specific_force_document.get("title") != "Mixed Flow Regime Calculations"
    ):
        raise ValueError("hec_ras_stage12_document_identity_invalid")
    equation_4_3 = (
        r"SF = \frac{Q^2 \beta}{gA_m} + A_t \overline{Y}"
        in specific_force_html
    )
    core_equations = all(
        value in junction_html
        for value in (
            r"SF_3 = SF_4 cos \theta _1",
            r"F_{x_{4-3}} = \overline{S}",
            r"F_{x_{0-3}} = \overline{S}",
            r"W_{x_{4-3}} = S_{0_{4-3}}",
        )
    )
    return {
        "specific_force_page": {
            "id": specific_force_document["id"],
            "title": specific_force_document["title"],
            "version": specific_force_document["version"]["number"],
            "equation": "SF=beta*Q^2/(g*A_m)+A_t*Ybar",
        },
        "junction_method_page": {
            "id": junction_document["id"],
            "title": junction_document["title"],
            "version": junction_document["version"]["number"],
        },
        "specific_force_equation_4_3_present": equation_4_3,
        "core_junction_equations_present": core_equations,
        "equation_4_7_reuses_theta_1": (
            r"A_0 cos \theta _1" in junction_html
        ),
        "equation_4_9_reuses_branch_and_friction_slope": (
            r"W_{x_{4-3}} = S_{f_{4-3}}" in junction_html
        ),
        "ambiguity_effect": (
            "the prose defines bed-slope water weight and branch-specific angles; "
            "the displayed 4-7 and 4-9 symbols are internally inconsistent"
        ),
    }


def _catalog_audit(value: dict[str, Any]) -> dict[str, object]:
    if value.get("size") != 62 or value.get("totalSize") != 62:
        raise ValueError("hec_ras_stage12_catalog_result_count_invalid")
    rows = [
        {
            "id": row["id"],
            "title": row["title"],
            "space": row["space"]["key"],
        }
        for row in value["results"]
    ]
    application_examples = [
        row
        for row in rows
        if row["space"] == "RASAppGuide" and "Junction" in row["title"]
    ]
    combining_examples = [
        row
        for row in application_examples
        if "Stream Junction - Example 10" in row["title"]
    ]
    split_examples = [
        row for row in application_examples if "Split Flow Junction" in row["title"]
    ]
    return {
        "query": value["cqlQuery"],
        "result_count": value["size"],
        "ras_application_guide_junction_pages": application_examples,
        "same_example10_pages": combining_examples,
        "split_flow_lateral_weir_pages": split_examples,
        "unique_combining_example_ids": ["Example 10"],
        "independent_same_method_case_found": False,
        "scope_note": (
            "the two Example 10 page IDs are current/versioned presentations of "
            "the same model; Example 15 is a lateral-weir split-flow problem"
        ),
        "negative_search_is_not_proof_of_global_absence": True,
    }


def _transparent_source_audit(text: str) -> dict[str, object]:
    unimplemented_marker = (
        "As of now, we only have the energy based option for junction simulation"
    )
    return {
        "repository": "babakpst/RiverNetwork",
        "commit": "f0f5f07ceecd416cf6a1fbe629d3e1050d6d2a74",
        "path": "src/Simulator/solve_network_mod.f90",
        "declares_momentum_junction_option": (
            "Momentum based junction method" in text
        ),
        "unimplemented_marker_count": text.count(unimplemented_marker),
        "momentum_junction_implemented": text.count(unimplemented_marker) == 0,
        "usable_as_independent_discriminating_case": False,
        "reason": (
            "both upstream and downstream momentum-junction branches explicitly "
            "state that only the energy-based option is implemented"
        ),
        "source_is_reference_truth": False,
    }


def _canonical_search_sha256(body: bytes) -> str:
    value = json.loads(body)
    value.pop("searchDuration", None)
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _decode(value: bytes) -> str:
    return value.decode("ascii").strip()


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ValueError("hec_ras_stage12_source_missing")
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
