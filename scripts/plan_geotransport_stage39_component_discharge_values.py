#!/usr/bin/env python3
"""Compile the no-network Stage 39 component-discharge value request plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.parse
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import (  # noqa: E402
    freeze_geotransport_stage39_component_discharge_value_protocol as freeze,
)

DEFAULT_OUTPUT = REPO_ROOT / freeze.STAGE39_ROOT / "value_acquisition_plan.json"
SCHEMA = "gwm.geotransport.stage39_component_discharge_value_acquisition.v1"
FROZEN_PROTOCOL_SHA256 = "b065308dd8b5e44aebd08d3da41dc6a0d822cf4aeb5c5ea5e88500ad95aa557b"
CWMS_HOST = "cwms-data.usace.army.mil"
CWMS_ROOT = f"https://{CWMS_HOST}/cwms-data"
CWMS_OFFICE = "LRN"
CWMS_UNIT = "cms"
CWMS_PAGE_SIZE = 20_000
MAXIMUM_REQUEST_COUNT = 20
MAXIMUM_ATTEMPTS_PER_REQUEST = 3
MAXIMUM_BYTES_PER_ATTEMPT = 1_000_000
MAXIMUM_PERSISTED_DOWNLOAD_BYTES = 20_000_000
MAXIMUM_TOTAL_RESPONSE_BYTES_ACROSS_ATTEMPTS = 60_000_000
SOURCE_TERMS = (
    "USACE CWMS Data API public endpoint; redistribution terms not independently adjudicated"
)
SOURCE_TERMS_URL = "https://cwms-data.usace.army.mil/cwms-data/swagger-ui.html"
EXPECTED_ANNUAL_INCLUSIVE_POSITIONS = {
    2021: 8_761,
    2022: 8_761,
    2023: 8_761,
    2024: 8_785,
    2025: 8_761,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_plan() -> dict[str, Any]:
    protocol = _load_frozen_protocol()
    sources = _sources(protocol)
    if len(sources) != MAXIMUM_REQUEST_COUNT:
        raise ValueError("stage39_request_count_boundary_invalid")
    return {
        "schema": SCHEMA,
        "mode": "component_discharge_value_plan",
        "purpose": (
            "acquire source-only Center Hill component-discharge values for "
            "coverage, quality, duplicate-boundary, and synchronized-support audit"
        ),
        "frozen_protocol_artifact": _artifact(freeze.DEFAULT_OUTPUT),
        "request_execution": {
            "network_code_path_present_in_this_planner": False,
            "request_execution_authorized": False,
            "fresh_user_approval_required": True,
        },
        "request_boundary": {
            "allowed_hosts": [CWMS_HOST],
            "maximum_logical_request_count": MAXIMUM_REQUEST_COUNT,
            "maximum_attempts_per_request": MAXIMUM_ATTEMPTS_PER_REQUEST,
            "maximum_total_attempt_count": (MAXIMUM_REQUEST_COUNT * MAXIMUM_ATTEMPTS_PER_REQUEST),
            "maximum_response_bytes_per_attempt": MAXIMUM_BYTES_PER_ATTEMPT,
            "maximum_persisted_download_bytes": (MAXIMUM_PERSISTED_DOWNLOAD_BYTES),
            "maximum_total_response_bytes_across_attempts": (
                MAXIMUM_TOTAL_RESPONSE_BYTES_ACROSS_ATTEMPTS
            ),
            "workspace_or_private_data_sent": False,
            "downstream_or_tributary_outcome_values_requested": False,
            "tailwater_elevation_values_requested": False,
            "server_returned_pagination_followed": False,
            "unexpected_pagination_policy": "fail_closed",
        },
        "source_support": {
            "component_count": 4,
            "annual_window_count_per_component": 5,
            "begin_utc": freeze.BEGIN_UTC,
            "end_utc": freeze.END_UTC,
            "sample_interval_minutes": 60,
            "expected_unique_inclusive_positions_per_component": (
                freeze.EXPECTED_UNIQUE_HOURLY_POSITIONS_PER_COMPONENT
            ),
            "expected_combined_component_positions": (freeze.EXPECTED_COMBINED_COMPONENT_POSITIONS),
            "annual_windows_share_boundary_samples": True,
            "duplicate_boundary_policy": "require_identical_then_keep_one",
            "missing_values_filled": False,
        },
        "post_acquisition_allowed_assessment": protocol["post_acquisition_assessment_boundary"],
        "sources": sources,
        "claim_boundary": {
            "request_plan_frozen": True,
            "component_values_acquired": False,
            "coverage_or_quality_support_admitted": False,
            "synchronized_total_discharge_admitted": False,
            "component_discharge_event_admitted": False,
            "gate_command_admitted": False,
            "human_action_admitted": False,
            "causal_intervention_admitted": False,
            "physical_response_time_admitted": False,
            "runtime_operator_admitted": False,
        },
    }


def _sources(protocol: dict[str, Any]) -> list[dict[str, Any]]:
    sources = []
    identities = protocol["admitted_source_identities"]
    for identity in identities:
        component = str(identity["component"])
        series_id = str(identity["series_id"])
        for begin, end in freeze.YEAR_WINDOWS:
            year = int(begin[:4])
            query = urllib.parse.urlencode(
                {
                    "name": series_id,
                    "office": CWMS_OFFICE,
                    "begin": begin,
                    "end": end,
                    "unit": CWMS_UNIT,
                    "page-size": CWMS_PAGE_SIZE,
                }
            )
            sources.append(
                {
                    "source_id": f"cwms_center_hill_{component}_{year}",
                    "source": "usace_cwms",
                    "component": component,
                    "series_id": series_id,
                    "office": CWMS_OFFICE,
                    "unit": CWMS_UNIT,
                    "begin_utc": begin,
                    "end_utc": end,
                    "expected_maximum_inclusive_grid_positions": (
                        EXPECTED_ANNUAL_INCLUSIVE_POSITIONS[year]
                    ),
                    "url": f"{CWMS_ROOT}/timeseries?{query}",
                    "output_name": f"raw/cwms_{component}_flow_{year}.json",
                    "maximum_bytes_per_attempt": MAXIMUM_BYTES_PER_ATTEMPT,
                    "role": "source_only_component_discharge_values",
                    "source_terms": SOURCE_TERMS,
                    "source_terms_url": SOURCE_TERMS_URL,
                }
            )
    return sources


def _load_frozen_protocol() -> dict[str, Any]:
    path = freeze.DEFAULT_OUTPUT
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != FROZEN_PROTOCOL_SHA256:
        raise ValueError("stage39_frozen_protocol_hash_invalid")
    value = json.loads(body)
    if value != freeze.build_protocol():
        raise ValueError("stage39_frozen_protocol_not_reproducible")
    return value


def _artifact(path: Path) -> dict[str, object]:
    body = path.read_bytes()
    return {
        "path": str(path.resolve().relative_to(REPO_ROOT)),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> int:
    args = parse_args()
    body = json_bytes(compile_plan())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(body)
    print(args.output)
    print(f"sha256={hashlib.sha256(body).hexdigest()}")
    print("network_requests=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
