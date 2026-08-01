#!/usr/bin/env python3
"""Compile Stage 40 component-discharge value support gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent.uwm.geospatial_kernel_v2 import (  # noqa: E402
    public_component_discharge_value_support as evidence,
)

DEFAULT_DATA_ROOT = REPO_ROOT / evidence.STAGE40_ROOT
DEFAULT_LEDGER_OUTPUT = DEFAULT_DATA_ROOT / ("component_discharge_value_support_ledger.json")
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/stage40_component_discharge_value_support_gates.json"
)
STAGE39_GATES_PATH = (
    "benchmarks/geotransport_v0_1/stage39_component_discharge_value_plan_gates.json"
)
EXPECTED_STAGE39_GATES_SHA256 = "6b205a953f4f69f27322366fdbdf86cb7241e03529d13e4fa61fcdab5a179802"
SCHEMA = "gwm.geotransport.stage40_component_discharge_value_support_gates.v1"
STATUS = evidence.STATUS

FROZEN_HASHES = {
    ("data_agent/uwm/geospatial_kernel_v2/component_discharge_value_support.py"): (
        "7ae1c6358c560db3acd7743bc983e551d67c9d90ae11b48e27b43b9661041cea"
    ),
    (
        "data_agent/test_geospatial_kernel_component_discharge_value_support.py"
    ): "bd2639f39876bcbd6d6f28f4c6cd994559ef9ada8a8cb12765bdfa405657338a",
    (
        "data_agent/uwm/geospatial_kernel_v2/public_component_discharge_value_support.py"
    ): "6421089b14d6b82df51225f62058ede76f92b0060bd2fa3aca86230f5afe07e3",
    (
        "data_agent/test_geospatial_kernel_public_component_discharge_value_support.py"
    ): "13d3486c9ca99b048af6ff4d794448feea4376ecf600b967546b2521913f917e",
    (
        "scripts/acquire_geotransport_stage39_component_discharge_values.py"
    ): "97dfc4fce4e1f9512686a154049ccc8b5796dfe8efa84a6eeb1cb251c8aa4500",
    (
        "data_agent/test_acquire_geotransport_stage39_component_discharge_values.py"
    ): "27de41a888ff2034b9d91b8f8b162dbbe1d0c2075742d35d0a8f25b779380d28",
    evidence.PROTOCOL_PATH: evidence.EXPECTED_PROTOCOL_SHA256,
    evidence.PLAN_PATH: evidence.EXPECTED_PLAN_SHA256,
    evidence.STATE_PATH: evidence.EXPECTED_STATE_SHA256,
    evidence.MANIFEST_PATH: evidence.EXPECTED_MANIFEST_SHA256,
    STAGE39_GATES_PATH: EXPECTED_STAGE39_GATES_SHA256,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger-output", type=Path, default=DEFAULT_LEDGER_OUTPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ledger = evidence.compile_public_component_discharge_value_support()
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
    ledger: evidence.PublicComponentDischargeValueSupportLedger | None = None,
    ledger_artifact: dict[str, object] | None = None,
) -> dict[str, Any]:
    if ledger is None:
        ledger = evidence.compile_public_component_discharge_value_support()
    ledger_report = ledger.as_dict()
    if ledger_artifact is None:
        ledger_artifact = _memory_artifact(DEFAULT_LEDGER_OUTPUT, ledger_report)
    frozen = _frozen_hash_report(FROZEN_HASHES)
    stage39_gates = _read_json(REPO_ROOT / STAGE39_GATES_PATH)
    manifest = _read_json(REPO_ROOT / evidence.MANIFEST_PATH)
    components = ledger.support.components
    decision = ledger_report["decision"]
    refusals = _refusal_control(ledger)
    expected_quality = (
        ((-2147480957, 83), (-2147478653, 1571), (0, 42171)),
        ((-2147480957, 83), (-2147478653, 1501), (0, 42241)),
        ((-2147480957, 78), (-2147478653, 1535), (0, 42212)),
        ((-2147480957, 4), (-2147478653, 1664), (0, 42157)),
    )
    gates = {
        "all_eleven_stage39_and_stage40_artifacts_match": all(
            value["matches"] for value in frozen.values()
        ),
        "stage39_protocol_is_exactly_bound": (
            ledger.protocol_artifact["sha256"] == evidence.EXPECTED_PROTOCOL_SHA256
        ),
        "stage39_value_plan_is_exactly_bound": (
            ledger.plan_artifact["sha256"] == evidence.EXPECTED_PLAN_SHA256
        ),
        "stage39_acquisition_state_is_exactly_bound": (
            ledger.acquisition_state_artifact["sha256"] == evidence.EXPECTED_STATE_SHA256
        ),
        "stage39_acquisition_manifest_is_exactly_bound": (
            ledger.acquisition_manifest_artifact["sha256"] == evidence.EXPECTED_MANIFEST_SHA256
        ),
        "stage39_plan_gate_report_is_exactly_bound": (
            frozen[STAGE39_GATES_PATH]["matches"] is True
        ),
        "stage39_plan_gate_status_is_preserved": (
            stage39_gates["all_gates_passed"] is True
            and stage39_gates["status"]
            == "stage39_component_discharge_value_plan_frozen_values_pending_approval"
            and len(stage39_gates["gates"]) == 34
        ),
        "acquisition_code_and_tests_are_frozen": (
            frozen["scripts/acquire_geotransport_stage39_component_discharge_values.py"]["matches"]
            is True
            and frozen[
                "data_agent/test_acquire_geotransport_stage39_component_discharge_values.py"
            ]["matches"]
            is True
        ),
        "all_twenty_requests_succeeded_on_first_attempt": (
            manifest["actual_request_count"] == 20
            and manifest["actual_attempt_count"] == 20
            and all(
                value["attempt_count"] == 1 and value["failed_attempts"] == []
                for value in manifest["artifacts"]
            )
        ),
        "download_bytes_are_exact_and_within_frozen_boundary": (
            manifest["actual_download_bytes"] == 4_225_697
            and manifest["actual_download_bytes"]
            <= manifest["request_boundary"]["maximum_persisted_download_bytes"]
        ),
        "all_twenty_raw_artifacts_are_hash_and_tls_verified": (
            len(ledger.source_artifacts) == 20
            and all(
                value["hash_verified"] is True
                and value["tls_hostname_verification_retained"] is True
                for value in manifest["artifacts"]
            )
        ),
        "component_order_is_orifice_sluice_spillway_turbine": (
            tuple(value.component for value in components)
            == ("orifice", "sluice", "spillway", "turbine")
        ),
        "each_component_has_five_annual_payloads": all(
            value.annual_payload_count == 5 for value in components
        ),
        "each_component_has_43829_raw_rows": (
            tuple(value.raw_row_count for value in components) == (43_829,) * 4
        ),
        "each_component_has_four_identical_boundary_duplicates": (
            tuple(value.duplicate_boundary_row_count for value in components) == (4,) * 4
        ),
        "each_component_has_43825_unique_timestamps": (
            tuple(value.unique_timestamp_count for value in components) == (43_825,) * 4
        ),
        "all_component_hourly_grids_are_complete": all(
            value.complete_hourly_grid for value in components
        ),
        "all_component_missing_timestamp_counts_are_zero": (
            tuple(value.missing_timestamp_count for value in components) == (0,) * 4
        ),
        "all_component_null_value_counts_are_zero": (
            tuple(value.null_value_count for value in components) == (0,) * 4
        ),
        "all_component_negative_value_counts_are_zero": (
            tuple(value.negative_value_count for value in components) == (0,) * 4
        ),
        "all_component_real_value_counts_are_43825": (
            tuple(value.real_value_count for value in components) == (43_825,) * 4
        ),
        "component_zero_value_counts_are_exact": (
            tuple(value.zero_value_count for value in components)
            == (35_361, 43_480, 42_941, 22_259)
        ),
        "component_positive_value_counts_are_exact": (
            tuple(value.positive_value_count for value in components) == (8_464, 345, 884, 21_566)
        ),
        "component_quality_code_histograms_are_exact": (
            tuple(value.quality_code_counts for value in components) == expected_quality
        ),
        "quality_codes_are_not_interpreted_as_approval": (
            decision["quality_code_approval_semantics_admitted"] is False
        ),
        "all_43825_hours_have_synchronized_component_support": (
            ledger.support.eligible_synchronized_hour_count == 43_825
            and ledger.support.missing_component_hour_count == 0
            and ledger.support.null_component_hour_count == 0
            and ledger.support.negative_component_hour_count == 0
        ),
        "synchronized_four_component_value_support_is_admitted": (
            decision["synchronized_four_component_value_support_admitted"] is True
        ),
        "synchronized_total_discharge_values_are_not_compiled": (
            decision["synchronized_total_discharge_values_compiled"] is False
        ),
        "component_discharge_event_is_not_admitted": (
            decision["component_discharge_event_admitted"] is False
        ),
        "no_downstream_outcome_values_were_acquired": (
            decision["downstream_outcome_values_acquired"] is False
        ),
        "gate_commands_remain_rejected": (decision["gate_commands_admitted"] is False),
        "human_actions_remain_rejected": (decision["human_actions_admitted"] is False),
        "causal_interventions_remain_rejected": (
            decision["causal_interventions_admitted"] is False
        ),
        "physical_response_time_remains_rejected": (
            decision["physical_response_time_admitted"] is False
        ),
        "runtime_operators_remain_rejected": (decision["runtime_operators_admitted"] is False),
        "separate_event_selection_protocol_is_required": (
            decision["separate_event_selection_protocol_required"] is True
        ),
        "eight_typed_refusal_controls_fail_closed": all(refusals.values()),
        "stage40_ledger_is_content_addressed": (
            len(str(ledger_artifact["sha256"])) == 64 and int(ledger_artifact["size_bytes"]) > 0
        ),
    }
    return {
        "schema": SCHEMA,
        "compiled_at": datetime.now(UTC).isoformat(),
        "status": STATUS,
        "frozen_artifacts": frozen,
        "stage40_ledger_artifact": ledger_artifact,
        "acquisition_summary": {
            "logical_request_count": manifest["actual_request_count"],
            "actual_attempt_count": manifest["actual_attempt_count"],
            "actual_download_bytes": manifest["actual_download_bytes"],
        },
        "component_summary": [value.as_dict() for value in components],
        "synchronized_support": ledger_report["support"]["synchronized_support"],
        "refusal_controls": refusals,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "decision": decision,
    }


def _refusal_control(
    ledger: evidence.PublicComponentDischargeValueSupportLedger,
) -> dict[str, bool]:
    calls = {
        "quality_approval": ledger.require_quality_approval_semantics,
        "total_values": ledger.require_total_discharge_values,
        "event_selection": ledger.require_event_selection,
        "gate_command": ledger.require_gate_command,
        "human_action": ledger.require_human_action,
        "causal_intervention": ledger.require_causal_intervention,
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


def _memory_artifact(path: Path, value: dict[str, object]) -> dict[str, object]:
    return _artifact(path, _json_bytes(value))


def _artifact(path: Path, body: bytes) -> dict[str, object]:
    return {
        "path": str(path.resolve().relative_to(REPO_ROOT)),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _json_bytes(value: dict[str, object]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("stage40_gate_json_object_required")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
