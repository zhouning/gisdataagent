#!/usr/bin/env python3
"""Reconcile prospective manifests with sealed outcome-free Manning executions."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.branching_network import (
    BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA,
)
from data_agent.uwm.geospatial_kernel_v2.internal_innovation_instrumentation import (
    EDGE_AXIS_SCHEMA,
    EDGE_FLUX_SCHEMA,
    FEATURE_AXIS_SCHEMA,
    INTERNAL_INNOVATION_TELEMETRY_SCHEMA,
    REACH_STATE_SCHEMA,
    STEP_MASS_LEDGER_SCHEMA,
)

if __package__:
    from scripts.assess_geospatial_kernel_internal_innovation_episode_preflight import (
        PROTOCOL_PATH,
        REPO_ROOT,
        REQUIRED_INPUT_ARTIFACTS,
        SYSTEM_IDS,
        assess_manifest,
        assess_queue,
    )
    from scripts.run_geospatial_kernel_internal_innovation_manning_episode import (
        EXECUTION_SCHEMA,
        PREDICTION_SCHEMA,
    )
else:
    from assess_geospatial_kernel_internal_innovation_episode_preflight import (
        PROTOCOL_PATH,
        REPO_ROOT,
        REQUIRED_INPUT_ARTIFACTS,
        SYSTEM_IDS,
        assess_manifest,
        assess_queue,
    )
    from run_geospatial_kernel_internal_innovation_manning_episode import (
        EXECUTION_SCHEMA,
        PREDICTION_SCHEMA,
    )

SCHEMA = "gwm.geospatial_kernel.internal_innovation_execution_ledger.v1"
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_internal_innovation_execution_ledger.json"
)
EXPECTED_STEP_COUNT = 24
MINIMUM_EPISODES_PER_SYSTEM = 28
MINIMUM_HOURLY_STEPS_PER_SYSTEM = 672

_TELEMETRY_SCHEMAS = {
    "feature_axis_artifact": FEATURE_AXIS_SCHEMA,
    "edge_axis_artifact": EDGE_AXIS_SCHEMA,
    "reach_state_artifact": REACH_STATE_SCHEMA,
    "edge_flux_artifact": EDGE_FLUX_SCHEMA,
    "step_mass_ledger_artifact": STEP_MASS_LEDGER_SCHEMA,
}
_ALIGNMENT_ASSERTIONS = {
    "feature_axis_matches_reach_state": True,
    "edge_axis_matches_edge_flux": True,
    "every_step_has_mass_ledger": True,
    "every_step_mass_ledger_conservative": True,
    "state_transition_continuity_verified": True,
    "causal_availability_recorded": True,
}
_REPORT_FIELDS = {
    "schema",
    "status",
    "episode_id",
    "system_id",
    "forecast_issue_time",
    "support",
    "manifest_artifact",
    "protocol",
    "execution_addendum",
    "input_artifacts",
    "registered_execution",
    "prediction_artifact",
    "internal_innovation_artifacts",
    "invariants",
    "data_isolation",
    "claim_boundary",
}
_FORBIDDEN_OUTCOME_KEYS = {
    "outcome_values",
    "outcome_columns",
    "outcome_manifest",
    "outcome_path",
    "outcome_url",
    "future_target_observations",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        action="append",
        default=[],
        help="One submitted episode manifest; repeat for the complete inventory.",
    )
    parser.add_argument(
        "--execution-report",
        type=Path,
        action="append",
        default=[],
        help="One sealed execution report; repeat for the complete inventory.",
    )
    parser.add_argument("--protocol", type=Path, default=PROTOCOL_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = compile_internal_innovation_execution_ledger(
        tuple(args.manifest),
        execution_report_paths=tuple(args.execution_report),
        protocol_path=args.protocol,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(f"status={report['status']}")
    print(f"diagnostic_fit_ready={report['diagnostic_fit_ready']}")
    return 0 if report["ledger_integrity_passed"] else 1


def compile_internal_innovation_execution_ledger(
    manifest_paths: Sequence[Path],
    *,
    execution_report_paths: Sequence[Path] = (),
    repo_root: Path = REPO_ROOT,
    protocol_path: Path = PROTOCOL_PATH,
) -> dict[str, Any]:
    """Compile one outcome-blind ledger from complete submitted inventories."""

    root = Path(repo_root).resolve()
    protocol = assess_queue((), repo_root=root, protocol_path=protocol_path)["protocol"]
    manifests = [
        _load_manifest_record(path, root=root, protocol_path=protocol_path)
        for path in manifest_paths
    ]
    _reject_duplicate_manifest_identities(manifests)

    executions = [
        _load_execution_report(path, root=root) for path in execution_report_paths
    ]
    _reject_duplicate_execution_identities(executions)
    _reject_reused_output_hashes(executions)
    executions_by_episode = {record["episode_id"]: record for record in executions}
    manifests_by_episode = {
        record["episode_id"]: record
        for record in manifests
        if isinstance(record["episode_id"], str) and record["episode_id"].strip()
    }
    if set(executions_by_episode) - set(manifests_by_episode):
        raise ValueError("internal_innovation_execution_ledger_unbound_execution_report")

    entries = []
    sealed_records = []
    invalid_count = 0
    pending_count = 0
    for manifest_record in manifests:
        execution = executions_by_episode.get(manifest_record["episode_id"])
        if manifest_record["ready"] is not True:
            if execution is not None:
                raise ValueError(
                    "internal_innovation_execution_ledger_execution_for_invalid_manifest"
                )
            status = "invalid"
            invalid_count += 1
        elif execution is None:
            status = "pending_execution"
            pending_count += 1
        else:
            _bind_execution_to_manifest(execution, manifest_record)
            status = "executed_and_sealed"
            sealed_records.append(execution)
        entries.append(_inventory_entry(manifest_record, execution, status=status))
    entries.sort(
        key=lambda value: (
            str(value.get("system_id") or ""),
            str(value.get("forecast_issue_time") or ""),
            str(value.get("episode_id") or ""),
        )
    )

    coverage = _system_coverage(sealed_records)
    gates = {
        "frozen_protocol_identity_verified": protocol.get("identity_matches") is True,
        "submitted_manifest_inventory_nonempty": bool(manifests),
        "no_duplicate_episode_or_system_issue_identity": True,
        "no_reused_prediction_or_telemetry_hash": True,
        "no_invalid_submitted_manifest": invalid_count == 0,
        "every_ready_manifest_executed_and_sealed": bool(manifests)
        and invalid_count == 0
        and pending_count == 0,
        "every_execution_report_bound_to_exact_manifest": len(sealed_records)
        == len(executions),
        "all_output_artifact_identities_recomputed": all(
            record["artifact_validation"]["all_identities_recomputed"] is True
            for record in sealed_records
        ),
        "all_episode_semantics_recomputed": all(
            record["artifact_validation"]["all_semantics_recomputed"] is True
            for record in sealed_records
        ),
        "both_required_systems_have_sealed_episodes": all(
            coverage[system_id]["sealed_episode_count"] > 0 for system_id in SYSTEM_IDS
        ),
        "minimum_28_unique_issue_times_per_system": all(
            coverage[system_id]["unique_issue_time_count"]
            >= MINIMUM_EPISODES_PER_SYSTEM
            for system_id in SYSTEM_IDS
        ),
        "minimum_672_sealed_hourly_steps_per_system": all(
            coverage[system_id]["sealed_hourly_prediction_step_count"]
            >= MINIMUM_HOURLY_STEPS_PER_SYSTEM
            for system_id in SYSTEM_IDS
        ),
        "outcome_values_never_loaded": True,
        "innovation_fit_never_executed": True,
    }
    diagnostic_fit_ready = all(gates.values())
    ledger_integrity_passed = (
        gates["frozen_protocol_identity_verified"]
        and gates["no_duplicate_episode_or_system_issue_identity"]
        and gates["no_reused_prediction_or_telemetry_hash"]
        and gates["no_invalid_submitted_manifest"]
        and gates["every_execution_report_bound_to_exact_manifest"]
        and gates["all_output_artifact_identities_recomputed"]
        and gates["all_episode_semantics_recomputed"]
    )
    if not gates["frozen_protocol_identity_verified"]:
        status = "blocked_protocol_identity_failure"
    elif not manifests:
        status = "awaiting_prospective_episode_manifests"
    elif invalid_count:
        status = "blocked_invalid_prospective_episode_manifest"
    elif pending_count:
        status = "awaiting_outcome_free_episode_execution"
    elif diagnostic_fit_ready:
        status = "diagnostic_fit_ready_outcomes_still_forbidden"
    else:
        status = "accumulating_sealed_cross_system_episodes"
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "protocol": protocol,
        "submitted_manifest_count": len(manifests),
        "submitted_execution_report_count": len(executions),
        "reconciliation": {
            "executed_and_sealed_count": len(sealed_records),
            "pending_execution_count": pending_count,
            "invalid_manifest_count": invalid_count,
            "entries": entries,
        },
        "coverage_by_system": coverage,
        "diagnostic_fit_gates": gates,
        "diagnostic_fit_ready": diagnostic_fit_ready,
        "ledger_integrity_passed": ledger_integrity_passed,
        "data_isolation": {
            "manifest_and_execution_metadata_loaded": True,
            "prediction_and_internal_telemetry_loaded_for_recomputation": bool(
                executions
            ),
            "outcome_argument_accepted": False,
            "outcome_artifacts_opened": False,
            "outcome_values_loaded": False,
            "innovation_fit_executed": False,
            "network_requests_performed": False,
        },
        "claim_boundary": {
            "submitted_inventory_reconciled": True,
            "sealed_outcome_free_episode_coverage_sufficient": diagnostic_fit_ready,
            "outcomes_acquired": False,
            "innovation_fitted": False,
            "candidate_outperformed_raw_physical": False,
            "candidate_promoted": False,
            "runtime_enabled": False,
            "geospatial_kernel_validated": False,
        },
    }


def _load_manifest_record(
    path: Path,
    *,
    root: Path,
    protocol_path: Path,
) -> dict[str, Any]:
    manifest_path = _inside_root(root, path)
    body = manifest_path.read_bytes()
    strict_error = None
    try:
        payload = _strict_json_object(body)
    except ValueError as error:
        payload = {}
        strict_error = str(error)
    assessment = assess_manifest(
        manifest_path,
        repo_root=root,
        protocol_path=protocol_path,
    )
    ready = strict_error is None and assessment.get("episode_execution_ready") is True
    return {
        "path": manifest_path,
        "body": body,
        "artifact": _artifact(manifest_path, body, root=root),
        "payload": payload,
        "assessment": assessment,
        "strict_json_error": strict_error,
        "episode_id": payload.get("episode_id"),
        "system_id": payload.get("system_id"),
        "forecast_issue_time": payload.get("forecast_issue_time"),
        "ready": ready,
    }


def _load_execution_report(path: Path, *, root: Path) -> dict[str, Any]:
    report_path = _inside_root(root, path)
    if report_path.is_symlink():
        raise ValueError("internal_innovation_execution_ledger_symlink_forbidden")
    body = report_path.read_bytes()
    payload = _strict_json_object(body)
    if set(payload) != _REPORT_FIELDS:
        raise ValueError("internal_innovation_execution_ledger_report_fields_invalid")
    if (
        payload.get("schema") != EXECUTION_SCHEMA
        or payload.get("status")
        != "outcome_free_physical_prediction_and_internal_telemetry_sealed"
        or payload.get("system_id") not in SYSTEM_IDS
        or not _nonempty_string(payload.get("episode_id"))
        or _aware_datetime(payload.get("forecast_issue_time")) is None
    ):
        raise ValueError("internal_innovation_execution_ledger_report_identity_invalid")
    _validate_report_claims(payload)
    prediction_descriptor, prediction = _load_bound_artifact(
        root,
        payload.get("prediction_artifact"),
        expected_schema=PREDICTION_SCHEMA,
    )
    internal = payload.get("internal_innovation_artifacts")
    if not isinstance(internal, dict) or set(internal) != {
        *_TELEMETRY_SCHEMAS,
        "alignment_assertions",
        "telemetry_bundle",
    }:
        raise ValueError("internal_innovation_execution_ledger_telemetry_block_invalid")
    telemetry = {
        name: _load_bound_artifact(
            root,
            internal.get(name),
            expected_schema=schema,
        )
        for name, schema in _TELEMETRY_SCHEMAS.items()
    }
    artifacts = {name: value[1] for name, value in telemetry.items()}
    forbidden_locations = _find_forbidden_outcome_content(prediction)
    for name, artifact in artifacts.items():
        forbidden_locations.extend(
            f"$.{name}{location[1:]}"
            for location in _find_forbidden_outcome_content(artifact)
        )
    if forbidden_locations:
        raise ValueError("internal_innovation_execution_ledger_outcome_content_forbidden")
    validation = _validate_episode_artifacts(
        report=payload,
        prediction=prediction,
        telemetry=artifacts,
    )
    return {
        "path": report_path,
        "body": body,
        "artifact": _artifact(report_path, body, root=root),
        "payload": payload,
        "episode_id": payload["episode_id"],
        "system_id": payload["system_id"],
        "forecast_issue_time": payload["forecast_issue_time"],
        "step_count": validation["step_count"],
        "prediction_artifact": prediction_descriptor,
        "telemetry_artifacts": {
            name: descriptor for name, (descriptor, _) in telemetry.items()
        },
        "artifact_validation": validation,
    }


def _validate_report_claims(report: Mapping[str, Any]) -> None:
    execution = report.get("registered_execution")
    invariants = report.get("invariants")
    if (
        execution
        != {
            "operator": "BranchingManningNetworkTransportOperator",
            "operator_schema": BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA,
            "timestep_seconds": 3600.0,
            "integration_substep_seconds": 300.0,
            "network_fingerprint": execution.get("network_fingerprint")
            if isinstance(execution, dict)
            else None,
        }
        or not isinstance(execution, dict)
        or not _valid_sha256(execution.get("network_fingerprint"))
        or invariants
        != {
            "step_count": EXPECTED_STEP_COUNT,
            "actual_conservation_passed": True,
            "state_transition_continuity_verified": True,
            "all_source_steps_admitted": True,
        }
        or report.get("data_isolation")
        != {
            "outcome_argument_accepted": False,
            "outcome_values_loaded": False,
            "outcome_artifacts_opened": False,
            "score_report_loaded": False,
            "candidate_fit_executed": False,
            "network_requests_performed": False,
        }
        or report.get("claim_boundary")
        != {
            "prospective_input_manifest_preflight_passed": True,
            "physical_prediction_sealed": True,
            "internal_telemetry_sealed": True,
            "outcomes_acquired": False,
            "innovation_fitted": False,
            "candidate_promoted": False,
            "runtime_enabled": False,
            "geospatial_kernel_validated": False,
        }
    ):
        raise ValueError("internal_innovation_execution_ledger_report_claim_invalid")


def _validate_episode_artifacts(
    *,
    report: Mapping[str, Any],
    prediction: Mapping[str, Any],
    telemetry: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    episode_id = report["episode_id"]
    system_id = report["system_id"]
    issue_text = report["forecast_issue_time"]
    issue_time = _aware_datetime(issue_text)
    support = report.get("support")
    if issue_time is None or not isinstance(support, dict):
        raise ValueError("internal_innovation_execution_ledger_support_invalid")
    support_start = _aware_datetime(support.get("start_inclusive"))
    support_end = _aware_datetime(support.get("end_exclusive"))
    if (
        support_start is None
        or support_end != support_start + timedelta(hours=EXPECTED_STEP_COUNT)
        or issue_time > support_start
        or support.get("time_step_seconds") != 3600
        or support.get("step_count") != EXPECTED_STEP_COUNT
    ):
        raise ValueError("internal_innovation_execution_ledger_support_invalid")
    execution = report["registered_execution"]
    network_fingerprint = execution["network_fingerprint"]
    shared = (system_id, issue_text, network_fingerprint)
    for artifact in telemetry.values():
        if (
            artifact.get("system_id") != shared[0]
            or artifact.get("forecast_issue_time") != shared[1]
            or artifact.get("network_fingerprint") != shared[2]
            or artifact.get("operator_schema")
            != BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA
            or artifact.get("source_steps_admitted") is not True
            or artifact.get("diagnostic_only") is not False
        ):
            raise ValueError("internal_innovation_execution_ledger_telemetry_identity_invalid")
    if (
        prediction.get("episode_id") != episode_id
        or prediction.get("system_id") != system_id
        or prediction.get("forecast_issue_time") != issue_text
        or prediction.get("operator_schema")
        != BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA
        or prediction.get("support") != support
        or prediction.get("step_count") != EXPECTED_STEP_COUNT
        or prediction.get("claim_boundary")
        != {
            "outcome_values_loaded": False,
            "physical_prediction_only": True,
            "innovation_applied": False,
        }
    ):
        raise ValueError("internal_innovation_execution_ledger_prediction_invalid")

    feature = telemetry["feature_axis_artifact"]
    edge = telemetry["edge_axis_artifact"]
    state = telemetry["reach_state_artifact"]
    flux = telemetry["edge_flux_artifact"]
    mass = telemetry["step_mass_ledger_artifact"]
    feature_rows = _list_of_mappings(feature.get("features"))
    edge_rows = _list_of_mappings(edge.get("edges"))
    feature_ids = [row.get("feature_id") for row in feature_rows]
    if (
        feature.get("feature_count") != len(feature_rows)
        or not feature_rows
        or any(
            row.get("feature_index") != index or not _positive_int(row.get("feature_id"))
            for index, row in enumerate(feature_rows)
        )
        or len(set(feature_ids)) != len(feature_ids)
    ):
        raise ValueError("internal_innovation_execution_ledger_feature_axis_invalid")
    edge_keys = [row.get("edge_key") for row in edge_rows]
    if (
        edge.get("edge_count") != len(edge_rows)
        or not edge_rows
        or any(
            row.get("edge_index") != index
            or not _nonempty_string(row.get("edge_key"))
            or row.get("source_feature_id") not in feature_ids
            or row.get("target_feature_id") not in feature_ids
            or row.get("source_feature_id") == row.get("target_feature_id")
            or row.get("edge_admitted") is not True
            for index, row in enumerate(edge_rows)
        )
        or len(set(edge_keys)) != len(edge_keys)
    ):
        raise ValueError("internal_innovation_execution_ledger_edge_axis_invalid")

    prediction_rows = _list_of_mappings(prediction.get("rows"))
    state_rows = _list_of_mappings(state.get("rows"))
    flux_rows = _list_of_mappings(flux.get("rows"))
    mass_rows = _list_of_mappings(mass.get("rows"))
    if (
        len(prediction_rows) != EXPECTED_STEP_COUNT
        or state.get("step_count") != EXPECTED_STEP_COUNT
        or state.get("row_count") != EXPECTED_STEP_COUNT * len(feature_rows)
        or len(state_rows) != state.get("row_count")
        or flux.get("step_count") != EXPECTED_STEP_COUNT
        or flux.get("row_count") != EXPECTED_STEP_COUNT * len(edge_rows)
        or len(flux_rows) != flux.get("row_count")
        or mass.get("step_count") != EXPECTED_STEP_COUNT
        or mass.get("row_count") != EXPECTED_STEP_COUNT
        or len(mass_rows) != EXPECTED_STEP_COUNT
    ):
        raise ValueError("internal_innovation_execution_ledger_step_coverage_invalid")
    if (
        state.get("feature_axis_sha256")
        != _canonical_sha256(dict(feature))
        or mass.get("feature_axis_sha256")
        != _canonical_sha256(dict(feature))
        or flux.get("edge_axis_sha256") != _canonical_sha256(dict(edge))
    ):
        raise ValueError("internal_innovation_execution_ledger_axis_binding_invalid")

    for index in range(EXPECTED_STEP_COUNT):
        expected_start = support_start + timedelta(hours=index)
        expected_end = expected_start + timedelta(hours=1)
        _validate_prediction_row(prediction_rows[index], index, expected_start, expected_end)
        ledger_row = mass_rows[index]
        _validate_temporal_row(ledger_row, index, expected_start, expected_end, issue_time)
        _validate_mass_row(ledger_row)
        state_step = state_rows[index * len(feature_rows) : (index + 1) * len(feature_rows)]
        flux_step = flux_rows[index * len(edge_rows) : (index + 1) * len(edge_rows)]
        for feature_index, row in enumerate(state_step):
            _validate_temporal_row(row, index, expected_start, expected_end, issue_time)
            if (
                row.get("feature_index") != feature_index
                or row.get("feature_id") != feature_ids[feature_index]
                or row.get("state_role") != "modeled_physical_internal_state"
                or row.get("ground_truth") is not False
                or not all(
                    _finite_nonnegative(row.get(name))
                    for name in ("initial_stock_m3", "final_stock_m3", "final_depth_m")
                )
            ):
                raise ValueError("internal_innovation_execution_ledger_reach_state_invalid")
        for edge_index, row in enumerate(flux_step):
            _validate_temporal_row(row, index, expected_start, expected_end, issue_time)
            if (
                row.get("edge_index") != edge_index
                or row.get("edge_key") != edge_keys[edge_index]
                or row.get("flux_role")
                != "modeled_physical_base_internal_transfer"
                or row.get("ground_truth") is not False
                or not _finite_nonnegative(row.get("base_mean_flux_m3s"))
            ):
                raise ValueError("internal_innovation_execution_ledger_edge_flux_invalid")
        if index:
            previous = state_rows[
                (index - 1) * len(feature_rows) : index * len(feature_rows)
            ]
            if any(
                current.get("initial_stock_m3") != prior.get("final_stock_m3")
                for prior, current in zip(previous, state_step, strict=True)
            ):
                raise ValueError(
                    "internal_innovation_execution_ledger_state_transition_discontinuity"
                )

    internal = report["internal_innovation_artifacts"]
    bundle = internal.get("telemetry_bundle")
    if (
        internal.get("alignment_assertions") != _ALIGNMENT_ASSERTIONS
        or not isinstance(bundle, dict)
        or bundle
        != {
            "schema": INTERNAL_INNOVATION_TELEMETRY_SCHEMA,
            "system_id": system_id,
            "operator_schema": BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA,
            "network_fingerprint": network_fingerprint,
            "step_count": EXPECTED_STEP_COUNT,
            "alignment_assertions": _ALIGNMENT_ASSERTIONS,
            "source_steps_admitted": True,
            "diagnostic_only": False,
            "claim_boundary": {
                "reach_states_are_modeled_not_observed": True,
                "edge_fluxes_are_physical_base_flux_not_observed_truth": True,
                "outcome_values_loaded": False,
                "innovation_fitted": False,
            },
        }
    ):
        raise ValueError("internal_innovation_execution_ledger_bundle_invalid")
    return {
        "step_count": EXPECTED_STEP_COUNT,
        "all_identities_recomputed": True,
        "all_semantics_recomputed": True,
        "mass_conservation_recomputed": True,
        "state_transition_continuity_recomputed": True,
        "causal_availability_recomputed": True,
    }


def _validate_prediction_row(
    row: Mapping[str, Any],
    index: int,
    expected_start: datetime,
    expected_end: datetime,
) -> None:
    if (
        row.get("step_index") != index
        or _aware_datetime(row.get("support_start_utc")) != expected_start
        or _aware_datetime(row.get("support_end_utc")) != expected_end
        or not _finite_nonnegative(row.get("physical_outlet_mean_flow_m3s"))
        or not _finite_number(row.get("global_mass_balance_residual_m3"))
        or not _finite_positive(row.get("numeric_mass_tolerance_m3"))
        or abs(float(row["global_mass_balance_residual_m3"]))
        > float(row["numeric_mass_tolerance_m3"])
        or row.get("diagnostic_only") is not False
    ):
        raise ValueError("internal_innovation_execution_ledger_prediction_row_invalid")


def _validate_temporal_row(
    row: Mapping[str, Any],
    index: int,
    expected_start: datetime,
    expected_end: datetime,
    issue_time: datetime,
) -> None:
    available = _aware_datetime(row.get("inputs_available_at"))
    if (
        row.get("step_index") != index
        or _aware_datetime(row.get("forecast_issue_time")) != issue_time
        or _aware_datetime(row.get("support_start_utc")) != expected_start
        or _aware_datetime(row.get("support_end_utc")) != expected_end
        or available is None
        or available > issue_time
    ):
        raise ValueError("internal_innovation_execution_ledger_temporal_row_invalid")


def _validate_mass_row(row: Mapping[str, Any]) -> None:
    names = (
        "initial_network_storage_m3",
        "final_network_storage_m3",
        "total_input_volume_m3",
        "outlet_volume_m3",
        "displaced_upstream_outflow_volume_m3",
        "residual_m3",
        "numeric_tolerance_m3",
    )
    if not all(_finite_number(row.get(name)) for name in names):
        raise ValueError("internal_innovation_execution_ledger_mass_row_invalid")
    calculated = (
        float(row["final_network_storage_m3"])
        + float(row["outlet_volume_m3"])
        + float(row["displaced_upstream_outflow_volume_m3"])
        - float(row["initial_network_storage_m3"])
        - float(row["total_input_volume_m3"])
    )
    residual = float(row["residual_m3"])
    tolerance = float(row["numeric_tolerance_m3"])
    scale = max(
        1.0,
        *(abs(float(row[name])) for name in names if name != "numeric_tolerance_m3"),
    )
    numeric_slack = math.ulp(scale) * 32.0
    if (
        tolerance <= 0.0
        or abs(calculated - residual) > numeric_slack
        or abs(calculated) > tolerance + numeric_slack
        or row.get("mass_balance_passed") is not True
        or row.get("source_step_admitted") is not True
        or row.get("diagnostic_only") is not False
    ):
        raise ValueError("internal_innovation_execution_ledger_mass_conservation_invalid")


def _bind_execution_to_manifest(
    execution: Mapping[str, Any], manifest: Mapping[str, Any]
) -> None:
    report = execution["payload"]
    payload = manifest["payload"]
    expected_inputs = {
        name: {
            **dict(payload["artifacts"][name]),
            "identity_recomputed_before_execution": True,
        }
        for name in REQUIRED_INPUT_ARTIFACTS
    }
    if (
        execution["episode_id"] != manifest["episode_id"]
        or execution["system_id"] != manifest["system_id"]
        or execution["forecast_issue_time"] != manifest["forecast_issue_time"]
        or report.get("support") != payload.get("support")
        or report.get("manifest_artifact") != manifest["artifact"]
        or report.get("protocol") != manifest["assessment"].get("protocol")
        or report.get("execution_addendum")
        != manifest["assessment"].get("execution_addendum")
        or report.get("input_artifacts") != expected_inputs
    ):
        raise ValueError("internal_innovation_execution_ledger_manifest_binding_invalid")


def _inventory_entry(
    manifest: Mapping[str, Any],
    execution: Mapping[str, Any] | None,
    *,
    status: str,
) -> dict[str, Any]:
    assessment = manifest["assessment"]
    failed_gates = [
        name for name, passed in assessment.get("gates", {}).items() if passed is not True
    ]
    if manifest["strict_json_error"] is not None:
        failed_gates.append("strict_json_without_duplicate_or_nonfinite_values")
    return {
        "episode_id": manifest["episode_id"],
        "system_id": manifest["system_id"],
        "forecast_issue_time": manifest["forecast_issue_time"],
        "reconciliation_status": status,
        "manifest_artifact": manifest["artifact"],
        "manifest_preflight_ready": manifest["ready"],
        "failed_manifest_gates": sorted(set(failed_gates)),
        "execution_report_artifact": execution["artifact"] if execution else None,
        "prediction_artifact": execution["prediction_artifact"] if execution else None,
        "telemetry_artifacts": execution["telemetry_artifacts"] if execution else None,
        "sealed_hourly_prediction_step_count": execution["step_count"] if execution else 0,
    }


def _system_coverage(executions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result = {}
    for system_id in SYSTEM_IDS:
        records = [value for value in executions if value["system_id"] == system_id]
        issue_times = sorted({str(value["forecast_issue_time"]) for value in records})
        episode_count = len(records)
        step_count = sum(int(value["step_count"]) for value in records)
        result[system_id] = {
            "sealed_episode_count": episode_count,
            "unique_issue_time_count": len(issue_times),
            "sealed_hourly_prediction_step_count": step_count,
            "minimum_episode_count_required": MINIMUM_EPISODES_PER_SYSTEM,
            "minimum_hourly_prediction_step_count_required": (
                MINIMUM_HOURLY_STEPS_PER_SYSTEM
            ),
            "episode_minimum_met": episode_count >= MINIMUM_EPISODES_PER_SYSTEM,
            "unique_issue_time_minimum_met": (
                len(issue_times) >= MINIMUM_EPISODES_PER_SYSTEM
            ),
            "hourly_prediction_step_minimum_met": (
                step_count >= MINIMUM_HOURLY_STEPS_PER_SYSTEM
            ),
            "first_issue_time": issue_times[0] if issue_times else None,
            "last_issue_time": issue_times[-1] if issue_times else None,
        }
    return result


def _reject_duplicate_manifest_identities(records: Sequence[Mapping[str, Any]]) -> None:
    episode_ids = [value["episode_id"] for value in records if value["episode_id"] is not None]
    issue_keys = [
        (value["system_id"], value["forecast_issue_time"])
        for value in records
        if value["system_id"] is not None and value["forecast_issue_time"] is not None
    ]
    if len(episode_ids) != len(set(episode_ids)):
        raise ValueError("internal_innovation_execution_ledger_duplicate_episode_id")
    if len(issue_keys) != len(set(issue_keys)):
        raise ValueError("internal_innovation_execution_ledger_duplicate_system_issue")


def _reject_duplicate_execution_identities(records: Sequence[Mapping[str, Any]]) -> None:
    episode_ids = [value["episode_id"] for value in records]
    issue_keys = [(value["system_id"], value["forecast_issue_time"]) for value in records]
    if len(episode_ids) != len(set(episode_ids)):
        raise ValueError("internal_innovation_execution_ledger_duplicate_execution_episode")
    if len(issue_keys) != len(set(issue_keys)):
        raise ValueError("internal_innovation_execution_ledger_duplicate_execution_issue")


def _reject_reused_output_hashes(records: Sequence[Mapping[str, Any]]) -> None:
    hashes = []
    for record in records:
        hashes.append(record["prediction_artifact"]["sha256"])
        hashes.extend(
            descriptor["sha256"] for descriptor in record["telemetry_artifacts"].values()
        )
    if len(hashes) != len(set(hashes)):
        raise ValueError("internal_innovation_execution_ledger_reused_output_hash")


def _load_bound_artifact(
    root: Path,
    descriptor_value: object,
    *,
    expected_schema: str,
) -> tuple[dict[str, object], dict[str, Any]]:
    if not isinstance(descriptor_value, dict) or set(descriptor_value) != {
        "path",
        "sha256",
        "size_bytes",
        "schema",
    }:
        raise ValueError("internal_innovation_execution_ledger_artifact_descriptor_invalid")
    descriptor = dict(descriptor_value)
    if (
        not _nonempty_string(descriptor.get("path"))
        or not _valid_sha256(descriptor.get("sha256"))
        or not _nonnegative_int(descriptor.get("size_bytes"))
        or descriptor.get("schema") != expected_schema
    ):
        raise ValueError("internal_innovation_execution_ledger_artifact_descriptor_invalid")
    path = _inside_root(root, Path(str(descriptor["path"])))
    if path.is_symlink():
        raise ValueError("internal_innovation_execution_ledger_symlink_forbidden")
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor["sha256"]
        or len(body) != descriptor["size_bytes"]
    ):
        raise ValueError("internal_innovation_execution_ledger_artifact_identity_mismatch")
    payload = _strict_json_object(body)
    if payload.get("schema") != expected_schema:
        raise ValueError("internal_innovation_execution_ledger_artifact_schema_mismatch")
    return descriptor, payload


def _artifact(path: Path, body: bytes, *, root: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _inside_root(root: Path, path: Path) -> Path:
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError("internal_innovation_execution_ledger_path_outside_repository") from error
    if not resolved.is_file():
        raise ValueError("internal_innovation_execution_ledger_artifact_missing")
    return resolved


def _strict_json_object(body: bytes) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("internal_innovation_execution_ledger_json_duplicate_key")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> None:
        raise ValueError(f"internal_innovation_execution_ledger_json_nonfinite:{value}")

    try:
        payload = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite,
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("internal_innovation_execution_ledger_json_invalid") from error
    if not isinstance(payload, dict):
        raise ValueError("internal_innovation_execution_ledger_json_root_not_object")
    return payload


def _canonical_sha256(value: object) -> str:
    body = (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _find_forbidden_outcome_content(value: object, location: str = "$") -> list[str]:
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_location = f"{location}.{key}"
            if key in _FORBIDDEN_OUTCOME_KEYS:
                found.append(child_location)
            found.extend(_find_forbidden_outcome_content(child, child_location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_find_forbidden_outcome_content(child, f"{location}[{index}]"))
    return found


def _list_of_mappings(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("internal_innovation_execution_ledger_rows_invalid")
    return value


def _aware_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _finite_nonnegative(value: object) -> bool:
    return _finite_number(value) and float(value) >= 0.0


def _finite_positive(value: object) -> bool:
    return _finite_number(value) and float(value) > 0.0


if __name__ == "__main__":
    raise SystemExit(main())
