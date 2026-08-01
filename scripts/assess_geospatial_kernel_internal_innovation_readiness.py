#!/usr/bin/env python3
"""Fail closed on fitting internal innovation without observable graph states."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_internal_innovation_readiness_report.json"
)
SCHEMA = "gwm.geospatial_kernel.internal_innovation_readiness.v1"

SYSTEM_IDS = ("center_hill", "j_percy_priest")
ROLLOUT_SPECS: dict[str, dict[str, object]] = {
    "primary": {
        "path": (
            "benchmarks/geotransport_v0_1/geotransport_v2_blind_validation_rollout_report.json"
        ),
        "sha256": ("b7430983224d4c3facfede6df87484f0a37414da6fd0f6e7bd96052c527114db"),
        "schema": "gwm.geotransport.v2_blind_validation_rollout.v1",
        "system_ids": SYSTEM_IDS,
    },
    "replication": {
        "path": ("benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_rollout_report.json"),
        "sha256": ("82be075838f1579bcd24af3bfb3b1f20dc02f047da30c7d6e0e22ae1359b66e3"),
        "schema": "gwm.geotransport.kinematic_wave_holdout_rollout.v2",
        "system_ids": SYSTEM_IDS,
    },
}

REQUIRED_INTERNAL_ARTIFACTS = {
    "feature_axis_artifact": "gwm.geospatial_kernel.feature_axis.v1",
    "edge_axis_artifact": "gwm.geospatial_kernel.edge_axis.v1",
    "reach_state_artifact": "gwm.geospatial_kernel.reach_state_timeseries.v1",
    "edge_flux_artifact": "gwm.geospatial_kernel.edge_flux_timeseries.v1",
    "step_mass_ledger_artifact": "gwm.geospatial_kernel.step_mass_ledger.v1",
}
REQUIRED_ALIGNMENT_ASSERTIONS = (
    "feature_axis_matches_reach_state",
    "edge_axis_matches_edge_flux",
    "every_step_has_mass_ledger",
    "every_step_mass_ledger_conservative",
    "causal_availability_recorded",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = assess()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(f"status={report['status']}")
    print(f"internal_innovation_fit_ready={report['decision']['internal_innovation_fit_ready']}")
    return 0 if report["assessment_integrity_passed"] else 1


def assess(
    repo_root: Path = REPO_ROOT,
    rollout_specs: Mapping[str, Mapping[str, object]] = ROLLOUT_SPECS,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    source_rollouts: dict[str, dict[str, object]] = {}
    combinations: dict[str, dict[str, object]] = {}

    for rollout_id, spec in rollout_specs.items():
        source_path = _resolve_repo_path(root, spec.get("path"))
        source = _expected_artifact_identity(
            root=root,
            path=source_path,
            expected_path=spec.get("path"),
            expected_sha256=spec.get("sha256"),
        )
        payload, json_error = _read_json_object(source_path)
        expected_schema = spec.get("schema")
        expected_system_ids = tuple(spec.get("system_ids", ()))
        report_contract_matches = (
            payload.get("schema") == expected_schema
            and payload.get("status") == "joint_outcome_free_predictions_sealed"
            and isinstance(payload.get("systems"), dict)
            and all(
                payload.get("data_isolation", {}).get(field) is False
                for field in (
                    "outcome_columns_accepted_by_executor",
                    "outcome_manifest_accepted_by_executor",
                    "outcome_path_accepted_by_executor",
                    "outcome_urls_requested",
                    "outcome_values_loaded",
                    "usgs_observations_loaded",
                )
            )
        )
        source.update(
            {
                "json_object_loaded": json_error is None,
                "json_error": json_error,
                "expected_schema": expected_schema,
                "actual_schema": payload.get("schema"),
                "outcome_free_rollout_contract_matches": report_contract_matches,
            }
        )
        source_rollouts[rollout_id] = source

        systems = payload.get("systems")
        if not isinstance(systems, dict):
            systems = {}
        for system_id in expected_system_ids:
            combination_id = f"{rollout_id}:{system_id}"
            system = systems.get(system_id)
            if not isinstance(system, dict):
                system = {}
            combinations[combination_id] = _assess_combination(
                root=root,
                rollout_id=rollout_id,
                system_id=system_id,
                system=system,
                source_identity_matches=bool(source["identity_matches"]),
                report_contract_matches=report_contract_matches,
            )

    expected_combination_count = sum(
        len(tuple(spec.get("system_ids", ()))) for spec in rollout_specs.values()
    )
    gates = {
        "source_rollout_identities_match": all(
            value["identity_matches"] is True for value in source_rollouts.values()
        ),
        "outcome_free_rollout_contracts_match": all(
            value["outcome_free_rollout_contract_matches"] is True
            for value in source_rollouts.values()
        ),
        "expected_system_window_combinations_present": (
            len(combinations) == expected_combination_count
            and all(value["system_record_present"] is True for value in combinations.values())
        ),
        "sealed_prediction_identities_match": all(
            value["sealed_outlet_prediction"]["identity_matches"] is True
            for value in combinations.values()
        ),
        "aggregate_conservation_available_and_passed": all(
            value["aggregate_conservation"]["available"] is True
            and value["aggregate_conservation"]["passed"] is True
            for value in combinations.values()
        ),
        "required_internal_artifacts_hash_bound": all(
            not value["missing_or_invalid_internal_artifacts"] for value in combinations.values()
        ),
        "internal_artifact_alignment_assertions_passed": all(
            value["all_alignment_assertions_passed"] is True for value in combinations.values()
        ),
        "internal_artifact_semantics_validated": all(
            value["semantic_validation"]["all_checks_passed"] is True
            for value in combinations.values()
        ),
    }
    assessment_integrity_passed = all(
        gates[name]
        for name in (
            "source_rollout_identities_match",
            "outcome_free_rollout_contracts_match",
            "expected_system_window_combinations_present",
            "sealed_prediction_identities_match",
            "aggregate_conservation_available_and_passed",
        )
    )
    fit_ready = bool(combinations) and all(
        value["internal_innovation_fit_ready"] is True for value in combinations.values()
    )
    if not assessment_integrity_passed:
        status = "blocked_source_or_sealed_prediction_integrity_failure"
    elif not fit_ready:
        status = "blocked_missing_or_invalid_internal_state_and_flux_artifacts"
    else:
        status = "internal_innovation_instrumentation_ready"

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "instrumentation_contract": {
            "artifact_container": ("systems.<system_id>.internal_innovation_artifacts"),
            "required_artifacts": REQUIRED_INTERNAL_ARTIFACTS,
            "required_descriptor_fields": [
                "path",
                "sha256",
                "size_bytes",
                "schema",
            ],
            "required_alignment_assertions": list(REQUIRED_ALIGNMENT_ASSERTIONS),
            "semantic_validation_required": True,
            "artifact_identity_algorithm": "sha256_streaming_bytes",
            "prediction_values_are_not_parsed": True,
            "outcome_artifacts_are_not_opened": True,
        },
        "source_rollouts": source_rollouts,
        "combinations": combinations,
        "gates": gates,
        "assessment_integrity_passed": assessment_integrity_passed,
        "decision": {
            "aggregate_conservation_evidence_available": gates[
                "aggregate_conservation_available_and_passed"
            ],
            "internal_innovation_fit_ready": fit_ready,
            "fit_executed": False,
            "prediction_reexecution_performed": False,
            "prediction_values_parsed": False,
            "outcome_values_loaded": False,
            "candidate_promoted": False,
            "runtime_enabled": False,
        },
        "claim_boundary": {
            "current_rollouts_support_aggregate_conservation": (assessment_integrity_passed),
            "current_rollouts_expose_internal_training_state": fit_ready,
            "missing_internal_quantities_inferred_or_fabricated": False,
            "posthoc_comparison_reclassified_as_prospective_validation": False,
            "geospatial_kernel_validated_by_this_assessment": False,
        },
    }


def _assess_combination(
    *,
    root: Path,
    rollout_id: str,
    system_id: str,
    system: Mapping[str, object],
    source_identity_matches: bool,
    report_contract_matches: bool,
) -> dict[str, object]:
    system_record_present = system.get("system_id") == system_id
    prediction = _descriptor_identity(root, system.get("prediction_artifact"))
    invariants = system.get("invariants")
    if not isinstance(invariants, dict):
        invariants = {}
    conservation_value = invariants.get("actual_conservation_passed")

    artifact_container = system.get("internal_innovation_artifacts")
    if not isinstance(artifact_container, dict):
        artifact_container = {}
    artifacts: dict[str, dict[str, object]] = {}
    missing_or_invalid = []
    for artifact_name, expected_schema in REQUIRED_INTERNAL_ARTIFACTS.items():
        descriptor = artifact_container.get(artifact_name)
        artifact = _descriptor_identity(root, descriptor)
        artifact["expected_schema"] = expected_schema
        artifact["schema_matches"] = (
            isinstance(descriptor, dict) and descriptor.get("schema") == expected_schema
        )
        artifact["contract_and_identity_match"] = (
            artifact["identity_matches"] is True and artifact["schema_matches"] is True
        )
        artifacts[artifact_name] = artifact
        if artifact["contract_and_identity_match"] is not True:
            missing_or_invalid.append(artifact_name)

    assertions = artifact_container.get("alignment_assertions")
    if not isinstance(assertions, dict):
        assertions = {}
    alignment = {name: assertions.get(name) is True for name in REQUIRED_ALIGNMENT_ASSERTIONS}
    all_alignment_passed = all(alignment.values())
    semantic_validation = _validate_internal_artifact_semantics(
        root=root,
        system_id=system_id,
        artifact_container=artifact_container,
        artifacts=artifacts,
    )
    ready = (
        source_identity_matches
        and report_contract_matches
        and system_record_present
        and prediction["identity_matches"] is True
        and conservation_value is True
        and not missing_or_invalid
        and all_alignment_passed
        and semantic_validation["all_checks_passed"] is True
    )
    registered_execution = system.get("registered_execution")
    if not isinstance(registered_execution, dict):
        registered_execution = {}
    return {
        "rollout_id": rollout_id,
        "system_id": system_id,
        "system_record_present": system_record_present,
        "operator": registered_execution.get("operator"),
        "sealed_outlet_prediction": prediction,
        "aggregate_conservation": {
            "available": isinstance(conservation_value, bool),
            "passed": conservation_value is True,
        },
        "internal_artifacts": artifacts,
        "missing_or_invalid_internal_artifacts": missing_or_invalid,
        "alignment_assertions": alignment,
        "all_alignment_assertions_passed": all_alignment_passed,
        "semantic_validation": semantic_validation,
        "internal_innovation_fit_ready": ready,
        "decision": (
            "ready_for_outcome_blind_internal_innovation_fit"
            if ready
            else "blocked_missing_or_invalid_internal_instrumentation"
        ),
        "execution_boundary": {
            "fit_executed": False,
            "prediction_reexecuted": False,
            "prediction_values_parsed": False,
            "outcome_values_loaded": False,
        },
    }


def _validate_internal_artifact_semantics(
    *,
    root: Path,
    system_id: str,
    artifact_container: Mapping[str, object],
    artifacts: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    payloads: dict[str, dict[str, Any]] = {}
    json_payloads_valid = True
    for artifact_name, expected_schema in REQUIRED_INTERNAL_ARTIFACTS.items():
        descriptor = artifact_container.get(artifact_name)
        if (
            not isinstance(descriptor, dict)
            or artifacts[artifact_name].get("contract_and_identity_match") is not True
        ):
            json_payloads_valid = False
            continue
        payload, error = _read_json_object(_resolve_repo_path(root, descriptor.get("path")))
        if error is not None or payload.get("schema") != expected_schema:
            json_payloads_valid = False
            continue
        payloads[artifact_name] = payload

    checks = {
        "json_payloads_match_declared_schemas": json_payloads_valid
        and len(payloads) == len(REQUIRED_INTERNAL_ARTIFACTS),
        "artifact_system_operator_and_network_identity_match": False,
        "cross_artifact_hash_bindings_match": False,
        "feature_and_edge_axes_valid": False,
        "state_and_flux_rows_match_immutable_axes": False,
        "state_transition_continuity_verified": False,
        "causal_step_time_and_input_lineage_valid": False,
        "step_mass_ledgers_recomputed_conservative": False,
        "modeled_state_and_flux_claim_boundary_valid": False,
        "telemetry_bundle_contract_valid": False,
    }
    if not checks["json_payloads_match_declared_schemas"]:
        return _semantic_result(checks)

    feature_payload = payloads["feature_axis_artifact"]
    edge_payload = payloads["edge_axis_artifact"]
    state_payload = payloads["reach_state_artifact"]
    flux_payload = payloads["edge_flux_artifact"]
    ledger_payload = payloads["step_mass_ledger_artifact"]
    all_payloads = tuple(payloads.values())
    operator_values = [value.get("operator_schema") for value in all_payloads]
    network_values = [value.get("network_fingerprint") for value in all_payloads]
    operator_schemas = {value for value in operator_values if isinstance(value, str)}
    network_fingerprints = {value for value in network_values if isinstance(value, str)}
    checks["artifact_system_operator_and_network_identity_match"] = (
        all(value.get("system_id") == system_id for value in all_payloads)
        and all(isinstance(value, str) and bool(value.strip()) for value in operator_values)
        and len(operator_schemas) == 1
        and all(_valid_sha256(value) for value in network_values)
        and len(network_fingerprints) == 1
    )
    checks["cross_artifact_hash_bindings_match"] = (
        state_payload.get("feature_axis_sha256")
        == artifacts["feature_axis_artifact"].get("actual_sha256")
        and ledger_payload.get("feature_axis_sha256")
        == artifacts["feature_axis_artifact"].get("actual_sha256")
        and flux_payload.get("edge_axis_sha256")
        == artifacts["edge_axis_artifact"].get("actual_sha256")
    )

    feature_rows = feature_payload.get("features")
    edge_rows = edge_payload.get("edges")
    feature_ids: list[int] = []
    valid_feature_axis = isinstance(feature_rows, list) and bool(feature_rows)
    if valid_feature_axis:
        for index, row in enumerate(feature_rows):
            if (
                not isinstance(row, dict)
                or row.get("feature_index") != index
                or not _positive_integer(row.get("feature_id"))
                or not _finite_nonnegative(row.get("effective_length_m"))
            ):
                valid_feature_axis = False
                break
            feature_ids.append(int(row["feature_id"]))
        valid_feature_axis = valid_feature_axis and len(feature_ids) == len(set(feature_ids))
    valid_feature_axis = valid_feature_axis and feature_payload.get("feature_count") == len(
        feature_ids
    )

    edge_keys: list[str] = []
    valid_edge_axis = isinstance(edge_rows, list) and bool(edge_rows)
    if valid_edge_axis:
        feature_set = set(feature_ids)
        for index, row in enumerate(edge_rows):
            if (
                not isinstance(row, dict)
                or row.get("edge_index") != index
                or not isinstance(row.get("edge_key"), str)
                or not str(row["edge_key"]).strip()
                or row.get("source_feature_id") not in feature_set
                or row.get("target_feature_id") not in feature_set
                or row.get("source_feature_id") == row.get("target_feature_id")
                or row.get("direction_role") != "authoritative_network_direction"
                or not isinstance(row.get("edge_admitted"), bool)
            ):
                valid_edge_axis = False
                break
            edge_keys.append(str(row["edge_key"]))
        valid_edge_axis = valid_edge_axis and len(edge_keys) == len(set(edge_keys))
    valid_edge_axis = valid_edge_axis and edge_payload.get("edge_count") == len(edge_keys)
    checks["feature_and_edge_axes_valid"] = valid_feature_axis and valid_edge_axis

    step_count_values = [
        value.get("step_count") for value in (state_payload, flux_payload, ledger_payload)
    ]
    step_count = step_count_values[0] if step_count_values[1:] == step_count_values[:-1] else None
    valid_step_count = _positive_integer(step_count)
    state_rows = state_payload.get("rows")
    flux_rows = flux_payload.get("rows")
    ledger_rows = ledger_payload.get("rows")
    row_metadata_valid = (
        valid_step_count
        and isinstance(state_rows, list)
        and isinstance(flux_rows, list)
        and isinstance(ledger_rows, list)
        and state_payload.get("row_count") == len(state_rows)
        and flux_payload.get("row_count") == len(flux_rows)
        and ledger_payload.get("row_count") == len(ledger_rows)
        and len(state_rows) == int(step_count) * len(feature_ids)
        and len(flux_rows) == int(step_count) * len(edge_keys)
        and len(ledger_rows) == int(step_count)
    )
    valid_state_rows = row_metadata_valid
    valid_flux_rows = row_metadata_valid
    continuity_valid = row_metadata_valid
    causal_valid = row_metadata_valid
    ledger_valid = row_metadata_valid
    temporal_by_step: list[tuple[object, ...]] = []
    if row_metadata_valid:
        for step_index, ledger in enumerate(ledger_rows):
            if not isinstance(ledger, dict):
                causal_valid = False
                ledger_valid = False
                temporal_by_step.append(())
                continue
            temporal = _temporal_identity(ledger)
            temporal_by_step.append(temporal)
            issue_time = _aware_datetime(ledger.get("forecast_issue_time"))
            available_at = _aware_datetime(ledger.get("inputs_available_at"))
            support_start = _aware_datetime(ledger.get("support_start_utc"))
            support_end = _aware_datetime(ledger.get("support_end_utc"))
            provenance = ledger.get("input_provenance_ids")
            causal_valid = causal_valid and (
                ledger.get("step_index") == step_index
                and issue_time is not None
                and available_at is not None
                and support_start is not None
                and support_end is not None
                and available_at <= issue_time <= support_start < support_end
                and isinstance(provenance, list)
                and bool(provenance)
                and all(isinstance(value, str) and value.strip() for value in provenance)
                and len(provenance) == len(set(provenance))
            )
            residual = ledger.get("residual_m3")
            tolerance = ledger.get("numeric_tolerance_m3")
            ledger_valid = ledger_valid and (
                ledger.get("step_index") == step_index
                and _finite_number(residual)
                and _finite_nonnegative(tolerance)
                and abs(float(residual)) <= float(tolerance)
                and ledger.get("mass_balance_passed") is True
            )

        for step_index in range(int(step_count)):
            for feature_index, feature_id in enumerate(feature_ids):
                row = state_rows[step_index * len(feature_ids) + feature_index]
                valid_state_rows = valid_state_rows and (
                    isinstance(row, dict)
                    and row.get("step_index") == step_index
                    and row.get("feature_index") == feature_index
                    and row.get("feature_id") == feature_id
                    and _finite_nonnegative(row.get("initial_stock_m3"))
                    and _finite_nonnegative(row.get("final_stock_m3"))
                    and _finite_nonnegative(row.get("final_depth_m"))
                    and row.get("ground_truth") is False
                    and _temporal_identity(row) == temporal_by_step[step_index]
                )
                if step_index > 0:
                    previous = state_rows[(step_index - 1) * len(feature_ids) + feature_index]
                    continuity_valid = continuity_valid and (
                        isinstance(previous, dict)
                        and isinstance(row, dict)
                        and previous.get("final_stock_m3") == row.get("initial_stock_m3")
                    )
            for edge_index, edge_key in enumerate(edge_keys):
                row = flux_rows[step_index * len(edge_keys) + edge_index]
                valid_flux_rows = valid_flux_rows and (
                    isinstance(row, dict)
                    and row.get("step_index") == step_index
                    and row.get("edge_index") == edge_index
                    and row.get("edge_key") == edge_key
                    and _finite_nonnegative(row.get("base_mean_flux_m3s"))
                    and row.get("ground_truth") is False
                    and _temporal_identity(row) == temporal_by_step[step_index]
                )
    checks["state_and_flux_rows_match_immutable_axes"] = bool(valid_state_rows) and bool(
        valid_flux_rows
    )
    checks["state_transition_continuity_verified"] = bool(continuity_valid)
    checks["causal_step_time_and_input_lineage_valid"] = bool(causal_valid)
    checks["step_mass_ledgers_recomputed_conservative"] = bool(ledger_valid)
    checks["modeled_state_and_flux_claim_boundary_valid"] = state_payload.get("claim_boundary") == {
        "modeled": True,
        "ground_truth": False,
        "observation_values_loaded": False,
    } and flux_payload.get("claim_boundary") == {
        "physical_base_flux": True,
        "observed_flux_truth": False,
        "innovation_values_included": False,
    }
    telemetry_bundle = artifact_container.get("telemetry_bundle")
    bundle_assertions = (
        telemetry_bundle.get("alignment_assertions") if isinstance(telemetry_bundle, dict) else None
    )
    claim_boundary = (
        telemetry_bundle.get("claim_boundary") if isinstance(telemetry_bundle, dict) else None
    )
    checks["telemetry_bundle_contract_valid"] = (
        isinstance(telemetry_bundle, dict)
        and telemetry_bundle.get("schema")
        == "gwm.geospatial_kernel.internal_innovation_telemetry.v1"
        and telemetry_bundle.get("system_id") == system_id
        and telemetry_bundle.get("operator_schema") in operator_schemas
        and telemetry_bundle.get("network_fingerprint") in network_fingerprints
        and telemetry_bundle.get("step_count") == step_count
        and isinstance(bundle_assertions, dict)
        and all(bundle_assertions.get(name) is True for name in REQUIRED_ALIGNMENT_ASSERTIONS)
        and isinstance(claim_boundary, dict)
        and claim_boundary.get("reach_states_are_modeled_not_observed") is True
        and claim_boundary.get("edge_fluxes_are_physical_base_flux_not_observed_truth") is True
        and claim_boundary.get("outcome_values_loaded") is False
        and claim_boundary.get("innovation_fitted") is False
    )
    return _semantic_result(checks)


def _semantic_result(checks: Mapping[str, bool]) -> dict[str, object]:
    return {
        "checks": dict(checks),
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "all_checks_passed": all(checks.values()),
    }


def _temporal_identity(row: Mapping[str, object]) -> tuple[object, ...]:
    return tuple(
        row.get(name)
        for name in (
            "forecast_issue_time",
            "inputs_available_at",
            "support_start_utc",
            "support_end_utc",
            "input_provenance_ids",
            "initial_state_provenance_id",
            "final_state_provenance_id",
        )
    )


def _positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _finite_nonnegative(value: object) -> bool:
    return _finite_number(value) and float(value) >= 0.0


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _aware_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _descriptor_identity(root: Path, descriptor: object) -> dict[str, object]:
    if not isinstance(descriptor, dict):
        return {
            "declared": False,
            "descriptor_complete": False,
            "path_within_repo": False,
            "exists": False,
            "identity_matches": False,
        }
    return _expected_artifact_identity(
        root=root,
        path=_resolve_repo_path(root, descriptor.get("path")),
        expected_path=descriptor.get("path"),
        expected_sha256=descriptor.get("sha256"),
        expected_size_bytes=descriptor.get("size_bytes"),
        declared=True,
        require_size=True,
    )


def _expected_artifact_identity(
    *,
    root: Path,
    path: Path | None,
    expected_path: object,
    expected_sha256: object,
    expected_size_bytes: object | None = None,
    declared: bool = True,
    require_size: bool = False,
) -> dict[str, object]:
    valid_sha = (
        isinstance(expected_sha256, str)
        and len(expected_sha256) == 64
        and all(value in "0123456789abcdef" for value in expected_sha256)
    )
    valid_size = (not require_size and expected_size_bytes is None) or (
        isinstance(expected_size_bytes, int)
        and not isinstance(expected_size_bytes, bool)
        and expected_size_bytes >= 0
    )
    descriptor_complete = (
        isinstance(expected_path, str) and bool(expected_path.strip()) and valid_sha and valid_size
    )
    exists = path is not None and path.is_file()
    actual_sha256 = _sha256_file(path) if exists else None
    actual_size_bytes = path.stat().st_size if exists else None
    size_matches = expected_size_bytes is None or actual_size_bytes == expected_size_bytes
    return {
        "declared": declared,
        "path": expected_path,
        "expected_sha256": expected_sha256,
        "expected_size_bytes": expected_size_bytes,
        "descriptor_complete": descriptor_complete,
        "path_within_repo": path is not None,
        "exists": exists,
        "actual_sha256": actual_sha256,
        "actual_size_bytes": actual_size_bytes,
        "identity_matches": (
            descriptor_complete and exists and actual_sha256 == expected_sha256 and size_matches
        ),
    }


def _resolve_repo_path(root: Path, value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    relative = Path(value)
    if relative.is_absolute():
        return None
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json_object(path: Path | None) -> tuple[dict[str, Any], str | None]:
    if path is None or not path.is_file():
        return {}, "source_rollout_missing_or_outside_repo"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return {}, f"source_rollout_json_invalid:{type(error).__name__}"
    if not isinstance(value, dict):
        return {}, "source_rollout_root_must_be_object"
    return value, None


if __name__ == "__main__":
    raise SystemExit(main())
