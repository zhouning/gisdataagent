#!/usr/bin/env python3
"""Compile Stage 26 observed-anchor local-perturbation gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import (
    public_reach_local_perturbation as perturbation,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/stage26_center_hill_local_perturbation"
)
DEFAULT_PERTURBATION_OUTPUT = (
    DEFAULT_DATA_ROOT / "observed_anchor_local_perturbation.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "stage26_public_local_perturbation_gates.json"
)
SCHEMA = "gwm.geotransport.stage26_public_local_perturbation_gates.v1"

FROZEN_STAGE25_HASHES = {
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "public_reach_geometry_response.py"
    ): "849d60993c6e06bdd2661000a8aef413c58a5075d93e92c84d0fcb7e71818112",
    (
        "data_agent/test_geospatial_kernel_public_reach_geometry_response.py"
    ): "9fe357149895d1fb54167e6ca29dec83b5b6b2b22f9e008420779599934cbcf7",
    (
        "scripts/compile_geotransport_stage25_public_geometry_response_gates.py"
    ): "0063261abe72a82a669f3b99f6db804188b7efb4c3c3ec056b1685a35cb67ff0",
    (
        "data/geotransport_v0_1/stage25_center_hill_geometry_response/"
        "geometry_hydrodynamic_response.json"
    ): "48e212176dc833a1d8c8bdac196d70d7314a53d2a1b9172b2e1cbc65020a090b",
    (
        "benchmarks/geotransport_v0_1/"
        "stage25_public_geometry_response_gates.json"
    ): "492512f5e8cf87f5f4e59c022c82ef890073f24975a3a24065ac608c1e83e1c9",
    (
        "docs/architecture-decisions/"
        "adr-066-public-observed-state-geometry-response.md"
    ): "243a8a12051f56b752eb2ca1b6575c478c776e8e757217df3ab85023d11d0785",
    (
        "data/geotransport_v0_1/"
        "stage25_center_hill_geometry_response/README.md"
    ): "f01aa3fc3f1f5393c20d7af286dba3c231daf5cb75532aa051c03a7f992cf6ab",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--perturbation-output",
        type=Path,
        default=DEFAULT_PERTURBATION_OUTPUT,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    audit = perturbation.compile_public_reach_local_perturbation_audit()
    artifact = _write_artifact(args.perturbation_output, audit.as_dict())
    report = compile_report(audit=audit, perturbation_artifact=artifact)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_json_bytes(report))
    print(args.output)
    print(f"status={report['status']}")
    print(f"gates={sum(report['gates'].values())}/{len(report['gates'])}")
    return 0 if report["all_gates_passed"] else 1


def compile_report(
    *, audit=None, perturbation_artifact: dict[str, object] | None = None
) -> dict[str, Any]:
    if audit is None:
        audit = perturbation.compile_public_reach_local_perturbation_audit()
    audit_dict = audit.as_dict()
    if perturbation_artifact is None:
        perturbation_artifact = _memory_artifact(
            DEFAULT_PERTURBATION_OUTPUT, audit_dict
        )
    frozen_stage25 = _frozen_hash_report(FROZEN_STAGE25_HASHES)
    distributions = audit_dict["response_distributions"]
    refusals = _refusal_control(audit)
    steps = [
        step
        for value in audit.perturbations
        for step in (
            value.state_conditioned_rectangle,
            value.bridge_trapezoid_candidate,
        )
    ]
    gates = {
        "stage25_artifacts_hash_frozen": all(
            value["matches"] for value in frozen_stage25.values()
        ),
        "exactly_twenty_observed_anchor_states_are_used": (
            len(audit.perturbations) == 20
            and tuple(value.measurement_id for value in audit.perturbations)
            == tuple(value.measurement_id for value in audit.source.responses)
        ),
        "declared_symmetric_five_percent_patterns_are_exact": all(
            value.input_state.area_m2
            == tuple(
                value.anchor_area_m2 * multiplier
                for multiplier in perturbation.AREA_MULTIPLIERS
            )
            and value.input_state.discharge_m3s
            == tuple(
                value.anchor_discharge_m3s * multiplier
                for multiplier in perturbation.DISCHARGE_MULTIPLIERS
            )
            for value in audit.perturbations
        ),
        "observed_anchors_and_manufactured_perturbations_are_distinguished": (
            audit_dict["perturbation_contract"]["anchor_state_observed"] is True
            and audit_dict["perturbation_contract"]["perturbed_states_observed"]
            is False
        ),
        "periodic_grid_is_explicitly_numerical_not_real_reach_topology": (
            audit_dict["perturbation_contract"][
                "cell_length_is_observed_reach_discretization"
            ]
            is False
            and audit_dict["perturbation_contract"][
                "periodic_ring_is_real_reach_topology"
            ]
            is False
        ),
        "every_anchor_uses_minimum_stable_timestep_across_geometries": all(
            value.shared_timestep_seconds
            == min(
                value.state_conditioned_rectangle
                .geometry_stable_timestep_seconds,
                value.bridge_trapezoid_candidate
                .geometry_stable_timestep_seconds,
            )
            for value in audit.perturbations
        ),
        "all_shared_timesteps_are_positive_and_finite": (
            distributions["shared_timestep_seconds"]["minimum"] > 0.0
            and math.isfinite(
                distributions["shared_timestep_seconds"]["maximum"]
            )
        ),
        "all_steps_respect_target_courant_number": (
            audit_dict["maximum_courant_number"]
            <= perturbation.TARGET_COURANT_NUMBER + 1e-12
        ),
        "all_steps_remain_finite_and_strictly_wet": (
            audit_dict["minimum_area_after_m2"] > 0.0
            and all(step.forward.finite_state for step in steps)
            and all(step.forward.nonnegative_area for step in steps)
        ),
        "periodic_volume_ledger_closes": (
            audit_dict["maximum_absolute_volume_ledger_error_m3"]
            <= perturbation.LEDGER_TOLERANCE
        ),
        "periodic_discharge_integral_ledger_closes": (
            audit_dict["maximum_absolute_discharge_ledger_error_m4s"]
            <= perturbation.LEDGER_TOLERANCE
        ),
        "perturbation_reversal_is_translation_covariant": (
            audit_dict["maximum_reversal_area_covariance_error_m2"]
            <= perturbation.REVERSAL_TOLERANCE
            and audit_dict["maximum_reversal_discharge_covariance_error_m3s"]
            <= perturbation.REVERSAL_TOLERANCE
        ),
        "both_geometries_receive_identical_manufactured_input": all(
            value.state_conditioned_rectangle.shared_timestep_seconds
            == value.bridge_trapezoid_candidate.shared_timestep_seconds
            == value.shared_timestep_seconds
            for value in audit.perturbations
        ),
        "geometry_response_propagates_into_updated_area": (
            distributions["maximum_area_geometry_response_relative"]["maximum"]
            > 0.0
        ),
        "geometry_response_is_material_in_updated_discharge_for_some_anchor": (
            distributions["maximum_discharge_geometry_response_relative"][
                "maximum"
            ]
            > perturbation.TRANSITION_RESPONSE_MATERIALITY
        ),
        "geometry_changes_stability_limit_without_one_fixed_winner": (
            audit_dict["limiting_geometry_counts"]
            == {
                "stage24_bridge_trapezoid_candidate": 15,
                "state_conditioned_observed_rectangle": 5,
            }
            and distributions[
                "stable_timestep_candidate_relative_to_rectangle"
            ]["minimum"]
            < 0.0
            < distributions[
                "stable_timestep_candidate_relative_to_rectangle"
            ]["maximum"]
        ),
        "unsupported_observed_grid_and_runtime_claims_fail_closed": all(
            refusals.values()
        ),
        "observed_spatial_rollout_remains_unclaimed": (
            audit_dict["decision"]["observed_spatial_rollout_completed"]
            is False
            and audit_dict["claim_boundary"][
                "reach_boundary_conditions_observed"
            ]
            is False
        ),
        "real_reach_grid_and_runtime_operator_remain_closed": (
            audit_dict["decision"]["real_reach_grid_admitted"] is False
            and audit_dict["decision"]["runtime_operator_admitted"] is False
        ),
        "candidate_operator_remains_unadmitted": (
            audit_dict["decision"]["operator_admitted"] is False
        ),
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "observed_anchor_local_transition_verified_"
            "real_reach_runtime_admission_pending"
        ),
        "perturbation_artifact": perturbation_artifact,
        "frozen_stage25_hashes": frozen_stage25,
        "perturbation_contract": audit_dict["perturbation_contract"],
        "response_summary": distributions,
        "limiting_geometry_counts": audit_dict["limiting_geometry_counts"],
        "invariant_summary": {
            "maximum_absolute_volume_ledger_error_m3": audit_dict[
                "maximum_absolute_volume_ledger_error_m3"
            ],
            "maximum_absolute_discharge_ledger_error_m4s": audit_dict[
                "maximum_absolute_discharge_ledger_error_m4s"
            ],
            "maximum_reversal_area_covariance_error_m2": audit_dict[
                "maximum_reversal_area_covariance_error_m2"
            ],
            "maximum_reversal_discharge_covariance_error_m3s": audit_dict[
                "maximum_reversal_discharge_covariance_error_m3s"
            ],
            "maximum_courant_number": audit_dict["maximum_courant_number"],
            "minimum_area_after_m2": audit_dict["minimum_area_after_m2"],
        },
        "typed_refusals": refusals,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "decision": audit_dict["decision"],
        "claim_boundary": audit_dict["claim_boundary"],
    }


def _refusal_control(audit) -> dict[str, bool]:
    calls = {
        "observed_spatial_rollout": (
            audit.require_observed_spatial_rollout,
            "public_reach_local_perturbation_is_manufactured",
        ),
        "real_reach_discretization": (
            audit.require_real_reach_discretization,
            "public_reach_local_perturbation_grid_is_numerical",
        ),
        "runtime_operator": (
            audit.require_runtime_operator,
            "public_reach_local_perturbation_operator_unadmitted",
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
