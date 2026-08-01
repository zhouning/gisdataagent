#!/usr/bin/env python3
"""Compile the no-network Stage 45 replication-target request plan."""

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
    freeze_geotransport_stage45_component_lag_replication_target_protocol as freeze,
)

DEFAULT_OUTPUT = REPO_ROOT / freeze.STAGE45_ROOT / "target_acquisition_plan.json"
SCHEMA = "gwm.geotransport.stage45_component_lag_replication_target_plan.v1"
FROZEN_PROTOCOL_SHA256 = "6c24d7b507bd4046dcd9e5ff329a090c57ab4e2a760609364f1b5e7a4bca790b"
USGS_HOST = "api.waterdata.usgs.gov"
USGS_ROOT = f"https://{USGS_HOST}/ogcapi/v0"
USGS_LICENSE = "USGS public-domain data"
USGS_LICENSE_URL = (
    "https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits"
)
MAXIMUM_LOGICAL_REQUEST_COUNT = 4
MAXIMUM_ATTEMPTS_PER_REQUEST = 3
MAXIMUM_BYTES_PER_ATTEMPT = 2_000_000
MAXIMUM_PERSISTED_DOWNLOAD_BYTES = 8_000_000
MAXIMUM_TOTAL_RESPONSE_BYTES_ACROSS_ATTEMPTS = 24_000_000
OGC_LIMIT = 10_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_plan() -> dict[str, Any]:
    protocol = _load_frozen_protocol()
    sources = _sources(protocol)
    if len(sources) != MAXIMUM_LOGICAL_REQUEST_COUNT:
        raise ValueError("stage45_request_count_boundary_invalid")
    return {
        "schema": SCHEMA,
        "mode": "component_lag_replication_target_value_plan",
        "purpose": (
            "acquire only four bounded Stonewall downstream target windows "
            "after the complete exposure boundary source cohort and strict "
            "high-five-low-six replication hypothesis are hash frozen"
        ),
        "frozen_protocol_artifact": _artifact(freeze.DEFAULT_OUTPUT),
        "request_execution": {
            "network_code_path_present_in_this_planner": False,
            "request_execution_authorized": False,
            "fresh_user_approval_required": True,
            "approval_scope": "exact_four_stage45_logical_requests_only",
        },
        "request_boundary": {
            "allowed_hosts": [USGS_HOST],
            "allowed_http_methods": ["GET"],
            "maximum_logical_request_count": MAXIMUM_LOGICAL_REQUEST_COUNT,
            "maximum_attempts_per_request": MAXIMUM_ATTEMPTS_PER_REQUEST,
            "maximum_total_attempt_count": (
                MAXIMUM_LOGICAL_REQUEST_COUNT * MAXIMUM_ATTEMPTS_PER_REQUEST
            ),
            "maximum_response_bytes_per_attempt": MAXIMUM_BYTES_PER_ATTEMPT,
            "maximum_persisted_download_bytes": (MAXIMUM_PERSISTED_DOWNLOAD_BYTES),
            "maximum_total_response_bytes_across_attempts": (
                MAXIMUM_TOTAL_RESPONSE_BYTES_ACROSS_ATTEMPTS
            ),
            "ogc_limit": OGC_LIMIT,
            "server_returned_pagination_followed": False,
            "unexpected_pagination_policy": "fail_closed",
            "workspace_or_private_data_sent": False,
            "new_cwms_source_values_requested": False,
            "smith_fork_graph_state_values_requested": False,
            "tailwater_elevation_values_requested": False,
            "only_frozen_stonewall_replication_outcomes_requested": True,
        },
        "target_support": {
            "event_count": len(protocol["frozen_events"]),
            "site_count_per_event": 1,
            "sample_interval_minutes": 30,
            "requested_elapsed_hours_per_event": 84,
            "expected_ideal_inclusive_positions_per_event": (
                freeze.EXPECTED_IDEAL_HALF_HOUR_POSITIONS
            ),
            "lag_candidates_hours": list(range(13)),
            "missing_values_filled": False,
            "event_selection_frozen_before_target_values": True,
            "replication_hypothesis_frozen_before_target_values": True,
            "target_operator_frozen_before_target_values": True,
        },
        "strict_replication_hypothesis": protocol["strict_replication_hypothesis"],
        "post_acquisition_allowed_assessment": protocol["post_acquisition_allowed_assessment"],
        "sources": sources,
        "claim_boundary": {
            "exact_request_plan_frozen": True,
            "stage44_source_only_replication_cohort_preserved": True,
            "target_values_acquired": False,
            "replication_test_executed": False,
            "stage43_pattern_replicated": False,
            "stage30_historical_falsification_overturned": False,
            "universal_lag_admitted": False,
            "non_turbine_component_contrast_admitted": False,
            "causal_or_physical_relation_admitted": False,
            "runtime_operator_admitted": False,
        },
    }


def _sources(protocol: dict[str, Any]) -> list[dict[str, Any]]:
    target = protocol["target_source"]
    sources = []
    for event in protocol["frozen_events"]:
        event_id = str(event["event_id"])
        begin = str(event["target_begin_utc"])
        end = str(event["target_end_utc"])
        site_id = str(target["site_id"])
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
        source_id = f"usgs_{short_id}_replication_{event_id}"
        sources.append(
            {
                "source_id": source_id,
                "source": "usgs_water_data",
                "event_id": event_id,
                "selection_rank": event["selection_rank"],
                "selection_stratum": event["selection_stratum"],
                "antecedent_flow_class": event["antecedent_flow_class"],
                "total_direction": event["total_direction"],
                "site_id": site_id,
                "site_role": target["site_role"],
                "parameter_code": target["parameter_code"],
                "begin_utc": begin,
                "end_utc": end,
                "expected_maximum_inclusive_grid_positions": (
                    freeze.EXPECTED_IDEAL_HALF_HOUR_POSITIONS
                ),
                "url": (f"{USGS_ROOT}/collections/continuous/items?{query}"),
                "output_name": f"raw/{source_id}.json",
                "maximum_bytes_per_attempt": MAXIMUM_BYTES_PER_ATTEMPT,
                "role": "blind_component_lag_replication_outcome_values",
                "license": USGS_LICENSE,
                "license_url": USGS_LICENSE_URL,
            }
        )
    return sources


def _load_frozen_protocol() -> dict[str, Any]:
    body = freeze.DEFAULT_OUTPUT.read_bytes()
    if hashlib.sha256(body).hexdigest() != FROZEN_PROTOCOL_SHA256:
        raise ValueError("stage45_frozen_protocol_hash_invalid")
    value = json.loads(body)
    if value != freeze.build_protocol():
        raise ValueError("stage45_frozen_protocol_not_reproducible")
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
    print("planned_requests=4")
    print("network_requests=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
