#!/usr/bin/env python3
"""Compile Stage 37 hydraulic-boundary falsification attribution gates."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import (
    public_hydraulic_boundary_falsification as evidence,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = REPO_ROOT / evidence.STAGE37_ROOT
DEFAULT_LEDGER_OUTPUT = DEFAULT_DATA_ROOT / (
    "hydraulic_boundary_falsification_ledger.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "stage37_hydraulic_boundary_falsification_gates.json"
)
SCHEMA = "gwm.geotransport.stage37_hydraulic_boundary_falsification_gates.v1"
STATUS = "stage36_falsification_attributed_no_alternative_admitted"

FROZEN_HASHES = {
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "hydraulic_boundary_perturbation.py"
    ): "ae3b8e856301d3a0dd2afdf3dc1d03aa4080c66ec2cbe7455243bce6bff13b3f",
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "public_hydraulic_boundary_response.py"
    ): "d8c1000ddb465e026ce888f56f86185ed9a32294fe2842514c7e8eb485b65823",
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "hydraulic_boundary_falsification.py"
    ): "a4c4158b1d9b51adbf484690a0d52b9cc5156d7384a54b3dbefdce833ca69d6c",
    (
        "data_agent/test_geospatial_kernel_"
        "hydraulic_boundary_falsification.py"
    ): "8dd4548a2545b6bf164902ade301b19cd7fef18071ef7bdd4112d6f1292768cd",
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "public_hydraulic_boundary_falsification.py"
    ): "a2459c9b7e0a38ba138d15f8db92cff7845e32df356ce61bbd2064dd1b013d41",
    (
        "data_agent/test_geospatial_kernel_"
        "public_hydraulic_boundary_falsification.py"
    ): "8cc27c141846e8e2eef528665d9f1a6ae7254a039c23c3948b6982f415b90389",
    evidence.STAGE36_LEDGER_PATH: (
        "81d981243976d147c2a6b2fba78bef2f478095c21fde118d24f57eab88250689"
    ),
    evidence.STAGE36_GATES_PATH: (
        "a48cdfbe0d808dd1e409c4676f75caf92665cef3d7a037c89bde611d8f752e58"
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
    ledger = evidence.compile_public_hydraulic_boundary_falsification()
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
    ledger: evidence.PublicHydraulicBoundaryFalsificationLedger | None = None,
    ledger_artifact: dict[str, object] | None = None,
) -> dict[str, Any]:
    if ledger is None:
        ledger = evidence.compile_public_hydraulic_boundary_falsification()
    ledger_report = ledger.as_dict()
    if ledger_artifact is None:
        ledger_artifact = _memory_artifact(
            DEFAULT_LEDGER_OUTPUT, ledger_report
        )
    frozen = _frozen_hash_report(FROZEN_HASHES)
    events = ledger.events
    assessable = tuple(
        value.attribution
        for value in events
        if value.attribution is not None
    )
    persistent_ratios = (
        0.14288277770843766,
        0.7226686708677803,
        0.18882633012996847,
    )
    single_ratios = (
        0.15128764698540456,
        0.7398750677932036,
        0.19135178516257093,
    )
    shortfalls = (
        231.0171030167408,
        68.46130020331938,
        354.7183865217565,
    )
    refusals = _refusal_control(ledger)
    gates = {
        "all_eight_stage36_and_stage37_artifacts_match": all(
            value["matches"] for value in frozen.values()
        ),
        "stage36_evidence_ledger_is_exactly_bound": (
            ledger.stage36_ledger_artifact["sha256"]
            == FROZEN_HASHES[evidence.STAGE36_LEDGER_PATH]
        ),
        "stage36_gate_report_is_exactly_bound": (
            ledger.stage36_gates_artifact["sha256"]
            == FROZEN_HASHES[evidence.STAGE36_GATES_PATH]
        ),
        "stage37_operator_is_content_addressed": (
            ledger.attribution_operator_artifact["sha256"]
            == FROZEN_HASHES[
                "data_agent/uwm/geospatial_kernel_v2/"
                "hydraulic_boundary_falsification.py"
            ]
        ),
        "four_stage36_event_identities_and_ranks_are_preserved": (
            [value.event_id for value in events]
            == [
                "tailwater_stage_change_20231004T1730Z",
                "tailwater_stage_change_20210901T1530Z",
                "tailwater_stage_change_20210303T2330Z",
                "tailwater_stage_change_20220903T1630Z",
            ]
            and [value.selection_rank for value in events] == [1, 2, 3, 4]
        ),
        "all_four_source_perturbations_are_rises": (
            [value.source_direction for value in events] == ["rise"] * 4
        ),
        "one_event_is_measurement_support_failure": (
            ledger.measurement_support_failure_count == 1
            and events[0].failure_class == evidence.SUPPORT_FAILURE
        ),
        "three_events_are_frozen_threshold_failures": (
            ledger.frozen_threshold_failure_count == 3
            and all(
                value.failure_class == evidence.THRESHOLD_FAILURE
                for value in events[1:]
            )
        ),
        "half_hour_grid_support_is_preserved_without_fill": (
            [value.grid_real_sample_count for value in events]
            == [48, 97, 97, 97]
            and [value.grid_missing_sample_count for value in events]
            == [49, 0, 0, 0]
        ),
        "baseline_support_counts_remain_eighteen_then_thirty_six": (
            [value.baseline_real_sample_count for value in events]
            == [18, 36, 36, 36]
        ),
        "unassessable_event_receives_no_posthoc_attribution": (
            events[0].attribution is None
            and not events[0].frozen_target_functional_assessable
        ),
        "three_assessable_events_reproduce_frozen_target_reports": (
            len(assessable) == 3
            and all(value.target_report.baseline_sample_count == 36 for value in assessable)
        ),
        "robust_mad_dominates_all_assessable_thresholds": all(
            value.dominant_threshold_component == "robust_mad"
            for value in assessable
        ),
        "strongest_persistent_offsets_are_exact": (
            [value.strongest_persistent_start_offset_minutes for value in assessable]
            == [210, 180, 240]
        ),
        "strongest_persistent_directions_are_all_decreases": (
            [value.strongest_persistent_direction for value in assessable]
            == ["decrease", "decrease", "decrease"]
        ),
        "strongest_persistent_threshold_ratios_are_exact": all(
            abs(value.strongest_persistent_threshold_ratio - expected) < 1e-12
            for value, expected in zip(assessable, persistent_ratios, strict=True)
            if value.strongest_persistent_threshold_ratio is not None
        ),
        "maximum_single_sample_threshold_ratios_are_exact": all(
            abs(value.maximum_single_sample_threshold_ratio - expected) < 1e-12
            for value, expected in zip(assessable, single_ratios, strict=True)
        ),
        "persistent_threshold_shortfalls_are_exact": all(
            value.persistent_threshold_shortfall_m3s is not None
            and abs(value.persistent_threshold_shortfall_m3s - expected) < 1e-12
            for value, expected in zip(assessable, shortfalls, strict=True)
        ),
        "no_single_sample_crosses_the_frozen_threshold": (
            ledger.single_sample_threshold_crossing_count == 0
        ),
        "persistence_requirement_is_not_the_decisive_failure": (
            ledger.persistence_only_failure_count == 0
        ),
        "no_assessable_direction_is_concordant_with_source_rise": (
            ledger.direction_concordant_event_count == 0
        ),
        "no_assessable_event_passes_the_frozen_gate": (
            ledger.any_assessable_event_detected is False
            and all(not value.frozen_gate_detected for value in assessable)
        ),
        "stage36_negative_result_is_preserved": (
            ledger_report["decision"]["stage36_negative_result_preserved"]
            is True
        ),
        "only_failure_attribution_is_admitted": (
            ledger_report["decision"]["failure_attribution_admitted"] is True
        ),
        "directional_response_support_is_rejected": (
            ledger_report["decision"][
                "directional_response_support_admitted"
            ]
            is False
        ),
        "alternative_detector_is_rejected": (
            ledger_report["decision"]["alternative_detector_admitted"]
            is False
        ),
        "causal_response_is_rejected": (
            ledger_report["decision"]["causal_response_admitted"] is False
        ),
        "physical_response_time_is_rejected": (
            ledger_report["decision"]["physical_response_time_admitted"]
            is False
        ),
        "runtime_operator_is_rejected": (
            ledger_report["decision"]["runtime_operator_admitted"] is False
        ),
        "typed_refusal_controls_fail_closed": all(refusals.values()),
        "stage37_ledger_is_content_addressed": (
            len(str(ledger_artifact["sha256"])) == 64
            and int(ledger_artifact["size_bytes"]) > 0
        ),
    }
    decision = dict(ledger_report["decision"])
    decision["stage37_status"] = STATUS
    return {
        "schema": SCHEMA,
        "compiled_at": datetime.now(UTC).isoformat(),
        "status": STATUS,
        "frozen_artifacts": frozen,
        "stage37_ledger_artifact": ledger_artifact,
        "diagnostic_summary": ledger_report["diagnostic_summary"],
        "refusal_controls": refusals,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "decision": decision,
    }


def _refusal_control(
    ledger: evidence.PublicHydraulicBoundaryFalsificationLedger,
) -> dict[str, bool]:
    calls = {
        "alternative_detector": ledger.require_alternative_detector,
        "causal_response": ledger.require_causal_response,
        "physical_response_time": ledger.require_physical_response_time,
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
