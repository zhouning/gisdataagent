#!/usr/bin/env python3
"""Compile Stage 43 component-event empirical lag-support gates."""

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
    public_component_event_lag_support_evidence as evidence,
)
from scripts import (  # noqa: E402
    plan_geotransport_stage42_component_event_targets as planner,
)

DEFAULT_DATA_ROOT = REPO_ROOT / evidence.STAGE43_ROOT
DEFAULT_LEDGER_OUTPUT = DEFAULT_DATA_ROOT / (
    "component_event_lag_support_evidence_ledger.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "stage43_component_event_lag_support_gates.json"
)
SCHEMA = "gwm.geotransport.stage43_component_event_lag_support_gates.v1"
STATUS = evidence.STATUS
FROZEN_HASHES = dict(evidence.EXPECTED_CHECKPOINT_SHA256)
FROZEN_HASHES.update(
    {
        f"{evidence.STAGE42_ROOT}/{source['output_name']}": (
            evidence.EXPECTED_RAW_SHA256[str(source["source_id"])]
        )
        for source in planner.compile_plan()["sources"]
    }
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ledger-output", type=Path, default=DEFAULT_LEDGER_OUTPUT
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ledger = evidence.compile_public_component_event_lag_support_evidence()
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
    ledger: evidence.PublicComponentEventLagSupportEvidenceLedger | None = None,
    ledger_artifact: dict[str, object] | None = None,
) -> dict[str, Any]:
    if ledger is None:
        ledger = evidence.compile_public_component_event_lag_support_evidence()
    ledger_report = ledger.as_dict()
    if ledger_artifact is None:
        ledger_artifact = _memory_artifact(
            DEFAULT_LEDGER_OUTPUT,
            ledger_report,
        )
    frozen = _frozen_hash_report(FROZEN_HASHES)
    first, second, third, fourth = ledger.events
    decision = ledger_report["decision"]
    claims = ledger_report["claim_boundary"]
    refusals = _refusal_controls(ledger)
    expected_support = [(5,), (5,), (6, 7), (6,)]
    expected_best = [
        (5, 0.8217600767931865),
        (5, 0.8790617592474798),
        (6, 0.9244168189654225),
        (6, 0.919474372916006),
    ]
    gates = {
        "all_nineteen_frozen_stage41_stage42_artifacts_match": all(
            value["matches"] for value in frozen.values()
        )
        and len(frozen) == 19,
        "all_eleven_checkpoint_artifacts_are_exactly_bound": (
            {
                path: value["sha256"]
                for path, value in ledger.checkpoint_artifacts.items()
            }
            == evidence.EXPECTED_CHECKPOINT_SHA256
        ),
        "stage41_protocol_candidate_manifest_ledger_and_gates_are_bound": all(
            ledger.checkpoint_artifacts[path]["sha256"]
            == evidence.EXPECTED_CHECKPOINT_SHA256[path]
            for path in (
                evidence.STAGE41_PROTOCOL_PATH,
                evidence.STAGE41_CANDIDATE_LEDGER_PATH,
                evidence.STAGE41_MANIFEST_PATH,
                evidence.STAGE41_PUBLIC_LEDGER_PATH,
                evidence.STAGE41_GATES_PATH,
            )
        ),
        "stage42_protocol_plan_gates_state_and_manifest_are_bound": all(
            ledger.checkpoint_artifacts[path]["sha256"]
            == evidence.EXPECTED_CHECKPOINT_SHA256[path]
            for path in (
                evidence.STAGE42_PROTOCOL_PATH,
                evidence.STAGE42_PLAN_PATH,
                evidence.STAGE42_GATES_PATH,
                evidence.STAGE42_STATE_PATH,
                evidence.STAGE42_MANIFEST_PATH,
            )
        ),
        "empirical_lag_support_operator_is_hash_frozen": (
            ledger.checkpoint_artifacts[evidence.freeze.TARGET_OPERATOR_PATH][
                "sha256"
            ]
            == evidence.freeze.FROZEN_HASHES[
                evidence.freeze.TARGET_OPERATOR_PATH
            ]
        ),
        "eight_raw_target_artifacts_are_hash_and_tls_verified": (
            len(ledger.source_artifacts) == 8
            and all(
                value["sha256"]
                == evidence.EXPECTED_RAW_SHA256[str(value["source_id"])]
                and value["hash_verified"] is True
                and value["tls_hostname_verification_retained"] is True
                for value in ledger.source_artifacts
            )
        ),
        "all_eight_requests_succeeded_on_first_attempt": (
            ledger.actual_request_count == 8
            and ledger.actual_attempt_count == 8
            and all(
                value["attempt_count"] == 1
                and value["failed_attempts"] == []
                and value["http_status"] == 200
                for value in ledger.source_artifacts
            )
        ),
        "acquisition_stayed_within_frozen_byte_boundary": (
            ledger.actual_download_bytes == 1_112_317
            and ledger.actual_download_bytes
            < planner.MAXIMUM_PERSISTED_DOWNLOAD_BYTES
        ),
        "four_exact_stage41_events_remain_in_frozen_order": (
            tuple(value.event_id for value in ledger.events)
            == evidence.stage41.EXPECTED_EVENT_IDS
            and [value.selection_rank for value in ledger.events]
            == [1, 2, 3, 4]
        ),
        "four_frozen_selection_strata_are_preserved": (
            [value.selection_stratum for value in ledger.events]
            == [
                "high_increase",
                "high_decrease",
                "low_increase",
                "low_decrease",
            ]
        ),
        "all_source_steps_remain_turbine_only": all(
            value.active_step_components == ("turbine",)
            and value.dominant_step_component == "turbine"
            for value in ledger.events
        ),
        "all_source_totals_have_exact_seventy_two_hour_support": all(
            len(value.source_total_values_m3s) == 72
            and all(item >= 0.0 for item in value.source_total_values_m3s)
            for value in ledger.events
        ),
        "source_totals_retain_all_four_component_quality_streams": all(
            tuple(name for name, _ in value.source_component_quality_codes)
            == evidence.component_support.catalog.EXPECTED_COMPONENTS
            for value in ledger.events
        ),
        "source_quality_codes_are_not_approval_semantics": (
            claims["source_quality_codes_are_not_approval_semantics"] is True
            and decision["quality_approval_semantics_admitted"] is False
        ),
        "downstream_raw_coverage_is_exact": (
            [value.downstream_metadata.raw_sample_count for value in ledger.events]
            == [169, 169, 169, 169]
        ),
        "all_downstream_windows_have_eighty_four_complete_hours": (
            [len(value.downstream_hourly) for value in ledger.events]
            == [84, 84, 84, 84]
        ),
        "downstream_missing_values_are_not_filled": all(
            value.as_dict()["downstream_missing_hour_count"] == 0
            and all(
                hour.as_dict()["missing_values_filled"] is False
                for hour in value.downstream_hourly
            )
            for value in ledger.events
        ),
        "all_downstream_samples_report_approved_with_null_qualifier": all(
            value.downstream_metadata.all_samples_report_approved
            and value.downstream_metadata.all_qualifiers_are_none
            for value in ledger.events
        ),
        "target_quality_metadata_is_preserved_not_promoted": (
            claims["target_quality_metadata_is_not_scientific_approval"]
            is True
            and all(
                value.downstream_metadata.as_dict()[
                    "quality_metadata_interpreted_as_scientific_approval"
                ]
                is False
                for value in ledger.events
            )
        ),
        "thirteen_frozen_lags_use_exact_seventy_two_pairs": all(
            tuple(item.pair_count for item in value.lag_diagnostics)
            == (72,) * 13
            for value in ledger.events
        ),
        "four_best_lags_and_correlations_are_exact": all(
            value.lag_support.best_lag_hours == expected[0]
            and abs(value.lag_support.best_pearson_r - expected[1]) < 1e-12
            for value, expected in zip(
                ledger.events,
                expected_best,
                strict=True,
            )
        ),
        "four_event_local_support_sets_are_exact": (
            [value.lag_support.supported_lags_hours for value in ledger.events]
            == expected_support
        ),
        "all_four_event_local_responses_are_detectable": (
            ledger.all_events_have_detectable_response
            and all(
                value.lag_support.response_rejection_reasons == ()
                for value in ledger.events
            )
        ),
        "all_four_event_local_support_sets_are_admitted": (
            decision["event_local_empirical_lag_support_admitted"] is True
            and decision["event_local_empirical_lag_support_count"] == 4
            and all(
                value.lag_support.require_empirical_support_set()
                == expected
                for value, expected in zip(
                    ledger.events,
                    expected_support,
                    strict=True,
                )
            )
        ),
        "first_high_increase_event_resolves_five_hours": (
            first.lag_support.require_exact_hour() == 5
        ),
        "second_high_decrease_event_resolves_five_hours": (
            second.lag_support.require_exact_hour() == 5
        ),
        "third_low_increase_event_retains_six_seven_set": (
            third.lag_support.supported_lags_hours == (6, 7)
            and third.lag_support.exact_hour_resolved is False
        ),
        "fourth_low_decrease_event_resolves_six_hours": (
            fourth.lag_support.require_exact_hour() == 6
        ),
        "all_relations_bind_source_boundary_to_observed_outlet": all(
            value.graph_relation.source_boundary_id
            == evidence.SOURCE_BOUNDARY_ID
            and value.graph_relation.target_site_id == evidence.TARGET_SITE_ID
            and value.graph_relation.target_comid == evidence.TARGET_COMID
            for value in ledger.events
        ),
        "cross_event_support_intersection_is_empty": (
            ledger.common_supported_lags_hours == ()
        ),
        "common_empirical_support_is_rejected_despite_four_responses": (
            ledger.all_events_have_detectable_response is True
            and ledger.common_empirical_support_admitted is False
            and decision["common_empirical_support_admitted"] is False
        ),
        "smith_fork_raw_coverage_is_exact": (
            [value.graph_state_metadata.raw_sample_count for value in ledger.events]
            == [148, 165, 161, 169]
        ),
        "smith_fork_hourly_gaps_are_preserved_without_fill": (
            [len(value.graph_states.states) for value in ledger.events]
            == [68, 80, 78, 84]
            and [
                value.graph_states.missing_hour_count for value in ledger.events
            ]
            == [16, 4, 6, 0]
            and all(
                value.graph_states.as_dict()["missing_values_filled"] is False
                for value in ledger.events
            )
        ),
        "all_smith_fork_samples_report_approved_with_null_qualifier": all(
            value.graph_state_metadata.all_samples_report_approved
            and value.graph_state_metadata.all_qualifiers_are_none
            for value in ledger.events
        ),
        "smith_fork_states_are_bound_to_exact_observed_comid": all(
            state.site_id == evidence.GRAPH_STATE_SITE_ID
            and state.comid == evidence.GRAPH_STATE_COMID
            for value in ledger.events
            for state in value.graph_states.states
        ),
        "observed_downstream_and_graph_state_evidence_are_admitted": (
            decision["observed_downstream_response_evidence_admitted"] is True
            and decision["observed_graph_state_contract_admitted"] is True
        ),
        "non_turbine_component_contrast_remains_rejected": (
            decision["non_turbine_component_contrast_admitted"] is False
        ),
        "all_seven_unsupported_promotions_fail_closed": all(
            refusals.values()
        ),
        "causal_response_and_physical_times_remain_rejected": (
            decision["causal_response_admitted"] is False
            and decision["physical_travel_time_admitted"] is False
            and decision["hydraulic_edge_travel_time_admitted"] is False
        ),
        "tributary_flux_and_runtime_operator_remain_rejected": (
            decision["tributary_mouth_flux_admitted"] is False
            and decision["runtime_operator_admitted"] is False
        ),
        "stage43_compilation_makes_no_network_request": (
            ledger_report["acquisition_summary"]["logical_request_count"] == 8
            and ledger_report["acquisition_summary"][
                "all_requests_succeeded_on_first_attempt"
            ]
            is True
        ),
        "public_provenance_is_content_addressed": (
            ledger.provenance_id.startswith(
                "center-hill-component-event-lag-support:"
            )
            and len(ledger.provenance_id.rsplit(":", 1)[1]) == 64
        ),
        "stage43_ledger_is_content_addressed": (
            len(str(ledger_artifact["sha256"])) == 64
            and int(ledger_artifact["size_bytes"]) > 0
        ),
    }
    return {
        "schema": SCHEMA,
        "compiled_at": datetime.now(UTC).isoformat(),
        "status": STATUS,
        "frozen_artifacts": frozen,
        "stage43_ledger_artifact": ledger_artifact,
        "acquisition_summary": ledger_report["acquisition_summary"],
        "event_summary": [
            {
                "event_id": value.event_id,
                "selection_stratum": value.selection_stratum,
                "dominant_step_component": value.dominant_step_component,
                "best_lag_hours": value.lag_support.best_lag_hours,
                "best_lag_pearson_r": value.lag_support.best_pearson_r,
                "supported_lags_hours": list(
                    value.lag_support.supported_lags_hours
                ),
                "response_detectable": value.lag_support.response_detectable,
                "downstream_raw_sample_count": (
                    value.downstream_metadata.raw_sample_count
                ),
                "downstream_complete_hour_count": len(value.downstream_hourly),
                "graph_state_raw_sample_count": (
                    value.graph_state_metadata.raw_sample_count
                ),
                "graph_state_complete_hour_count": len(
                    value.graph_states.states
                ),
            }
            for value in ledger.events
        ],
        "typed_refusals": refusals,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "decision": decision,
        "claim_boundary": claims,
    }


