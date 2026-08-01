#!/usr/bin/env python3
"""Compile Stage 33 geospatial temporal-support reconciliation gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import (
    public_temporal_support_reconciliation as evidence,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/stage33_center_hill_temporal_support_path"
)
DEFAULT_LEDGER_OUTPUT = DEFAULT_DATA_ROOT / (
    "temporal_support_reconciliation_ledger.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "stage33_temporal_support_gates.json"
)
SCHEMA = "gwm.geotransport.stage33_temporal_support_gates.v1"

FROZEN_STAGE32_HASHES = {
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "empirical_lag_support.py"
    ): "43d561732f0aba563ea5a1138fd748a5017fdfde9c2b850ac4327e3a1e2ec4fc",
    (
        "data_agent/test_geospatial_kernel_empirical_lag_support.py"
    ): "0a14f3a817729b23a7b303831e3d03ddf2108bc302b094345555ad4129c5b0c9",
    (
        "scripts/acquire_geotransport_stage32_lag_support_events.py"
    ): "a56824920066f6b09af667273b21e2fee6abae834f6cef217bd6ddc0c8a079d3",
    (
        "data_agent/test_acquire_geotransport_stage32_lag_support_events.py"
    ): "86366e6b0429f03df3b51166709440e0a47193994e4f6c018d5434ab2eb1922d",
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "public_lag_support_evidence.py"
    ): "2079e39d179f371da95abdd545d2fd670fcb6763c87898f7da2c93226ab2a7a1",
    (
        "data_agent/test_geospatial_kernel_public_lag_support_evidence.py"
    ): "1318905cde84541bd03831f2a05dc4296cfc82ace5c5745e753a0320ea729185",
    (
        "scripts/compile_geotransport_stage32_lag_support_gates.py"
    ): "5b7a23051758124d8ac893c881e06835dc7e5d221f36a12fa04c8454a9939dfc",
    (
        "data/geotransport_v0_1/"
        "stage32_center_hill_lag_support_events/selection_plan.json"
    ): "dc43874cb02b865cca760d21dfa7352db7e85e73329c414f65af5168bf491282",
    (
        "data/geotransport_v0_1/stage32_center_hill_lag_support_events/"
        "event_selection_manifest.json"
    ): "d66df4681831774b55bde7b156b52be3673e129b31b601bcff038fcb3ea6b17d",
    (
        "data/geotransport_v0_1/"
        "stage32_center_hill_lag_support_events/observation_plan.json"
    ): "f1e5f2e7d6f0183023f29b960deb8ce0a41c38542e2f9e8dbb0dd5a223026af5",
    (
        "data/geotransport_v0_1/stage32_center_hill_lag_support_events/"
        "observation_acquisition_manifest.json"
    ): "8960a952be727defda098de02b3005b7a335c7ef1b8ec40f4c082dbe1294b648",
    (
        "data/geotransport_v0_1/stage32_center_hill_lag_support_events/"
        "lag_support_evidence_ledger.json"
    ): "c95bbf18d3d606161fc9b5cb6fe9d6f8b8439d495b25e326d4a9cf675d416b74",
    (
        "benchmarks/geotransport_v0_1/stage32_lag_support_gates.json"
    ): "175101fc441395c82a2a2870986ed074bd91aa49d9e639d92d0540dcdba938fc",
    (
        "docs/architecture-decisions/"
        "adr-073-admit-event-local-lag-support-reject-common-support.md"
    ): "3cb68a16f50a1bc6e7d7416d67642d1a6850c2cab17f19f008fa274d723d7adf",
    (
        "data/geotransport_v0_1/"
        "stage32_center_hill_lag_support_events/README.md"
    ): "a0feeb68920ff39cd3b0b549eb9e3203c40566d70b444e458ea35388ca94a789",
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
    ledger = evidence.compile_public_temporal_support_reconciliation()
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
        ledger = evidence.compile_public_temporal_support_reconciliation()
    report = ledger.as_dict()
    if ledger_artifact is None:
        ledger_artifact = _memory_artifact(DEFAULT_LEDGER_OUTPUT, report)
    acquisition_plan = json.loads(
        (
            REPO_ROOT
            / str(ledger.acquisition_plan_artifact["path"])
        ).read_bytes()
    )
    frozen_stage32 = _frozen_hash_report(FROZEN_STAGE32_HASHES)
    path = ledger.path_binding
    values = ledger.reconciliation.compatibilities
    physics = [value.physics for value in values]
    refusals = _refusal_control(ledger)
    decision = report["decision"]
    claim_boundary = report["claim_boundary"]
    expected_intervals = (
        (
            1.1636556564598701,
            1.2017945393393767,
            1.2434852223876611,
        ),
        (
            15.582960350766653,
            16.144952135344774,
            16.802247333679684,
        ),
        (
            18.329537115520722,
            22.907743002956767,
            24.170511891777153,
        ),
    )
    expected_gaps = (
        3.756514777612339,
        8.582960350766653,
        11.329537115520722,
    )
    gates = {
        "all_fifteen_stage32_artifacts_remain_hash_frozen": all(
            value["matches"] for value in frozen_stage32.values()
        ),
        "geospatial_temporal_support_operator_is_hash_frozen": (
            ledger.operator_artifact["sha256"]
            == "62bda56dedfb65995556aa4964ea220c4ea8a9976738694f2e784cd664b360d1"
        ),
        "acquisition_plan_was_hash_frozen_before_path_values": (
            ledger.acquisition_plan_artifact["sha256"]
            == "55f2618d7d6508a0b6e0ef4556d934514f8f42ea20a208e4272d53e27d0f76b8"
        ),
        "acquisition_manifest_is_hash_bound": (
            ledger.acquisition_manifest_artifact["sha256"]
            == "79895bfd9f499b8a383d29b4deb06b0326bc9a6cb62e09e10c390371657921f3"
        ),
        "one_public_nldi_path_is_hash_and_tls_verified": (
            path.source_artifact["source"] == "usgs_nldi"
            and path.source_artifact["sha256"]
            == "80658a566575b65a89961ecb6d9ce28b8266028bd47863d6a2127753c2fac215"
            and path.source_artifact["size_bytes"] == 12_096
            and path.source_artifact["hash_verified"] is True
            and path.source_artifact["tls_hostname_verification_retained"]
            is True
        ),
        "path_request_is_outcome_free_and_private_data_free": (
            acquisition_plan["request_boundary"]["maximum_request_count"]
            == 1
            and acquisition_plan["request_boundary"][
                "release_or_downstream_outcome_values_requested"
            ]
            is False
            and acquisition_plan["request_boundary"][
                "workspace_or_private_data_sent"
            ]
            is False
        ),
        "path_starts_at_source_and_ends_at_target": (
            path.feature_ids[0] == evidence.SOURCE_COMID
            and path.feature_ids[-1] == evidence.TARGET_COMID
            and len(path.feature_ids) == 24
        ),
        "path_flowlines_are_unique_and_connected": (
            len(set(path.feature_ids)) == 24
            and path.maximum_connection_gap_m == 0.0
        ),
        "source_and_target_pass_predeclared_snap_tolerances": (
            path.source_snap_distance_m <= evidence.SOURCE_ZONE_RADIUS_M
            and path.target_snap_distance_m
            <= evidence.TARGET_SNAP_TOLERANCE_M
        ),
        "independent_path_matches_both_physics_path_suffixes": (
            path.physics_path_suffix_matches is True
        ),
        "independent_and_physics_path_lengths_are_equivalent": (
            path.physics_path_extra_upstream_length_m
            <= evidence.PATH_LENGTH_EQUIVALENCE_TOLERANCE_M
        ),
        "spatial_path_is_admitted_by_typed_binding": (
            path.spatial_path_admitted is True
            and path.require_spatial_path() == path.feature_ids
        ),
        "stage32_event_support_sets_are_preserved_exactly": (
            ledger.stage32_event_support_sets
            == ((5, 6, 7), (6, 7), (7,), ())
        ),
        "only_three_stage32_events_have_detectable_relations": (
            ledger.stage32_detectable_relation_count == 3
        ),
        "empirical_union_is_five_six_seven": (
            ledger.reconciliation.empirical.supported_hours == (5, 6, 7)
        ),
        "empirical_union_is_not_mislabeled_as_common_support": (
            ledger.reconciliation.all_event_common_empirical_support
            is False
            and claim_boundary[
                "stage32_empirical_union_is_common_support"
            ]
            is False
        ),
        "three_physics_quantities_are_typed_and_distinct": (
            [value.quantity for value in physics]
            == [
                "gravity_wave_time",
                "manning_kinematic_centroid_time",
                "advective_residence_time",
            ]
            and len({value.support_id for value in physics}) == 3
        ),
        "physics_candidates_are_state_dependent": all(
            value.state_dependent for value in physics
        ),
        "physics_candidates_are_not_outcome_calibrated": all(
            value.outcome_calibrated is False for value in physics
        ),
        "physics_candidates_are_not_admitted_as_response_lag": all(
            value.admitted_as_physical_time is False for value in physics
        ),
        "all_temporal_candidates_use_the_admitted_spatial_path": all(
            value.same_spatial_path is True for value in values
        ),
        "gravity_wave_interval_reproduces_public_state_evidence": (
            _interval(physics[0]) == expected_intervals[0]
        ),
        "manning_interval_reproduces_public_state_evidence": (
            _interval(physics[1]) == expected_intervals[1]
        ),
        "advective_interval_reproduces_nwm_evidence": (
            _interval(physics[2]) == expected_intervals[2]
        ),
        "no_physics_interval_overlaps_empirical_union": all(
            value.numerical_overlap is False
            and value.overlapping_empirical_hours == ()
            for value in values
        ),
        "minimum_temporal_separations_are_reproduced": all(
            abs(value.minimum_separation_hours - expected) < 1e-12
            for value, expected in zip(values, expected_gaps, strict=True)
        ),
        "numerical_overlap_is_not_declared_physical_validation": (
            claim_boundary["numerical_overlap_equals_physical_validation"]
            is False
        ),
        "typed_spatial_path_access_succeeds": refusals["spatial_path"],
        "typed_physics_consistency_access_fails_closed": refusals[
            "physics_consistency"
        ],
        "typed_runtime_transition_promotion_fails_closed": refusals[
            "runtime_transition"
        ],
        "nine_upstream_artifacts_are_hash_bound": (
            len(ledger.source_artifacts) == 9
            and all(
                len(str(value["sha256"])) == 64
                and int(value["size_bytes"]) > 0
                for value in ledger.source_artifacts
            )
        ),
        "decision_admits_path_but_rejects_temporal_consistency": (
            decision["spatial_path_admitted"] is True
            and decision["physics_support_candidates_admitted"] is True
            and decision["any_numerical_temporal_overlap"] is False
            and decision["physics_consistency_admitted"] is False
        ),
        "runtime_transition_remains_unadmitted": (
            decision["runtime_transition_admitted"] is False
            and claim_boundary["runtime_transition_admitted"] is False
        ),
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "spatial_path_admitted_temporal_reconciliation_rejected"
        ),
        "ledger_artifact": ledger_artifact,
        "frozen_stage32_hashes": frozen_stage32,
        "path_summary": {
            "source_comid": path.source_comid,
            "target_comid": path.target_comid,
            "feature_count": len(path.feature_ids),
            "linear_referenced_length_m": path.linear_referenced_length_m,
            "source_snap_distance_m": path.source_snap_distance_m,
            "target_snap_distance_m": path.target_snap_distance_m,
            "maximum_connection_gap_m": path.maximum_connection_gap_m,
            "spatial_path_admitted": path.spatial_path_admitted,
        },
        "temporal_support_summary": [
            {
                "support_id": value.physics.support_id,
                "quantity": value.physics.quantity,
                "support_interval_hours": [
                    value.physics.lower_hours,
                    value.physics.upper_hours,
                ],
                "central_hours": value.physics.central_hours,
                "overlapping_empirical_hours": list(
                    value.overlapping_empirical_hours
                ),
                "minimum_separation_hours": (
                    value.minimum_separation_hours
                ),
                "physical_consistency_admitted": (
                    value.physical_consistency_admitted
                ),
            }
            for value in values
        ],
        "typed_controls": refusals,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "decision": decision,
        "claim_boundary": claim_boundary,
    }


def _interval(value) -> tuple[float, float, float]:
    return value.lower_hours, value.central_hours, value.upper_hours


def _refusal_control(ledger) -> dict[str, bool]:
    try:
        spatial_path = ledger.require_spatial_path() == (
            ledger.path_binding.feature_ids
        )
    except ValueError:
        spatial_path = False

    calls = {
        "physics_consistency": (
            ledger.require_physics_consistent_support,
            "geospatial_temporal_physics_consistency_unadmitted",
        ),
        "runtime_transition": (
            ledger.promote_to_runtime_transition,
            "geospatial_temporal_runtime_transition_unadmitted",
        ),
    }
    result = {"spatial_path": spatial_path}
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
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
