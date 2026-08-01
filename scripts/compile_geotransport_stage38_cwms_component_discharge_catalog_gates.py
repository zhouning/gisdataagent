#!/usr/bin/env python3
"""Compile Stage 38 Center Hill CWMS component-catalog gates."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import (
    cwms_component_discharge_catalog as catalog_operator,
)
from data_agent.uwm.geospatial_kernel_v2 import (
    public_cwms_component_discharge_catalog as evidence,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = REPO_ROOT / evidence.STAGE38_ROOT
DEFAULT_LEDGER_OUTPUT = DEFAULT_DATA_ROOT / ("cwms_component_discharge_catalog_ledger.json")
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/stage38_cwms_component_discharge_catalog_gates.json"
)
SCHEMA = "gwm.geotransport.stage38_cwms_component_discharge_catalog_gates.v1"
STATUS = evidence.STATUS

FROZEN_HASHES = {
    ("data_agent/uwm/geospatial_kernel_v2/cwms_component_discharge_catalog.py"): (
        "53d308373fa1a75343056a32bb7878c3ccea773f68f3bf74cd3ee4a32e727bb7"
    ),
    ("data_agent/test_geospatial_kernel_cwms_component_discharge_catalog.py"): (
        "1c9ce5c35db9cab487b242108f3bba3b876cc95e8055fe9520e5dddc0b852dc1"
    ),
    (
        "data_agent/uwm/geospatial_kernel_v2/public_cwms_component_discharge_catalog.py"
    ): "c215c5a77465519d5f0863f896e023540cb3e1b9bf48496e685680a16bf1fdb3",
    (
        "data_agent/test_geospatial_kernel_public_cwms_component_discharge_catalog.py"
    ): "373a5b85dac993c78ed5c883785e50677235e58c0c5488c2ee8ac64dc1b2887a",
    evidence.RAW_CATALOG_PATH: evidence.EXPECTED_RAW_SHA256,
    evidence.ACQUISITION_MANIFEST_PATH: (
        "2c908e632c9f389730f7c5184ed719bdc87bf49f5058ee29832ef19c8d3601ac"
    ),
    evidence.STAGE37_LEDGER_PATH: evidence.EXPECTED_STAGE37_LEDGER_SHA256,
    evidence.STAGE37_GATES_PATH: evidence.EXPECTED_STAGE37_GATES_SHA256,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger-output", type=Path, default=DEFAULT_LEDGER_OUTPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ledger = evidence.compile_public_cwms_component_discharge_catalog()
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
    ledger: evidence.PublicCWMSComponentDischargeCatalogLedger | None = None,
    ledger_artifact: dict[str, object] | None = None,
) -> dict[str, Any]:
    if ledger is None:
        ledger = evidence.compile_public_cwms_component_discharge_catalog()
    ledger_report = ledger.as_dict()
    if ledger_artifact is None:
        ledger_artifact = _memory_artifact(DEFAULT_LEDGER_OUTPUT, ledger_report)
    frozen = _frozen_hash_report(FROZEN_HASHES)
    components = ledger.catalog_evidence.components
    manifest = _read_json(REPO_ROOT / evidence.ACQUISITION_MANIFEST_PATH)
    boundary = manifest["approved_request_boundary"]
    catalog_summary = ledger.catalog_evidence.as_dict()["catalog_summary"]
    decision = ledger_report["decision"]
    refusals = _refusal_control(ledger)
    gates = {
        "all_eight_stage37_and_stage38_artifacts_match": all(
            value["matches"] for value in frozen.values()
        ),
        "raw_catalog_sha256_is_exact": (
            ledger.raw_catalog_artifact["sha256"] == evidence.EXPECTED_RAW_SHA256
        ),
        "raw_catalog_size_is_exact": (
            ledger.raw_catalog_artifact["size_bytes"] == evidence.EXPECTED_RAW_SIZE_BYTES
        ),
        "catalog_manifest_is_content_addressed": (
            ledger.acquisition_manifest_artifact["sha256"]
            == FROZEN_HASHES[evidence.ACQUISITION_MANIFEST_PATH]
        ),
        "one_logical_catalog_request_was_made": (manifest["actual_request_count"] == 1),
        "catalog_request_succeeded_on_first_attempt": (manifest["actual_attempt_count"] == 1),
        "catalog_download_remained_below_one_megabyte": (
            manifest["actual_download_bytes"] == evidence.EXPECTED_RAW_SIZE_BYTES
            and manifest["actual_download_bytes"] <= boundary["maximum_total_download_bytes"]
        ),
        "approved_exact_catalog_url_is_preserved": (boundary["exact_url"] == evidence.CATALOG_URL),
        "no_workspace_data_or_timeseries_values_were_requested": (
            boundary["workspace_or_private_data_sent"] is False
            and boundary["timeseries_values_requested"] is False
        ),
        "catalog_response_has_37_entries_and_no_pagination": (
            catalog_summary["catalog_total"] == 37
            and catalog_summary["entry_count"] == 37
            and catalog_summary["page_size"] == 500
            and catalog_summary["next_page_token_present"] is False
            and catalog_summary["pagination_followed"] is False
        ),
        "stage37_ledger_is_exactly_bound": (
            ledger.stage37_ledger_artifact["sha256"] == evidence.EXPECTED_STAGE37_LEDGER_SHA256
        ),
        "stage37_gate_report_is_exactly_bound": (
            ledger.stage37_gates_artifact["sha256"] == evidence.EXPECTED_STAGE37_GATES_SHA256
        ),
        "stage37_negative_result_is_preserved": (
            decision["stage37_negative_result_preserved"] is True
        ),
        "catalog_total_is_exactly_thirty_seven": (ledger.catalog_evidence.catalog_total == 37),
        "exactly_four_component_sources_are_selected": (len(components) == 4),
        "component_order_is_orifice_sluice_spillway_turbine": (
            tuple(value.component for value in components) == catalog_operator.EXPECTED_COMPONENTS
        ),
        "four_hourly_manual_revision_series_ids_are_exact": (
            tuple(value.series_id for value in components)
            == tuple(
                catalog_operator.EXPECTED_SERIES_IDS[key]
                for key in catalog_operator.EXPECTED_COMPONENTS
            )
        ),
        "four_display_aliases_are_explicit": (
            tuple(value.display_alias for value in components)
            == tuple(
                catalog_operator.EXPECTED_DISPLAY_ALIASES[key]
                for key in catalog_operator.EXPECTED_COMPONENTS
            )
        ),
        "all_component_sources_are_lrn": all(value.office == "LRN" for value in components),
        "all_component_sources_use_cubic_metres_per_second": all(
            value.units == "cms" for value in components
        ),
        "all_component_sources_are_hourly_with_zero_offset": all(
            value.interval == "1Hour" and value.interval_offset == 0 for value in components
        ),
        "all_component_sources_are_manual_revision_series": all(
            value.manually_revised for value in components
        ),
        "all_component_sources_use_us_central_catalog_timezone": all(
            value.time_zone == "US/Central" for value in components
        ),
        "component_earliest_catalog_extents_are_exact": (
            tuple(value.earliest_time_utc for value in components)
            == (
                "2008-08-04T06:00:00Z",
                "2004-09-30T19:00:00Z",
                "1987-05-20T05:00:00Z",
                "1987-05-20T05:00:00Z",
            )
        ),
        "component_latest_catalog_extents_are_exact": (
            {value.latest_time_utc for value in components} == {"2026-07-28T05:00:00Z"}
        ),
        "historical_value_acquisition_is_not_admitted": (
            decision["component_values_acquisition_admitted"] is False
        ),
        "catalog_extents_do_not_admit_continuous_coverage": (
            decision["coverage_continuity_admitted"] is False
        ),
        "catalog_identities_do_not_admit_gate_commands": (
            decision["gate_commands_admitted"] is False
        ),
        "catalog_identities_do_not_admit_human_actions": (
            decision["human_actions_admitted"] is False
        ),
        "catalog_identities_do_not_admit_causal_interventions": (
            decision["causal_interventions_admitted"] is False
        ),
        "catalog_identities_do_not_admit_runtime_operators": (
            decision["runtime_operators_admitted"] is False
        ),
        "separate_bounded_value_plan_is_required": (
            decision["separate_bounded_value_acquisition_plan_required"] is True
        ),
        "six_typed_refusal_controls_fail_closed": all(refusals.values()),
        "stage38_ledger_is_content_addressed": (
            len(str(ledger_artifact["sha256"])) == 64 and int(ledger_artifact["size_bytes"]) > 0
        ),
    }
    return {
        "schema": SCHEMA,
        "compiled_at": datetime.now(UTC).isoformat(),
        "status": STATUS,
        "frozen_artifacts": frozen,
        "stage38_ledger_artifact": ledger_artifact,
        "catalog_summary": catalog_summary,
        "component_summary": [value.as_dict() for value in components],
        "refusal_controls": refusals,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "decision": decision,
    }


def _refusal_control(
    ledger: evidence.PublicCWMSComponentDischargeCatalogLedger,
) -> dict[str, bool]:
    calls = {
        "historical_values": ledger.require_historical_values,
        "continuous_coverage": ledger.require_continuous_coverage,
        "gate_command": ledger.require_gate_command,
        "human_action": ledger.require_human_action,
        "causal_intervention": ledger.require_causal_intervention,
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


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("stage38_gate_json_object_required")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
