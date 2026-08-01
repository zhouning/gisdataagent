#!/usr/bin/env python3
"""Compile Stage 34 temporal observation and process-semantics gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import (
    public_temporal_response_semantics as evidence,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/stage34_center_hill_temporal_semantics"
)
DEFAULT_LEDGER_OUTPUT = DEFAULT_DATA_ROOT / (
    "temporal_response_semantics_ledger.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/stage34_temporal_semantics_gates.json"
)
SCHEMA = "gwm.geotransport.stage34_temporal_semantics_gates.v1"

FROZEN_STAGE33_HASHES = {
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "geospatial_temporal_support.py"
    ): "62bda56dedfb65995556aa4964ea220c4ea8a9976738694f2e784cd664b360d1",
    (
        "data_agent/test_geospatial_kernel_geospatial_temporal_support.py"
    ): "cc322ac4e58b2e2a6b946ac6e1522be0aa39eaef3ab12592c1f66ddb96518d73",
    (
        "scripts/acquire_geotransport_stage33_temporal_support_path.py"
    ): "f868905ac4610f0b84b69ae13e40f1473588e58b7086c55b1ec94e421686a504",
    (
        "data_agent/test_acquire_geotransport_stage33_temporal_support_path.py"
    ): "7e4b77aac2632a6e96cad0181ac4feac28ce5e56665408992b75fc9e68cf1fd0",
    (
        "data/geotransport_v0_1/stage33_center_hill_temporal_support_path/"
        "acquisition_plan.json"
    ): "55f2618d7d6508a0b6e0ef4556d934514f8f42ea20a208e4272d53e27d0f76b8",
    (
        "data/geotransport_v0_1/stage33_center_hill_temporal_support_path/"
        "acquisition_manifest.json"
    ): "79895bfd9f499b8a383d29b4deb06b0326bc9a6cb62e09e10c390371657921f3",
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "public_temporal_support_reconciliation.py"
    ): "63537c92af92af3fcc35003fc3575ceadff6ddccc79e02c82bd791a7da02cdc6",
    (
        "data_agent/"
        "test_geospatial_kernel_public_temporal_support_reconciliation.py"
    ): "47aa14e044802477f120a9543c9083301ca21c97d48e45b92d9aef2cdc468eca",
    (
        "scripts/compile_geotransport_stage33_temporal_support_gates.py"
    ): "3ef5089ad1cabf843f8f5e5efd157f621fad3bf86326c80032b9d4d7fe1fb09e",
    (
        "data/geotransport_v0_1/stage33_center_hill_temporal_support_path/"
        "temporal_support_reconciliation_ledger.json"
    ): "7e69e9dc4eaa027ae23503cf6fb121035030f953260a989df29c9515fcf9b7df",
    (
        "benchmarks/geotransport_v0_1/"
        "stage33_temporal_support_gates.json"
    ): "a4ec722e078fc67a3940d8cb06621b1ebe9ac5eb99f1c03bf6738c6f6a4d3fab",
    (
        "docs/architecture-decisions/"
        "adr-074-admit-spatial-path-reject-temporal-reconciliation.md"
    ): "a5155f9e4c16737d2199b42094555aab7926106188c29c5caa0aa1eb9308a1f7",
    (
        "data/geotransport_v0_1/stage33_center_hill_temporal_support_path/"
        "README.md"
    ): "dd8ab5ea307c78a3450e88edccdcc959843cf745bfc7077b96d802b6ef68ca78",
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
    ledger = evidence.compile_public_temporal_response_semantics()
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
        ledger = evidence.compile_public_temporal_response_semantics()
    report = ledger.as_dict()
    if ledger_artifact is None:
        ledger_artifact = _memory_artifact(DEFAULT_LEDGER_OUTPUT, report)
    plan = json.loads(
        (
            REPO_ROOT / str(ledger.acquisition_plan_artifact["path"])
        ).read_bytes()
    )
    frozen_stage33 = _frozen_hash_report(FROZEN_STAGE33_HASHES)
    source = ledger.source_field
    target = ledger.target_field
    values = ledger.reconciliation.compatibilities
    refusals = _refusal_control(ledger)
    decision = report["decision"]
    observation = report["stage32_observation_support"]
    expected_reasons = (
        "transport_carrier_mismatch",
        "source_event_marker_mismatch",
        "target_response_functional_mismatch",
        "candidate_physical_response_time_unadmitted",
        "numerical_support_disjoint",
    )
    gates = {
        "all_thirteen_stage33_artifacts_remain_hash_frozen": all(
            value["matches"] for value in frozen_stage33.values()
        ),
        "temporal_response_semantics_operator_is_hash_frozen": (
            ledger.operator_artifact["sha256"]
            == "8632158a2ecfe194f6419fc6ceab5f7eca7ef958cc694a8719742b97ffd90bdd"
        ),
        "acquisition_plan_was_hash_frozen_before_document_values": (
            ledger.acquisition_plan_artifact["sha256"]
            == "86b646f133e705a226afbc079bd1d4d02f814fc0f6b7f05be589c77413f8c043"
        ),
        "acquisition_manifest_is_hash_bound": (
            ledger.acquisition_manifest_artifact["sha256"]
            == "82fbf0460344331f25f567b19665ce3883699f8283ed856820fb0fa49901749d"
        ),
        "one_public_document_is_hash_and_tls_verified": (
            ledger.source_artifacts[2]["sha256"]
            == "997fd03b31e798d1f434c7e9d5b56a4a2c9c8d578c2432c3c8ed07019f778f70"
            and ledger.source_artifacts[2]["size_bytes"] == 11_453
            and ledger.source_artifacts[2]["hash_verified"] is True
            and ledger.source_artifacts[2][
                "tls_hostname_verification_retained"
            ]
            is True
        ),
        "document_request_is_outcome_free_and_private_data_free": (
            plan["request_boundary"]["maximum_request_count"] == 1
            and plan["request_boundary"][
                "release_or_downstream_outcome_values_requested"
            ]
            is False
            and plan["request_boundary"]["workspace_or_private_data_sent"]
            is False
        ),
        "document_is_bound_to_fixed_upstream_commit": (
            ledger.document_findings["source_commit"]
            == "beb8d507c9da8ec074d444117bda7d7daf69e5ee"
        ),
        "authoritative_document_defines_composite_eop_and_utc_semantics": (
            ledger.document_findings["instantaneous_is_not_composite"]
            is True
            and ledger.document_findings[
                "composite_default_timestamp_position"
            ]
            == "end"
            and ledger.document_findings[
                "one_hour_duration_is_composite_window_seconds"
            ]
            == 3600
            and ledger.document_findings["cwms_storage_time_basis"] == "UTC"
        ),
        "source_is_center_hill_operational_discharge": (
            source.field_id == "cwms-center-hill-release"
            and source.spatial_role == "operational_tailwater_zone"
            and source.variable == "discharge"
            and source.unit == "m3/s"
        ),
        "source_is_authoritative_hourly_eop_interval_average": (
            source.statistic == "interval_average"
            and source.temporal_support.kind == "interval_mean"
            and source.temporal_support.duration_seconds == 3600.0
            and source.temporal_support.timestamp_position == "end"
            and source.temporal_support.evidence_level == "authoritative"
        ),
        "source_actuation_instant_access_fails_closed": refusals[
            "release_actuation_instant"
        ],
        "target_is_primary_usgs_instantaneous_discharge_series": (
            target.field_id == "usgs-stonewall-hourly-sample-mean"
            and "1eed13fd6d90461fa6a04892af197e6d"
            in target.provenance_id
        ),
        "target_is_derived_interval_sample_mean": (
            target.statistic == "instantaneous_sample_mean"
            and target.temporal_support.kind == "interval_sample_mean"
            and target.temporal_support.timestamp_position == "end"
            and target.temporal_support.evidence_level == "derived"
        ),
        "target_native_sampling_is_two_half_hour_points": (
            target.native_sampling_interval_seconds == 1800.0
            and target.native_samples_per_compiled_support == 2
        ),
        "target_continuous_hour_mean_access_fails_closed": refusals[
            "target_continuous_interval_average"
        ],
        "source_and_target_admit_interval_end_label_shift": (
            ledger.reconciliation.label_shift_diagnostic_admitted is True
        ),
        "admitted_label_shift_grid_is_exactly_one_hour": (
            ledger.require_label_shift_grid_seconds() == 3600.0
        ),
        "physical_observation_equivalence_access_fails_closed": refusals[
            "physical_observation_equivalence"
        ],
        "stage32_complete_observation_hours_are_preserved": (
            ledger.stage32_downstream_complete_hours == (84, 84, 77, 84)
        ),
        "stage32_real_missing_hours_are_preserved": (
            ledger.stage32_downstream_missing_hours == (0, 0, 7, 0)
        ),
        "compiled_observations_are_approved_and_unfilled": (
            observation["all_compiled_samples_approved"] is True
            and observation["missing_values_filled"] is False
        ),
        "empirical_quantity_is_windowed_label_association_peak": (
            ledger.reconciliation.empirical.carrier == "discharge_series"
            and ledger.reconciliation.empirical.source_event_marker
            == "interval_end_label_step"
            and ledger.reconciliation.empirical.target_response_functional
            == "windowed_linear_association_peak"
        ),
        "physics_transport_carriers_remain_distinct": (
            [value.candidate.carrier for value in values]
            == ["hydraulic_disturbance", "discharge_perturbation", "water_mass"]
        ),
        "physics_source_event_markers_remain_distinct": (
            [value.candidate.source_event_marker for value in values]
            == [
                "physical_boundary_perturbation",
                "physical_boundary_perturbation",
                "material_injection",
            ]
        ),
        "physics_target_response_functionals_remain_distinct": (
            [value.candidate.target_response_functional for value in values]
            == ["first_signal_arrival", "response_centroid", "material_exit_centroid"]
        ),
        "all_process_candidates_share_admitted_spatial_path": all(
            value.same_spatial_path for value in values
        ),
        "all_process_candidates_remain_numerically_disjoint": all(
            value.numerical_overlap is False for value in values
        ),
        "every_process_substitution_has_five_typed_rejection_reasons": all(
            value.rejection_reasons == expected_reasons for value in values
        ),
        "semantic_equivalence_remains_unadmitted": all(
            value.semantic_equivalence_admitted is False for value in values
        ),
        "physical_response_comparison_remains_unadmitted": all(
            value.physical_response_comparison_admitted is False
            for value in values
        ),
        "all_event_common_empirical_support_remains_false": (
            ledger.reconciliation.all_event_common_empirical_support is False
        ),
        "physical_response_time_access_fails_closed": refusals[
            "physical_response_time"
        ],
        "runtime_transition_access_fails_closed": refusals[
            "runtime_transition"
        ],
        "decision_admits_semantics_only_not_physical_transition": (
            decision["public_temporal_semantics_evidence_admitted"] is True
            and decision["interval_end_label_shift_diagnostic_admitted"]
            is True
            and decision["release_actuation_instant_admitted"] is False
            and decision["target_continuous_interval_average_admitted"]
            is False
            and decision["physical_observation_equivalence_admitted"]
            is False
            and decision["physical_response_time_admitted"] is False
            and decision["runtime_transition_admitted"] is False
        ),
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "interval_label_shift_admitted_"
            "physical_response_semantics_rejected"
        ),
        "ledger_artifact": ledger_artifact,
        "frozen_stage33_hashes": frozen_stage33,
        "field_summary": {
            "source": source.as_dict(),
            "target": target.as_dict(),
            "label_shift_grid_seconds": (
                ledger.require_label_shift_grid_seconds()
            ),
        },
        "process_summary": [value.as_dict() for value in values],
        "typed_controls": refusals,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "decision": decision,
        "claim_boundary": report["claim_boundary"],
    }


def _refusal_control(ledger) -> dict[str, bool]:
    calls = {
        "release_actuation_instant": (
            ledger.require_release_actuation_instant,
            "temporal_field_actuation_instant_unadmitted",
        ),
        "target_continuous_interval_average": (
            ledger.require_target_continuous_interval_average,
            "temporal_field_continuous_interval_average_unadmitted",
        ),
        "physical_observation_equivalence": (
            ledger.require_physical_observation_equivalence,
            "temporal_field_physical_observation_equivalence_unadmitted",
        ),
        "physical_response_time": (
            ledger.require_physical_response_time,
            "geospatial_response_physical_time_unadmitted",
        ),
        "runtime_transition": (
            ledger.promote_to_runtime_transition,
            "geospatial_response_runtime_transition_unadmitted",
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
