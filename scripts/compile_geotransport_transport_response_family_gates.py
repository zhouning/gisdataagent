#!/usr/bin/env python3
"""Compile outcome-independent analytic transport response-family gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from data_agent.uwm.geospatial_kernel_v2.transport_response_families import (
    AnalyticTransportFamilyCase,
    evaluate_transport_family_profile,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/transport_response_family_gates.json"
)
SCHEMA = "gwm.geotransport.transport_response_family_gates.v1"
INITIAL_IDENTITY_ABSOLUTE_TOLERANCE_M2 = 1e-15


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    return parser.parse_args()


def compile_gates() -> dict[str, Any]:
    common = {
        "initial_volume_m3": 1_000.0,
        "initial_center_m": 0.0,
        "initial_standard_deviation_m": 100.0,
        "elapsed_seconds": 300.0,
    }
    cases = (
        AnalyticTransportFamilyCase(
            case_id="linearized-kinematic-gaussian-v1",
            family="kinematic",
            advection_celerity_mps=2.0,
            **common,
        ),
        AnalyticTransportFamilyCase(
            case_id="linearized-diffusive-gaussian-v1",
            family="diffusive",
            advection_celerity_mps=2.0,
            diffusion_coefficient_m2s=25.0,
            **common,
        ),
        AnalyticTransportFamilyCase(
            case_id="linearized-local-inertial-gaussian-v1",
            family="local_inertial",
            gravity_wave_celerity_mps=4.0,
            **common,
        ),
    )
    coordinates = np.linspace(-6_000.0, 6_000.0, 12_001)
    results = []
    for case in cases:
        profile = case.profile_incremental_area_m2(coordinates)
        gate = evaluate_transport_family_profile(
            case,
            coordinates_m=coordinates,
            profile_incremental_area_m2=profile,
            maximum_relative_volume_error=1e-10,
            maximum_absolute_centroid_error_m=1e-8,
            maximum_relative_variance_error=1e-10,
        )
        results.append({"case": case.as_dict(), "sampled_profile_gate": gate.as_dict()})

    initial_cases = tuple(
        AnalyticTransportFamilyCase(
            case_id=f"{family}-initial-identity-v1",
            family=family,
            elapsed_seconds=0.0,
            advection_celerity_mps=(2.0 if family != "local_inertial" else None),
            diffusion_coefficient_m2s=(25.0 if family == "diffusive" else None),
            gravity_wave_celerity_mps=(4.0 if family == "local_inertial" else None),
            **{key: value for key, value in common.items() if key != "elapsed_seconds"},
        )
        for family in ("kinematic", "diffusive", "local_inertial")
    )
    initial_profiles = tuple(
        case.profile_incremental_area_m2(coordinates) for case in initial_cases
    )
    zero_diffusion = AnalyticTransportFamilyCase(
        case_id="diffusive-zero-coefficient-limit-v1",
        family="diffusive",
        advection_celerity_mps=2.0,
        diffusion_coefficient_m2s=0.0,
        **common,
    )
    kinematic_profile = cases[0].profile_incremental_area_m2(coordinates)
    zero_diffusion_profile = zero_diffusion.profile_incremental_area_m2(coordinates)
    variance_by_family = {
        case.family: case.expected_variance_m2 for case in cases
    }
    limiting_gates = {
        "all_families_share_initial_identity": all(
            np.allclose(
                initial_profiles[0],
                profile,
                rtol=0.0,
                atol=INITIAL_IDENTITY_ABSOLUTE_TOLERANCE_M2,
            )
            for profile in initial_profiles[1:]
        ),
        "diffusive_zero_coefficient_equals_kinematic": np.array_equal(
            zero_diffusion_profile, kinematic_profile
        ),
        "selected_cases_have_distinct_variance_growth": (
            variance_by_family["kinematic"]
            < variance_by_family["diffusive"]
            < variance_by_family["local_inertial"]
        ),
        "local_inertial_has_two_counterpropagating_components": (
            len(cases[2].components) == 2
            and cases[2].components[0].center_m < 0.0
            and cases[2].components[1].center_m > 0.0
        ),
    }
    all_sampled = all(
        row["sampled_profile_gate"]["all_gates_passed"] for row in results
    )
    return {
        "schema": SCHEMA,
        "status": "analytic_response_family_gates_compiled_not_operator_admission",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_isolation": {
            "public_or_user_data_read": False,
            "action_values_read": False,
            "observation_values_read": False,
            "saved_prediction_values_read": False,
            "cases_outcome_calibrated": False,
        },
        "linearized_equation_scope": {
            "kinematic": "first-order translation of an area perturbation",
            "diffusive": "advection-diffusion of an area perturbation",
            "local_inertial": (
                "undamped linear gravity-wave limit with zero initial time tendency"
            ),
            "nonlinear_river_operator_implemented": False,
        },
        "sample_axis": {
            "start_m": float(coordinates[0]),
            "end_m": float(coordinates[-1]),
            "spacing_m": float(coordinates[1] - coordinates[0]),
            "count": int(coordinates.size),
        },
        "numeric_tolerances": {
            "initial_identity_absolute_area_m2": (
                INITIAL_IDENTITY_ABSOLUTE_TOLERANCE_M2
            ),
            "profile_relative_volume": 1e-10,
            "profile_absolute_centroid_m": 1e-8,
            "profile_relative_variance": 1e-10,
        },
        "cases": results,
        "limiting_gates": limiting_gates,
        "gates": {
            "all_sampled_profile_gates_passed": all_sampled,
            "all_limiting_gates_passed": all(limiting_gates.values()),
            "mass_centroid_variance_contract_fixed": True,
            "candidate_operator_compared": False,
        },
        "claim_boundary": {
            "analytic_reference_families_available": True,
            "candidate_operator_implemented": False,
            "candidate_operator_admitted": False,
            "physical_parameter_values_admitted": False,
            "predictive_validation_complete": False,
            "geospatial_kernel_validated": False,
        },
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    report = compile_gates()
    _write_json(args.report, report)
    print(args.report)
    print(f"case_count={len(report['cases'])}")
    print(
        "all_analytic_gates_passed="
        f"{report['gates']['all_sampled_profile_gates_passed'] and report['gates']['all_limiting_gates_passed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
