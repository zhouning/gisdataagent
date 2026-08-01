#!/usr/bin/env python3
"""Compile Stage 36 hydraulic-boundary response evidence gates."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import (
    public_hydraulic_boundary_response as evidence,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = REPO_ROOT / evidence.STAGE36_ROOT
DEFAULT_LEDGER_OUTPUT = DEFAULT_DATA_ROOT / (
    "hydraulic_boundary_response_evidence_ledger.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "stage36_hydraulic_boundary_response_gates.json"
)
SCHEMA = "gwm.geotransport.stage36_hydraulic_boundary_response_gates.v1"
STATUS = "blind_hydraulic_boundary_departure_support_rejected"

FROZEN_STAGE36_HASHES = {
    "data_agent/uwm/geospatial_kernel_v2/hydraulic_boundary_perturbation.py": (
        "ae3b8e856301d3a0dd2afdf3dc1d03aa4080c66ec2cbe7455243bce6bff13b3f"
    ),
    (
        "scripts/freeze_geotransport_stage36_"
        "hydraulic_boundary_event_protocol.py"
    ): "75b1275d8978d9f1e699f5571653d16ef2f648eac810aa05d8f7d3f185f460b5",
    (
        "scripts/acquire_geotransport_stage36_"
        "hydraulic_boundary_events.py"
    ): "9299138feb32918d930ac423ac644de5ec983fc812eb8643d9029978908d1866",
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "public_hydraulic_boundary_response.py"
    ): "d8c1000ddb465e026ce888f56f86185ed9a32294fe2842514c7e8eb485b65823",
    (
        "data_agent/"
        "test_geospatial_kernel_public_hydraulic_boundary_response.py"
    ): "24c9aa359489a998f10ce6c231cf946a874529ecbf493f3dfff528ebaa4b047c",
    f"{evidence.STAGE36_ROOT}/protocol.json": (
        "b0be7dedec2b7dfd933f2c81ea16a2b6bf853a3acafa499fd9beef84f7551ff7"
    ),
    f"{evidence.STAGE36_ROOT}/selection_plan.json": (
        "bee38f828d4a40fb9322e3cbf9bb14181b7e976b2a6e93c31423493c1f8e66a2"
    ),
    f"{evidence.STAGE36_ROOT}/event_selection_manifest.json": (
        "532a94a860b65d46f2361703c6acd6c1dafa2a4ab5860b801aebe339960a7540"
    ),
    f"{evidence.STAGE36_ROOT}/observation_plan.json": (
        "6402bbe5ef8fabca8090590b97379cc422bfbc557df53829f23cbfd5869e4f6f"
    ),
    f"{evidence.STAGE36_ROOT}/observation_acquisition_manifest.json": (
        "88c88416741287984ab5091e3d6e4a6d95384dad14a545832e76c50bf784a269"
    ),
}

EXPECTED_SOURCE_HASHES = {
    "cwms_tailwater_stage_part_1": (
        "7c4a6928fd3591783b4d33d25adc56c8df1932b3aaca12ac70197c608f92355c"
    ),
    "cwms_tailwater_stage_part_2": (
        "4815f3687d9ca1651c6bbaa9169931d89ea0cc15c6f63c5b62a01bafc194d0a2"
    ),
    "cwms_tailwater_stage_part_3": (
        "1f78055689f7f24fca2d1f535084e958d06bd810779ecf4df51d35869b5b0e84"
    ),
    "cwms_tailwater_stage_part_4": (
        "48d4cba0400b07935b6e219f0f85e526aad68aaa8427ff164fbe7de64d755299"
    ),
    "cwms_tailwater_stage_part_5": (
        "65c46c7bc95b123d6d573a5f95938efb9320db95ea52d3470c3144aa53ca1650"
    ),
    "usgs_downstream_tailwater_stage_change_20231004T1730Z": (
        "4f24874be03bf43d09734cdf24e146c5386506e158eb7fae62ba7daf05b45ced"
    ),
    "usgs_downstream_tailwater_stage_change_20210901T1530Z": (
        "f35efac377c4f015fbc3ac23a6e20ef6730f00e0360568faa45894b43c3d0ccb"
    ),
    "usgs_downstream_tailwater_stage_change_20210303T2330Z": (
        "c636833cb64641b54862a1d43c3ca2931b26362f90479e4dbb2642e80a28e8ef"
    ),
    "usgs_downstream_tailwater_stage_change_20220903T1630Z": (
        "d74a9cb9b1d5c5732b3db3d0f00065997e7628a283b08855527660045ef6f7f3"
    ),
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
    ledger = evidence.compile_public_hydraulic_boundary_response()
    ledger_artifact = _write_artifact(args.ledger_output, ledger.as_dict())
    report = compile_report(ledger=ledger, ledger_artifact=ledger_artifact)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_json_bytes(report))
    print(args.output)
    print(f"status={report['status']}")
    print(f"gates={sum(report['gates'].values())}/{len(report['gates'])}")
    return 0 if report["all_gates_passed"] else 1


def compile_report(
    *,
    ledger: evidence.PublicHydraulicBoundaryResponseLedger | None = None,
    ledger_artifact: dict[str, object] | None = None,
) -> dict[str, Any]:
    if ledger is None:
        ledger = evidence.compile_public_hydraulic_boundary_response()
    ledger_report = ledger.as_dict()
    if ledger_artifact is None:
        ledger_artifact = _memory_artifact(
            DEFAULT_LEDGER_OUTPUT, ledger_report
        )
    frozen = _frozen_hash_report(FROZEN_STAGE36_HASHES)
    events = ledger.events
    reports = [value.target_report for value in events]
    source_hashes = {
        str(value["source_id"]): str(value["sha256"])
        for value in ledger.source_artifacts
    }
    refusals = _refusal_control(ledger)
    expected_medians = (
        111.56837557248001,
        259.94865171456,
        99.53371577088001,
    )
    expected_mads = (
        45.44853878015999,
        41.625764490240016,
        73.737068525568,
    )
    expected_thresholds = (
        269.5280143818608,
        246.8574337329194,
        437.2903111840285,
    )
    assessable_reports = [value for value in reports if value is not None]
    gates = {
        "all_ten_stage36_code_and_freeze_artifacts_match": all(
            value["matches"] for value in frozen.values()
        ),
        "source_and_target_operator_remains_hash_frozen": (
            ledger.operator_artifact["sha256"]
            == FROZEN_STAGE36_HASHES[
                "data_agent/uwm/geospatial_kernel_v2/"
                "hydraulic_boundary_perturbation.py"
            ]
        ),
        "protocol_was_frozen_before_candidate_or_outcome_values": (
            ledger.protocol_artifact["sha256"]
            == FROZEN_STAGE36_HASHES[f"{evidence.STAGE36_ROOT}/protocol.json"]
        ),
        "selection_plan_was_frozen_before_candidate_pool_values": (
            ledger.selection_plan_artifact["sha256"]
            == FROZEN_STAGE36_HASHES[
                f"{evidence.STAGE36_ROOT}/selection_plan.json"
            ]
        ),
        "events_were_frozen_before_downstream_values": (
            ledger.event_selection_manifest_artifact["sha256"]
            == FROZEN_STAGE36_HASHES[
                f"{evidence.STAGE36_ROOT}/event_selection_manifest.json"
            ]
        ),
        "observation_plan_was_frozen_before_downstream_values": (
            ledger.observation_plan_artifact["sha256"]
            == FROZEN_STAGE36_HASHES[
                f"{evidence.STAGE36_ROOT}/observation_plan.json"
            ]
        ),
        "acquisition_manifest_records_four_bounded_requests": (
            ledger.observation_acquisition_manifest_artifact["sha256"]
            == FROZEN_STAGE36_HASHES[
                f"{evidence.STAGE36_ROOT}/"
                "observation_acquisition_manifest.json"
            ]
        ),
        "all_nine_raw_sources_match_exact_hashes": (
            source_hashes == EXPECTED_SOURCE_HASHES
        ),
        "all_nine_raw_sources_are_hash_and_tls_verified": all(
            value.get("hash_verified") is True
            and value.get("tls_hostname_verification_retained") is True
            for value in ledger.source_artifacts
        ),
        "four_expected_blind_events_and_ranks_are_preserved": (
            tuple(value.event_id for value in events)
            == evidence.EXPECTED_EVENT_IDS
            and tuple(value.selection_rank for value in events)
            == (1, 2, 3, 4)
        ),
        "all_source_events_pass_the_frozen_source_gate": all(
            value.source_perturbation["blind_target_test_admissible"] is True
            for value in events
        ),
        "all_downstream_samples_are_approved": all(
            value.approved_sample_count == value.raw_sample_count
            for value in events
        ),
        "raw_sample_counts_preserve_the_hourly_2023_window": (
            [value.raw_sample_count for value in events] == [48, 97, 97, 97]
        ),
        "half_hour_grid_missingness_is_preserved_without_fill": (
            [value.grid_missing_sample_count for value in events]
            == [49, 0, 0, 0]
        ),
        "baseline_real_sample_counts_are_exact": (
            [value.baseline_real_sample_count for value in events]
            == [18, 36, 36, 36]
        ),
        "search_real_sample_counts_are_exact": (
            [value.search_real_sample_count for value in events]
            == [12, 24, 24, 24]
        ),
        "2023_event_fails_closed_on_baseline_support": (
            events[0].target_functional_assessable is False
            and events[0].target_support_rejection_reasons
            == (evidence.BASELINE_SUPPORT_REJECTION,)
        ),
        "remaining_three_events_are_target_assessable": (
            [value.target_functional_assessable for value in events]
            == [False, True, True, True]
            and ledger.assessable_event_count == 3
        ),
        "assessable_baseline_medians_match_frozen_computation": all(
            abs(value.baseline_median_m3s - expected) < 1e-12
            for value, expected in zip(
                assessable_reports, expected_medians, strict=True
            )
        ),
        "assessable_baseline_mads_match_frozen_computation": all(
            abs(value.baseline_mad_m3s - expected) < 1e-12
            for value, expected in zip(
                assessable_reports, expected_mads, strict=True
            )
        ),
        "assessable_departure_thresholds_match_frozen_formula": all(
            abs(value.departure_threshold_m3s - expected) < 1e-12
            for value, expected in zip(
                assessable_reports, expected_thresholds, strict=True
            )
        ),
        "assessable_search_windows_have_no_missing_samples": all(
            value.search_missing_sample_count == 0
            for value in assessable_reports
        ),
        "no_assessable_event_crosses_the_frozen_departure_gate": (
            ledger.detected_event_count == 0
            and all(not value.detected for value in assessable_reports)
        ),
        "all_event_target_assessability_is_rejected": (
            ledger.all_events_target_functional_assessable is False
        ),
        "all_assessable_event_departure_detection_is_rejected": (
            ledger.all_assessable_events_detect_departure is False
        ),
        "all_event_statistical_departure_support_is_rejected": (
            ledger_report["decision"][
                "all_event_statistical_departure_support_admitted"
            ]
            is False
        ),
        "causal_release_response_is_rejected": (
            ledger_report["decision"]["causal_release_response_admitted"]
            is False
        ),
        "physical_first_arrival_is_rejected": (
            ledger_report["decision"]["physical_first_arrival_admitted"]
            is False
        ),
        "physical_travel_time_is_rejected": (
            ledger_report["decision"]["physical_travel_time_admitted"]
            is False
        ),
        "runtime_operator_is_rejected": (
            ledger_report["decision"]["runtime_operator_admitted"] is False
        ),
        "typed_refusal_controls_fail_closed": all(refusals.values()),
        "evidence_ledger_is_content_addressed": (
            len(str(ledger_artifact["sha256"])) == 64
            and int(ledger_artifact["size_bytes"]) > 0
        ),
    }
    decision = dict(ledger_report["decision"])
    decision["stage36_status"] = STATUS
    return {
        "schema": SCHEMA,
        "compiled_at": datetime.now(UTC).isoformat(),
        "status": STATUS,
        "frozen_stage36_artifacts": frozen,
        "evidence_ledger_artifact": ledger_artifact,
        "diagnostic_summary": ledger_report["diagnostic_summary"],
        "refusal_controls": refusals,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "decision": decision,
    }


def _refusal_control(
    ledger: evidence.PublicHydraulicBoundaryResponseLedger,
) -> dict[str, bool]:
    calls = {
        "all_event_departures": ledger.require_all_event_statistical_departures,
        "causal_release_response": ledger.require_causal_release_response,
        "physical_first_arrival": ledger.require_physical_first_arrival,
        "physical_travel_time": ledger.require_physical_travel_time,
        "runtime_operator": ledger.promote_to_runtime_operator,
    }
    result = {}
    for key, call in calls.items():
        try:
            call()
        except ValueError:
            result[key] = True
        else:
            result[key] = False
    return result


def _frozen_hash_report(
    expected: dict[str, str],
) -> dict[str, dict[str, object]]:
    return {
        path: {
            "expected_sha256": digest,
            "actual_sha256": _sha256(REPO_ROOT / path),
            "matches": _sha256(REPO_ROOT / path) == digest,
        }
        for path, digest in expected.items()
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_artifact(path: Path, value: dict[str, object]) -> dict[str, object]:
    body = _json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return _artifact(path, body)


def _memory_artifact(
    path: Path, value: dict[str, object]
) -> dict[str, object]:
    return _artifact(path, _json_bytes(value))


def _artifact(path: Path, body: bytes) -> dict[str, object]:
    return {
        "path": str(path.resolve().relative_to(REPO_ROOT)),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _json_bytes(value: dict[str, object]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
