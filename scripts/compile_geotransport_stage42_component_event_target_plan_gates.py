#!/usr/bin/env python3
"""Compile Stage 42 component-event target protocol and plan gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import (  # noqa: E402
    freeze_geotransport_stage42_component_event_target_protocol as freeze,
)
from scripts import (  # noqa: E402
    plan_geotransport_stage42_component_event_targets as planner,
)

DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "stage42_component_event_target_plan_gates.json"
)
SCHEMA = "gwm.geotransport.stage42_component_event_target_plan_gates.v1"
STATUS = "stage42_component_event_target_plan_frozen_values_pending_approval"
PROTOCOL_PATH = f"{freeze.STAGE42_ROOT}/protocol.json"
PLAN_PATH = f"{freeze.STAGE42_ROOT}/target_acquisition_plan.json"
FROZEN_HASHES = {
    freeze.STAGE41_MANIFEST_PATH: freeze.FROZEN_HASHES[
        freeze.STAGE41_MANIFEST_PATH
    ],
    freeze.STAGE41_LEDGER_PATH: freeze.FROZEN_HASHES[
        freeze.STAGE41_LEDGER_PATH
    ],
    freeze.STAGE41_GATES_PATH: freeze.FROZEN_HASHES[
        freeze.STAGE41_GATES_PATH
    ],
    freeze.TARGET_OPERATOR_PATH: freeze.FROZEN_HASHES[
        freeze.TARGET_OPERATOR_PATH
    ],
    (
        "scripts/freeze_geotransport_stage42_"
        "component_event_target_protocol.py"
    ): "0c3a6558f70ae65a9e5d27f0ce104a2daa91789c543b08f7403566df39eff3e8",
    (
        "data_agent/test_freeze_geotransport_stage42_"
        "component_event_target_protocol.py"
    ): "ce4f24f5351d303a333b5deb5c99203716a9bfc84f167874d0a7b7e1f8ef1b62",
    (
        "scripts/plan_geotransport_stage42_component_event_targets.py"
    ): "0029ca49e53ba93d145a0fe8323614a379d9e0b33ad2e7b5699ec46b765dfac4",
    (
        "data_agent/test_plan_geotransport_stage42_"
        "component_event_targets.py"
    ): "6c3e7434e63c3b3223e3bc590df2e30aee270abc5e07aa8d18ee6dea503d4d31",
    PROTOCOL_PATH: planner.FROZEN_PROTOCOL_SHA256,
    PLAN_PATH: (
        "28519b1c7834527da9b9b8c2bf30e15f15b293e040b264f60cdbf8df88449ef0"
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = compile_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_json_bytes(report))
    print(args.output)
    print(f"status={report['status']}")
    print(f"gates={sum(report['gates'].values())}/{len(report['gates'])}")
    return 0 if report["all_gates_passed"] else 1


def compile_report() -> dict[str, Any]:
    protocol = freeze.build_protocol()
    plan = planner.compile_plan()
    stored_protocol = _read_json(REPO_ROOT / PROTOCOL_PATH)
    stored_plan = _read_json(REPO_ROOT / PLAN_PATH)
    frozen = _frozen_hash_report(FROZEN_HASHES)
    events = protocol["frozen_events"]
    targets = protocol["target_sources"]
    sources = plan["sources"]
    boundary = plan["request_boundary"]
    execution = plan["request_execution"]
    claims = plan["claim_boundary"]
    queries = [parse_qs(urlparse(value["url"]).query) for value in sources]
    expected_windows = [
        ("2025-04-14T16:00:00Z", "2025-04-18T04:00:00Z"),
        ("2023-03-10T20:00:00Z", "2023-03-14T08:00:00Z"),
        ("2021-01-11T16:00:00Z", "2021-01-15T04:00:00Z"),
        ("2021-07-26T03:00:00Z", "2021-07-29T15:00:00Z"),
    ]
    gates = {
        "all_ten_stage41_and_stage42_artifacts_match": all(
            value["matches"] for value in frozen.values()
        ),
        "stage41_event_manifest_is_exactly_bound": (
            frozen[freeze.STAGE41_MANIFEST_PATH]["matches"] is True
        ),
        "stage41_public_ledger_is_exactly_bound": (
            frozen[freeze.STAGE41_LEDGER_PATH]["matches"] is True
        ),
        "stage41_gate_report_is_exactly_bound": (
            frozen[freeze.STAGE41_GATES_PATH]["matches"] is True
        ),
        "empirical_lag_target_operator_is_exactly_bound": (
            frozen[freeze.TARGET_OPERATOR_PATH]["matches"] is True
        ),
        "stage42_protocol_hash_is_exact": (
            frozen[PROTOCOL_PATH]["matches"] is True
        ),
        "stage42_plan_hash_is_exact": frozen[PLAN_PATH]["matches"] is True,
        "stage42_protocol_is_reproducible": stored_protocol == protocol,
        "stage42_plan_is_reproducible": stored_plan == plan,
        "protocol_freeze_performed_no_network_requests": (
            protocol["data_boundary"][
                "network_requests_allowed_during_protocol_freeze"
            ]
            is False
        ),
        "four_exact_stage41_events_are_preserved": (
            tuple(value["event_id"] for value in events)
            == freeze.EXPECTED_EVENT_IDS
            and [value["selection_rank"] for value in events]
            == [1, 2, 3, 4]
        ),
        "all_events_remain_turbine_only_source_steps": all(
            value["dominant_step_component"] == "turbine"
            for value in events
        ),
        "all_events_were_selected_without_target_values": all(
            value["selected_without_target_values"] is True
            for value in events
        ),
        "exact_two_target_sites_are_frozen": (
            [(value["site_id"], value["site_role"]) for value in targets]
            == [
                ("USGS-03424860", "downstream_outcome"),
                ("USGS-03424730", "observed_graph_state"),
            ]
        ),
        "all_targets_use_continuous_discharge_parameter_00060": all(
            value["quantity"] == "continuous_discharge"
            and value["parameter_code"] == "00060"
            for value in targets
        ),
        "four_exact_84_hour_target_windows_are_frozen": (
            [
                (value["target_begin_utc"], value["target_end_utc"])
                for value in events
            ]
            == expected_windows
        ),
        "each_window_has_169_ideal_half_hour_positions": (
            protocol["target_observation_contract"][
                "expected_ideal_inclusive_half_hour_positions"
            ]
            == 169
            and all(
                value["expected_maximum_inclusive_grid_positions"] == 169
                for value in sources
            )
        ),
        "missing_values_remain_unfilled": (
            protocol["target_observation_contract"][
                "missing_samples_filled"
            ]
            is False
            and plan["target_support"]["missing_values_filled"] is False
        ),
        "quality_metadata_is_not_approval_semantics": (
            protocol["target_observation_contract"][
                "quality_metadata_is_approval_semantics"
            ]
            is False
        ),
        "lag_candidates_and_thresholds_are_frozen": (
            protocol["frozen_target_functional"]["lag_candidates_hours"]
            == list(range(13))
            and protocol["frozen_target_functional"][
                "minimum_pearson_r"
            ]
            == 0.8
            and protocol["frozen_target_functional"][
                "maximum_best_loss_pearson_r"
            ]
            == 0.02
            and protocol["frozen_target_functional"][
                "minimum_pair_count"
            ]
            == 60
        ),
        "supported_lag_is_not_physical_travel_time": (
            protocol["frozen_target_functional"][
                "supported_lag_is_physical_travel_time"
            ]
            is False
        ),
        "eight_logical_requests_are_exact": (
            len(sources) == 8
            and boundary["maximum_logical_request_count"] == 8
        ),
        "request_order_is_event_then_downstream_and_graph_state": (
            [value["event_id"] for value in sources]
            == [event_id for event_id in freeze.EXPECTED_EVENT_IDS for _ in range(2)]
            and [value["site_id"] for value in sources]
            == ["USGS-03424860", "USGS-03424730"] * 4
        ),
        "all_request_windows_match_frozen_events": all(
            (source["begin_utc"], source["end_utc"])
            == expected_windows[(index // 2)]
            for index, source in enumerate(sources)
        ),
        "all_requests_use_https_allowlisted_usgs_host": all(
            urlparse(value["url"]).scheme == "https"
            and urlparse(value["url"]).hostname == planner.USGS_HOST
            for value in sources
        ),
        "all_queries_preserve_site_parameter_limit_and_time": all(
            query
            == {
                "f": ["json"],
                "limit": ["10000"],
                "monitoring_location_id": [source["site_id"]],
                "parameter_code": ["00060"],
                "datetime": [
                    f"{source['begin_utc']}/{source['end_utc']}"
                ],
            }
            for source, query in zip(sources, queries, strict=True)
        ),
        "all_requests_preserve_usgs_public_domain_terms": all(
            value["license"] == planner.USGS_LICENSE
            and value["license_url"] == planner.USGS_LICENSE_URL
            for value in sources
        ),
        "per_attempt_response_is_bounded_to_two_megabytes": (
            boundary["maximum_response_bytes_per_attempt"] == 2_000_000
            and all(
                value["maximum_bytes_per_attempt"] == 2_000_000
                for value in sources
            )
        ),
        "retry_and_response_worst_case_are_explicit": (
            boundary["maximum_attempts_per_request"] == 3
            and boundary["maximum_total_attempt_count"] == 24
            and boundary["maximum_persisted_download_bytes"] == 16_000_000
            and boundary["maximum_total_response_bytes_across_attempts"]
            == 48_000_000
        ),
        "unexpected_pagination_fails_closed_without_following": (
            boundary["server_returned_pagination_followed"] is False
            and boundary["unexpected_pagination_policy"] == "fail_closed"
        ),
        "no_private_cwms_or_tailwater_values_are_requested": (
            boundary["workspace_or_private_data_sent"] is False
            and boundary["new_cwms_source_values_requested"] is False
            and boundary["tailwater_elevation_values_requested"] is False
        ),
        "planner_has_no_network_execution_path": (
            execution["network_code_path_present_in_this_planner"] is False
        ),
        "fresh_user_approval_is_required_before_execution": (
            execution["request_execution_authorized"] is False
            and execution["fresh_user_approval_required"] is True
        ),
        "target_values_and_lag_support_remain_unadmitted": (
            claims["target_values_acquired"] is False
            and claims["empirical_lag_support_sets_compiled"] is False
            and claims["common_empirical_lag_support_admitted"] is False
        ),
        "non_turbine_component_contrast_remains_rejected": (
            claims["non_turbine_component_contrast_admitted"] is False
        ),
        "observed_response_and_causality_remain_rejected": (
            claims["observed_downstream_response_admitted"] is False
            and claims["causal_intervention_admitted"] is False
        ),
        "physical_time_and_runtime_promotions_remain_rejected": (
            claims["physical_response_time_admitted"] is False
            and claims["runtime_operator_admitted"] is False
        ),
    }
    decision = {
        "stage41_source_only_events_preserved": True,
        "component_event_target_protocol_frozen": True,
        "component_event_target_request_plan_frozen": True,
        "planned_logical_request_count": len(sources),
        "planned_event_count": len(events),
        "planned_site_count_per_event": len(targets),
        "target_values_acquired": False,
        "empirical_lag_support_sets_compiled": False,
        "common_empirical_lag_support_admitted": False,
        "non_turbine_component_contrast_admitted": False,
        "observed_downstream_response_admitted": False,
        "causal_interventions_admitted": False,
        "physical_response_time_admitted": False,
        "runtime_operators_admitted": False,
        "fresh_user_approval_required_before_target_requests": True,
    }
    return {
        "schema": SCHEMA,
        "compiled_at": datetime.now(UTC).isoformat(),
        "status": STATUS,
        "frozen_artifacts": frozen,
        "protocol_artifact": _artifact(REPO_ROOT / PROTOCOL_PATH),
        "target_acquisition_plan_artifact": _artifact(REPO_ROOT / PLAN_PATH),
        "request_boundary": boundary,
        "request_sources": sources,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "decision": decision,
    }


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


def _artifact(path: Path) -> dict[str, object]:
    body = path.read_bytes()
    return {
        "path": str(path.resolve().relative_to(REPO_ROOT)),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("stage42_gate_json_object_required")
    return value


def _json_bytes(value: dict[str, object]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
