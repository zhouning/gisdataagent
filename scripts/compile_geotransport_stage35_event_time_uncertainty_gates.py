#!/usr/bin/env python3
"""Compile Stage 35 event-time uncertainty propagation gates."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import (
    event_time_uncertainty as time,
)
from data_agent.uwm.geospatial_kernel_v2 import (
    public_event_time_uncertainty as evidence,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/stage35_center_hill_event_time_uncertainty"
)
DEFAULT_LEDGER_OUTPUT = DEFAULT_DATA_ROOT / (
    "event_time_uncertainty_ledger.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "stage35_event_time_uncertainty_gates.json"
)
SCHEMA = "gwm.geotransport.stage35_event_time_uncertainty_gates.v1"
STATUS = "event_time_uncertainty_propagated_physical_response_rejected"

FROZEN_STAGE34_HASHES = {
    "data_agent/uwm/geospatial_kernel_v2/temporal_response_semantics.py": (
        "8632158a2ecfe194f6419fc6ceab5f7eca7ef958cc694a8719742b97ffd90bdd"
    ),
    "data_agent/test_geospatial_kernel_temporal_response_semantics.py": (
        "3bb48799ad34daf2913e0b9f327ad6d76cd31d8d1babd134a197d5bdaec7acfb"
    ),
    "scripts/acquire_geotransport_stage34_temporal_semantics_evidence.py": (
        "4ddc6664ae57d1fae613b5b1ac1ab264a49d34e24719cd38e6e8aea7159772c5"
    ),
    (
        "data_agent/"
        "test_acquire_geotransport_stage34_temporal_semantics_evidence.py"
    ): "d75589648c7158caa83c68d5497d0b27b739f7f151af39c49514baa320b4d345",
    (
        "data/geotransport_v0_1/stage34_center_hill_temporal_semantics/"
        "acquisition_plan.json"
    ): "86b646f133e705a226afbc079bd1d4d02f814fc0f6b7f05be589c77413f8c043",
    (
        "data/geotransport_v0_1/stage34_center_hill_temporal_semantics/"
        "acquisition_manifest.json"
    ): "82fbf0460344331f25f567b19665ce3883699f8283ed856820fb0fa49901749d",
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "public_temporal_response_semantics.py"
    ): "8fe448855cc1a4837abf3f2c2636903440f2b9056aed6ab456fcac67bb955f73",
    (
        "data_agent/"
        "test_geospatial_kernel_public_temporal_response_semantics.py"
    ): "3792f20f0636be9c58aacae63899e3dc826bf27196a20c206b32647ea7381075",
    "scripts/compile_geotransport_stage34_temporal_semantics_gates.py": (
        "8a9fb54548a8ddeb2a121b6c9532f4811a50899159baf106b3b344e3804fb49b"
    ),
    (
        "data/geotransport_v0_1/stage34_center_hill_temporal_semantics/"
        "temporal_response_semantics_ledger.json"
    ): "45b5a51d4ec0500e9288dd97b1a41a9632c9c95d45c7a959a65ffc4cab8a101c",
    "benchmarks/geotransport_v0_1/stage34_temporal_semantics_gates.json": (
        "482024d6517f1da7a4f5cd4ee793515e97d7eb39269db03a343f90c3c273fba7"
    ),
    (
        "docs/architecture-decisions/"
        "adr-075-admit-interval-label-shift-reject-process-time-substitution.md"
    ): "2e88042a6d46ad07dd57a30713c49b083ac1f9c84c2e99d0489dc3a55a1728d6",
    (
        "data/geotransport_v0_1/stage34_center_hill_temporal_semantics/"
        "README.md"
    ): "a57eeaa00ebc636c87fd552abaef2a51ba5ae31dc2d97eaf9c1086221af42c0d",
}

FROZEN_STAGE35_HASHES = {
    "data_agent/uwm/geospatial_kernel_v2/event_time_uncertainty.py": (
        "660d596341eea9a54c96332834e58d1418953cc4838589ac4826aba35ce4600d"
    ),
    "data_agent/test_geospatial_kernel_event_time_uncertainty.py": (
        "d096f8391f410ead674934f32b098419c2011d1f2d7e17c66b72256282535e28"
    ),
    "scripts/freeze_geotransport_stage35_event_time_uncertainty_protocol.py": (
        "1ab6643b7ba9af43d3e9cff97441e63cc8b75afc979eb7c109f81b14e1fd165c"
    ),
    (
        "data_agent/"
        "test_freeze_geotransport_stage35_event_time_uncertainty_protocol.py"
    ): "901852ded5265e6901cefb99c3064ffc037b454b1e086e56b65d44511d5b8f16",
    (
        "data/geotransport_v0_1/stage35_center_hill_event_time_uncertainty/"
        "protocol.json"
    ): "e3a226937ffb0a15298d2f55d02c8e465fd71a2e6bd1453f9c3c3f7be1963f25",
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "public_event_time_uncertainty.py"
    ): "11df05ca5bb2e01e70e58d8c1c2d3f137bcad94d6bc06f3cc000680866782af7",
    "data_agent/test_geospatial_kernel_public_event_time_uncertainty.py": (
        "8896af241ed9a10b49af725c93218417f51e94763186d981a24efee07bf6e540"
    ),
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
    ledger = evidence.compile_public_event_time_uncertainty()
    ledger_artifact = _write_artifact(args.ledger_output, ledger.as_dict())
    report = compile_report(
        ledger=ledger,
        ledger_artifact=ledger_artifact,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_json_bytes(report))
    print(args.output)
    print(f"status={report['status']}")
    print(f"gates={sum(report['gates'].values())}/{len(report['gates'])}")
    return 0 if report["all_gates_passed"] else 1


def compile_report(
    *,
    ledger=None,
    ledger_artifact: dict[str, object] | None = None,
) -> dict[str, Any]:
    if ledger is None:
        ledger = evidence.compile_public_event_time_uncertainty()
    ledger_report = ledger.as_dict()
    if ledger_artifact is None:
        ledger_artifact = _memory_artifact(
            DEFAULT_LEDGER_OUTPUT, ledger_report
        )
    protocol = json.loads(
        (REPO_ROOT / str(ledger.protocol_artifact["path"])).read_bytes()
    )
    frozen_stage34 = _frozen_hash_report(FROZEN_STAGE34_HASHES)
    frozen_stage35 = _frozen_hash_report(FROZEN_STAGE35_HASHES)
    reconciliation = ledger.reconciliation
    compatibilities = reconciliation.compatibilities
    refusals = _refusal_control(ledger)
    diagnostic = ledger_report["diagnostic_summary"]
    decision = ledger_report["decision"]
    disconnected = time.compile_relative_event_delay_envelope(
        evidence.RELATION_ID,
        evidence.PATH_ID,
        (2, 6),
        ledger.support_uncertainty,
        "stage35:disconnected-control",
    )
    expected_event_envelopes = [
        [[4.0, 8.0]],
        [[5.0, 8.0]],
        [[6.0, 8.0]],
        [],
    ]
    expected_physics_intervals = [
        [1.1636556564598701, 1.2434852223876611],
        [15.582960350766653, 16.802247333679684],
        [18.329537115520722, 24.170511891777153],
    ]
    gates = {
        "all_thirteen_stage34_artifacts_remain_hash_frozen": all(
            value["matches"] for value in frozen_stage34.values()
        ),
        "stage35_operator_and_unit_test_are_hash_frozen": all(
            frozen_stage35[path]["matches"]
            for path in (
                "data_agent/uwm/geospatial_kernel_v2/"
                "event_time_uncertainty.py",
                "data_agent/test_geospatial_kernel_event_time_uncertainty.py",
            )
        ),
        "stage35_protocol_builder_and_test_are_hash_frozen": all(
            frozen_stage35[path]["matches"]
            for path in (
                "scripts/freeze_geotransport_stage35_"
                "event_time_uncertainty_protocol.py",
                "data_agent/test_freeze_geotransport_stage35_"
                "event_time_uncertainty_protocol.py",
            )
        ),
        "stage35_protocol_was_hash_frozen_before_evidence_compilation": (
            frozen_stage35[
                "data/geotransport_v0_1/"
                "stage35_center_hill_event_time_uncertainty/protocol.json"
            ]["matches"]
        ),
        "stage35_evidence_compiler_and_test_are_hash_frozen": all(
            frozen_stage35[path]["matches"]
            for path in (
                "data_agent/uwm/geospatial_kernel_v2/"
                "public_event_time_uncertainty.py",
                "data_agent/"
                "test_geospatial_kernel_public_event_time_uncertainty.py",
            )
        ),
        "protocol_forbids_network_new_data_and_posthoc_calibration": (
            protocol["data_boundary"]["network_requests_allowed"] is False
            and protocol["data_boundary"]["new_public_data_acquired"] is False
            and protocol["data_boundary"]["post_stage34_calibration_allowed"]
            is False
        ),
        "protocol_binds_exact_stage34_ledger": (
            ledger.stage34_ledger_artifact["sha256"]
            == FROZEN_STAGE34_HASHES[evidence.STAGE34_LEDGER_PATH]
        ),
        "protocol_binds_exact_stage34_gate_report": (
            ledger.stage34_gates_artifact["sha256"]
            == FROZEN_STAGE34_HASHES[evidence.STAGE34_GATES_PATH]
        ),
        "source_observation_support_is_exactly_one_hour": (
            ledger.support_uncertainty.source_duration_hours == 1.0
        ),
        "target_observation_support_is_exactly_one_hour": (
            ledger.support_uncertainty.target_duration_hours == 1.0
        ),
        "source_and_target_timestamps_remain_end_labeled": (
            ledger.support_uncertainty.source_timestamp_position == "end"
            and ledger.support_uncertainty.target_timestamp_position == "end"
        ),
        "open_left_observation_supports_are_closed_conservatively": (
            ledger.support_uncertainty.conservative_closure_used is True
            and ledger.support_uncertainty.source_event_offset_hours
            == (-1.0, 0.0)
            and ledger.support_uncertainty.target_event_offset_hours
            == (-1.0, 0.0)
        ),
        "delay_dilation_formulas_are_exactly_frozen": (
            protocol["frozen_dilation"]["delay_lower_formula"]
            == "max(0,label_shift-target_duration)"
            and protocol["frozen_dilation"]["delay_upper_formula"]
            == "label_shift+source_duration"
        ),
        "five_hour_label_shift_dilates_to_four_through_six_hours": (
            ledger.support_uncertainty.delay_interval_for_label_shift(5)
            == time.ClosedTemporalInterval(4.0, 6.0)
        ),
        "disconnected_lag_sets_remain_disconnected_after_dilation": (
            disconnected.intervals
            == (
                time.ClosedTemporalInterval(1.0, 3.0),
                time.ClosedTemporalInterval(5.0, 7.0),
            )
        ),
        "all_four_stage32_event_identities_and_ranks_are_preserved": (
            ledger.event_ids == evidence.EVENT_IDS
            and [value["selection_rank"] for value in protocol[
                "frozen_empirical_support"
            ]["events"]]
            == [1, 2, 3, 4]
        ),
        "all_four_stage32_discrete_lag_sets_are_preserved": (
            ledger.event_label_shift_sets
            == ((5, 6, 7), (6, 7), (7,), ())
        ),
        "event_delay_envelopes_match_frozen_dilation": (
            diagnostic["event_delay_envelopes_hours"]
            == expected_event_envelopes
        ),
        "empty_fourth_event_remains_empty_after_dilation": (
            reconciliation.event_envelopes[-1].intervals == ()
        ),
        "empirical_union_dilates_to_four_through_eight_hours": (
            diagnostic["empirical_union_delay_envelope_hours"]
            == [[4.0, 8.0]]
        ),
        "stage34_common_empirical_support_refusal_is_preserved": (
            reconciliation.original_common_empirical_support_admitted is False
        ),
        "not_all_events_have_nonempty_uncertainty_support": (
            reconciliation.all_events_have_nonempty_support is False
        ),
        "all_event_uncertainty_intersection_remains_empty": (
            reconciliation.common_event_delay_intervals == ()
        ),
        "three_typed_physics_quantities_are_preserved": (
            diagnostic["physics_quantities"]
            == [
                "gravity_wave_time",
                "manning_kinematic_centroid_time",
                "advective_residence_time",
            ]
        ),
        "three_stage33_physics_intervals_are_preserved": (
            diagnostic["physics_intervals_hours"]
            == expected_physics_intervals
        ),
        "all_uncertainty_comparisons_share_the_admitted_spatial_path": all(
            value.same_spatial_path for value in compatibilities
        ),
        "post_dilation_physics_separation_matches_frozen_values": (
            diagnostic["minimum_separation_hours"]
            == [
                2.756514777612339,
                7.582960350766653,
                10.329537115520722,
            ]
        ),
        "no_physics_interval_overlaps_maximum_empirical_uncertainty": (
            not any(
                value.measurement_support_overlap
                for value in compatibilities
            )
        ),
        "stage34_process_semantic_refusals_are_preserved": all(
            not value.semantic_equivalence_admitted
            for value in compatibilities
        ),
        "uncertainty_envelope_physical_delay_access_fails_closed": refusals[
            "envelope_physical_delay"
        ],
        "all_physics_comparison_accesses_fail_closed": refusals[
            "physics_comparison"
        ],
        "common_event_delay_access_fails_closed": refusals[
            "common_event_delay"
        ],
        "physical_response_time_access_fails_closed": refusals[
            "physical_response_time"
        ],
        "runtime_transition_access_fails_closed": refusals[
            "runtime_transition"
        ],
        "decision_admits_only_bounded_uncertainty_propagation": (
            decision["hash_bound_prior_evidence_verified"] is True
            and decision["event_time_uncertainty_propagation_admitted"] is True
            and decision["common_event_delay_intervals_admitted"] is False
            and decision["any_measurement_support_physics_overlap"] is False
            and decision["semantic_equivalence_admitted"] is False
            and decision["physical_response_time_admitted"] is False
            and decision["runtime_transition_admitted"] is False
        ),
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": STATUS,
        "ledger_artifact": ledger_artifact,
        "frozen_stage34_hashes": frozen_stage34,
        "frozen_stage35_hashes": frozen_stage35,
        "protocol_summary": {
            "protocol_id": protocol["protocol_id"],
            "network_requests_allowed": protocol["data_boundary"][
                "network_requests_allowed"
            ],
            "post_stage34_calibration_allowed": protocol["data_boundary"][
                "post_stage34_calibration_allowed"
            ],
        },
        "diagnostic_summary": diagnostic,
        "typed_controls": refusals,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "decision": decision,
        "claim_boundary": ledger_report["claim_boundary"],
    }


def _refusal_control(ledger) -> dict[str, bool]:
    envelope_refusals = []
    for value in ledger.reconciliation.event_envelopes:
        try:
            value.require_physical_event_delay()
        except ValueError as exc:
            envelope_refusals.append(
                str(exc)
                == "event_time_uncertainty_envelope_is_not_physical_delay"
            )
        else:
            envelope_refusals.append(False)
    comparison_refusals = []
    for value in ledger.reconciliation.compatibilities:
        try:
            value.require_physical_comparison()
        except ValueError as exc:
            comparison_refusals.append(
                str(exc)
                == "event_time_uncertainty_physical_comparison_unadmitted"
            )
        else:
            comparison_refusals.append(False)
    calls = {
        "common_event_delay": (
            ledger.require_common_event_delay_intervals,
            "event_time_uncertainty_common_delay_unadmitted",
        ),
        "physical_response_time": (
            ledger.require_physical_response_time,
            "event_time_uncertainty_physical_response_unadmitted",
        ),
        "runtime_transition": (
            ledger.promote_to_runtime_transition,
            "event_time_uncertainty_runtime_transition_unadmitted",
        ),
    }
    result = {
        "envelope_physical_delay": all(envelope_refusals),
        "physics_comparison": all(comparison_refusals),
    }
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
        path = REPO_ROOT / relative
        body = path.read_bytes()
        actual = hashlib.sha256(body).hexdigest()
        result[relative] = {
            "expected_sha256": expected_hash,
            "actual_sha256": actual,
            "size_bytes": len(body),
            "matches": actual == expected_hash,
        }
    return result


def _write_artifact(path: Path, value: dict[str, Any]) -> dict[str, object]:
    body = _json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return {
        "path": _display_path(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _memory_artifact(path: Path, value: dict[str, Any]) -> dict[str, object]:
    body = _json_bytes(value)
    return {
        "path": _display_path(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
