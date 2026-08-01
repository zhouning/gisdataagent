#!/usr/bin/env python3
"""Compile Stage 27 public spatial-boundary evidence gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import (
    public_spatial_boundary_evidence as evidence,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/stage27_center_hill_spatial_boundary_evidence"
)
DEFAULT_LEDGER_OUTPUT = DEFAULT_DATA_ROOT / "spatial_boundary_evidence_ledger.json"
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "stage27_public_spatial_boundary_gates.json"
)
SCHEMA = "gwm.geotransport.stage27_public_spatial_boundary_gates.v1"

FROZEN_STAGE26_HASHES = {
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "public_reach_local_perturbation.py"
    ): "effe52c819020fb4729a26c02024b784a587772bc8d74acbd9cb2b0f7c98f5e5",
    (
        "data_agent/test_geospatial_kernel_public_reach_local_perturbation.py"
    ): "71d749e6b819f5752adf3562d4a6ba239caa823ed0c2c1f5d083986b14aaf60c",
    (
        "scripts/compile_geotransport_stage26_public_local_perturbation_gates.py"
    ): "04d7a9c4314e84567385e82fd250f59989e4bab223c6a0a74991fcb9782a8cf9",
    (
        "data/geotransport_v0_1/stage26_center_hill_local_perturbation/"
        "observed_anchor_local_perturbation.json"
    ): "0fb7728dc281b366f6439389181a629125982d01413d7bf6e6e8f687313782fb",
    (
        "benchmarks/geotransport_v0_1/"
        "stage26_public_local_perturbation_gates.json"
    ): "20a3502f0fd29e3693906ad942958f448f339d4272662cfa88fbf1182da9fb2f",
    (
        "docs/architecture-decisions/"
        "adr-067-observed-anchor-local-perturbation-transition.md"
    ): "576ec572af43e62a969590d6796e5b75340b380c13d02fb5d2f03511337419a0",
    (
        "data/geotransport_v0_1/"
        "stage26_center_hill_local_perturbation/README.md"
    ): "bd9db4917b9b5e9e778478f5da555a3292b51d5558809bae45ea35568cb70e69",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ledger-output", type=Path, default=DEFAULT_LEDGER_OUTPUT
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ledger = evidence.compile_public_spatial_boundary_evidence()
    artifact = _write_artifact(args.ledger_output, ledger.as_dict())
    report = compile_report(ledger=ledger, ledger_artifact=artifact)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_json_bytes(report))
    print(args.output)
    print(f"status={report['status']}")
    print(f"gates={sum(report['gates'].values())}/{len(report['gates'])}")
    return 0 if report["all_gates_passed"] else 1


def compile_report(
    *, ledger=None, ledger_artifact: dict[str, object] | None = None
) -> dict[str, Any]:
    if ledger is None:
        ledger = evidence.compile_public_spatial_boundary_evidence()
    ledger_dict = ledger.as_dict()
    if ledger_artifact is None:
        ledger_artifact = _memory_artifact(
            DEFAULT_LEDGER_OUTPUT, ledger_dict
        )
    frozen_stage26 = _frozen_hash_report(FROZEN_STAGE26_HASHES)
    snapshots = ledger.synchronized_snapshots
    candidates = ledger.candidates
    distinct = [value for value in candidates if not value.is_anchor]
    refusals = _refusal_control(ledger)
    gates = {
        "stage26_artifacts_hash_frozen": all(
            value["matches"] for value in frozen_stage26.values()
        ),
        "acquisition_is_public_bounded_and_private_free": (
            ledger.request_boundary["workspace_or_private_data_sent"] is False
            and len(ledger.source_artifacts)
            <= ledger.request_boundary["maximum_request_count"]
            and sum(
                int(value["size_bytes"]) for value in ledger.source_artifacts
            )
            <= ledger.request_boundary["maximum_total_download_bytes"]
        ),
        "all_source_artifacts_are_hash_verified": (
            len(ledger.source_artifacts) == 38
            and all(
                len(str(value["sha256"])) == 64
                for value in ledger.source_artifacts
            )
        ),
        "exactly_eleven_nldi_sites_and_ten_spatial_candidates_are_bound": (
            len(candidates) == 11 and len(distinct) == 10
        ),
        "anchor_is_bound_to_target_comid": any(
            value.is_anchor and value.comid == evidence.ROOT_COMID
            for value in candidates
        ),
        "all_navigation_directions_are_represented": (
            {
                direction
                for value in candidates
                for direction in value.topology_directions
            }
            == {"upstream_tributaries", "upstream_main", "downstream_main"}
        ),
        "six_spatial_candidates_share_anchor_mainstem": (
            sum(value.same_mainstem_as_anchor for value in distinct) == 6
        ),
        "every_spatial_candidate_has_comid_coordinate_and_distance": all(
            value.comid > 0
            and len(value.coordinate_wgs84) == 2
            and value.distance_from_anchor_m > 0.0
            for value in distinct
        ),
        "parameter_units_and_time_support_are_explicit": all(
            value.parameter_code in evidence.RELEVANT_PARAMETER_CODES
            and value.unit in {"ft", "ft^3/s"}
            and value.begin_utc <= value.end_utc
            for candidate in candidates
            for value in candidate.temporal_series
        ),
        "two_spatially_distinct_synchronized_snapshots_are_found": (
            len(snapshots) == 2
            and all(
                value.candidate.monitoring_location_id != evidence.ANCHOR_SITE_ID
                for value in snapshots
            )
        ),
        "snapshot_candidate_is_nldi_upstream_main_on_same_mainstem": all(
            value.candidate.monitoring_location_id == "USGS-03424010"
            and value.candidate_comid == 18421761
            and value.candidate_topology_directions == ("upstream_main",)
            and value.candidate_same_mainstem_as_anchor
            for value in snapshots
        ),
        "candidate_times_are_bracketed_without_interpolation": all(
            value.anchor_before.time < value.candidate.time < value.anchor_after.time
            and value.as_dict()["synchronization"][
                "linear_interpolation_performed"
            ]
            is False
            for value in snapshots
        ),
        "nearest_time_offsets_respect_fifteen_minute_tolerance": all(
            value.nearest_time_difference_seconds
            <= evidence.NEAREST_OBSERVATION_TOLERANCE_SECONDS
            for value in snapshots
        ),
        "anchor_brackets_respect_thirty_minute_limit": all(
            value.bracket_width_seconds <= evidence.MAXIMUM_BRACKET_SECONDS
            for value in snapshots
        ),
        "snapshot_parameters_and_units_match": all(
            value.candidate.parameter_code
            == value.anchor_before.parameter_code
            == value.anchor_after.parameter_code
            == "00060"
            and value.candidate.unit
            == value.anchor_before.unit
            == value.anchor_after.unit
            == "ft^3/s"
            for value in snapshots
        ),
        "candidate_provisional_status_is_preserved": (
            all(value.candidate.approval_status == "Provisional" for value in snapshots)
            and all(
                value.anchor_before.approval_status == "Approved"
                and value.anchor_after.approval_status == "Approved"
                for value in snapshots
            )
        ),
        "source_license_and_request_limits_are_recorded": (
            ledger.licenses
            == (
                {
                    "license": "USGS public-domain data",
                    "license_url": (
                        "https://www.usgs.gov/information-policies-and-"
                        "instructions/copyrights-and-credits"
                    ),
                },
            )
            and ledger.request_boundary["maximum_candidate_count"] == 12
            and ledger.request_boundary["maximum_match_window_count"] == 4
        ),
        "unsupported_boundary_claims_fail_closed": all(refusals.values()),
        "snapshots_are_not_relabelled_as_continuous_boundaries": (
            ledger_dict["evidence_admission"][
                "spatially_distinct_synchronized_snapshots_admitted"
            ]
            is True
            and ledger_dict["evidence_admission"][
                "continuous_boundary_hydrographs_admitted"
            ]
            is False
        ),
        "observed_spatial_rollout_remains_unclaimed": (
            ledger_dict["decision"]["observed_spatial_rollout_completed"]
            is False
        ),
        "runtime_operator_remains_unadmitted": (
            ledger_dict["decision"]["runtime_operator_admitted"] is False
        ),
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "two_public_spatial_snapshots_verified_"
            "continuous_boundary_hydrographs_pending"
        ),
        "ledger_artifact": ledger_artifact,
        "frozen_stage26_hashes": frozen_stage26,
        "candidate_summary": {
            "candidate_count": len(candidates),
            "spatially_distinct_candidate_count": len(distinct),
            "same_mainstem_spatial_candidate_count": sum(
                value.same_mainstem_as_anchor for value in distinct
            ),
        },
        "snapshot_summary": [
            value.as_dict() for value in snapshots
        ],
        "typed_refusals": refusals,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "decision": ledger_dict["decision"],
        "claim_boundary": ledger_dict["claim_boundary"],
    }


def _refusal_control(ledger) -> dict[str, bool]:
    calls = {
        "continuous_boundary_hydrographs": (
            ledger.require_continuous_boundary_hydrographs,
            "public_spatial_boundary_continuous_hydrographs_unavailable",
        ),
        "fully_approved_spatial_snapshots": (
            ledger.require_fully_approved_spatial_snapshots,
            "public_spatial_boundary_candidate_measurements_provisional",
        ),
        "observed_spatial_rollout": (
            ledger.require_observed_spatial_rollout,
            "public_spatial_boundary_snapshots_are_not_spatial_rollout",
        ),
        "same_site_temporal_substitution": (
            ledger.substitute_anchor_history_for_neighbor,
            "public_spatial_boundary_same_site_temporal_substitution_forbidden",
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
