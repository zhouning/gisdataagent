#!/usr/bin/env python3
"""Compile Stage 30 regime-validation and graph-state evidence gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import (
    public_regime_transfer_evidence as evidence,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "stage30_center_hill_regime_validation_events"
)
DEFAULT_LEDGER_OUTPUT = DEFAULT_DATA_ROOT / (
    "regime_transfer_evidence_ledger.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "stage30_regime_validation_gates.json"
)
SCHEMA = "gwm.geotransport.stage30_regime_validation_gates.v1"

FROZEN_STAGE29_HASHES = {
    (
        "scripts/acquire_geotransport_stage29_blind_transfer_events.py"
    ): "3eab4bc9d5721660f43ac28b154f2ea54f6da88dba9d8bbe1a5e08f7de2452ef",
    (
        "data_agent/test_acquire_geotransport_stage29_blind_transfer_events.py"
    ): "690b09f56382aeb586c5f54a5e344bb51dd139bec1c844d9ab7b217fba2645c5",
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "public_blind_transfer_evidence.py"
    ): "8e7ebbd4fb08b1d639771cb2bcd887763828767937eaf7ef176a25624afc8449",
    (
        "data_agent/test_geospatial_kernel_public_blind_transfer_evidence.py"
    ): "aacc61177f64de9b3cf52d530544ce6fd801f2292b8076f8b198a27da139789e",
    (
        "scripts/compile_geotransport_stage29_blind_transfer_gates.py"
    ): "d308a464f4be2bd34d5e9c9299a0a707fd61ca60e7ab67b08b00cb8b4394389e",
    (
        "data/geotransport_v0_1/"
        "stage29_center_hill_blind_transfer_events/selection_plan.json"
    ): "6b1a2b776ac1cc8d91ef1722e9b82fe48046f86cc242d88b091388090408dff5",
    (
        "data/geotransport_v0_1/stage29_center_hill_blind_transfer_events/"
        "event_selection_manifest.json"
    ): "480734abcdb2a535e7a2bc794dbf2a5d7e708d3d6faac7becbdea9429d05c91b",
    (
        "data/geotransport_v0_1/"
        "stage29_center_hill_blind_transfer_events/observation_plan.json"
    ): "ab90b2795616242c27c80cf06b5cba3c43462c535f4da1d8424a92c4a7b53727",
    (
        "data/geotransport_v0_1/stage29_center_hill_blind_transfer_events/"
        "observation_acquisition_manifest.json"
    ): "6e4597cc00612c4846e2f3cfdc1affbe5c9e75572fd81c2260d833c01d9864a8",
    (
        "data/geotransport_v0_1/stage29_center_hill_blind_transfer_events/"
        "blind_transfer_evidence_ledger.json"
    ): "dc87665b11ed243859cf8f7ff8cfd0b640c7998e83966b4eb3f5f9bfe558ce0f",
    (
        "benchmarks/geotransport_v0_1/stage29_blind_transfer_gates.json"
    ): "621c11f66cdc4c3b1462b0de4b1864e4fc0972b51d06ccb12bc64bb5fb39d71b",
    (
        "docs/architecture-decisions/"
        "adr-070-release-selected-blind-transfer-and-observed-tributary-state.md"
    ): "8bcfe70a026b94fc604b65393febdc12b4b804235c7274f251cfa8f420cccfca",
    (
        "data/geotransport_v0_1/"
        "stage29_center_hill_blind_transfer_events/README.md"
    ): "0dd6707eea0b73b1ba553deb627e35cac8793fb73e57f700f46ba158722e1d2b",
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
    ledger = evidence.compile_public_regime_transfer_evidence()
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
        ledger = evidence.compile_public_regime_transfer_evidence()
    report = ledger.as_dict()
    if ledger_artifact is None:
        ledger_artifact = _memory_artifact(DEFAULT_LEDGER_OUTPUT, report)
    frozen_stage29 = _frozen_hash_report(FROZEN_STAGE29_HASHES)
    high_increase, high_decrease, low_increase, low_decrease = ledger.events
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
        "all_thirteen_stage29_artifacts_remain_hash_frozen": all(
            value["matches"] for value in frozen_stage29.values()
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
        "selection_plan_froze_rule_before_release_values": (
            ledger.selection_plan_artifact["sha256"]
            == "dfea2f8c9abf9ba0044dd8c55027087d00e7c3221fbd9696fa44524015c38175"
        ),
        "event_manifest_froze_events_before_observations": (
            ledger.event_selection_manifest_artifact["sha256"]
            == "63ab64c6e6cbb9d4372d58e28d52d005a499b31ff6d5526a1aa9b7a7429364b6"
        ),
        "observation_plan_was_hash_frozen_before_values": (
            ledger.observation_plan_artifact["sha256"]
            == "51dfcb8ae9daa797fd4fead0629bfb9651fbcb4cd3bfecfea85ce6a8e9c32a6a"
        ),
        "five_year_release_pool_is_complete_and_unpaginated": (
            ledger.candidate_count == 4873
            and selection_sources[0]["size_bytes"] == 1_244_077
        ),
        "four_required_release_strata_are_present_once": (
            tuple(value.selection_stratum for value in ledger.events)
            == evidence.STRATUM_ORDER
        ),
        "direction_flow_and_magnitude_classes_are_explicit": (
            [value.release_direction for value in ledger.events]
            == ["increase", "decrease", "increase", "decrease"]
            and [value.antecedent_flow_class for value in ledger.events]
            == ["high", "high", "low", "low"]
            and [value.step_magnitude_class for value in ledger.events]
            == ["large", "moderate", "large", "moderate"]
        ),
        "selected_events_are_pairwise_separated_by_180_days": all(
            abs(left - right).days >= 180
            for index, left in enumerate(event_times)
            for right in event_times[index + 1 :]
        ),
        "frozen_rule_predicts_five_for_high_and_six_for_low": (
            [value.predicted_lag_hours for value in ledger.events]
            == [5, 5, 6, 6]
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
        "high_increase_counterexample_is_preserved": (
            high_increase.best_lag_hours == 4
            and high_increase.predicted_lag_hours == 5
            and not high_increase.rule_supported
            and abs(
                float(high_increase.predicted_lag_diagnostic.pearson_r)
                - 0.42541305790444195
            )
            < 1e-12
        ),
        "high_decrease_supports_frozen_prediction": (
            high_decrease.rule_supported
            and abs(
                float(high_decrease.predicted_lag_diagnostic.pearson_r)
                - 0.9324142144179708
            )
            < 1e-12
        ),
        "low_increase_supports_frozen_prediction": (
            low_increase.rule_supported
            and abs(
                float(low_increase.predicted_lag_diagnostic.pearson_r)
                - 0.8990338841735641
            )
            < 1e-12
        ),
        "low_decrease_supports_frozen_prediction": (
            low_decrease.rule_supported
            and abs(
                float(low_decrease.predicted_lag_diagnostic.pearson_r)
                - 0.8546508671711874
            )
            < 1e-12
        ),
        "three_of_four_support_and_regime_rule_is_rejected": (
            sum(value.rule_supported for value in ledger.events) == 3
            and ledger.all_strata_support_rule is False
            and report["decision"][
                "regime_conditioned_empirical_lag_admitted"
            ]
            is False
        ),
        "smith_fork_graph_state_is_bound_to_observed_comid": (
            ledger.stage29_tributary_binding.site_id
            == evidence.TRIBUTARY_SITE_ID
            and ledger.stage29_tributary_binding.comid
            == evidence.TRIBUTARY_COMID
            and evidence.OUTLET_COMID
            in ledger.stage29_tributary_binding.downstream_path_feature_ids
        ),
        "graph_state_gaps_are_preserved_without_fill": (
            [len(value.graph_states.states) for value in ledger.events]
            == [84, 80, 82, 84]
            and [
                value.graph_states.missing_hour_count
                for value in ledger.events
            ]
            == [0, 4, 2, 0]
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
        "observed_graph_state_contract_is_admitted": (
            report["decision"]["observed_graph_state_contract_admitted"]
            is True
        ),
        "graph_state_is_not_mouth_flux_lateral_total_or_oracle": (
            report["claim_boundary"][
                "smith_fork_is_tributary_mouth_flux"
            ]
            is False
            and report["claim_boundary"][
                "smith_fork_represents_all_lateral_inflow"
            ]
            is False
            and report["claim_boundary"][
                "smith_fork_is_mass_conservation_oracle"
            ]
            is False
        ),
        "unsupported_claims_fail_closed": all(refusals.values()),
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
            "four_strata_scored_regime_rule_rejected_graph_state_admitted"
        ),
        "ledger_artifact": ledger_artifact,
        "frozen_stage29_hashes": frozen_stage29,
        "event_summary": [
            {
                "event_id": value.event_id,
                "selection_stratum": value.selection_stratum,
                "antecedent_release_mean_m3s": (
                    value.antecedent_release_mean_m3s
                ),
                "predicted_lag_hours": value.predicted_lag_hours,
                "best_lag_hours": value.best_lag_hours,
                "predicted_lag_pearson_r": (
                    value.predicted_lag_diagnostic.pearson_r
                ),
                "rule_supported": value.rule_supported,
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
        "regime_conditioned_lag_rule": (
            ledger.require_regime_conditioned_lag_rule,
            "public_regime_transfer_rule_not_supported_by_all_strata",
        ),
        "physical_travel_time": (
            ledger.require_physical_travel_time,
            "public_regime_transfer_empirical_lag_is_not_physical_time",
        ),
        "tributary_mouth_flux": (
            ledger.require_tributary_mouth_flux,
            "public_regime_transfer_graph_state_is_not_mouth_flux",
        ),
        "total_lateral_inflow": (
            ledger.require_total_lateral_inflow,
            "public_regime_transfer_graph_state_is_not_lateral_total",
        ),
        "conservation_oracle": (
            ledger.require_conservation_oracle,
            "public_regime_transfer_graph_state_is_not_conservation_oracle",
        ),
        "runtime_operator": (
            ledger.promote_to_runtime_operator,
            "public_regime_transfer_runtime_operator_unadmitted",
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
