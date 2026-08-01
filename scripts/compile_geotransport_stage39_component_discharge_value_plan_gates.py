#!/usr/bin/env python3
"""Compile Stage 39 component-discharge value protocol and plan gates."""

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
    freeze_geotransport_stage39_component_discharge_value_protocol as freeze,
)
from scripts import (  # noqa: E402
    plan_geotransport_stage39_component_discharge_values as planner,
)

DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/stage39_component_discharge_value_plan_gates.json"
)
SCHEMA = "gwm.geotransport.stage39_component_discharge_value_plan_gates.v1"
STATUS = "stage39_component_discharge_value_plan_frozen_values_pending_approval"
PROTOCOL_PATH = f"{freeze.STAGE39_ROOT}/protocol.json"
PLAN_PATH = f"{freeze.STAGE39_ROOT}/value_acquisition_plan.json"

FROZEN_HASHES = {
    freeze.STAGE34_LEDGER_PATH: freeze.FROZEN_HASHES[freeze.STAGE34_LEDGER_PATH],
    freeze.STAGE34_GATES_PATH: freeze.FROZEN_HASHES[freeze.STAGE34_GATES_PATH],
    freeze.STAGE38_LEDGER_PATH: freeze.FROZEN_HASHES[freeze.STAGE38_LEDGER_PATH],
    freeze.STAGE38_GATES_PATH: freeze.FROZEN_HASHES[freeze.STAGE38_GATES_PATH],
    (
        "scripts/freeze_geotransport_stage39_component_discharge_value_protocol.py"
    ): "b39440aaac2779157ccbe550256ffe2126261ea96b9f3f5653f123e8e4481f7c",
    (
        "data_agent/test_freeze_geotransport_stage39_component_discharge_value_protocol.py"
    ): "0fb8078802102fab812564cecfa1d714bef7754218e7b0092c25dd700b8a7170",
    ("scripts/plan_geotransport_stage39_component_discharge_values.py"): (
        "d9b40243eabcb6674f649d8f9eea1e93f3d8a76fbcd870448a518d2ed9e0a442"
    ),
    ("data_agent/test_plan_geotransport_stage39_component_discharge_values.py"): (
        "664f89790ef64f3a187db6a6162a99d281d299c71c205a8e4b0f383e1c26281e"
    ),
    PROTOCOL_PATH: planner.FROZEN_PROTOCOL_SHA256,
    PLAN_PATH: "0870a5c636d59b8074efaab199b881e4a384b58d19fd7410ca12e00a329e4f26",
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
    sources = plan["sources"]
    boundary = plan["request_boundary"]
    execution = plan["request_execution"]
    claims = plan["claim_boundary"]
    protocol_claims = protocol["claim_boundary"]
    expected_series = {
        value["component"]: value["series_id"] for value in protocol["admitted_source_identities"]
    }
    parsed_queries = [parse_qs(urlparse(value["url"]).query) for value in sources]
    gates = {
        "all_ten_stage34_stage38_and_stage39_artifacts_match": all(
            value["matches"] for value in frozen.values()
        ),
        "stage34_temporal_semantics_ledger_is_exactly_bound": (
            frozen[freeze.STAGE34_LEDGER_PATH]["matches"] is True
        ),
        "stage34_temporal_semantics_gates_are_exactly_bound": (
            frozen[freeze.STAGE34_GATES_PATH]["matches"] is True
        ),
        "stage38_catalog_ledger_is_exactly_bound": (
            frozen[freeze.STAGE38_LEDGER_PATH]["matches"] is True
        ),
        "stage38_catalog_gates_are_exactly_bound": (
            frozen[freeze.STAGE38_GATES_PATH]["matches"] is True
        ),
        "stage39_protocol_hash_is_exact": (frozen[PROTOCOL_PATH]["matches"] is True),
        "stage39_plan_hash_is_exact": frozen[PLAN_PATH]["matches"] is True,
        "stage39_protocol_is_reproducible": stored_protocol == protocol,
        "stage39_plan_is_reproducible": stored_plan == plan,
        "protocol_freeze_performed_no_network_requests": (
            protocol["data_boundary"]["network_requests_allowed_during_protocol_freeze"] is False
        ),
        "exact_four_component_identities_are_preserved": (
            [value["component"] for value in protocol["admitted_source_identities"]]
            == list(freeze.COMPONENT_ORDER)
        ),
        "hourly_interval_average_end_label_semantics_are_preserved": (
            protocol["source_observation_semantics"]["measurement_statistic"]
            == "one_hour_interval_average"
            and protocol["source_observation_semantics"][
                "cwms_composite_default_timestamp_position"
            ]
            == "end"
        ),
        "source_time_support_is_the_prior_hour": (
            protocol["source_observation_semantics"]["source_time_support_offsets_minutes"]
            == [-60, 0]
        ),
        "five_year_value_window_is_exact": (
            protocol["frozen_value_window"]["begin_utc"] == "2021-01-01T00:00:00Z"
            and protocol["frozen_value_window"]["end_utc"] == "2026-01-01T00:00:00Z"
        ),
        "expected_hourly_component_grid_size_is_exact": (
            protocol["frozen_value_window"]["expected_unique_inclusive_positions_per_component"]
            == 43_825
            and protocol["frozen_value_window"]["expected_combined_component_positions"] == 175_300
        ),
        "missing_values_and_quality_codes_are_preserved_without_fill": (
            protocol["value_shape_contract"]["explicit_null_values_preserved"] is True
            and protocol["value_shape_contract"]["missing_values_filled"] is False
            and protocol["value_shape_contract"][
                "quality_codes_preserved_without_approval_interpretation"
            ]
            is True
        ),
        "total_discharge_requires_four_simultaneous_components": (
            protocol["synchronized_total_discharge_eligibility"][
                "all_four_component_values_required_at_same_hour"
            ]
            is True
        ),
        "partial_or_imputed_component_sum_is_rejected": (
            protocol["synchronized_total_discharge_eligibility"]["partial_component_sum_allowed"]
            is False
            and protocol["synchronized_total_discharge_eligibility"][
                "missing_component_imputation_allowed"
            ]
            is False
        ),
        "post_acquisition_scope_is_coverage_and_quality_audit_only": (
            plan["post_acquisition_allowed_assessment"]["per_component_time_coverage_audit_allowed"]
            is True
            and plan["post_acquisition_allowed_assessment"]["event_selection_allowed"] is False
            and plan["post_acquisition_allowed_assessment"]["model_fitting_or_scoring_allowed"]
            is False
        ),
        "fresh_user_approval_is_required_before_execution": (
            execution["fresh_user_approval_required"] is True
            and execution["request_execution_authorized"] is False
        ),
        "twenty_logical_requests_are_exact": (
            len(sources) == 20 and boundary["maximum_logical_request_count"] == 20
        ),
        "request_order_is_four_components_then_five_years": (
            [value["component"] for value in sources]
            == [component for component in freeze.COMPONENT_ORDER for _ in range(5)]
        ),
        "each_component_has_five_exact_annual_windows": all(
            [
                (value["begin_utc"], value["end_utc"])
                for value in sources
                if value["component"] == component
            ]
            == list(freeze.YEAR_WINDOWS)
            for component in freeze.COMPONENT_ORDER
        ),
        "all_requests_use_https_cwms_allowlisted_host": all(
            urlparse(value["url"]).scheme == "https"
            and urlparse(value["url"]).hostname == planner.CWMS_HOST
            for value in sources
        ),
        "all_request_queries_preserve_exact_series_office_unit_and_page_size": all(
            query["name"] == [expected_series[source["component"]]]
            and query["office"] == ["LRN"]
            and query["unit"] == ["cms"]
            and query["page-size"] == ["20000"]
            for source, query in zip(sources, parsed_queries, strict=True)
        ),
        "per_attempt_response_is_bounded_to_one_megabyte": (
            boundary["maximum_response_bytes_per_attempt"] == 1_000_000
        ),
        "retry_and_total_response_worst_case_are_explicit": (
            boundary["maximum_attempts_per_request"] == 3
            and boundary["maximum_total_attempt_count"] == 60
            and boundary["maximum_persisted_download_bytes"] == 20_000_000
            and boundary["maximum_total_response_bytes_across_attempts"] == 60_000_000
        ),
        "no_private_tailwater_or_downstream_data_is_requested": (
            boundary["workspace_or_private_data_sent"] is False
            and boundary["downstream_or_tributary_outcome_values_requested"] is False
            and boundary["tailwater_elevation_values_requested"] is False
        ),
        "unexpected_pagination_fails_closed_without_following": (
            boundary["server_returned_pagination_followed"] is False
            and boundary["unexpected_pagination_policy"] == "fail_closed"
        ),
        "planner_has_no_network_execution_path": (
            execution["network_code_path_present_in_this_planner"] is False
        ),
        "component_values_and_coverage_remain_unadmitted": (
            claims["component_values_acquired"] is False
            and claims["coverage_or_quality_support_admitted"] is False
            and protocol_claims["component_values_acquired"] is False
        ),
        "synchronized_total_and_events_remain_unadmitted": (
            claims["synchronized_total_discharge_admitted"] is False
            and claims["component_discharge_event_admitted"] is False
        ),
        "command_human_and_causal_promotions_remain_rejected": (
            claims["gate_command_admitted"] is False
            and claims["human_action_admitted"] is False
            and claims["causal_intervention_admitted"] is False
        ),
        "physical_time_and_runtime_promotions_remain_rejected": (
            claims["physical_response_time_admitted"] is False
            and claims["runtime_operator_admitted"] is False
        ),
    }
    decision = {
        "stage38_source_identity_checkpoint_preserved": True,
        "component_discharge_value_protocol_frozen": True,
        "component_discharge_value_request_plan_frozen": True,
        "planned_logical_request_count": len(sources),
        "component_values_acquired": False,
        "coverage_or_quality_support_admitted": False,
        "synchronized_total_discharge_admitted": False,
        "component_discharge_event_admitted": False,
        "gate_commands_admitted": False,
        "human_actions_admitted": False,
        "causal_interventions_admitted": False,
        "physical_response_time_admitted": False,
        "runtime_operators_admitted": False,
        "fresh_user_approval_required_before_value_requests": True,
    }
    return {
        "schema": SCHEMA,
        "compiled_at": datetime.now(UTC).isoformat(),
        "status": STATUS,
        "frozen_artifacts": frozen,
        "protocol_artifact": _artifact(REPO_ROOT / PROTOCOL_PATH),
        "value_acquisition_plan_artifact": _artifact(REPO_ROOT / PLAN_PATH),
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
        raise ValueError("stage39_gate_json_object_required")
    return value


def _json_bytes(value: dict[str, object]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
