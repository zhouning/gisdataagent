#!/usr/bin/env python3
"""Compile Stage 44 source-only component-lag replication gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import (  # noqa: E402
    compile_geotransport_stage44_component_lag_replication_events as events,
)
from scripts import (  # noqa: E402
    compile_geotransport_stage44_target_exposure_inventory as exposure,
)
from scripts import (  # noqa: E402
    freeze_geotransport_stage44_component_lag_replication_protocol as freeze,
)

DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/stage44_component_lag_replication_gates.json"
)
SCHEMA = "gwm.geotransport.stage44_component_lag_replication_gates.v1"
STATUS = events.STATUS
FROZEN_HASHES = {
    "scripts/freeze_geotransport_stage44_component_lag_replication_protocol.py": (
        "dd2954fe76ba36a0e9a30fc7eb40ca29529c96e8528c62764a1c6d552ce98798"
    ),
    "scripts/compile_geotransport_stage44_component_lag_replication_events.py": (
        "a2c0eff4b639d1c7e85a3578bcb65388db3dab755c40e25b73fb23704595ea29"
    ),
    f"{freeze.STAGE44_ROOT}/{events.PROTOCOL_NAME}": (
        "ee84167cf3b58b6ce1721795286f6539448f9fec5d781cd2212abfc67e47006d"
    ),
    f"{freeze.STAGE44_ROOT}/{events.CANDIDATE_LEDGER_NAME}": (
        "8ee23589977a0bf0520da90a4fb062b72f7448ba05fca4cda2ad84da2564f12b"
    ),
    f"{freeze.STAGE44_ROOT}/{events.MANIFEST_NAME}": (
        "b98851b30c5c3556eb52daff493546d7832e072beee256d9a6dd82e5c99abe9f"
    ),
    "data_agent/test_geospatial_kernel_target_exposure_inventory.py": (
        "a0b578d9a195bc881a061ebfda0afa51a93246efc2c58f4b7d9048aa3449e829"
    ),
    "data_agent/test_compile_geotransport_stage44_target_exposure_inventory.py": (
        "c990f30df91a5a0b706ec8188ef05c1934fd5d5e4abcb0f7c25b235b7f7c036f"
    ),
    (
        "data_agent/test_freeze_geotransport_stage44_component_lag_replication_protocol.py"
    ): "f90c1729475ec3ded5db999446e1a4b2540c65ff7b2afd64dff944d6b719d7bb",
    (
        "data_agent/test_compile_geotransport_stage44_component_lag_replication_events.py"
    ): "7ce6b1894906d82a3791239e3d839386aaea6fd28764e9bb2b952d3fb91e3b31",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_report() -> dict[str, Any]:
    protocol = freeze.build_protocol()
    inventory = exposure.compile_inventory()
    inventory_report = exposure.compile_report()
    selection = events.compile_selection()
    candidate_path = REPO_ROOT / freeze.STAGE44_ROOT / events.CANDIDATE_LEDGER_NAME
    manifest_path = REPO_ROOT / freeze.STAGE44_ROOT / events.MANIFEST_NAME
    protocol_path = REPO_ROOT / freeze.STAGE44_ROOT / events.PROTOCOL_NAME
    manifest = _read_json(manifest_path)
    frozen = _frozen_hash_report(FROZEN_HASHES)
    upstream = _frozen_hash_report(freeze.FROZEN_HASHES)
    selected = selection.selected_events
    exposure_counts: dict[str, int] = {}
    for record in inventory.records:
        exposure_counts[record.phase] = exposure_counts.get(record.phase, 0) + 1
    claims = manifest["claim_boundary"]
    later = protocol["later_target_protocol_boundary"]
    hypothesis = protocol["strict_replication_hypothesis"]
    gates = {
        "all_nine_stage44_implementation_test_and_output_artifacts_match": (
            len(frozen) == 9 and all(value["matches"] for value in frozen.values())
        ),
        "all_ten_upstream_protocol_inputs_match": (
            len(upstream) == 10 and all(value["matches"] for value in upstream.values())
        ),
        "all_fifteen_exposure_source_artifacts_are_hash_frozen": (
            len(inventory.source_artifacts) == 15
            and all(
                value["sha256"] == exposure.FROZEN_HASHES[str(value["path"])]
                for value in inventory.source_artifacts
            )
        ),
        "target_exposure_inventory_artifact_is_exactly_reproducible": (
            _read_json(REPO_ROOT / freeze.TARGET_EXPOSURE_INVENTORY_PATH) == inventory_report
        ),
        "all_thirty_four_target_exposure_records_are_preserved": (
            len(inventory.records) == 34 and inventory_report["exposure_record_count"] == 34
        ),
        "target_exposures_merge_to_twenty_seven_unique_intervals": (
            len(inventory.merged_intervals) == 27
            and inventory_report["merged_interval_count"] == 27
        ),
        "development_companion_and_d3_broad_windows_are_included": all(
            inventory.overlaps(begin, end)
            for begin, end in (
                ("2021-12-09T00:00:00Z", "2022-01-06T02:00:00Z"),
                ("2022-01-06T00:00:00Z", "2022-02-03T02:00:00Z"),
                ("2022-02-03T00:00:00Z", "2022-03-03T02:00:00Z"),
            )
        ),
        "blind_and_kinematic_broad_holdout_windows_are_included": all(
            inventory.overlaps(begin, end)
            for begin, end in (
                ("2022-03-31T00:00:00Z", "2022-04-28T02:00:00Z"),
                ("2022-10-13T00:00:00Z", "2022-12-08T02:00:00Z"),
            )
        ),
        "all_fifteen_stage29_through_stage32_event_windows_are_included": (
            sum(
                exposure_counts[name]
                for name in (
                    "stage29_blind_transfer",
                    "stage30_regime_validation",
                    "stage31_identifiable_response",
                    "stage32_lag_support",
                )
            )
            == 15
        ),
        "all_four_stage36_target_windows_are_included": (
            exposure_counts["stage36_hydraulic_boundary"] == 4
        ),
        "all_four_stage42_target_windows_are_included": (
            exposure_counts["stage42_component_event_targets"] == 4
        ),
        "stage27_probes_and_stage28_three_day_windows_are_included": (
            exposure_counts["stage27_spatial_boundary"] == 2
            and exposure_counts["stage28_operational_boundary"] == 2
        ),
        "request_boundaries_are_used_without_analysis_support_trimming": (
            inventory_report["boundary"]["request_boundaries_are_used_not_trimmed_analysis_support"]
            is True
        ),
        "inventory_compiler_loads_no_target_value_payloads": (
            inventory_report["boundary"]["target_values_loaded_by_inventory_compiler"] is False
            and inventory_report["boundary"]["network_request_count"] == 0
        ),
        "replication_protocol_is_exactly_reproducible": (_read_json(protocol_path) == protocol),
        "selector_compatibility_anchor_is_contained_by_first_exposure_window": (
            protocol["target_exposure_boundary"][
                "compatibility_anchor_is_already_contained_by_first_window"
            ]
            is True
            and protocol["target_exposure_boundary"]["selector_api_compatibility_anchor_utc"]
            == inventory.excluded_windows_utc[0][0]
        ),
        "thirty_day_closed_window_exclusion_is_frozen": (
            protocol["target_exposure_boundary"]["exclusion_radius_days"] == 30
            and protocol["target_exposure_boundary"][
                "candidate_window_must_not_overlap_expanded_interval"
            ]
            is True
        ),
        "source_support_retains_all_43825_synchronized_hours": (
            selection.total_value_count == 43_825
            and selection.synchronized_total_derivation_admissible is True
        ),
        "eligible_candidate_count_is_exactly_1343": (
            len(selection.candidates) == freeze.EXPECTED_ELIGIBLE_CANDIDATE_COUNT == 1_343
        ),
        "candidate_stratum_counts_are_exact": (
            dict(selection.candidate_counts_by_stratum) == freeze.EXPECTED_STRATUM_COUNTS
        ),
        "both_high_flow_direction_strata_remain_available": (
            freeze.EXPECTED_STRATUM_COUNTS["high_increase"] == 3
            and freeze.EXPECTED_STRATUM_COUNTS["high_decrease"] == 11
        ),
        "both_low_flow_direction_strata_remain_available": (
            freeze.EXPECTED_STRATUM_COUNTS["low_increase"] == 700
            and freeze.EXPECTED_STRATUM_COUNTS["low_decrease"] == 629
        ),
        "component_gate_candidate_counts_are_exact": (
            dict(selection.component_gate_candidate_counts) == freeze.EXPECTED_COMPONENT_COUNTS
        ),
        "exactly_four_source_only_replication_events_are_selected": (
            len(selected) == 4
            and all(value["selected_without_downstream_values"] is True for value in selected)
        ),
        "four_exact_event_ids_are_frozen": (
            tuple(str(value["event_id"]) for value in selected) == freeze.EXPECTED_EVENT_IDS
        ),
        "four_exact_event_times_are_frozen": (
            tuple(str(value["step_time_utc"]) for value in selected)
            == freeze.EXPECTED_EVENT_TIMES_UTC
        ),
        "four_strata_remain_in_predeclared_order": (
            tuple(str(value["selection_stratum"]) for value in selected)
            == ("high_increase", "high_decrease", "low_increase", "low_decrease")
        ),
        "all_selected_events_are_at_least_180_days_apart": (
            _events_are_separated(selected, timedelta(days=180))
        ),
        "selected_source_windows_do_not_overlap_raw_exposure_intervals": (
            all(
                not inventory.overlaps(str(value["start_utc"]), str(value["end_utc"]))
                for value in selected
            )
        ),
        "selected_source_windows_do_not_overlap_expanded_exposure_intervals": (
            _events_clear_expanded_exposures(selected, inventory.excluded_windows_utc)
        ),
        "all_selected_source_windows_have_exact_73_hour_support": all(
            value["inclusive_total_value_count"] == 73 for value in selected
        ),
        "all_selected_steps_exceed_fifty_cms": all(
            float(value["absolute_total_step_m3s"]) >= 50.0 for value in selected
        ),
        "all_selected_ranges_exceed_one_hundred_cms": all(
            float(value["total_window_range_m3s"]) >= 100.0 for value in selected
        ),
        "all_selected_events_pass_frozen_excitation_identifiability": all(
            value["release_excitation_identifiability"]["blind_response_test_admissible"] is True
            for value in selected
        ),
        "all_selected_steps_are_turbine_only": all(
            value["active_step_components"] == ["turbine"]
            and value["dominant_step_component"] == "turbine"
            for value in selected
        ),
        "source_quality_codes_are_preserved_without_approval_semantics": all(
            value["quality_codes_interpreted_as_approval"] is False for value in selected
        ),
        "strict_high_five_low_six_bidirectional_hypothesis_is_frozen": (
            hypothesis["high_flow_required_supported_lag_hours"] == 5
            and hypothesis["low_flow_required_supported_lag_hours"] == 6
            and hypothesis["directions_required_within_each_flow_class"] == ["increase", "decrease"]
            and hypothesis["partial_direction_or_flow_class_pass_allowed"] is False
        ),
        "stage43_target_operator_thresholds_remain_unchanged": (
            hypothesis["lag_candidates_hours"] == list(range(13))
            and hypothesis["required_event_local_pearson_r"] == 0.8
            and hypothesis["maximum_supported_lag_loss_pearson_r"] == 0.02
            and hypothesis["minimum_pair_count"] == 60
            and hypothesis["best_lag_must_be_interior"] is True
        ),
        "post_target_retuning_and_event_reselection_are_forbidden": (
            hypothesis["target_operator_retuning_after_values_allowed"] is False
            and hypothesis["event_reselection_after_values_allowed"] is False
        ),
        "stage44_creates_no_target_request_plan": (
            later["target_request_plan_created_in_stage44"] is False
            and manifest["data_boundary"]["target_request_plan_created"] is False
        ),
        "stage44_makes_no_network_request_and_acquires_no_values": (
            protocol["data_boundary"]["network_request_count"] == 0
            and manifest["data_boundary"]["network_request_count"] == 0
            and manifest["data_boundary"]["new_target_values_acquired"] is False
        ),
        "stage30_historical_falsification_is_explicitly_preserved": (
            protocol["decision_rule"]["future_pass_does_not_overturn_stage30_falsification"] is True
            and claims["stage30_historical_falsification_overturned"] is False
        ),
        "universal_causal_physical_component_and_runtime_promotions_are_rejected": (
            claims["universal_lag_admitted"] is False
            and claims["non_turbine_component_contrast_admitted"] is False
            and claims["causal_or_physical_relation_admitted"] is False
            and claims["runtime_operator_admitted"] is False
        ),
        "source_cohort_is_frozen_while_replication_remains_pending": (
            manifest["status"] == STATUS
            and claims["complete_known_target_exposure_boundary_applied"] is True
            and claims["source_only_replication_cohort_frozen"] is True
            and claims["stage44_replication_test_executed"] is False
            and claims["stage43_pattern_replicated"] is False
            and later["fresh_bounded_plan_required_before_requests"] is True
            and later["fresh_user_approval_required_after_plan_freeze"] is True
        ),
    }
    if len(gates) != 44:
        raise ValueError(f"stage44_gate_count_invalid:{len(gates)}")
    return {
        "schema": SCHEMA,
        "status": STATUS,
        "frozen_artifacts": frozen,
        "upstream_frozen_artifacts": upstream,
        "protocol_artifact": _artifact(protocol_path),
        "target_exposure_inventory_artifact": _artifact(
            REPO_ROOT / freeze.TARGET_EXPOSURE_INVENTORY_PATH
        ),
        "candidate_ledger_artifact": _artifact(candidate_path),
        "event_manifest_artifact": _artifact(manifest_path),
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "decision": {
            "complete_known_target_exposure_boundary_admitted": True,
            "source_only_replication_cohort_frozen": True,
            "selected_event_count": len(selected),
            "eligible_candidate_count": len(selection.candidates),
            "target_request_plan_created": False,
            "new_network_request_count": 0,
            "new_target_values_acquired": False,
            "stage43_pattern_replicated": False,
            "stage30_historical_falsification_overturned": False,
            "universal_lag_admitted": False,
            "non_turbine_component_contrast_admitted": False,
            "causal_or_physical_relation_admitted": False,
            "runtime_operator_admitted": False,
        },
    }


def _events_are_separated(selected: tuple[dict[str, object], ...], minimum: timedelta) -> bool:
    return all(
        abs(_parse_time(str(left["step_time_utc"])) - _parse_time(str(right["step_time_utc"])))
        >= minimum
        for index, left in enumerate(selected)
        for right in selected[index + 1 :]
    )


def _events_clear_expanded_exposures(
    selected: tuple[dict[str, object], ...],
    intervals: tuple[tuple[str, str], ...],
) -> bool:
    radius = timedelta(days=freeze.EXCLUSION_RADIUS_DAYS)
    return all(
        _parse_time(str(event["start_utc"])) > _parse_time(end) + radius
        or _parse_time(str(event["end_utc"])) < _parse_time(begin) - radius
        for event in selected
        for begin, end in intervals
    )


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("stage44_timezone_required")
    return parsed.astimezone(UTC)


def _frozen_hash_report(
    expected: dict[str, str],
) -> dict[str, dict[str, object]]:
    result = {}
    for relative_path, expected_sha256 in expected.items():
        artifact = _artifact(REPO_ROOT / relative_path)
        result[relative_path] = {
            **artifact,
            "expected_sha256": expected_sha256,
            "matches": artifact["sha256"] == expected_sha256,
        }
    return result


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
        raise ValueError("stage44_json_object_required")
    return value


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> int:
    args = parse_args()
    events.compile_artifacts()
    report = compile_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_json_bytes(report))
    print(args.output)
    print(f"status={report['status']}")
    print(f"gates={sum(report['gates'].values())}/{len(report['gates'])}")
    return 0 if report["all_gates_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
