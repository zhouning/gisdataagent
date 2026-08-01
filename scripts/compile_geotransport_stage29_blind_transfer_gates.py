#!/usr/bin/env python3
"""Compile Stage 29 blind-transfer and observed-tributary gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import (
    public_blind_transfer_evidence as evidence,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/stage29_center_hill_blind_transfer_events"
)
DEFAULT_LEDGER_OUTPUT = DEFAULT_DATA_ROOT / "blind_transfer_evidence_ledger.json"
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/stage29_blind_transfer_gates.json"
)
SCHEMA = "gwm.geotransport.stage29_blind_transfer_gates.v1"

FROZEN_STAGE28_HASHES = {
    (
        "scripts/"
        "acquire_geotransport_stage28_public_operational_boundary_evidence.py"
    ): "82dd57130d57e623f6413b48bee6814d5a0f67ba60f73e48c49cce138d9c0a98",
    (
        "data_agent/"
        "test_acquire_geotransport_stage28_public_operational_boundary_evidence.py"
    ): "c2eb25be51954ded84243168bc37f86f2c6432e17c65ddad3997232aa0bae70c",
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "public_operational_boundary_evidence.py"
    ): "fc406d649b7d4c845e10f84f1d02190f63d293da0d4678c251afcec5230a1e52",
    (
        "data_agent/"
        "test_geospatial_kernel_public_operational_boundary_evidence.py"
    ): "99b80ce74de5716387234e5bb0d080b319a06b50466a14ac5893fe614fc73cf4",
    (
        "scripts/compile_geotransport_stage28_public_operational_boundary_gates.py"
    ): "4e8a95c1dadac96f6df7369f480d628d9b3bcaa771613c57d0f60675cfaba013",
    (
        "data/geotransport_v0_1/"
        "stage28_center_hill_operational_boundary_evidence/"
        "acquisition_plan.json"
    ): "335cf57dad76c469e1f8e78cf9e93ccba2a606c38258cd69b45153f5ebc4d0bb",
    (
        "data/geotransport_v0_1/"
        "stage28_center_hill_operational_boundary_evidence/"
        "acquisition_manifest.json"
    ): "1af45b76c416fed176307a6f3acdfabde006c1514a57cddc71f7008b6ea36af6",
    (
        "data/geotransport_v0_1/"
        "stage28_center_hill_operational_boundary_evidence/"
        "operational_boundary_evidence_ledger.json"
    ): "d3ae3752c098592f2861aade525d82748432cf086fe208bd736a49cd6b4837a1",
    (
        "benchmarks/geotransport_v0_1/"
        "stage28_public_operational_boundary_gates.json"
    ): "09b2e66b32b01e7bef9c788a0b5f890680ec5bc1386a36a449cb96fb86fb2c55",
    (
        "docs/architecture-decisions/"
        "adr-069-public-operational-boundary-lag-diagnostic.md"
    ): "972769626c629c49651a315a0c95f7c9f01e551ac7798bc32c31a07b5f8197c4",
    (
        "data/geotransport_v0_1/"
        "stage28_center_hill_operational_boundary_evidence/README.md"
    ): "57ae4e6dd26f3d9fb8581025cb0ade75c6cf5df1973951a2ad7947032e87118e",
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
    ledger = evidence.compile_public_blind_transfer_evidence()
    artifact = _write_artifact(args.ledger_output, ledger.as_dict())
    report = compile_report(ledger=ledger, ledger_artifact=artifact)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_json_bytes(report))
    print(args.output)
    print(f"status={report['status']}")
    print(f"gates={sum(report['gates'].values())}/{len(report['gates'])}")
    return 0 if report["all_gates_passed"] else 1


def compile_report(
    *, ledger=None, ledger_artifact: dict[str, object] | None = None
) -> dict[str, Any]:
    if ledger is None:
        ledger = evidence.compile_public_blind_transfer_evidence()
    report = ledger.as_dict()
    if ledger_artifact is None:
        ledger_artifact = _memory_artifact(DEFAULT_LEDGER_OUTPUT, report)
    frozen_stage28 = _frozen_hash_report(FROZEN_STAGE28_HASHES)
    first, second, third = ledger.events
    refusals = _refusal_control(ledger)
    selection_sources = [
        value for value in ledger.source_artifacts if value.get("event_id") is None
    ]
    observation_sources = [
        value for value in ledger.source_artifacts if value.get("event_id") is not None
    ]
    gates = {
        "stage28_artifacts_hash_frozen": all(
            value["matches"] for value in frozen_stage28.values()
        ),
        "selection_acquisition_is_public_bounded_and_private_free": (
            len(selection_sources) == 5
            and all(
                value["source"]
                in {"usace_cwms", "usgs_water_data", "usgs_nldi"}
                for value in selection_sources
            )
        ),
        "eleven_source_artifacts_are_hash_and_tls_verified": (
            len(ledger.source_artifacts) == 11
            and all(
                len(str(value["sha256"])) == 64
                and value["hash_verified"] is True
                and value["tls_hostname_verification_retained"] is True
                for value in ledger.source_artifacts
            )
        ),
        "selection_plan_was_frozen_before_release_values": (
            ledger.selection_plan_artifact["sha256"]
            == "6b1a2b776ac1cc8d91ef1722e9b82fe48046f86cc242d88b091388090408dff5"
        ),
        "event_manifest_was_frozen_before_observation_values": (
            ledger.event_selection_manifest_artifact["sha256"]
            == "480734abcdb2a535e7a2bc794dbf2a5d7e708d3d6faac7becbdea9429d05c91b"
        ),
        "observation_plan_was_frozen_before_observation_values": (
            ledger.observation_plan_artifact["sha256"]
            == "ab90b2795616242c27c80cf06b5cba3c43462c535f4da1d8424a92c4a7b53727"
        ),
        "five_year_release_pool_is_complete_and_unpaginated": (
            ledger.candidate_count == 7266
            and next(
                value
                for value in selection_sources
                if value["source_id"] == "cwms_release_candidate_pool"
            )["size_bytes"]
            == 1_244_077
        ),
        "three_events_are_release_selected_blind_transfers": (
            len(ledger.events) == 3
            and all(
                value.as_dict()["selected_without_observation_values"] is True
                and value.as_dict()["role"] == "blind_transfer"
                for value in ledger.events
            )
        ),
        "selected_events_meet_step_range_and_separation_contract": (
            all(
                value.absolute_step_m3s >= 50.0
                and value.window_range_m3s >= 100.0
                for value in ledger.events
            )
            and [value.selection_rank for value in ledger.events] == [1, 2, 3]
        ),
        "smith_fork_site_and_continuous_series_are_bound": (
            ledger.tributary_binding.site_id == evidence.TRIBUTARY_SITE_ID
            and ledger.tributary_binding.comid == evidence.TRIBUTARY_COMID
            and ledger.tributary_binding.continuous_series_id
            == "c59c7559af4f4a0ebef64eb811803ea0"
        ),
        "smith_fork_nldi_path_reaches_stonewall_outlet": (
            ledger.tributary_binding.path_reaches_outlet
            and evidence.OUTLET_COMID
            in ledger.tributary_binding.downstream_path_feature_ids
        ),
        "all_selected_release_windows_have_seventy_two_support_hours": all(
            len(value.release_values_m3s) == 72
            and len(value.release_quality_codes) == 72
            and set(value.release_quality_codes) == {0}
            for value in ledger.events
        ),
        "all_downstream_windows_are_complete_and_approved": all(
            value.raw_downstream_sample_count == 169
            and len(value.downstream_hourly) == 84
            and all(hour.fully_approved for hour in value.downstream_hourly)
            for value in ledger.events
        ),
        "all_thirteen_lags_have_equal_real_pair_counts": all(
            tuple(value.pair_count for value in event.lag_diagnostics)
            == (72,) * 13
            for event in ledger.events
        ),
        "first_blind_event_prefers_five_hours_and_rejects_fixed_six": (
            first.best_lag_hours == 5
            and first.fixed_lag_supported is False
            and abs(float(first.best_lag_diagnostic.pearson_r) - 0.799624219109659)
            < 1e-12
            and abs(float(first.fixed_lag_diagnostic.pearson_r) - 0.7270395584160697)
            < 1e-12
        ),
        "second_blind_event_supports_fixed_six_hours": (
            second.best_lag_hours == 6
            and second.fixed_lag_supported
            and abs(float(second.fixed_lag_diagnostic.pearson_r) - 0.8310662796172466)
            < 1e-12
        ),
        "third_blind_event_supports_fixed_six_hours": (
            third.best_lag_hours == 6
            and third.fixed_lag_supported
            and abs(float(third.fixed_lag_diagnostic.pearson_r) - 0.8177595568106913)
            < 1e-12
        ),
        "two_of_three_blind_events_support_stage28_fixed_lag": (
            sum(value.fixed_lag_supported for value in ledger.events) == 2
        ),
        "unanimous_stable_empirical_lag_remains_unadmitted": (
            ledger.all_events_support_fixed_lag is False
            and report["decision"]["stable_empirical_lag_admitted"] is False
        ),
        "smith_fork_gaps_are_preserved_without_fill": (
            [value.tributary_context.complete_hour_count for value in ledger.events]
            == [61, 84, 79]
            and [value.tributary_context.missing_hour_count for value in ledger.events]
            == [23, 0, 5]
            and all(
                value.tributary_context.as_dict()["missing_values_filled"] is False
                for value in ledger.events
            )
        ),
        "all_compiled_smith_fork_hours_are_approved": all(
            value.tributary_context.complete_hour_count
            == value.tributary_context.fully_approved_hour_count
            for value in ledger.events
        ),
        "observed_tributary_state_is_admitted": (
            report["decision"]["observed_tributary_state_admitted"] is True
        ),
        "tributary_gauge_is_not_relabelled_as_mouth_or_total_lateral_flux": (
            report["claim_boundary"][
                "observed_tributary_is_mouth_boundary_flux"
            ]
            is False
            and report["claim_boundary"][
                "observed_tributary_represents_all_lateral_inflow"
            ]
            is False
        ),
        "unsupported_transfer_and_lateral_claims_fail_closed": all(
            refusals.values()
        ),
        "empirical_lag_is_not_relabelled_physical_travel_time": (
            report["decision"]["physical_travel_time_admitted"] is False
        ),
        "observed_spatial_rollout_remains_unclaimed": (
            report["decision"]["observed_spatial_rollout_completed"] is False
        ),
        "runtime_operator_remains_unadmitted": (
            report["decision"]["runtime_operator_admitted"] is False
        ),
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "three_blind_events_scored_two_support_six_hours_"
            "stable_lag_and_rollout_pending"
        ),
        "ledger_artifact": ledger_artifact,
        "frozen_stage28_hashes": frozen_stage28,
        "event_summary": [
            {
                "event_id": value.event_id,
                "selection_rank": value.selection_rank,
                "best_lag_hours": value.best_lag_hours,
                "best_lag_pearson_r": value.best_lag_diagnostic.pearson_r,
                "fixed_lag_pearson_r": value.fixed_lag_diagnostic.pearson_r,
                "fixed_lag_supported": value.fixed_lag_supported,
                "tributary_complete_hour_count": (
                    value.tributary_context.complete_hour_count
                ),
            }
            for value in ledger.events
        ],
        "tributary_binding": ledger.tributary_binding.as_dict(),
        "typed_refusals": refusals,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "decision": report["decision"],
        "claim_boundary": report["claim_boundary"],
    }


def _refusal_control(ledger) -> dict[str, bool]:
    calls = {
        "stable_empirical_lag": (
            ledger.require_stable_empirical_release_response_lag,
            "public_blind_transfer_fixed_lag_not_supported_by_all_events",
        ),
        "physical_travel_time": (
            ledger.require_physical_travel_time,
            "public_blind_transfer_empirical_lag_is_not_physical_travel_time",
        ),
        "tributary_mouth_flux": (
            ledger.require_tributary_mouth_flux,
            "public_blind_transfer_gauge_is_not_tributary_mouth_flux",
        ),
        "all_lateral_inflow": (
            ledger.require_all_lateral_inflow,
            "public_blind_transfer_single_tributary_is_not_lateral_inflow_total",
        ),
        "boundary_conditioned_rollout": (
            ledger.require_boundary_conditioned_rollout,
            "public_blind_transfer_evidence_is_not_spatial_rollout",
        ),
        "runtime_operator": (
            ledger.promote_to_runtime_operator,
            "public_blind_transfer_runtime_operator_unadmitted",
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
    result = {}
    for relative, expected_hash in expected.items():
        actual = hashlib.sha256((REPO_ROOT / relative).read_bytes()).hexdigest()
        result[relative] = {
            "expected_sha256": expected_hash,
            "actual_sha256": actual,
            "matches": actual == expected_hash,
        }
    return result


def _write_artifact(path: Path, value: dict[str, Any]) -> dict[str, object]:
    body = _json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return {
        "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _memory_artifact(path: Path, value: dict[str, Any]) -> dict[str, object]:
    body = _json_bytes(value)
    return {
        "path": path.relative_to(REPO_ROOT).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
