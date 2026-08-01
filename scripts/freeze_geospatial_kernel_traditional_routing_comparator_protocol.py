#!/usr/bin/env python3
"""Freeze admission gates for an independent professional routing comparator."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_traditional_routing_comparator_protocol.json"
)
READINESS_REPORT = (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_traditional_routing_baseline_readiness_report.json"
)
EVIDENCE_PATHS = {
    "two_system_input_report": (
        "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_inputs_report.json"
    ),
    "official_runtime_build": (
        "data/geotransport_v0_1/t_route_mc_runtime/build_manifest.json"
    ),
    "official_runtime_semantics": (
        "benchmarks/geotransport_v0_1/t_route_mc_execution_semantics_report.json"
    ),
    "derived_runtime_build": (
        "data/geotransport_v0_1/"
        "t_route_mc_initialized_diagnostic_runtime/build_manifest.json"
    ),
    "derived_runtime_response_matrix": (
        "benchmarks/geotransport_v0_1/"
        "t_route_mc_initialized_diagnostic_response_matrix.json"
    ),
}
EXPECTED_EVIDENCE_SHA256 = {
    "readiness_report": "eec9cbd296edd762a346d1df8e3b220f0804f2d64a5647aad86ce69dc5afe965",
    "two_system_input_report": (
        "79bbc235dbef5da8a6d284cb307b2753183773bfd7a28305b9ed896696394435"
    ),
    "official_runtime_build": (
        "26780f3c6cb9bcc4fa61b608c8e93843b4db2054a469ce0114c3880ba4b6a7f4"
    ),
    "official_runtime_semantics": (
        "d5858ca8e0ce1eafee04dc009f24f43003b584ab069b8a822f0dfd70efcc151d"
    ),
    "derived_runtime_build": (
        "5dc6cba8e1260db25499791e8dc5282f5705c72b0500f3e32aec8ec7c9988c9f"
    ),
    "derived_runtime_response_matrix": (
        "83d5ebeaada13505d1d51902903d8d79203e3f3dc243b366b3563b0930781447"
    ),
}
CODE_PATHS = (
    "scripts/assess_geospatial_kernel_traditional_routing_baseline_readiness.py",
    "scripts/audit_geotransport_troute_mc_execution_semantics.py",
    "scripts/certify_geotransport_troute_mc_initialized_diagnostic.py",
    "scripts/certify_geotransport_troute_mc_response_matrix.py",
)
SCHEMA = "gwm.geospatial_kernel.traditional_routing_comparator_protocol.v1"
FROZEN_AT = "2026-07-31T07:04:56Z"
SYSTEM_IDS = ("center_hill", "j_percy_priest")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_protocol(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    readiness, readiness_descriptor = _load_bound_readiness(
        root / READINESS_REPORT,
        root=root,
    )
    evidence = {"readiness_report": readiness_descriptor}
    evidence.update(
        {
            name: _bound_artifact(
                root,
                path,
                expected_sha256=EXPECTED_EVIDENCE_SHA256[name],
            )
            for name, path in EVIDENCE_PATHS.items()
        }
    )
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "frozen_before_independent_runtime_selection",
        "frozen_at": FROZEN_AT,
        "purpose": (
            "admit one independent professional Muskingum-Cunge-family comparator "
            "before any matched two-system execution"
        ),
        "method_scope": {
            "accepted_family": "Muskingum-Cunge or a documented close traditional routing method",
            "candidate_selected": False,
            "candidate_identity": None,
            "generic_muskingum_cunge_family_rejected": False,
            "previously_examined_runtimes_admitted": False,
            "admission_is_predictive_superiority_evidence": False,
        },
        "candidate_identity_contract": {
            "required": {
                "upstream_project_and_repository": True,
                "immutable_source_revision": True,
                "source_artifact_sha256": True,
                "release_or_version": True,
                "spdx_license_identifier": True,
                "license_artifact_sha256": True,
                "benchmark_and_redistribution_rights_documented": True,
                "compiler_or_interpreter_identity": True,
                "build_flags_and_dependency_lock": True,
                "executable_or_library_sha256": True,
                "host_platform_identity": True,
            },
            "independence": {
                "routing_equations_implemented_outside_geospatial_kernel_learned_code": True,
                "no_import_or_call_into_learned_innovation_operators": True,
                "no_shared_fitted_parameters_with_gwm_wwm": True,
                "thin_axis_and_unit_adapter_allowed": True,
                "adapter_source_hash_and_audit_required": True,
            },
        },
        "deterministic_interface_contract": {
            "units": {
                "time": "s",
                "discharge": "m3 s-1",
                "length": "m",
                "slope": "m m-1",
                "roughness": "s m-1/3",
                "storage": "m3",
            },
            "required_inputs": {
                "feature_ids": "int64[n_reaches] ordered exactly as the frozen feature axis",
                "downstream_feature_ids": "int64[n_reaches] with a documented outlet sentinel",
                "hydraulic_parameters": (
                    "finite width, slope, roughness and reach length on the feature axis"
                ),
                "initial_state": (
                    "finite nonnegative discharge plus every implementation carry/state value"
                ),
                "reservoir_action": "float64[n_steps] upstream boundary discharge",
                "lateral_inflow": "float64[n_steps,n_reaches] discharge rate",
                "timestep_seconds": "positive scalar shared by all reaches in one run",
            },
            "required_outputs": {
                "routed_discharge": "float64[n_steps,n_reaches]",
                "outlet_discharge": "float64[n_steps] derived from routed_discharge",
                "final_state": "all carry values required for an exact restart",
                "mass_ledger": "input, output and storage-change volume by step",
            },
            "execution_rules": {
                "explicit_initialization_before_first_read": True,
                "no_implicit_process_global_or_uninitialized_state": True,
                "cold_process_repeatability_required": True,
                "restart_from_serialized_state_matches_continuous_run": True,
                "input_arrays_are_read_only": True,
                "feature_and_time_axes_may_not_be_reordered_silently": True,
            },
        },
        "synthetic_conformance_suite": {
            "must_run_before_real_two_system_inputs": True,
            "outcome_data_allowed": False,
            "response_matrix": {
                "background_flows_m3s": [2.0, 20.0, 100.0],
                "pulse_rates_m3s": [0.1, 1.0, 10.0],
                "pulse_duration_seconds": 3600.0,
                "timesteps_seconds": [300.0, 900.0, 3600.0],
                "warmup_hours": 240,
                "rollout_hours": 240,
            },
            "mandatory_gates": {
                "source_build_license_and_adapter_identities_match": True,
                "abi_signature_and_array_shape_contract_pass": True,
                "all_required_carry_and_output_values_initialized_before_read": True,
                "cold_process_repeats_are_bitwise_equal_on_the_frozen_platform": True,
                "continuous_and_restart_runs_are_bitwise_equal": True,
                "zero_state_zero_boundary_zero_lateral_produces_zero_state_and_output": True,
                "all_impulse_and_step_states_and_outputs_are_finite": True,
                "all_impulse_and_step_incremental_responses_are_nonnegative": True,
                "timestep_response_quantiles_pass_frozen_stability_tolerances": True,
                "branching_dag_and_confluence_mass_accounting_pass": True,
                "confluence_upstream_order_permutation_is_invariant": True,
                "long_window_input_equals_output_plus_storage_change": True,
                "no_observed_outcome_or_fitted_target_parameter_is_loaded": True,
            },
            "numeric_tolerances": {
                "negative_discharge_m3s_absolute": 1e-6,
                "zero_identity_m3s_absolute": 1e-12,
                "mass_balance_relative_to_throughput": 1e-6,
                "mass_balance_m3_absolute": 1e-3,
                "timestep_quantile_seconds_absolute": 3600.0,
                "timestep_quantile_relative": 0.10,
            },
            "branching_cases": {
                "minimum_topologies": ["single_reach", "serial_path", "two_to_one_confluence"],
                "confluence_rule": (
                    "current and previous upstream contributions are each summed exactly once"
                ),
                "long_window_requires_residual_storage_accounting": True,
                "outflow_only_volume_recovery_is_not_a_mass_balance_substitute": True,
            },
        },
        "matched_execution_contract": {
            "systems": _frozen_existing_window_axes(readiness),
            "hour_count": 672,
            "same_feature_axis_for_all_comparators": True,
            "same_action_axis_for_all_comparators": True,
            "same_lateral_forcing_axis_for_all_comparators": True,
            "same_initial_discharge_axis_for_all_comparators": True,
            "same_route_link_geometry_and_topology": True,
            "candidate_specific_parameter_fitting_on_this_window": False,
            "candidate_specific_initial_state_invention": False,
            "predictions_must_be_sealed_before_score_access": True,
        },
        "forbidden_executor_inputs": [
            "outcome_values",
            "outcome_columns",
            "outcome_manifest",
            "outcome_path",
            "outcome_url",
            "score_report",
            "future_target_observations",
        ],
        "evaluation_policy": {
            "existing_672_hour_window": "historical_posthoc_comparison_only",
            "existing_window_may_tune_or_select_candidate": False,
            "existing_window_may_be_called_fresh_validation": False,
            "fresh_validation_requires_unexposed_window": True,
            "fresh_window_support_must_start_after_protocol_freeze": True,
            "every_dynamic_input_must_be_available_at_or_before_forecast_issue": True,
            "admission_precedes_any_matched_execution": True,
        },
        "admission_decision": {
            "required_gate_logic": "all mandatory gates must be true",
            "manual_waiver_allowed": False,
            "runtime_admitted": False,
            "matched_posthoc_execution_permitted": False,
            "fresh_validation_permitted": False,
            "runtime_default_enabled": False,
            "geospatial_kernel_validated": False,
        },
        "previous_runtime_disposition": {
            "official_fixed_commit": {
                "source_commit": "12a8eae0cdfed437143c590659fa7077605a5e70",
                "admitted": False,
                "reason": "required carry or output values are read before assignment",
            },
            "derived_initialized_diagnostic": {
                "source_commit": "12a8eae0cdfed437143c590659fa7077605a5e70",
                "admitted": False,
                "reason": "negative-response and timestep-stability gates fail",
            },
        },
        "bound_evidence": evidence,
        "frozen_code": {path: _artifact(root, path) for path in CODE_PATHS},
        "claim_boundary": {
            "protocol_frozen_before_candidate_selection": True,
            "network_requests_performed": False,
            "new_runtime_acquired_or_built": False,
            "candidate_selected": False,
            "candidate_certified": False,
            "traditional_predictions_executed": False,
            "outcome_values_opened_by_this_freeze": False,
            "historical_window_is_prospective": False,
            "professional_comparator_available": False,
            "runtime_default_enabled": False,
            "geospatial_kernel_validated": False,
        },
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload["protocol_seal"] = {
        "algorithm": "sha256_canonical_json_without_protocol_seal",
        "sha256": hashlib.sha256(canonical).hexdigest(),
    }
    return payload


def _load_bound_readiness(
    path: Path,
    *,
    root: Path = REPO_ROOT,
) -> tuple[dict[str, Any], dict[str, object]]:
    body = path.read_bytes()
    actual_sha256 = hashlib.sha256(body).hexdigest()
    if actual_sha256 != EXPECTED_EVIDENCE_SHA256["readiness_report"]:
        raise ValueError("traditional_routing_readiness_report_identity_mismatch")
    payload = json.loads(body)
    valid = (
        payload.get("schema")
        == "gwm.geospatial_kernel.traditional_routing_baseline_readiness.v1"
        and payload.get("status") == "blocked_professional_runtime_semantics"
        and payload.get("assessment_integrity_passed") is True
        and payload.get("decision", {}).get("two_system_data_ready") is True
        and payload.get("decision", {}).get("professional_runtime_ready") is False
        and payload.get("decision", {}).get("historical_posthoc_execution_ready") is False
        and payload.get("evaluation_exposure", {}).get(
            "new_comparator_on_this_window_is_posthoc_only"
        )
        is True
        and set(payload.get("systems") or {}) == set(SYSTEM_IDS)
        and all(
            system.get("data_ready") is True
            for system in (payload.get("systems") or {}).values()
        )
    )
    if not valid:
        raise ValueError("traditional_routing_readiness_report_contract_invalid")
    return payload, _artifact_from_body(root, path, body)


def _frozen_existing_window_axes(readiness: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for system_id in SYSTEM_IDS:
        system = readiness["systems"][system_id]
        result[system_id] = {
            "feature_count": system["feature_count"],
            "feature_ids": system["dynamic_artifacts"]["feature_ids"],
            "forcing_timestamps_utc": system["dynamic_artifacts"][
                "forcing_timestamps_utc"
            ],
            "initial_streamflow_m3s": system["dynamic_artifacts"][
                "initial_streamflow_m3s"
            ],
            "q_lateral_m3s": system["dynamic_artifacts"]["q_lateral_m3s"],
            "action_values": system["dynamic_artifacts"]["action_values"],
            "topology_report": system["topology_report"],
            "route_link_subset": system["route_link_subset"],
        }
    return result


def _bound_artifact(
    root: Path,
    relative_path: str,
    *,
    expected_sha256: str,
) -> dict[str, object]:
    descriptor = _artifact(root, relative_path)
    if descriptor["sha256"] != expected_sha256:
        raise ValueError(f"traditional_routing_evidence_identity_mismatch:{relative_path}")
    return descriptor


def _artifact(root: Path, relative_path: str) -> dict[str, object]:
    path = (root / relative_path).resolve()
    return _artifact_from_body(root, path, path.read_bytes())


def _artifact_from_body(root: Path, path: Path, body: bytes) -> dict[str, object]:
    resolved = path.resolve()
    try:
        display = resolved.relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise ValueError("traditional_routing_protocol_artifact_outside_repository") from error
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def main() -> int:
    args = parse_args()
    payload = compile_protocol()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(f"status={payload['status']}")
    print(f"protocol_sha256={payload['protocol_seal']['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
