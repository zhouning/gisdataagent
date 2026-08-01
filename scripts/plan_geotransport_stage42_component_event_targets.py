#!/usr/bin/env python3
"""Compile the no-network Stage 42 component-event target request plan."""

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
    freeze_geotransport_stage42_component_event_target_protocol as freeze,
)

DEFAULT_OUTPUT = REPO_ROOT / freeze.STAGE42_ROOT / "target_acquisition_plan.json"
SCHEMA = "gwm.geotransport.stage42_component_event_target_plan.v1"
FROZEN_PROTOCOL_SHA256 = "f5de9f9fb7b3f33964f2dd72490291362b5c20e9670fd65b539a36039de32fc1"
USGS_HOST = "api.waterdata.usgs.gov"
USGS_ROOT = f"https://{USGS_HOST}/ogcapi/v0"
USGS_LICENSE = "USGS public-domain data"
USGS_LICENSE_URL = (
    "https://www.usgs.gov/information-policies-and-instructions/"
    "copyrights-and-credits"
)
MAXIMUM_LOGICAL_REQUEST_COUNT = 8
MAXIMUM_ATTEMPTS_PER_REQUEST = 3
MAXIMUM_BYTES_PER_ATTEMPT = 2_000_000
MAXIMUM_PERSISTED_DOWNLOAD_BYTES = 16_000_000
MAXIMUM_TOTAL_RESPONSE_BYTES_ACROSS_ATTEMPTS = 48_000_000
OGC_LIMIT = 10_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_plan() -> dict[str, Any]:
    protocol = _load_frozen_protocol()
    sources = _sources(protocol)
    if len(sources) != MAXIMUM_LOGICAL_REQUEST_COUNT:
        raise ValueError("stage42_request_count_boundary_invalid")
    return {
        "schema": SCHEMA,
        "mode": "component_event_target_value_plan",
        "purpose": (
            "acquire bounded Stonewall downstream and Smith Fork graph-state "
            "values only after four component-total events and the empirical "
            "lag-support target functional are hash frozen"
        ),
        "frozen_protocol_artifact": _artifact(freeze.DEFAULT_OUTPUT),
        "request_execution": {
            "network_code_path_present_in_this_planner": False,
            "request_execution_authorized": False,
            "fresh_user_approval_required": True,
        },
        "request_boundary": {
            "allowed_hosts": [USGS_HOST],
            "maximum_logical_request_count": (
                MAXIMUM_LOGICAL_REQUEST_COUNT
            ),
            "maximum_attempts_per_request": MAXIMUM_ATTEMPTS_PER_REQUEST,
            "maximum_total_attempt_count": (
                MAXIMUM_LOGICAL_REQUEST_COUNT
                * MAXIMUM_ATTEMPTS_PER_REQUEST
            ),
            "maximum_response_bytes_per_attempt": (
                MAXIMUM_BYTES_PER_ATTEMPT
            ),
            "maximum_persisted_download_bytes": (
                MAXIMUM_PERSISTED_DOWNLOAD_BYTES
            ),
            "maximum_total_response_bytes_across_attempts": (
                MAXIMUM_TOTAL_RESPONSE_BYTES_ACROSS_ATTEMPTS
            ),
            "ogc_limit": OGC_LIMIT,
            "server_returned_pagination_followed": False,
            "unexpected_pagination_policy": "fail_closed",
            "workspace_or_private_data_sent": False,
            "new_cwms_source_values_requested": False,
            "tailwater_elevation_values_requested": False,
            "only_frozen_downstream_and_graph_state_values_requested": True,
        },
        "target_support": {
            "event_count": len(protocol["frozen_events"]),
            "site_count_per_event": len(protocol["target_sources"]),
            "sample_interval_minutes": 30,
            "requested_elapsed_hours_per_event": 84,
            "expected_ideal_inclusive_positions_per_event_site": (
                freeze.EXPECTED_IDEAL_HALF_HOUR_POSITIONS
            ),
            "lag_candidates_hours": list(range(13)),
            "missing_values_filled": False,
            "event_selection_frozen_before_target_values": True,
            "target_operator_frozen_before_target_values": True,
        },
        "post_acquisition_allowed_assessment": protocol[
            "post_acquisition_allowed_assessment"
        ],
        "sources": sources,
        "claim_boundary": {
            "request_plan_frozen": True,
            "stage41_source_only_events_preserved": True,
            "target_values_acquired": False,
            "empirical_lag_support_sets_compiled": False,
            "common_empirical_lag_support_admitted": False,
            "non_turbine_component_contrast_admitted": False,
            "observed_downstream_response_admitted": False,
            "causal_intervention_admitted": False,
            "physical_response_time_admitted": False,
            "runtime_operator_admitted": False,
        },
    }


def _sources(protocol: dict[str, Any]) -> list[dict[str, Any]]:
    sources = []
    for event in protocol["frozen_events"]:
        event_id = str(event["event_id"])
        begin = str(event["target_begin_utc"])
        end = str(event["target_end_utc"])
        for target in protocol["target_sources"]:
            site_id = str(target["site_id"])
            site_role = str(target["site_role"])
            query = urllib.parse.urlencode(
                {
                    "f": "json",
                    "limit": OGC_LIMIT,
                    "monitoring_location_id": site_id,
                    "parameter_code": target["parameter_code"],
                    "datetime": f"{begin}/{end}",
                }
            )
            short_id = site_id.removeprefix("USGS-")
            sources.append(
                {
                    "source_id": f"usgs_{short_id}_{event_id}",
                    "source": "usgs_water_data",
                    "event_id": event_id,
                    "selection_rank": event["selection_rank"],
                    "selection_stratum": event["selection_stratum"],
                    "site_id": site_id,
                    "site_role": site_role,
                    "parameter_code": target["parameter_code"],
                    "begin_utc": begin,
                    "end_utc": end,
                    "expected_maximum_inclusive_grid_positions": (
                        freeze.EXPECTED_IDEAL_HALF_HOUR_POSITIONS
                    ),
                    "url": (
                        f"{USGS_ROOT}/collections/continuous/items?{query}"
                    ),
                    "output_name": f"raw/usgs_{short_id}_{event_id}.json",
                    "maximum_bytes_per_attempt": MAXIMUM_BYTES_PER_ATTEMPT,
                    "role": f"blind_component_event_{site_role}_values",
                    "license": USGS_LICENSE,
                    "license_url": USGS_LICENSE_URL,
                }
            )
    return sources


def _load_frozen_protocol() -> dict[str, Any]:
    path = freeze.DEFAULT_OUTPUT
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != FROZEN_PROTOCOL_SHA256:
        raise ValueError("stage42_frozen_protocol_hash_invalid")
    value = json.loads(body)
    if value != freeze.build_protocol():
        raise ValueError("stage42_frozen_protocol_not_reproducible")
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
    print("planned_requests=8")
    print("network_requests=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
