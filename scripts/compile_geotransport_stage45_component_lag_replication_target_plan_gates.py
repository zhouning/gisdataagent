#!/usr/bin/env python3
"""Compile Stage 45 replication-target protocol and plan gates."""

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
    acquire_geotransport_stage45_component_lag_replication_targets as acquire,
)
from scripts import (  # noqa: E402
    freeze_geotransport_stage45_component_lag_replication_target_protocol as freeze,
)
from scripts import (  # noqa: E402
    plan_geotransport_stage45_component_lag_replication_targets as planner,
)

DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/stage45_component_lag_replication_target_plan_gates.json"
)
SCHEMA = "gwm.geotransport.stage45_component_lag_replication_target_plan_gates.v1"
STATUS = "stage45_component_lag_replication_target_plan_frozen_values_pending_approval"
PROTOCOL_PATH = f"{freeze.STAGE45_ROOT}/protocol.json"
PLAN_PATH = f"{freeze.STAGE45_ROOT}/target_acquisition_plan.json"
FROZEN_HASHES = {
    (
        "scripts/freeze_geotransport_stage45_component_lag_replication_target_protocol.py"
    ): "bd623b2b2c7531f59a5d27330cf1f37faa6b81d86d48e0675f909db9f2ebe5a1",
    (
        "scripts/plan_geotransport_stage45_component_lag_replication_targets.py"
    ): "03cc6a56b76cf652042c36eb550b79213001bca261770952712357116e31105f",
    (
        "scripts/acquire_geotransport_stage45_component_lag_replication_targets.py"
    ): "1bab223eb4e85cd12e47ae6d57ecddde28979341721a71c5bf9002d95c75b348",
    (
        "data_agent/test_freeze_geotransport_stage45_component_lag_replication_target_protocol.py"
    ): "f009511cbbdd6503a76258b662ac2addd0bd8c8fb57598bc995cee779b953c8b",
    (
        "data_agent/test_plan_geotransport_stage45_component_lag_replication_targets.py"
    ): "f774c2d029f107c2e07a2f21f74e74d9e164132e98a900402f24189b7942cfc0",
    (
        "data_agent/test_acquire_geotransport_stage45_component_lag_replication_targets.py"
    ): "4ebbf96570313108da2cdfcaf40569c1b90e5c8056bfd0110a5d508bd61ebeab",
    PROTOCOL_PATH: planner.FROZEN_PROTOCOL_SHA256,
    PLAN_PATH: acquire.FROZEN_PLAN_SHA256,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_report() -> dict[str, Any]:
    protocol = freeze.build_protocol()
    plan = planner.compile_plan()
    stored_protocol = _read_json(REPO_ROOT / PROTOCOL_PATH)
    stored_plan = _read_json(REPO_ROOT / PLAN_PATH)
    frozen = _frozen_hash_report(FROZEN_HASHES)
    upstream = _frozen_hash_report(freeze.FROZEN_HASHES)
    events = protocol["frozen_events"]
    target = protocol["target_source"]
    sources = plan["sources"]
    boundary = plan["request_boundary"]
    execution = plan["request_execution"]
    hypothesis = plan["strict_replication_hypothesis"]
    claims = plan["claim_boundary"]
    queries = [parse_qs(urlparse(value["url"]).query) for value in sources]
    gates = {
        "all_eight_stage45_code_test_protocol_and_plan_artifacts_match": (
            len(frozen) == 8 and all(value["matches"] for value in frozen.values())
        ),
        "all_six_stage44_and_target_operator_inputs_match": (
            len(upstream) == 6 and all(value["matches"] for value in upstream.values())
        ),
        "stage44_complete_target_exposure_inventory_is_bound": (
            frozen.get(freeze.STAGE44_INVENTORY_PATH, {}).get("matches", True)
            and upstream[freeze.STAGE44_INVENTORY_PATH]["matches"] is True
        ),
        "stage45_protocol_is_exactly_reproducible": stored_protocol == protocol,
        "stage45_request_plan_is_exactly_reproducible": stored_plan == plan,
        "protocol_freeze_performed_zero_network_requests": (
            protocol["data_boundary"]["network_request_count"] == 0
            and protocol["data_boundary"]["network_requests_allowed_during_protocol_freeze"]
            is False
        ),
        "four_exact_stage44_event_ids_are_preserved": (
            tuple(value["event_id"] for value in events) == freeze.EXPECTED_EVENT_IDS
        ),
        "selection_ranks_are_exactly_one_through_four": (
            [value["selection_rank"] for value in events] == [1, 2, 3, 4]
        ),
        "four_selection_strata_remain_in_frozen_order": (
            [value["selection_stratum"] for value in events]
            == ["high_increase", "high_decrease", "low_increase", "low_decrease"]
        ),
        "all_events_remain_turbine_only": all(
            value["dominant_step_component"] == "turbine" for value in events
        ),
        "all_events_were_selected_without_target_values": all(
            value["selected_without_target_values"] is True for value in events
        ),
        "exact_single_stonewall_target_site_is_frozen": (
            target["site_id"] == "USGS-03424860"
            and target["site_role"] == "downstream_replication_outcome"
        ),
        "target_quantity_and_parameter_are_exact": (
            target["quantity"] == "continuous_discharge" and target["parameter_code"] == "00060"
        ),
        "four_exact_derived_target_windows_are_frozen": (
            tuple((value["target_begin_utc"], value["target_end_utc"]) for value in events)
            == freeze.EXPECTED_TARGET_WINDOWS_UTC
        ),
        "each_target_window_has_exact_84_hour_elapsed_support": all(
            (
                _parse_time(value["target_end_utc"]) - _parse_time(value["target_begin_utc"])
            ).total_seconds()
            == 84 * 3600
            for value in events
        ),
        "each_target_window_has_169_ideal_half_hour_positions": (
            protocol["target_observation_contract"]["expected_ideal_inclusive_half_hour_positions"]
            == 169
            and all(value["expected_maximum_inclusive_grid_positions"] == 169 for value in sources)
        ),
        "missing_samples_and_hours_remain_unfilled": (
            protocol["target_observation_contract"]["missing_samples_filled"] is False
            and plan["target_support"]["missing_values_filled"] is False
        ),
        "quality_metadata_is_not_scientific_approval": (
            protocol["target_observation_contract"]["quality_metadata_is_scientific_approval"]
            is False
        ),
        "high_flow_replication_requires_five_hours": (
            hypothesis["high_flow_required_supported_lag_hours"] == 5
        ),
        "low_flow_replication_requires_six_hours": (
            hypothesis["low_flow_required_supported_lag_hours"] == 6
        ),
        "both_directions_are_required_within_each_flow_class": (
            hypothesis["directions_required_within_each_flow_class"] == ["increase", "decrease"]
        ),
        "partial_flow_class_or_direction_success_is_forbidden": (
            hypothesis["partial_direction_or_flow_class_pass_allowed"] is False
        ),
        "lag_candidates_and_detectability_thresholds_are_frozen": (
            hypothesis["lag_candidates_hours"] == list(range(13))
            and hypothesis["required_event_local_pearson_r"] == 0.8
            and hypothesis["maximum_supported_lag_loss_pearson_r"] == 0.02
            and hypothesis["minimum_pair_count"] == 60
            and hypothesis["best_lag_must_be_interior"] is True
        ),
        "post_value_event_reselection_and_retuning_are_forbidden": (
            hypothesis["event_reselection_after_values_allowed"] is False
            and hypothesis["target_operator_retuning_after_values_allowed"] is False
        ),
        "exactly_four_logical_requests_are_planned": (
            len(sources) == 4 and boundary["maximum_logical_request_count"] == 4
        ),
        "request_order_matches_frozen_event_order": (
            tuple(value["event_id"] for value in sources) == freeze.EXPECTED_EVENT_IDS
        ),
        "every_event_has_exactly_one_target_site": (
            plan["target_support"]["site_count_per_event"] == 1
            and {value["site_id"] for value in sources} == {"USGS-03424860"}
        ),
        "all_requests_use_https_allowlisted_usgs_host": all(
            urlparse(value["url"]).scheme == "https"
            and urlparse(value["url"]).hostname == planner.USGS_HOST
            for value in sources
        ),
        "all_requests_use_exact_continuous_items_path": all(
            urlparse(value["url"]).path == "/ogcapi/v0/collections/continuous/items"
            for value in sources
        ),
        "all_queries_preserve_exact_site_parameter_limit_and_window": all(
            query
            == {
                "f": ["json"],
                "limit": ["10000"],
                "monitoring_location_id": ["USGS-03424860"],
                "parameter_code": ["00060"],
                "datetime": [f"{source['begin_utc']}/{source['end_utc']}"],
            }
            for source, query in zip(sources, queries, strict=True)
        ),
        "all_requests_preserve_usgs_public_domain_terms": all(
            value["license"] == planner.USGS_LICENSE
            and value["license_url"] == planner.USGS_LICENSE_URL
            for value in sources
        ),
        "all_raw_output_names_are_unique_and_stage_local": (
            len({value["output_name"] for value in sources}) == 4
            and all(
                value["output_name"].startswith("raw/usgs_03424860_replication_")
                for value in sources
            )
        ),
        "per_attempt_response_is_bounded_to_two_megabytes": (
            boundary["maximum_response_bytes_per_attempt"] == 2_000_000
            and all(value["maximum_bytes_per_attempt"] == 2_000_000 for value in sources)
        ),
        "retry_count_and_total_attempts_are_explicit": (
            boundary["maximum_attempts_per_request"] == 3
            and boundary["maximum_total_attempt_count"] == 12
        ),
        "persisted_and_retry_worst_case_bytes_are_bounded": (
            boundary["maximum_persisted_download_bytes"] == 8_000_000
            and boundary["maximum_total_response_bytes_across_attempts"] == 24_000_000
        ),
        "unexpected_pagination_fails_closed_without_following": (
            boundary["server_returned_pagination_followed"] is False
            and boundary["unexpected_pagination_policy"] == "fail_closed"
        ),
        "no_private_cwms_smith_fork_or_tailwater_values_are_requested": (
            boundary["workspace_or_private_data_sent"] is False
            and boundary["new_cwms_source_values_requested"] is False
            and boundary["smith_fork_graph_state_values_requested"] is False
            and boundary["tailwater_elevation_values_requested"] is False
        ),
        "planner_has_no_network_execution_path": (
            execution["network_code_path_present_in_this_planner"] is False
        ),
        "request_execution_authorization_is_false": (
            execution["request_execution_authorized"] is False
        ),
        "fresh_approval_is_required_for_exact_four_request_scope": (
            execution["fresh_user_approval_required"] is True
            and execution["approval_scope"] == "exact_four_stage45_logical_requests_only"
        ),
        "executor_requires_explicit_frozen_plan_flag": (_execution_flag_is_required()),
        "executor_binds_plan_and_fails_closed_on_url_payload_size_and_pagination": (
            acquire.FROZEN_PLAN_SHA256 == FROZEN_HASHES[PLAN_PATH]
            and frozen["scripts/acquire_geotransport_stage45_component_lag_replication_targets.py"][
                "matches"
            ]
            is True
        ),
        "target_values_and_replication_decision_remain_pending": (
            claims["target_values_acquired"] is False
            and claims["replication_test_executed"] is False
            and claims["stage43_pattern_replicated"] is False
        ),
        "stage30_falsification_and_universal_lag_boundaries_remain": (
            claims["stage30_historical_falsification_overturned"] is False
            and claims["universal_lag_admitted"] is False
        ),
        "component_causal_physical_and_runtime_promotions_remain_rejected": (
            claims["non_turbine_component_contrast_admitted"] is False
            and claims["causal_or_physical_relation_admitted"] is False
            and claims["runtime_operator_admitted"] is False
        ),
    }
    if len(gates) != 45:
        raise ValueError(f"stage45_gate_count_invalid:{len(gates)}")
    return {
        "schema": SCHEMA,
        "status": STATUS,
        "frozen_artifacts": frozen,
        "upstream_frozen_artifacts": upstream,
        "protocol_artifact": _artifact(REPO_ROOT / PROTOCOL_PATH),
        "target_acquisition_plan_artifact": _artifact(REPO_ROOT / PLAN_PATH),
        "request_boundary": boundary,
        "request_sources": sources,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "decision": {
            "stage44_source_only_replication_cohort_preserved": True,
            "replication_target_protocol_frozen": True,
            "replication_target_request_plan_frozen": True,
            "planned_logical_request_count": 4,
            "planned_event_count": 4,
            "planned_site_count_per_event": 1,
            "request_execution_authorized": False,
            "fresh_user_approval_required": True,
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


def _execution_flag_is_required() -> bool:
    try:
        acquire._require_execution_flag(False)  # noqa: SLF001
    except ValueError as exc:
        return str(exc) == "stage45_explicit_frozen_plan_execution_flag_required"
    return False


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("stage45_timezone_required")
    return parsed.astimezone(UTC)


def _frozen_hash_report(
    expected: dict[str, str],
) -> dict[str, dict[str, object]]:
    result = {}
    for path, digest in expected.items():
        actual = _sha256(REPO_ROOT / path)
        result[path] = {
            "expected_sha256": digest,
            "actual_sha256": actual,
            "matches": actual == digest,
        }
    return result


def _artifact(path: Path) -> dict[str, object]:
    body = path.read_bytes()
    return {
        "path": str(path.resolve().relative_to(REPO_ROOT)),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("stage45_json_object_required")
    return value


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> int:
    args = parse_args()
    report = compile_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_json_bytes(report))
    print(args.output)
    print(f"status={report['status']}")
    print(f"gates={sum(report['gates'].values())}/{len(report['gates'])}")
    print("network_requests=0")
    return 0 if report["all_gates_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
