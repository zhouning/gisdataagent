#!/usr/bin/env python3
"""Assess whether a matched traditional routing baseline can run credibly."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import platform
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_inputs_report.json"
)
DEFAULT_SCORE_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_score.json"
)
DEFAULT_OFFICIAL_BUILD = REPO_ROOT / (
    "data/geotransport_v0_1/t_route_mc_runtime/build_manifest.json"
)
DEFAULT_EXECUTION_AUDIT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/t_route_mc_execution_semantics_report.json"
)
DEFAULT_DERIVED_BUILD = REPO_ROOT / (
    "data/geotransport_v0_1/t_route_mc_initialized_diagnostic_runtime/build_manifest.json"
)
DEFAULT_DERIVED_MATRIX = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/t_route_mc_initialized_diagnostic_response_matrix.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_traditional_routing_baseline_readiness_report.json"
)

SCHEMA = "gwm.geospatial_kernel.traditional_routing_baseline_readiness.v1"
SYSTEM_IDS = ("center_hill", "j_percy_priest")
HOUR_COUNT = 672
T_ROUTE_COMMIT = "12a8eae0cdfed437143c590659fa7077605a5e70"
EXPECTED_SOURCE_SHA256 = {
    "input_report": "79bbc235dbef5da8a6d284cb307b2753183773bfd7a28305b9ed896696394435",
    "score_report": "97eabc58c5cf9cff681e46793fa8f6167eff1217b31fbd8150cb256a97c47ed0",
    "official_build": "26780f3c6cb9bcc4fa61b608c8e93843b4db2054a469ce0114c3880ba4b6a7f4",
    "execution_audit": "d5858ca8e0ce1eafee04dc009f24f43003b584ab069b8a822f0dfd70efcc151d",
    "derived_build": "5dc6cba8e1260db25499791e8dc5282f5705c72b0500f3e32aec8ec7c9988c9f",
    "derived_matrix": "83d5ebeaada13505d1d51902903d8d79203e3f3dc243b366b3563b0930781447",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-report", type=Path, default=DEFAULT_INPUT_REPORT)
    parser.add_argument("--score-report", type=Path, default=DEFAULT_SCORE_REPORT)
    parser.add_argument("--official-build", type=Path, default=DEFAULT_OFFICIAL_BUILD)
    parser.add_argument("--execution-audit", type=Path, default=DEFAULT_EXECUTION_AUDIT)
    parser.add_argument("--derived-build", type=Path, default=DEFAULT_DERIVED_BUILD)
    parser.add_argument("--derived-matrix", type=Path, default=DEFAULT_DERIVED_MATRIX)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = assess_readiness(
        input_report_path=args.input_report,
        score_report_path=args.score_report,
        official_build_path=args.official_build,
        execution_audit_path=args.execution_audit,
        derived_build_path=args.derived_build,
        derived_matrix_path=args.derived_matrix,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(f"status={report['status']}")
    print(f"two_system_data_ready={report['decision']['two_system_data_ready']}")
    print(f"professional_runtime_ready={report['decision']['professional_runtime_ready']}")
    return 0 if report["assessment_integrity_passed"] else 1


def assess_readiness(
    *,
    input_report_path: Path = DEFAULT_INPUT_REPORT,
    score_report_path: Path = DEFAULT_SCORE_REPORT,
    official_build_path: Path = DEFAULT_OFFICIAL_BUILD,
    execution_audit_path: Path = DEFAULT_EXECUTION_AUDIT,
    derived_build_path: Path = DEFAULT_DERIVED_BUILD,
    derived_matrix_path: Path = DEFAULT_DERIVED_MATRIX,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    sources = {
        "input_report": _load_bound_json(
            input_report_path,
            root=root,
            expected_sha256=EXPECTED_SOURCE_SHA256["input_report"],
        ),
        "score_report": _load_bound_json(
            score_report_path,
            root=root,
            expected_sha256=EXPECTED_SOURCE_SHA256["score_report"],
        ),
        "official_build": _load_bound_json(
            official_build_path,
            root=root,
            expected_sha256=EXPECTED_SOURCE_SHA256["official_build"],
        ),
        "execution_audit": _load_bound_json(
            execution_audit_path,
            root=root,
            expected_sha256=EXPECTED_SOURCE_SHA256["execution_audit"],
        ),
        "derived_build": _load_bound_json(
            derived_build_path,
            root=root,
            expected_sha256=EXPECTED_SOURCE_SHA256["derived_build"],
        ),
        "derived_matrix": _load_bound_json(
            derived_matrix_path,
            root=root,
            expected_sha256=EXPECTED_SOURCE_SHA256["derived_matrix"],
        ),
    }
    source_identity_valid = all(value["identity_matches"] for value in sources.values())
    input_payload = sources["input_report"]["payload"]
    score_payload = sources["score_report"]["payload"]
    input_contract_valid = (
        input_payload.get("schema") == "gwm.geotransport.kinematic_wave_holdout_inputs.v2"
        and input_payload.get("status") == "pass_outcome_free_two_system_inputs_acquired"
        and set(input_payload.get("systems") or {}) == set(SYSTEM_IDS)
        and input_payload.get("claim_boundary", {}).get("dynamic_inputs_acquired") is True
    )
    systems = {
        system_id: _assess_system(
            system_id,
            (input_payload.get("systems") or {}).get(system_id),
            root=root,
        )
        for system_id in SYSTEM_IDS
    }
    two_system_data_ready = input_contract_valid and all(
        value["data_ready"] for value in systems.values()
    )
    evaluation_exposure = _evaluation_exposure(score_payload)
    official_runtime = _official_runtime_readiness(
        sources["official_build"]["payload"],
        sources["execution_audit"]["payload"],
        root=root,
    )
    derived_runtime = _derived_runtime_readiness(
        sources["derived_build"]["payload"],
        sources["derived_matrix"]["payload"],
        root=root,
    )
    professional_runtime_ready = (
        official_runtime["professional_baseline_eligible"]
        or derived_runtime["professional_baseline_eligible"]
    )
    historical_posthoc_execution_ready = (
        source_identity_valid and two_system_data_ready and professional_runtime_ready
    )
    assessment_integrity_passed = source_identity_valid
    if not source_identity_valid:
        status = "blocked_source_identity_failure"
    elif not two_system_data_ready:
        status = "blocked_two_system_input_or_parameter_gap"
    elif not professional_runtime_ready:
        status = "blocked_professional_runtime_semantics"
    else:
        status = "ready_for_historical_posthoc_traditional_routing_execution"
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "source_artifacts": {
            name: {key: value for key, value in record.items() if key != "payload"}
            for name, record in sources.items()
        },
        "systems": systems,
        "evaluation_exposure": evaluation_exposure,
        "runtime_candidates": {
            "official_fixed_commit": official_runtime,
            "derived_initialized_diagnostic": derived_runtime,
        },
        "decision": {
            "two_system_data_ready": two_system_data_ready,
            "professional_runtime_ready": professional_runtime_ready,
            "historical_posthoc_execution_ready": historical_posthoc_execution_ready,
            "fresh_validation_on_existing_window_permitted": False,
            "recommended_next_action": (
                "freeze_and_validate_an_independent_professional_muskingum_cunge_runtime_"
                "before_executing_the_matched_two_system_posthoc_comparison"
            ),
            "generic_muskingum_cunge_family_rejected": False,
            "geospatial_kernel_validated": False,
            "runtime_default_enabled": False,
        },
        "assessment_integrity_passed": assessment_integrity_passed,
        "execution_boundary": {
            "network_requests_performed": False,
            "outcome_value_artifacts_opened": False,
            "post_outcome_score_summary_read": True,
            "traditional_routing_predictions_executed": False,
            "predictions_scored": False,
            "candidate_parameters_fitted": False,
        },
    }


def _assess_system(system_id: str, value: object, *, root: Path) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"system_id": system_id, "gates": {}, "data_ready": False}
    count = value.get("feature_count")
    arrays = value.get("decoded_arrays")
    result = value.get("result")
    if not isinstance(arrays, dict):
        arrays = {}
    if not isinstance(result, dict):
        result = {}
    required_arrays = {
        name: _verify_descriptor(arrays.get(name), root=root)
        for name in (
            "feature_ids",
            "forcing_timestamps_utc",
            "initial_streamflow_m3s",
            "q_lateral_m3s",
        )
    }
    action = _verify_descriptor(value.get("action_values"), root=root)
    topology = _verify_descriptor(value.get("topology_report"), root=root)
    loaded = _load_arrays(required_arrays)
    action_rows = _load_action_rows(action)
    topology_payload, topology_error = _read_json(topology.get("resolved_path"))
    route_link = _verify_descriptor(
        (topology_payload.get("artifacts") or {}).get("route_link_subset"),
        root=root,
    )
    route_audit = (
        (topology_payload.get("artifacts") or {}).get("route_link_subset", {}).get("audit", {})
    )
    feature_ids = loaded.get("feature_ids")
    timestamps = loaded.get("forcing_timestamps_utc")
    initial = loaded.get("initial_streamflow_m3s")
    forcing = loaded.get("q_lateral_m3s")
    feature_axis_valid = (
        isinstance(count, int)
        and not isinstance(count, bool)
        and count > 0
        and isinstance(feature_ids, np.ndarray)
        and feature_ids.shape == (count,)
        and np.issubdtype(feature_ids.dtype, np.integer)
        and bool((feature_ids > 0).all())
        and len(set(int(item) for item in feature_ids)) == count
    )
    time_axis_valid = _time_axis_valid(timestamps, action_rows)
    dynamic_values_valid = (
        isinstance(initial, np.ndarray)
        and initial.shape == (count,)
        and np.isfinite(initial).all()
        and bool((initial >= 0.0).all())
        and isinstance(forcing, np.ndarray)
        and forcing.shape == (HOUR_COUNT, count)
        and np.isfinite(forcing).all()
        and bool((forcing >= 0.0).all())
        and len(action_rows) == HOUR_COUNT
        and all(
            _finite_nonnegative(row.get("action_release_m3s"))
            and row.get("source_role") == "boundary_action"
            for row in action_rows
        )
    )
    topology_and_parameters_valid = (
        topology_error is None
        and topology_payload.get("status") == "pass_full_incremental_subnetwork_compiled"
        and topology_payload.get("gates", {}).get("directed_network_contract_admitted") is True
        and topology_payload.get("gates", {}).get("official_route_link_identity_verified") is True
        and topology_payload.get("gates", {}).get("route_link_parameter_coverage_complete") is True
        and route_link["identity_matches"] is True
        and route_audit.get("all_required_parameter_fields_present") is True
        and route_audit.get("feature_axis_matches_requested_covered_order") is True
        and feature_axis_valid
        and route_audit.get("feature_ids") == [int(item) for item in feature_ids]
    )
    gates = {
        "all_declared_dynamic_artifacts_hash_bound": (
            all(item["identity_matches"] for item in required_arrays.values())
            and action["identity_matches"] is True
        ),
        "feature_axis_values_valid": feature_axis_valid,
        "hourly_action_and_forcing_axes_aligned": time_axis_valid,
        "initial_state_action_and_forcing_values_valid": dynamic_values_valid,
        "route_link_topology_and_parameter_axis_valid": topology_and_parameters_valid,
        "source_report_declares_no_fill_or_missing_values": (
            result.get("hour_count") == HOUR_COUNT
            and result.get("action_missing_value_count") == 0
            and result.get("initial_streamflow_fill_value_count") == 0
            and result.get("q_lateral_fill_value_count") == 0
        ),
    }
    return {
        "system_id": system_id,
        "feature_count": count,
        "dynamic_artifacts": {
            **{name: _public_descriptor(record) for name, record in required_arrays.items()},
            "action_values": _public_descriptor(action),
        },
        "topology_report": _public_descriptor(topology),
        "route_link_subset": _public_descriptor(route_link),
        "gates": gates,
        "data_ready": all(gates.values()),
    }


def _official_runtime_readiness(
    build: dict[str, Any], audit: dict[str, Any], *, root: Path
) -> dict[str, Any]:
    descriptors = [build.get("library_artifact"), build.get("source_manifest")]
    descriptors.extend(build.get("source_artifacts") or [])
    identities = [_verify_descriptor(value, root=root) for value in descriptors]
    build_valid = (
        build.get("schema") == "gwm.geotransport.t_route_mc_runtime_build.v1"
        and build.get("source_commit") == T_ROUTE_COMMIT
        and build.get("official_source_unmodified") is True
        and build.get("entrypoint") == "c_muskingcungenwm"
        and all(value["identity_matches"] for value in identities)
    )
    conformance = audit.get("adapter_conformance") or {}
    audit_valid = (
        audit.get("schema") == "gwm.geotransport.t_route_mc_execution_semantics.v1"
        and audit.get("status") == "fixed_commit_execution_semantics_audited"
        and audit.get("claim_boundary", {}).get("execution_semantics_audited") is True
        and all(
            conformance.get(name) is True
            for name in (
                "float32_fortran_call_boundary_matches",
                "fortran_abi_matches",
                "global_timestep_semantics_match",
                "lateral_flow_rate_semantics_match",
                "open_loop_serial_chain_default_upstream_recursion_matches",
                "open_loop_serial_chain_short_ts_recursion_matches",
            )
        )
        and conformance.get("missing_full_python_driver_explains_response_matrix_failure") is False
    )
    initialization_gate = (
        audit.get("claim_boundary", {}).get("fixed_commit_kernel_initialization_gate_passed")
        is True
    )
    return {
        "source_commit": build.get("source_commit"),
        "build_and_artifact_identity_valid": build_valid,
        "execution_semantics_audit_valid": audit_valid,
        "fixed_commit_initialization_gate_passed": initialization_gate,
        "current_host_direct_execution_compatible": _host_compatible(build.get("platform")),
        "professional_baseline_eligible": build_valid and audit_valid and initialization_gate,
        "rejection_reason": (
            None
            if initialization_gate
            else "fixed_commit_kernel_reads_required_carry_values_before_assignment"
        ),
    }


def _derived_runtime_readiness(
    build: dict[str, Any], matrix: dict[str, Any], *, root: Path
) -> dict[str, Any]:
    descriptors = [
        build.get("library_artifact"),
        build.get("source_manifest"),
        build.get("derived_core_source"),
        build.get("official_core_source"),
        build.get("source_patch"),
    ]
    identities = [_verify_descriptor(value, root=root) for value in descriptors]
    build_valid = (
        build.get("schema") == "gwm.geotransport.t_route_mc_initialized_diagnostic_runtime.v1"
        and build.get("source_commit") == T_ROUTE_COMMIT
        and build.get("official_source_unmodified") is False
        and build.get("derived_diagnostic_only") is True
        and all(value["identity_matches"] for value in identities)
    )
    gates = matrix.get("gates") or {}
    matrix_valid = (
        matrix.get("schema") == "gwm.geotransport.t_route_mc_initialized_diagnostic_matrix.v1"
        and matrix.get("status") == "derived_initialized_runtime_diagnostic_complete"
        and matrix.get("claim_boundary", {}).get("derived_matrix_executed") is True
    )
    eligible = (
        build_valid
        and matrix_valid
        and gates.get("all_outlet_negative_lobes_within_tolerance") is True
        and gates.get("timestep_stability") is True
        and gates.get("all_diagnostic_gates_passed") is True
        and matrix.get("claim_boundary", {}).get("professional_baseline_eligible") is True
    )
    return {
        "source_commit": build.get("source_commit"),
        "build_and_artifact_identity_valid": build_valid,
        "diagnostic_matrix_valid": matrix_valid,
        "negative_lobe_gate_passed": (
            gates.get("all_outlet_negative_lobes_within_tolerance") is True
        ),
        "timestep_stability_gate_passed": gates.get("timestep_stability") is True,
        "current_host_direct_execution_compatible": _host_compatible(build.get("platform")),
        "official_runtime": False,
        "professional_baseline_eligible": eligible,
        "rejection_reason": (
            None if eligible else "derived_runtime_fails_negative_lobe_and_timestep_stability_gates"
        ),
    }


def _evaluation_exposure(score: dict[str, Any]) -> dict[str, Any]:
    claim = score.get("claim_boundary") or {}
    valid = (
        score.get("schema") == "gwm.geotransport.kinematic_wave_holdout_score.v2"
        and score.get("status") == "two_system_kinematic_wave_holdout_scored_once"
        and claim.get("two_system_prospective_score_available") is True
        and claim.get("no_post_score_tuning_or_prediction_revision_permitted") is True
    )
    return {
        "score_summary_identity_and_claim_valid": valid,
        "target_window_outcomes_already_exposed": valid,
        "new_comparator_on_this_window_is_posthoc_only": True,
        "new_comparator_may_be_tuned_on_this_window": False,
        "fresh_unexposed_window_required_for_validation": True,
    }


def _load_bound_json(path: Path, *, root: Path, expected_sha256: str) -> dict[str, Any]:
    resolved = _inside_root(root, path)
    artifact = _file_identity(resolved, root=root)
    payload, error = _read_json(resolved)
    return {
        **artifact,
        "expected_sha256": expected_sha256,
        "identity_matches": error is None and artifact.get("sha256") == expected_sha256,
        "json_error": error,
        "payload": payload,
    }


def _verify_descriptor(value: object, *, root: Path) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"path": None, "identity_matches": False, "resolved_path": None}
    path_value = value.get("path")
    path = _inside_root(root, Path(path_value)) if isinstance(path_value, str) else None
    artifact = _file_identity(path, root=root)
    matches = (
        _valid_sha256(value.get("sha256"))
        and _nonnegative_integer(value.get("size_bytes"))
        and artifact.get("sha256") == value.get("sha256")
        and artifact.get("size_bytes") == value.get("size_bytes")
    )
    return {
        "path": path_value,
        "declared_sha256": value.get("sha256"),
        "actual_sha256": artifact.get("sha256"),
        "declared_size_bytes": value.get("size_bytes"),
        "actual_size_bytes": artifact.get("size_bytes"),
        "identity_matches": matches,
        "resolved_path": path if matches else None,
    }


def _public_descriptor(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "resolved_path"}


def _load_arrays(records: dict[str, dict[str, Any]]) -> dict[str, np.ndarray]:
    loaded: dict[str, np.ndarray] = {}
    for name, record in records.items():
        path = record.get("resolved_path")
        if isinstance(path, Path):
            try:
                loaded[name] = np.load(path, allow_pickle=False)
            except (OSError, ValueError):
                continue
    return loaded


def _load_action_rows(record: dict[str, Any]) -> list[dict[str, str]]:
    path = record.get("resolved_path")
    if not isinstance(path, Path):
        return []
    try:
        return list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))
    except (OSError, UnicodeError, csv.Error):
        return []


def _time_axis_valid(value: object, action_rows: list[dict[str, str]]) -> bool:
    if not isinstance(value, np.ndarray) or value.shape != (HOUR_COUNT,):
        return False
    timestamps = [_aware_datetime(str(item)) for item in value]
    if any(item is None for item in timestamps) or len(action_rows) != HOUR_COUNT:
        return False
    starts = [_aware_datetime(row.get("support_start_utc")) for row in action_rows]
    ends = [_aware_datetime(row.get("support_end_utc")) for row in action_rows]
    for index in range(HOUR_COUNT):
        timestamp = timestamps[index]
        if (
            timestamp is None
            or starts[index] != timestamp
            or ends[index] != timestamp + timedelta(hours=1)
            or (index > 0 and timestamp != timestamps[index - 1] + timedelta(hours=1))
        ):
            return False
    return True


def _host_compatible(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    expected_system = str(value.get("system", "")).lower()
    expected_machine = _normalize_machine(str(value.get("machine", "")))
    return expected_system == platform.system().lower() and expected_machine == _normalize_machine(
        platform.machine()
    )


def _normalize_machine(value: str) -> str:
    normalized = value.lower()
    return "arm64" if normalized in {"arm64", "aarch64"} else normalized


def _inside_root(root: Path, path: Path | None) -> Path | None:
    if path is None:
        return None
    candidate = path if path.is_absolute() else root / path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def _read_json(path: Path | None) -> tuple[dict[str, Any], str | None]:
    if path is None or not path.is_file():
        return {}, "json_artifact_missing_or_outside_repository"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return {}, f"json_artifact_invalid:{type(error).__name__}"
    if not isinstance(value, dict):
        return {}, "json_artifact_root_must_be_object"
    return value, None


def _file_identity(path: Path | None, *, root: Path) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"path": None, "sha256": None, "size_bytes": None}
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": digest.hexdigest(),
        "size_bytes": path.stat().st_size,
    }


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


def _finite_nonnegative(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        numeric = float(value)
    except ValueError:
        return False
    return math.isfinite(numeric) and numeric >= 0.0


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _nonnegative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


if __name__ == "__main__":
    raise SystemExit(main())
