#!/usr/bin/env python3
"""Compile Stage 31 release-support and blind-response evidence gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import (
    public_identifiable_response_evidence as evidence,
)
from data_agent.uwm.geospatial_kernel_v2 import (
    release_excitation_identifiability as excitation,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "stage31_center_hill_identifiable_response_events"
)
DEFAULT_LEDGER_OUTPUT = DEFAULT_DATA_ROOT / (
    "identifiable_response_evidence_ledger.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "stage31_identifiable_response_gates.json"
)
SCHEMA = "gwm.geotransport.stage31_identifiable_response_gates.v1"

FROZEN_STAGE30_HASHES = {
    (
        "scripts/acquire_geotransport_stage30_regime_validation_events.py"
    ): "d84f3b4ed4e646e6183548f84163ca905cb2b720c3b78e38b3c0334bd1b490bc",
    (
        "data_agent/"
        "test_acquire_geotransport_stage30_regime_validation_events.py"
    ): "56f20c368e212407a66c2d58f8f37f92cfa06a60fe868c907dc2c72b1b16bf52",
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "public_regime_transfer_evidence.py"
    ): "c6a136c657cb40a1a558f9a9d157be0568243d4f27c343c96936147c5783ce44",
    (
        "data_agent/"
        "test_geospatial_kernel_public_regime_transfer_evidence.py"
    ): "bc01e96f05f5749b9a53aefe111cb992628d6e97ae0c2c6108ec2610525a53c3",
    (
        "scripts/compile_geotransport_stage30_regime_validation_gates.py"
    ): "7e3d357f561f4d4c81d0229d58617d5919ff229ad23af7f3597e352ea89940c8",
    (
        "data/geotransport_v0_1/"
        "stage30_center_hill_regime_validation_events/selection_plan.json"
    ): "dfea2f8c9abf9ba0044dd8c55027087d00e7c3221fbd9696fa44524015c38175",
    (
        "data/geotransport_v0_1/"
        "stage30_center_hill_regime_validation_events/"
        "event_selection_manifest.json"
    ): "63ab64c6e6cbb9d4372d58e28d52d005a499b31ff6d5526a1aa9b7a7429364b6",
    (
        "data/geotransport_v0_1/"
        "stage30_center_hill_regime_validation_events/observation_plan.json"
    ): "51dfcb8ae9daa797fd4fead0629bfb9651fbcb4cd3bfecfea85ce6a8e9c32a6a",
    (
        "data/geotransport_v0_1/"
        "stage30_center_hill_regime_validation_events/"
        "observation_acquisition_manifest.json"
    ): "c44eb3d49e455e86f729ac1b3968481123ef37fe288de82f9da3c4416a349849",
    (
        "data/geotransport_v0_1/"
        "stage30_center_hill_regime_validation_events/"
        "regime_transfer_evidence_ledger.json"
    ): "6153cdea6451e8ff8b2126ce5776d2f4dc33d4bc616cb8e5eb201e56cebf283c",
    (
        "benchmarks/geotransport_v0_1/"
        "stage30_regime_validation_gates.json"
    ): "246c83a77a16478ec42155673f7ecd04c6de0d4da1d15f66ff3bb768fab25afd",
    (
        "docs/architecture-decisions/"
        "adr-071-reject-single-threshold-lag-rule-and-admit-"
        "graph-state-contract.md"
    ): "d9a5a39df403b4f5fb37697775e1d0ca4258eaffc797b592676abaf72f9ef1e1",
    (
        "data/geotransport_v0_1/"
        "stage30_center_hill_regime_validation_events/README.md"
    ): "e1b44c16530954e57743dde42949c2caf516e37d0e2c0974961fa08bc400257d",
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
    ledger = evidence.compile_public_identifiable_response_evidence()
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
        ledger = evidence.compile_public_identifiable_response_evidence()
    report = ledger.as_dict()
    if ledger_artifact is None:
        ledger_artifact = _memory_artifact(DEFAULT_LEDGER_OUTPUT, report)
    frozen_stage30 = _frozen_hash_report(FROZEN_STAGE30_HASHES)
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
    gates = {
        "all_thirteen_stage30_artifacts_remain_hash_frozen": all(
            value["matches"] for value in frozen_stage30.values()
        ),
        "release_support_operator_is_hash_frozen": (
            ledger.operator_artifact["sha256"]
            == "6dd4266e60c569bb19f7b79387d2d6cf9da06ee81c68d886e74cc0d6564226eb"
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
        "selection_plan_froze_operator_before_release_values": (
            ledger.selection_plan_artifact["sha256"]
            == "0ebb39f688776b64458283d1b39ad67312381bbf9acf8bdd7f9ee864f37e53f7"
        ),
        "event_manifest_froze_events_before_observations": (
            ledger.event_selection_manifest_artifact["sha256"]
            == "d03f6a8de7511c77105ba1a051f7b57292c43c48d7081256aecdf9db13b1bf3d"
        ),
        "observation_plan_was_hash_frozen_before_values": (
            ledger.observation_plan_artifact["sha256"]
            == "34169db80643a05a51c8579811c7c99320ba594734871c63cc70fc8ac8464e35"
        ),
        "five_year_release_pool_is_complete_and_unpaginated": (
            ledger.candidate_count == 1812
            and selection_sources[0]["size_bytes"] == 1_244_077
        ),
        "four_required_release_strata_are_present_once": (
            tuple(value.selection_stratum for value in ledger.events)
            == evidence.STRATUM_ORDER
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
        "all_selected_events_have_twelve_excitation_hours": (
            [
                value.release_support.excursion_support_hours
                for value in ledger.events
            ]
            == [12, 12, 12, 12]
        ),
        "all_release_windows_have_seventy_two_real_hours": all(
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
        "first_event_has_detectable_six_hour_response": (
            first.best_lag_hours == 6
            and first.response_detectable
            and abs(
                float(first.best_lag_diagnostic.pearson_r)
                - 0.9410482377387122
            )
            < 1e-12
        ),
        "second_event_has_detectable_six_hour_response": (
            second.best_lag_hours == 6
            and second.response_detectable
            and abs(
                float(second.best_lag_diagnostic.pearson_r)
                - 0.9368952303836997
            )
            < 1e-12
        ),
        "third_event_has_detectable_six_hour_response": (
            third.best_lag_hours == 6
            and third.response_detectable
            and abs(
                float(third.best_lag_diagnostic.pearson_r)
                - 0.9199966010515274
            )
            < 1e-12
        ),
        "fourth_event_has_detectable_six_hour_response": (
            fourth.best_lag_hours == 6
            and fourth.response_detectable
            and abs(
                float(fourth.best_lag_diagnostic.pearson_r)
                - 0.8310274060786108
            )
            < 1e-12
        ),
        "release_support_gate_is_validated_on_all_four_events": (
            ledger.all_events_have_detectable_response
            and report["decision"]["release_support_gate_validated"] is True
            and ledger.require_validated_release_support_gate()
            == excitation.SCHEMA
        ),
        "only_third_event_resolves_exact_hour": (
            [value.exact_hour_resolved for value in ledger.events]
            == [False, False, True, False]
            and third.require_exact_hour_lag() == 6
        ),
        "universal_exact_hour_lag_remains_unadmitted": (
            ledger.all_events_resolve_exact_hour is False
            and report["decision"]["universal_exact_hour_lag_admitted"]
            is False
        ),
        "smith_fork_graph_state_is_bound_to_observed_comid": (
            ledger.tributary_binding.site_id == evidence.TRIBUTARY_SITE_ID
            and ledger.tributary_binding.comid == evidence.TRIBUTARY_COMID
            and evidence.OUTLET_COMID
            in ledger.tributary_binding.downstream_path_feature_ids
        ),
        "graph_state_gaps_are_preserved_without_fill": (
            [len(value.graph_states.states) for value in ledger.events]
            == [84, 81, 84, 84]
            and [
                value.graph_states.missing_hour_count
                for value in ledger.events
            ]
            == [0, 3, 0, 0]
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
        "unsupported_exact_spatial_and_runtime_claims_fail_closed": all(
            refusals.values()
        ),
        "empirical_lag_is_not_physical_travel_time": (
            report["decision"]["physical_travel_time_admitted"] is False
        ),
        "runtime_operator_remains_unadmitted": (
            report["decision"]["runtime_operator_admitted"] is False
        ),
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "release_support_gate_validated_exact_hour_not_universal"
        ),
        "ledger_artifact": ledger_artifact,
        "frozen_stage30_hashes": frozen_stage30,
        "event_summary": [
            {
                "event_id": value.event_id,
                "selection_stratum": value.selection_stratum,
                "excitation_mode": value.release_support.excitation_mode,
                "excursion_support_hours": (
                    value.release_support.excursion_support_hours
                ),
                "normalized_excitation_volume_step_hours": (
                    value.release_support.
                    normalized_excitation_volume_step_hours
                ),
                "best_lag_hours": value.best_lag_hours,
                "best_lag_pearson_r": (
                    value.best_lag_diagnostic.pearson_r
                ),
                "peak_margin_pearson_r": value.peak_margin_pearson_r,
                "response_detectable": value.response_detectable,
                "exact_hour_resolved": value.exact_hour_resolved,
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
        "universal_exact_hour_lag": (
            ledger.require_universal_exact_hour_lag,
            "public_identifiable_response_exact_hour_not_universal",
        ),
        "physical_travel_time": (
            ledger.require_physical_travel_time,
            "public_identifiable_response_empirical_lag_is_not_physical_time",
        ),
        "tributary_mouth_flux": (
            ledger.require_tributary_mouth_flux,
            "public_identifiable_response_graph_state_is_not_mouth_flux",
        ),
        "runtime_operator": (
            ledger.promote_to_runtime_operator,
            "public_identifiable_response_runtime_operator_unadmitted",
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
