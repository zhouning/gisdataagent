#!/usr/bin/env python3
"""Compile Stage 32 empirical lag-support evidence gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import (
    public_lag_support_evidence as evidence,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/stage32_center_hill_lag_support_events"
)
DEFAULT_LEDGER_OUTPUT = DEFAULT_DATA_ROOT / (
    "lag_support_evidence_ledger.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/stage32_lag_support_gates.json"
)
SCHEMA = "gwm.geotransport.stage32_lag_support_gates.v1"

FROZEN_STAGE31_HASHES = {
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "release_excitation_identifiability.py"
    ): "6dd4266e60c569bb19f7b79387d2d6cf9da06ee81c68d886e74cc0d6564226eb",
    (
        "data_agent/"
        "test_geospatial_kernel_release_excitation_identifiability.py"
    ): "00759703c7dc1c2f48e4c550bdd89880aa80f93a1c1cca5093e87b72f3e9664e",
    (
        "scripts/"
        "acquire_geotransport_stage31_identifiable_response_events.py"
    ): "63ad0c813ee2359b67672bb344732100d6c55313457beef7ded7a7f0fd26dc83",
    (
        "data_agent/"
        "test_acquire_geotransport_stage31_identifiable_response_events.py"
    ): "0e1e91b3965b774989fc4589da0f515d4c028cd9e7bdab6b1e7f8ba2bf8f1b28",
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "public_identifiable_response_evidence.py"
    ): "c8955dbd6b69a51f2d4f8a708ca05696a731485e1cf0d75e400d808417382530",
    (
        "data_agent/"
        "test_geospatial_kernel_public_identifiable_response_evidence.py"
    ): "1acfe1a62db10ddca6ba4ab25b88c18e4e5bf70bfa87eeeef618a6c2d9263281",
    (
        "scripts/"
        "compile_geotransport_stage31_identifiable_response_gates.py"
    ): "8b893fde567c20abe29e1698470a81651dad443615ed02057067d63b20785b37",
    (
        "data/geotransport_v0_1/"
        "stage31_center_hill_identifiable_response_events/"
        "selection_plan.json"
    ): "0ebb39f688776b64458283d1b39ad67312381bbf9acf8bdd7f9ee864f37e53f7",
    (
        "data/geotransport_v0_1/"
        "stage31_center_hill_identifiable_response_events/"
        "event_selection_manifest.json"
    ): "d03f6a8de7511c77105ba1a051f7b57292c43c48d7081256aecdf9db13b1bf3d",
    (
        "data/geotransport_v0_1/"
        "stage31_center_hill_identifiable_response_events/"
        "observation_plan.json"
    ): "34169db80643a05a51c8579811c7c99320ba594734871c63cc70fc8ac8464e35",
    (
        "data/geotransport_v0_1/"
        "stage31_center_hill_identifiable_response_events/"
        "observation_acquisition_manifest.json"
    ): "8f84fe838c5a7cf641195a8bbc941a2a1396360c510043e9ffedb22547122b97",
    (
        "data/geotransport_v0_1/"
        "stage31_center_hill_identifiable_response_events/"
        "identifiable_response_evidence_ledger.json"
    ): "31d2a47b078d448c3bd8cbe682416a9521f63b4cd1e0256bfd1b84a9eb688d96",
    (
        "benchmarks/geotransport_v0_1/"
        "stage31_identifiable_response_gates.json"
    ): "20f50e2e4d8aba5c67a4150116cc7134061bdff47c4946cc00bf766633983fb5",
    (
        "docs/architecture-decisions/"
        "adr-072-admit-release-excitation-support-not-universal-exact-lag.md"
    ): "a5f3ce6e5cd00100655ae705b1bf9b49f00bb50b5fa9663495df052168e9f9bc",
    (
        "data/geotransport_v0_1/"
        "stage31_center_hill_identifiable_response_events/README.md"
    ): "99de369ce7190a822e88c5aefac822fcde16d263a5c1f0f8b14182a40d5ee04f",
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
    ledger = evidence.compile_public_lag_support_evidence()
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
        ledger = evidence.compile_public_lag_support_evidence()
    report = ledger.as_dict()
    if ledger_artifact is None:
        ledger_artifact = _memory_artifact(DEFAULT_LEDGER_OUTPUT, report)
    frozen_stage31 = _frozen_hash_report(FROZEN_STAGE31_HASHES)
    first, second, third, fourth = ledger.events
    refusals = _refusal_control(ledger)
    selection_sources = [
        value
        for value in ledger.source_artifacts
        if value.get("event_id") is None
    ]
    observation_sources = [
        value
        for value in ledger.source_artifacts
        if value.get("event_id") is not None
    ]
    event_times = [
        datetime.fromisoformat(value.step_time_utc.replace("Z", "+00:00"))
        for value in ledger.events
    ]
    expected_event_ids = [
        "release_step_20220202T1900Z",
        "release_step_20220919T1500Z",
        "release_step_20230911T1500Z",
        "release_step_20210625T1600Z",
    ]
    gates = {
        "all_fifteen_stage31_artifacts_remain_hash_frozen": all(
            value["matches"] for value in frozen_stage31.values()
        ),
        "release_support_operator_is_hash_frozen": (
            ledger.operator_artifacts["release_excitation_identifiability"][
                "sha256"
            ]
            == "6dd4266e60c569bb19f7b79387d2d6cf9da06ee81c68d886e74cc0d6564226eb"
        ),
        "empirical_lag_support_operator_is_hash_frozen": (
            ledger.operator_artifacts["empirical_lag_support"]["sha256"]
            == "43d561732f0aba563ea5a1138fd748a5017fdfde9c2b850ac4327e3a1e2ec4fc"
        ),
        "selection_is_one_public_request_and_private_free": (
            len(selection_sources) == 1
            and selection_sources[0]["source"] == "usace_cwms"
        ),
        "nine_public_sources_are_hash_and_tls_verified": (
            len(ledger.source_artifacts) == 9
            and len(observation_sources) == 8
            and all(
                len(str(value["sha256"])) == 64
                and value["hash_verified"] is True
                and value["tls_hostname_verification_retained"] is True
                for value in ledger.source_artifacts
            )
        ),
        "selection_plan_froze_both_operators_before_release_values": (
            ledger.selection_plan_artifact["sha256"]
            == "dc43874cb02b865cca760d21dfa7352db7e85e73329c414f65af5168bf491282"
        ),
        "event_manifest_froze_events_before_observations": (
            ledger.event_selection_manifest_artifact["sha256"]
            == "d66df4681831774b55bde7b156b52be3673e129b31b601bcff038fcb3ea6b17d"
        ),
        "observation_plan_was_hash_frozen_before_values": (
            ledger.observation_plan_artifact["sha256"]
            == "f1e5f2e7d6f0183023f29b960deb8ce0a41c38542e2f9e8dbb0dd5a223026af5"
        ),
        "five_year_release_pool_is_complete_and_unpaginated": (
            ledger.candidate_count == 401
            and selection_sources[0]["size_bytes"] == 1_244_077
        ),
        "four_expected_release_only_events_are_present": (
            [value.event_id for value in ledger.events]
            == expected_event_ids
        ),
        "selected_events_are_pairwise_separated_by_180_days": all(
            abs(left - right).days >= 180
            for index, left in enumerate(event_times)
            for right in event_times[index + 1 :]
        ),
        "all_selected_events_pass_frozen_release_gate": all(
            value.release_support.blind_response_test_admissible
            and value.release_support.rejection_reasons == ()
            for value in ledger.events
        ),
        "all_release_windows_have_seventy_two_real_hours": all(
            len(value.release_values_m3s) == 72
            and len(value.release_quality_codes) == 72
            and set(value.release_quality_codes) == {0}
            for value in ledger.events
        ),
        "downstream_gaps_are_preserved_without_fill": (
            [len(value.downstream_hourly) for value in ledger.events]
            == [84, 84, 77, 84]
            and [
                value.as_dict()["downstream_missing_hour_count"]
                for value in ledger.events
            ]
            == [0, 0, 7, 0]
        ),
        "all_compiled_downstream_hours_are_approved": all(
            hour.fully_approved
            for value in ledger.events
            for hour in value.downstream_hourly
        ),
        "lag_pair_counts_use_only_real_aligned_hours": (
            [
                tuple(item.pair_count for item in value.lag_diagnostics)
                for value in ledger.events
            ]
            == [
                (72,) * 13,
                (72,) * 13,
                (
                    66,
                    66,
                    66,
                    65,
                    65,
                    65,
                    65,
                    65,
                    65,
                    65,
                    65,
                    65,
                    65,
                ),
                (72,) * 13,
            ]
        ),
        "first_event_support_is_five_six_seven": (
            first.lag_support.supported_lags_hours == (5, 6, 7)
            and first.lag_support.best_lag_hours == 6
            and abs(first.lag_support.best_pearson_r - 0.8533970825151787)
            < 1e-12
        ),
        "second_event_support_is_six_seven": (
            second.lag_support.supported_lags_hours == (6, 7)
            and second.lag_support.best_lag_hours == 6
            and abs(second.lag_support.best_pearson_r - 0.8672719516081647)
            < 1e-12
        ),
        "third_event_resolves_seven_hour_empirical_support": (
            third.lag_support.supported_lags_hours == (7,)
            and third.lag_support.require_exact_hour() == 7
            and abs(third.lag_support.best_pearson_r - 0.8561258336937435)
            < 1e-12
        ),
        "fourth_event_fails_frozen_response_threshold": (
            fourth.lag_support.supported_lags_hours == ()
            and fourth.lag_support.response_rejection_reasons
            == ("best_lag_pearson_below_0_8",)
            and abs(fourth.lag_support.best_pearson_r - 0.7476521168447066)
            < 1e-12
        ),
        "only_detectable_events_receive_graph_relation_bindings": (
            [value.graph_relation is not None for value in ledger.events]
            == [True, True, True, False]
        ),
        "admitted_relations_bind_boundary_to_observed_outlet_node": all(
            value.graph_relation is not None
            and value.graph_relation.source_boundary_id
            == evidence.SOURCE_BOUNDARY_ID
            and value.graph_relation.target_site_id
            == evidence.TARGET_SITE_ID
            and value.graph_relation.target_comid == evidence.TARGET_COMID
            for value in ledger.events[:3]
        ),
        "not_all_blind_events_have_detectable_response": (
            ledger.all_events_have_detectable_response is False
        ),
        "cross_event_support_intersection_is_empty": (
            ledger.common_supported_lags_hours == ()
        ),
        "common_empirical_support_remains_unadmitted": (
            ledger.common_empirical_support_admitted is False
            and report["decision"]["common_empirical_support_admitted"]
            is False
        ),
        "smith_fork_graph_state_is_bound_to_observed_comid": (
            ledger.tributary_binding.site_id == evidence.TRIBUTARY_SITE_ID
            and ledger.tributary_binding.comid == evidence.TRIBUTARY_COMID
            and evidence.TARGET_COMID
            in ledger.tributary_binding.downstream_path_feature_ids
        ),
        "graph_state_gaps_are_preserved_without_fill": (
            [len(value.graph_states.states) for value in ledger.events]
            == [74, 84, 84, 81]
            and [
                value.graph_states.missing_hour_count
                for value in ledger.events
            ]
            == [10, 0, 0, 3]
            and all(
                value.graph_states.as_dict()["missing_values_filled"]
                is False
                for value in ledger.events
            )
        ),
        "all_compiled_graph_states_are_approved": all(
            state.fully_approved
            for value in ledger.events
            for state in value.graph_states.states
        ),
        "observed_graph_state_contract_remains_admitted": (
            report["decision"]["observed_graph_state_contract_admitted"]
            is True
        ),
        "unsupported_support_spatial_flux_and_runtime_claims_fail_closed": (
            all(refusals.values())
        ),
        "empirical_support_is_neither_physical_nor_hydraulic_time": (
            report["decision"]["physical_travel_time_admitted"] is False
            and report["decision"]["hydraulic_edge_travel_time_admitted"]
            is False
        ),
        "runtime_operator_remains_unadmitted": (
            report["decision"]["runtime_operator_admitted"] is False
        ),
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "blind_common_empirical_lag_support_rejected",
        "ledger_artifact": ledger_artifact,
        "frozen_stage31_hashes": frozen_stage31,
        "event_summary": [
            {
                "event_id": value.event_id,
                "release_direction": value.release_direction,
                "excursion_support_hours": (
                    value.release_support.excursion_support_hours
                ),
                "best_lag_hours": value.lag_support.best_lag_hours,
                "best_lag_pearson_r": value.lag_support.best_pearson_r,
                "supported_lags_hours": list(
                    value.lag_support.supported_lags_hours
                ),
                "response_detectable": (
                    value.lag_support.response_detectable
                ),
                "downstream_complete_hour_count": len(
                    value.downstream_hourly
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
        "decision": report["decision"],
        "claim_boundary": report["claim_boundary"],
    }


def _refusal_control(ledger) -> dict[str, bool]:
    calls = {
        "common_empirical_support": (
            ledger.require_common_empirical_support,
            "public_lag_support_common_empirical_support_unadmitted",
        ),
        "physical_travel_time": (
            ledger.require_physical_travel_time,
            "public_lag_support_empirical_set_is_not_physical_time",
        ),
        "hydraulic_edge_travel_time": (
            ledger.require_hydraulic_edge_travel_time,
            "public_lag_support_relation_is_not_hydraulic_edge_time",
        ),
        "tributary_mouth_flux": (
            ledger.require_tributary_mouth_flux,
            "public_lag_support_graph_state_is_not_mouth_flux",
        ),
        "runtime_operator": (
            ledger.promote_to_runtime_operator,
            "public_lag_support_runtime_operator_unadmitted",
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
