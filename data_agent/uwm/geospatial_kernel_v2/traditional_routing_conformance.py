"""Runtime-neutral conformance adjudication for traditional river routing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import product
from typing import Any

import numpy as np

from .transfer_response import analyze_dynamic_transfer_response

TRADITIONAL_ROUTING_CONFORMANCE_EVIDENCE_SCHEMA = (
    "gwm.geospatial_kernel.traditional_routing_conformance_evidence.v1"
)
TRADITIONAL_ROUTING_CONFORMANCE_REPORT_SCHEMA = (
    "gwm.geospatial_kernel.traditional_routing_conformance_report.v1"
)
BACKGROUND_FLOWS_M3S = (2.0, 20.0, 100.0)
PULSE_RATES_M3S = (0.1, 1.0, 10.0)
TIMESTEPS_SECONDS = (300.0, 900.0, 3600.0)
PULSE_DURATION_SECONDS = 3600.0
WARMUP_HOURS = 240
ROLLOUT_HOURS = 240
NEGATIVE_DISCHARGE_TOLERANCE_M3S = 1e-6
ZERO_IDENTITY_TOLERANCE_M3S = 1e-12
MASS_BALANCE_RELATIVE_TOLERANCE = 1e-6
MASS_BALANCE_ABSOLUTE_TOLERANCE_M3 = 1e-3
TIMESTEP_STABILITY_ABSOLUTE_TOLERANCE_SECONDS = 3600.0
TIMESTEP_STABILITY_RELATIVE_TOLERANCE = 0.10


@dataclass(frozen=True)
class _ParsedTrace:
    feature_ids: tuple[int, ...]
    downstream_feature_ids: tuple[int | None, ...]
    timestep_seconds: float
    geometry_identity: str
    boundary: np.ndarray
    lateral: np.ndarray
    routed: np.ndarray
    storage: np.ndarray
    initial_state: dict[str, Any]
    final_state: dict[str, Any]
    outlet_index: int
    public: dict[str, Any]


def evaluate_traditional_routing_conformance(
    evidence: Mapping[str, object],
) -> dict[str, Any]:
    """Recompute every dynamic gate from outcome-free candidate traces."""

    registration = _mapping(evidence.get("candidate_registration"))
    source_audit = _mapping(evidence.get("source_initialization_audit"))
    abi_audit = _mapping(evidence.get("abi_audit"))
    isolation = _mapping(evidence.get("data_isolation"))

    zero = _parse_trace(evidence.get("zero_input_trace"))
    cold_values = evidence.get("cold_process_traces")
    cold_items = cold_values if isinstance(cold_values, list) else []
    cold = [_parse_trace(value) for value in cold_items]
    restart = _mapping(evidence.get("restart_equivalence"))
    continuous = _parse_trace(restart.get("continuous_trace"))
    prefix = _parse_trace(restart.get("prefix_trace"))
    resumed = _parse_trace(restart.get("resumed_trace"))

    pulse_cases, pulse_matrix_complete = _evaluate_pulse_matrix(
        evidence.get("pulse_response_cases")
    )
    step_cases, step_matrix_complete = _evaluate_step_matrix(
        evidence.get("step_response_cases")
    )
    stability = _timestep_stability(pulse_cases)
    confluence = _evaluate_confluence(evidence.get("confluence_permutation"))

    all_case_traces_valid = bool(pulse_cases) and bool(step_cases) and all(
        case["pair_valid"] is True for case in pulse_cases + step_cases
    )
    all_case_values_finite = all(
        case["finite_states_and_outputs"] is True
        for case in pulse_cases + step_cases
    )
    all_responses_nonnegative = all(
        case["incremental_response_nonnegative"] is True
        for case in pulse_cases + step_cases
    )
    all_long_window_mass_passed = all(
        case["base_mass_balance_passed"] is True
        and case["perturbed_mass_balance_passed"] is True
        and case["incremental_mass_balance_passed"] is True
        for case in pulse_cases + step_cases
    )
    outcome_isolated = isolation == {
        "network_isolation_enforced": True,
        "observed_discharge_loaded": False,
        "observed_action_loaded": False,
        "observed_forcing_loaded": False,
        "score_report_loaded": False,
        "target_parameters_fitted": 0,
        "synthetic_inputs_only": True,
    }
    evidence_identity_valid = (
        evidence.get("schema")
        == TRADITIONAL_ROUTING_CONFORMANCE_EVIDENCE_SCHEMA
        and isinstance(evidence.get("candidate_id"), str)
        and bool(str(evidence.get("candidate_id")).strip())
    )
    gates = {
        "source_build_license_and_adapter_identities_match": (
            evidence_identity_valid
            and registration.get("identity_matches") is True
            and registration.get("candidate_registration_ready") is True
        ),
        "abi_signature_and_array_shape_contract_pass": (
            abi_audit.get("signature_matches_registered_adapter") is True
            and abi_audit.get("input_arrays_remain_read_only") is True
            and abi_audit.get("feature_and_time_axes_preserved") is True
            and all_case_traces_valid
        ),
        "all_required_carry_and_output_values_initialized_before_read": (
            source_audit.get("all_reads_dominated_by_assignment") is True
            and source_audit.get("uninitialized_read_check_passed") is True
            and source_audit.get("all_restart_state_variables_documented") is True
        ),
        "cold_process_repeats_are_bitwise_equal_on_the_frozen_platform": (
            len(cold) == 2
            and cold[0] is not None
            and cold[1] is not None
            and _traces_bitwise_equal(cold[0], cold[1])
        ),
        "continuous_and_restart_runs_are_bitwise_equal": _restart_matches(
            continuous,
            prefix,
            resumed,
        ),
        "zero_state_zero_boundary_zero_lateral_produces_zero_state_and_output": (
            _zero_identity_passed(zero)
        ),
        "all_impulse_and_step_states_and_outputs_are_finite": (
            pulse_matrix_complete
            and step_matrix_complete
            and all_case_values_finite
        ),
        "all_impulse_and_step_incremental_responses_are_nonnegative": (
            pulse_matrix_complete
            and step_matrix_complete
            and all_responses_nonnegative
        ),
        "timestep_response_quantiles_pass_frozen_stability_tolerances": (
            pulse_matrix_complete and stability["all_comparisons_passed"] is True
        ),
        "branching_dag_and_confluence_mass_accounting_pass": (
            confluence["topology_valid"] is True
            and confluence["all_mass_balances_passed"] is True
        ),
        "confluence_upstream_order_permutation_is_invariant": (
            confluence["permutation_invariant"] is True
        ),
        "long_window_input_equals_output_plus_storage_change": (
            pulse_matrix_complete
            and step_matrix_complete
            and all_long_window_mass_passed
        ),
        "no_observed_outcome_or_fitted_target_parameter_is_loaded": outcome_isolated,
    }
    passed = all(gates.values())
    return {
        "schema": TRADITIONAL_ROUTING_CONFORMANCE_REPORT_SCHEMA,
        "status": (
            "professional_traditional_routing_conformance_passed"
            if passed
            else "blocked_traditional_routing_conformance_failure"
        ),
        "candidate_id": evidence.get("candidate_id"),
        "evidence_schema_valid": evidence_identity_valid,
        "registered_protocol": {
            "background_flows_m3s": list(BACKGROUND_FLOWS_M3S),
            "pulse_rates_m3s": list(PULSE_RATES_M3S),
            "timesteps_seconds": list(TIMESTEPS_SECONDS),
            "pulse_duration_seconds": PULSE_DURATION_SECONDS,
            "warmup_hours": WARMUP_HOURS,
            "rollout_hours": ROLLOUT_HOURS,
            "pulse_case_count": 27,
            "step_case_count": 3,
        },
        "pulse_matrix_complete": pulse_matrix_complete,
        "step_matrix_complete": step_matrix_complete,
        "pulse_response_cases": pulse_cases,
        "step_response_cases": step_cases,
        "timestep_stability": stability,
        "confluence_permutation": confluence,
        "gates": gates,
        "all_mandatory_gates_passed": passed,
        "decision": {
            "professional_runtime_certified": passed,
            "matched_two_system_execution_permitted": passed,
            "runtime_admitted": passed,
            "runtime_default_enabled": False,
            "geospatial_kernel_validated": False,
        },
        "execution_boundary": {
            "outcome_values_loaded": False,
            "real_two_system_inputs_loaded": False,
            "candidate_parameters_fitted": False,
            "predictive_accuracy_scored": False,
        },
    }


def _parse_trace(value: object) -> _ParsedTrace | None:
    trace = _mapping(value)
    try:
        feature_values = trace.get("feature_ids")
        downstream_values = trace.get("downstream_feature_ids")
        if not isinstance(feature_values, list) or not isinstance(downstream_values, list):
            return None
        feature_ids = tuple(feature_values)
        downstream = tuple(downstream_values)
        if (
            not feature_ids
            or len(feature_ids) != len(downstream)
            or any(
                not isinstance(item, int) or isinstance(item, bool) or item <= 0
                for item in feature_ids
            )
            or len(feature_ids) != len(set(feature_ids))
            or any(item is not None and item not in feature_ids for item in downstream)
            or sum(item is None for item in downstream) != 1
            or not _directed_network_is_dag(feature_ids, downstream)
        ):
            return None
        timestep = float(trace.get("timestep_seconds"))
        boundary = np.asarray(trace.get("boundary_inflow_m3s"), dtype=np.float64)
        lateral = np.asarray(trace.get("lateral_inflow_m3s"), dtype=np.float64)
        routed = np.asarray(trace.get("routed_discharge_m3s"), dtype=np.float64)
        storage = np.asarray(trace.get("total_storage_m3"), dtype=np.float64)
        initial_state = trace.get("serialized_initial_state")
        final_state = trace.get("serialized_final_state")
        geometry_identity = trace.get("geometry_identity")
    except (TypeError, ValueError):
        return None
    count = len(feature_ids)
    if (
        not np.isfinite(timestep)
        or timestep <= 0.0
        or boundary.ndim != 2
        or boundary.shape[1:] != (count,)
        or boundary.shape != lateral.shape
        or boundary.shape != routed.shape
        or boundary.shape[0] == 0
        or storage.shape != (boundary.shape[0] + 1,)
        or not all(np.isfinite(item).all() for item in (boundary, lateral, routed, storage))
        or not isinstance(initial_state, dict)
        or not isinstance(final_state, dict)
        or not isinstance(geometry_identity, str)
        or not geometry_identity
    ):
        return None
    try:
        initial_state_sha256 = _json_sha256(initial_state)
        final_state_sha256 = _json_sha256(final_state)
    except (TypeError, ValueError):
        return None
    outlet_index = downstream.index(None)
    input_volume = (boundary.sum(axis=1) + lateral.sum(axis=1)) * timestep
    output_volume = routed[:, outlet_index] * timestep
    storage_change = np.diff(storage)
    residual = input_volume - output_volume - storage_change
    tolerance = MASS_BALANCE_ABSOLUTE_TOLERANCE_M3 + (
        MASS_BALANCE_RELATIVE_TOLERANCE
        * np.maximum.reduce(
            (
                np.abs(input_volume),
                np.abs(output_volume),
                np.abs(storage_change),
                np.ones_like(residual),
            )
        )
    )
    public = {
        "step_count": int(boundary.shape[0]),
        "feature_count": count,
        "timestep_seconds": timestep,
        "finite": True,
        "states_and_outputs_nonnegative": (
            float(min(boundary.min(), lateral.min(), routed.min(), storage.min()))
            >= -NEGATIVE_DISCHARGE_TOLERANCE_M3S
        ),
        "maximum_absolute_mass_residual_m3": float(np.abs(residual).max()),
        "maximum_mass_residual_to_tolerance_ratio": float(
            np.max(np.abs(residual) / tolerance)
        ),
        "mass_balance_passed": bool((np.abs(residual) <= tolerance).all()),
        "initial_state_sha256": initial_state_sha256,
        "final_state_sha256": final_state_sha256,
    }
    return _ParsedTrace(
        feature_ids=feature_ids,
        downstream_feature_ids=downstream,
        timestep_seconds=timestep,
        geometry_identity=geometry_identity,
        boundary=boundary,
        lateral=lateral,
        routed=routed,
        storage=storage,
        initial_state=initial_state,
        final_state=final_state,
        outlet_index=outlet_index,
        public=public,
    )


def _evaluate_pulse_matrix(value: object) -> tuple[list[dict[str, Any]], bool]:
    raw = value if isinstance(value, list) else []
    cases = [_evaluate_response_pair(item, excitation_kind="pulse") for item in raw]
    expected = set(product(BACKGROUND_FLOWS_M3S, PULSE_RATES_M3S, TIMESTEPS_SECONDS))
    actual = {
        (
            item["background_flow_m3s"],
            item["perturbation_rate_m3s"],
            item["timestep_seconds"],
        )
        for item in cases
        if item["metadata_valid"] is True
    }
    return cases, len(cases) == len(expected) and actual == expected


def _evaluate_step_matrix(value: object) -> tuple[list[dict[str, Any]], bool]:
    raw = value if isinstance(value, list) else []
    cases = [_evaluate_response_pair(item, excitation_kind="step") for item in raw]
    expected = {(2.0, 10.0, timestep) for timestep in TIMESTEPS_SECONDS}
    actual = {
        (
            item["background_flow_m3s"],
            item["perturbation_rate_m3s"],
            item["timestep_seconds"],
        )
        for item in cases
        if item["metadata_valid"] is True
    }
    return cases, len(cases) == len(expected) and actual == expected


def _evaluate_response_pair(
    value: object,
    *,
    excitation_kind: str,
) -> dict[str, Any]:
    case = _mapping(value)
    base = _parse_trace(case.get("base_trace"))
    perturbed = _parse_trace(case.get("perturbed_trace"))
    background = _finite_float(case.get("background_flow_m3s"))
    perturbation = _finite_float(case.get("perturbation_rate_m3s"))
    timestep = _finite_float(case.get("timestep_seconds"))
    metadata_valid = (
        case.get("excitation_kind") == excitation_kind
        and case.get("warmup_hours") == WARMUP_HOURS
        and case.get("rollout_hours") == ROLLOUT_HOURS
        and background is not None
        and perturbation is not None
        and timestep is not None
        and background >= 0.0
        and perturbation > 0.0
        and timestep in TIMESTEPS_SECONDS
    )
    pair_valid = (
        metadata_valid
        and base is not None
        and perturbed is not None
        and _trace_contract_equal(base, perturbed)
        and base.timestep_seconds == timestep
        and base.boundary.shape[0] == round(ROLLOUT_HOURS * 3600.0 / timestep)
        and base.initial_state == perturbed.initial_state
        and np.array_equal(base.storage[:1], perturbed.storage[:1])
    )
    result: dict[str, Any] = {
        "case_id": case.get("case_id"),
        "excitation_kind": excitation_kind,
        "background_flow_m3s": background,
        "perturbation_rate_m3s": perturbation,
        "timestep_seconds": timestep,
        "metadata_valid": metadata_valid,
        "pair_valid": pair_valid,
        "finite_states_and_outputs": False,
        "incremental_response_nonnegative": False,
        "base_mass_balance_passed": False,
        "perturbed_mass_balance_passed": False,
        "incremental_mass_balance_passed": False,
        "response_metrics": None,
    }
    if not pair_valid or base is None or perturbed is None or timestep is None:
        return result
    base_input_rate = base.boundary.sum(axis=1) + base.lateral.sum(axis=1)
    input_difference = (
        perturbed.boundary.sum(axis=1)
        + perturbed.lateral.sum(axis=1)
        - base_input_rate
    )
    expected_difference = np.full(base.boundary.shape[0], perturbation, dtype=float)
    if excitation_kind == "pulse":
        expected_difference[round(PULSE_DURATION_SECONDS / timestep) :] = 0.0
    input_semantics_valid = bool(
        np.allclose(base_input_rate, background, rtol=0.0, atol=1e-12)
        and np.allclose(input_difference, expected_difference, rtol=0.0, atol=1e-12)
    )
    response = (
        perturbed.routed[:, perturbed.outlet_index]
        - base.routed[:, base.outlet_index]
    )
    input_volume = float(input_difference.sum() * timestep)
    final_incremental_storage = float(perturbed.storage[-1] - base.storage[-1])
    incremental_residual = float(
        input_volume - response.sum() * timestep - final_incremental_storage
    )
    incremental_tolerance = MASS_BALANCE_ABSOLUTE_TOLERANCE_M3 + (
        MASS_BALANCE_RELATIVE_TOLERANCE
        * max(
            abs(input_volume),
            abs(float(response.sum() * timestep)),
            abs(final_incremental_storage),
            1.0,
        )
    )
    result.update(
        {
            "pair_valid": input_semantics_valid,
            "finite_states_and_outputs": (
                base.public["finite"] is True
                and perturbed.public["finite"] is True
                and base.public["states_and_outputs_nonnegative"] is True
                and perturbed.public["states_and_outputs_nonnegative"] is True
            ),
            "incremental_response_nonnegative": (
                float(response.min()) >= -NEGATIVE_DISCHARGE_TOLERANCE_M3S
            ),
            "base_mass_balance_passed": base.public["mass_balance_passed"],
            "perturbed_mass_balance_passed": perturbed.public[
                "mass_balance_passed"
            ],
            "incremental_mass_balance_residual_m3": incremental_residual,
            "incremental_mass_balance_tolerance_m3": incremental_tolerance,
            "incremental_mass_balance_passed": (
                abs(incremental_residual) <= incremental_tolerance
            ),
        }
    )
    if excitation_kind == "pulse" and input_semantics_valid:
        result["response_metrics"] = analyze_dynamic_transfer_response(
            response,
            timestep_seconds=timestep,
            input_volume_m3=input_volume,
            final_incremental_storage_m3=final_incremental_storage,
            absolute_mass_tolerance_m3=MASS_BALANCE_ABSOLUTE_TOLERANCE_M3,
            relative_mass_tolerance=MASS_BALANCE_RELATIVE_TOLERANCE,
            negative_lobe_relative_tolerance=0.0,
        ).as_dict()
    return result


def _timestep_stability(cases: list[dict[str, Any]]) -> dict[str, Any]:
    comparisons: list[dict[str, Any]] = []
    by_key = {
        (
            item["background_flow_m3s"],
            item["perturbation_rate_m3s"],
            item["timestep_seconds"],
        ): item
        for item in cases
    }
    for background, pulse in product(BACKGROUND_FLOWS_M3S, PULSE_RATES_M3S):
        reference = by_key.get((background, pulse, TIMESTEPS_SECONDS[0]), {})
        reference_metrics = _mapping(reference.get("response_metrics"))
        reference_quantiles = _mapping(
            reference_metrics.get("input_recovery_quantile_seconds")
        )
        for timestep in TIMESTEPS_SECONDS[1:]:
            candidate = by_key.get((background, pulse, timestep), {})
            candidate_metrics = _mapping(candidate.get("response_metrics"))
            candidate_quantiles = _mapping(
                candidate_metrics.get("input_recovery_quantile_seconds")
            )
            for quantile in ("t05", "t50", "t95"):
                reference_time = _finite_float(reference_quantiles.get(quantile))
                candidate_time = _finite_float(candidate_quantiles.get(quantile))
                tolerance = (
                    None
                    if reference_time is None
                    else max(
                        TIMESTEP_STABILITY_ABSOLUTE_TOLERANCE_SECONDS,
                        TIMESTEP_STABILITY_RELATIVE_TOLERANCE * reference_time,
                    )
                )
                difference = (
                    None
                    if reference_time is None or candidate_time is None
                    else abs(candidate_time - reference_time)
                )
                comparisons.append(
                    {
                        "background_flow_m3s": background,
                        "perturbation_rate_m3s": pulse,
                        "reference_timestep_seconds": TIMESTEPS_SECONDS[0],
                        "candidate_timestep_seconds": timestep,
                        "quantile": quantile,
                        "absolute_difference_seconds": difference,
                        "tolerance_seconds": tolerance,
                        "passed": (
                            difference is not None
                            and tolerance is not None
                            and difference <= tolerance
                        ),
                    }
                )
    return {
        "comparison_count": len(comparisons),
        "comparisons": comparisons,
        "all_comparisons_passed": (
            len(comparisons) == 54 and all(item["passed"] for item in comparisons)
        ),
    }


def _evaluate_confluence(value: object) -> dict[str, Any]:
    record = _mapping(value)
    original = _parse_trace(record.get("original_trace"))
    permuted = _parse_trace(record.get("permuted_trace"))
    topology_valid = (
        original is not None
        and permuted is not None
        and len(original.feature_ids) == 3
        and len(permuted.feature_ids) == 3
        and set(original.feature_ids) == set(permuted.feature_ids)
        and _confluence_count(original) == 1
        and _confluence_count(permuted) == 1
        and _topology_by_feature(original) == _topology_by_feature(permuted)
        and _same_inputs_by_feature(original, permuted)
    )
    mass_passed = (
        topology_valid
        and original is not None
        and permuted is not None
        and original.public["mass_balance_passed"] is True
        and permuted.public["mass_balance_passed"] is True
    )
    invariant = (
        topology_valid
        and original is not None
        and permuted is not None
        and np.array_equal(
            original.routed[:, original.outlet_index],
            permuted.routed[:, permuted.outlet_index],
        )
        and np.array_equal(original.storage, permuted.storage)
        and original.final_state == permuted.final_state
    )
    return {
        "topology_valid": topology_valid,
        "all_mass_balances_passed": mass_passed,
        "permutation_invariant": invariant,
        "original_trace": None if original is None else original.public,
        "permuted_trace": None if permuted is None else permuted.public,
    }


def _restart_matches(
    continuous: _ParsedTrace | None,
    prefix: _ParsedTrace | None,
    resumed: _ParsedTrace | None,
) -> bool:
    if continuous is None or prefix is None or resumed is None:
        return False
    if not _trace_contract_equal(continuous, prefix) or not _trace_contract_equal(
        continuous, resumed
    ):
        return False
    return bool(
        prefix.final_state == resumed.initial_state
        and continuous.initial_state == prefix.initial_state
        and continuous.final_state == resumed.final_state
        and continuous.boundary.shape[0]
        == prefix.boundary.shape[0] + resumed.boundary.shape[0]
        and np.array_equal(
            continuous.boundary,
            np.concatenate((prefix.boundary, resumed.boundary)),
        )
        and np.array_equal(
            continuous.lateral,
            np.concatenate((prefix.lateral, resumed.lateral)),
        )
        and np.array_equal(
            continuous.routed,
            np.concatenate((prefix.routed, resumed.routed)),
        )
        and np.array_equal(
            continuous.storage,
            np.concatenate((prefix.storage, resumed.storage[1:])),
        )
    )


def _zero_identity_passed(trace: _ParsedTrace | None) -> bool:
    if trace is None:
        return False
    return bool(
        np.max(np.abs(trace.boundary)) <= ZERO_IDENTITY_TOLERANCE_M3S
        and np.max(np.abs(trace.lateral)) <= ZERO_IDENTITY_TOLERANCE_M3S
        and np.max(np.abs(trace.routed)) <= ZERO_IDENTITY_TOLERANCE_M3S
        and np.max(np.abs(trace.storage)) <= MASS_BALANCE_ABSOLUTE_TOLERANCE_M3
        and trace.public["mass_balance_passed"] is True
    )


def _traces_bitwise_equal(first: _ParsedTrace, second: _ParsedTrace) -> bool:
    return bool(
        _trace_contract_equal(first, second)
        and np.array_equal(first.boundary, second.boundary)
        and np.array_equal(first.lateral, second.lateral)
        and np.array_equal(first.routed, second.routed)
        and np.array_equal(first.storage, second.storage)
        and first.initial_state == second.initial_state
        and first.final_state == second.final_state
    )


def _trace_contract_equal(first: _ParsedTrace, second: _ParsedTrace) -> bool:
    return (
        first.feature_ids == second.feature_ids
        and first.downstream_feature_ids == second.downstream_feature_ids
        and first.timestep_seconds == second.timestep_seconds
        and first.geometry_identity == second.geometry_identity
    )


def _confluence_count(trace: _ParsedTrace) -> int:
    counts = {feature_id: 0 for feature_id in trace.feature_ids}
    for target in trace.downstream_feature_ids:
        if target is not None:
            counts[target] += 1
    return sum(count > 1 for count in counts.values())


def _directed_network_is_dag(
    feature_ids: tuple[int, ...],
    downstream_feature_ids: tuple[int | None, ...],
) -> bool:
    index = {feature_id: offset for offset, feature_id in enumerate(feature_ids)}
    indegree = [0] * len(feature_ids)
    for source, target in zip(feature_ids, downstream_feature_ids, strict=True):
        if source == target:
            return False
        if target is not None:
            indegree[index[target]] += 1
    ready = [offset for offset, degree in enumerate(indegree) if degree == 0]
    visited = 0
    while ready:
        source_index = ready.pop()
        visited += 1
        target = downstream_feature_ids[source_index]
        if target is not None:
            target_index = index[target]
            indegree[target_index] -= 1
            if indegree[target_index] == 0:
                ready.append(target_index)
    return visited == len(feature_ids)


def _topology_by_feature(trace: _ParsedTrace) -> dict[int, int | None]:
    return dict(
        zip(trace.feature_ids, trace.downstream_feature_ids, strict=True)
    )


def _same_inputs_by_feature(first: _ParsedTrace, second: _ParsedTrace) -> bool:
    if first.boundary.shape[0] != second.boundary.shape[0]:
        return False
    first_index = {feature_id: index for index, feature_id in enumerate(first.feature_ids)}
    second_index = {
        feature_id: index for index, feature_id in enumerate(second.feature_ids)
    }
    return all(
        np.array_equal(
            first.boundary[:, first_index[feature_id]],
            second.boundary[:, second_index[feature_id]],
        )
        and np.array_equal(
            first.lateral[:, first_index[feature_id]],
            second.lateral[:, second_index[feature_id]],
        )
        for feature_id in first.feature_ids
    )


def _json_sha256(value: dict[str, Any]) -> str:
    body = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None
