#!/usr/bin/env python3
"""Compile Stage 25 public geometry-response propagation gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import (
    public_reach_geometry_response as response,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/stage25_center_hill_geometry_response"
)
DEFAULT_RESPONSE_OUTPUT = DEFAULT_DATA_ROOT / "geometry_hydrodynamic_response.json"
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "stage25_public_geometry_response_gates.json"
)
SCHEMA = "gwm.geotransport.stage25_public_geometry_response_gates.v1"

FROZEN_STAGE24_HASHES = {
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "public_reach_geometry_stability.py"
    ): "6e15d49516f81de19b8b963847c770b0b59242f1993ba231522a0d83f65faea0",
    (
        "data_agent/test_geospatial_kernel_public_reach_geometry_stability.py"
    ): "7c6f7838b73c0d8a5b119e9d4cdf459602700eda3c4913b63f623f134ed2a04d",
    (
        "scripts/compile_geotransport_stage24_public_reach_geometry_gates.py"
    ): "43903ed88f45772bda8f65b0cd71fbec3c9e9f4705f302376c73ec81fc3dc524",
    (
        "data/geotransport_v0_1/"
        "stage24_center_hill_reach_geometry_stability/"
        "reach_geometry_stability_audit.json"
    ): "b4955bc4d8669f70f49425661d73c81166e7e28dc6a7ee761d37d657b8c365c9",
    (
        "benchmarks/geotransport_v0_1/"
        "stage24_public_reach_geometry_stability_gates.json"
    ): "41b18e08e69d9b284112da51ff9dcda28b783a9f85b67e00a0cad252bf74ed2d",
    (
        "docs/architecture-decisions/"
        "adr-065-location-conditioned-public-reach-geometry-stability.md"
    ): "4b76d3c0117ddd8ad54ec99e2c9b9c38c71cab417e894cbcece6b601e320b15a",
    (
        "data/geotransport_v0_1/"
        "stage24_center_hill_reach_geometry_stability/README.md"
    ): "9cd73f271a2aec0dac8f2f89ebe26089e536f33f5739acb3c412c96233f9768e",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--response-output", type=Path, default=DEFAULT_RESPONSE_OUTPUT
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    audit = response.compile_public_reach_geometry_response_audit()
    response_artifact = _write_artifact(args.response_output, audit.as_dict())
    report = compile_report(audit=audit, response_artifact=response_artifact)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_json_bytes(report))
    print(args.output)
    print(f"status={report['status']}")
    print(f"gates={sum(report['gates'].values())}/{len(report['gates'])}")
    return 0 if report["all_gates_passed"] else 1


def compile_report(
    *, audit=None, response_artifact: dict[str, object] | None = None
) -> dict[str, Any]:
    if audit is None:
        audit = response.compile_public_reach_geometry_response_audit()
    audit_dict = audit.as_dict()
    if response_artifact is None:
        response_artifact = _memory_artifact(
            DEFAULT_RESPONSE_OUTPUT, audit_dict
        )
    frozen_stage24 = _frozen_hash_report(FROZEN_STAGE24_HASHES)
    distributions = audit_dict["response_distributions"]
    refusals = _refusal_control(audit)
    all_diagnostics = [
        diagnostic
        for item in audit.responses
        for diagnostic in (
            item.state_conditioned_rectangle,
            item.bridge_trapezoid_candidate,
        )
    ]
    gates = {
        "stage24_artifacts_hash_frozen": all(
            value["matches"] for value in frozen_stage24.values()
        ),
        "exactly_twenty_temporal_holdout_states_are_compared": (
            len(audit.responses) == 20
            and tuple(value.measurement_id for value in audit.responses)
            == audit.source.cohort_measurement_ids["temporal_holdout"]
        ),
        "both_geometries_use_identical_observed_area_and_discharge": all(
            item.state_conditioned_rectangle.physical_area_flux_m3s
            == item.observed_state.discharge_m3s
            and item.bridge_trapezoid_candidate.physical_area_flux_m3s
            == item.observed_state.discharge_m3s
            for item in audit.responses
        ),
        "temporal_records_are_not_invented_as_spatial_neighbors": (
            audit_dict["comparison_contract"][
                "temporal_records_treated_as_adjacent_spatial_cells"
            ]
            is False
            and audit_dict["claim_boundary"]["spatial_neighbor_state_observed"]
            is False
        ),
        "all_geometry_diagnostics_are_positive_and_finite": all(
            all(
                math.isfinite(value) and value > 0.0
                for value in (
                    diagnostic.depth_m,
                    diagnostic.top_width_m,
                    diagnostic.gravity_wave_celerity_mps,
                    diagnostic.hydrostatic_pressure_integral_m3,
                    diagnostic.physical_momentum_flux_m4s2,
                )
            )
            for diagnostic in all_diagnostics
        ),
        "both_geometry_hypotheses_retain_subcritical_hll_regime": all(
            diagnostic.minimum_signal_speed_mps < 0.0
            < diagnostic.maximum_signal_speed_mps
            and diagnostic.hll_wave_regime == "subcritical_or_transcritical"
            for diagnostic in all_diagnostics
        ),
        "identical_state_hll_area_flux_matches_observed_discharge": (
            audit_dict["maximum_hll_area_flux_identity_error_m3s"]
            <= response.FLUX_IDENTITY_TOLERANCE
        ),
        "identical_state_hll_momentum_matches_physical_flux": (
            audit_dict["maximum_hll_physical_momentum_identity_error_m4s2"]
            <= response.FLUX_IDENTITY_TOLERANCE
        ),
        "mass_flux_is_geometry_invariant_for_fixed_state": all(
            abs(
                item.state_conditioned_rectangle.hll_area_flux_m3s
                - item.bridge_trapezoid_candidate.hll_area_flux_m3s
            )
            <= response.FLUX_IDENTITY_TOLERANCE
            for item in audit.responses
        ),
        "convective_momentum_is_geometry_invariant_for_fixed_state": all(
            item.state_conditioned_rectangle.convective_momentum_flux_m4s2
            == item.bridge_trapezoid_candidate.convective_momentum_flux_m4s2
            for item in audit.responses
        ),
        "geometry_hypotheses_are_not_numerically_identical": (
            distributions["depth"]["maximum_absolute"] > 0.1
            and distributions["top_width"]["maximum_absolute"] > 0.01
        ),
        "bridge_candidate_is_deeper_for_all_temporal_states": (
            distributions["depth"]["minimum"] > 0.0
        ),
        "hydrostatic_pressure_response_exceeds_materiality_threshold": (
            distributions["hydrostatic_pressure_integral"]["minimum"]
            > response.GEOMETRY_RESPONSE_MATERIALITY
        ),
        "total_momentum_flux_response_exceeds_materiality_threshold": (
            distributions["physical_momentum_flux"]["minimum"]
            > response.GEOMETRY_RESPONSE_MATERIALITY
        ),
        "wave_celerity_response_is_nonzero_and_bounded": (
            distributions["gravity_wave_celerity"]["maximum_absolute"] > 0.01
            and distributions["gravity_wave_celerity"]["maximum_absolute"]
            < 0.10
        ),
        "froude_response_is_finite_without_regime_change": (
            math.isfinite(distributions["froude_number"]["maximum_absolute"])
            and distributions["froude_number"]["maximum_absolute"] < 0.10
        ),
        "candidate_stage_inverse_closes_within_eighteen_centimeters": (
            distributions["bridge_candidate_stage_error_m"]["maximum_absolute"]
            < 0.18
        ),
        "unsupported_runtime_and_transfer_claims_fail_closed": all(
            refusals.values()
        ),
        "runtime_geometry_and_dynamic_time_advance_remain_closed": (
            audit_dict["decision"][
                "stage24_bridge_geometry_admitted_for_runtime"
            ]
            is False
            and audit_dict["claim_boundary"]["dynamic_time_advance_performed"]
            is False
        ),
        "candidate_operator_remains_unadmitted": (
            audit_dict["decision"]["operator_admitted"] is False
        ),
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "location_conditioned_geometry_response_quantified_"
            "runtime_admission_pending"
        ),
        "response_artifact": response_artifact,
        "frozen_stage24_hashes": frozen_stage24,
        "response_summary": distributions,
        "maximum_hll_area_flux_identity_error_m3s": audit_dict[
            "maximum_hll_area_flux_identity_error_m3s"
        ],
        "maximum_hll_physical_momentum_identity_error_m4s2": audit_dict[
            "maximum_hll_physical_momentum_identity_error_m4s2"
        ],
        "typed_refusals": refusals,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "decision": audit_dict["decision"],
        "claim_boundary": audit_dict["claim_boundary"],
    }


def _refusal_control(audit) -> dict[str, bool]:
    calls = {
        "runtime_geometry_rollout": (
            audit.require_runtime_geometry_rollout,
            "public_reach_geometry_response_is_state_diagnostic_only",
        ),
        "reach_wide_geometry_transfer": (
            audit.require_reach_wide_geometry_transfer,
            "public_reach_geometry_response_not_reach_wide_transfer",
        ),
        "confluence_patch_geometry": (
            audit.require_confluence_patch_geometry,
            "public_reach_geometry_response_not_confluence_geometry",
        ),
    }
    results = {}
    for name, (call, message) in calls.items():
        try:
            call()
        except ValueError as exc:
            results[name] = str(exc) == message
        else:
            results[name] = False
    return results


def _frozen_hash_report(
    expected: dict[str, str],
) -> dict[str, dict[str, object]]:
    results = {}
    for relative, digest in expected.items():
        actual = _sha256(REPO_ROOT / relative)
        results[relative] = {
            "expected_sha256": digest,
            "actual_sha256": actual,
            "matches": digest == actual,
        }
    return results


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