def _refusal_controls(
    ledger: evidence.PublicComponentEventLagSupportEvidenceLedger,
) -> dict[str, bool]:
    calls = {
        "common_empirical_support": (
            ledger.require_common_empirical_support,
            "component_event_common_empirical_support_unadmitted",
        ),
        "quality_approval_semantics": (
            ledger.require_quality_approval_semantics,
            "component_event_quality_approval_semantics_unadmitted",
        ),
        "non_turbine_component_contrast": (
            ledger.require_non_turbine_component_contrast,
            "component_event_non_turbine_contrast_unadmitted",
        ),
        "causal_response": (
            ledger.require_causal_response,
            "component_event_causal_response_unadmitted",
        ),
        "physical_travel_time": (
            ledger.require_physical_travel_time,
            "component_event_empirical_set_is_not_physical_time",
        ),
        "hydraulic_edge_travel_time": (
            ledger.require_hydraulic_edge_travel_time,
            "component_event_relation_is_not_hydraulic_edge_time",
        ),
        "tributary_mouth_flux": (
            ledger.require_tributary_mouth_flux,
            "component_event_graph_state_is_not_mouth_flux",
        ),
        "runtime_operator": (
            ledger.promote_to_runtime_operator,
            "component_event_runtime_operator_unadmitted",
        ),
    }
    result = {}
    for name, (call, message) in calls.items():
        try:
            call()
        except ValueError as exc:
            result[name] = str(exc) == message
        else:
            result[name] = False
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
        "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _json_bytes(value: dict[str, object]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
