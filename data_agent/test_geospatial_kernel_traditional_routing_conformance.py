from __future__ import annotations

from copy import deepcopy
from itertools import product

import numpy as np

from data_agent.uwm.geospatial_kernel_v2.traditional_routing_conformance import (
    BACKGROUND_FLOWS_M3S,
    PULSE_RATES_M3S,
    ROLLOUT_HOURS,
    TIMESTEPS_SECONDS,
    TRADITIONAL_ROUTING_CONFORMANCE_EVIDENCE_SCHEMA,
    WARMUP_HOURS,
    evaluate_traditional_routing_conformance,
)


def test_complete_synthetic_fixture_passes_without_claiming_gk_validation() -> None:
    report = evaluate_traditional_routing_conformance(_passing_evidence())

    assert report["status"] == "professional_traditional_routing_conformance_passed"
    assert report["pulse_matrix_complete"] is True
    assert report["step_matrix_complete"] is True
    assert report["timestep_stability"]["comparison_count"] == 54
    assert report["timestep_stability"]["all_comparisons_passed"] is True
    assert all(report["gates"].values())
    assert report["decision"] == {
        "professional_runtime_certified": True,
        "matched_two_system_execution_permitted": True,
        "runtime_admitted": True,
        "runtime_default_enabled": False,
        "geospatial_kernel_validated": False,
    }
    assert report["execution_boundary"]["outcome_values_loaded"] is False
    assert report["execution_boundary"]["real_two_system_inputs_loaded"] is False


def test_negative_lobe_fails_even_when_candidate_trace_is_finite() -> None:
    evidence = _passing_evidence()
    case = evidence["pulse_response_cases"][0]
    case["perturbed_trace"]["routed_discharge_m3s"][20][-1] = (
        case["base_trace"]["routed_discharge_m3s"][20][-1] - 0.01
    )
    _repair_storage_for_mass(case["perturbed_trace"])

    report = evaluate_traditional_routing_conformance(evidence)

    assert report["gates"][
        "all_impulse_and_step_incremental_responses_are_nonnegative"
    ] is False
    assert report["all_mandatory_gates_passed"] is False
    assert report["decision"]["runtime_admitted"] is False


def test_hidden_volume_creation_fails_step_and_long_window_mass_gates() -> None:
    evidence = _passing_evidence()
    trace = evidence["step_response_cases"][0]["perturbed_trace"]
    trace["routed_discharge_m3s"][10][-1] += 2.0

    report = evaluate_traditional_routing_conformance(evidence)

    assert report["gates"]["long_window_input_equals_output_plus_storage_change"] is False
    assert report["all_mandatory_gates_passed"] is False


def test_restart_state_or_confluence_order_drift_fails_closed() -> None:
    evidence = _passing_evidence()
    evidence["restart_equivalence"]["resumed_trace"]["serialized_initial_state"] = {
        "step": 99
    }
    evidence["confluence_permutation"]["permuted_trace"][
        "routed_discharge_m3s"
    ][2][-1] += 0.5

    report = evaluate_traditional_routing_conformance(evidence)

    assert report["gates"]["continuous_and_restart_runs_are_bitwise_equal"] is False
    assert report["gates"]["confluence_upstream_order_permutation_is_invariant"] is False
    assert report["decision"]["matched_two_system_execution_permitted"] is False


def test_outcome_exposure_or_incomplete_matrix_cannot_be_waived() -> None:
    evidence = _passing_evidence()
    evidence["pulse_response_cases"].pop()
    evidence["data_isolation"]["score_report_loaded"] = True

    report = evaluate_traditional_routing_conformance(evidence)

    assert report["pulse_matrix_complete"] is False
    assert report["gates"][
        "no_observed_outcome_or_fitted_target_parameter_is_loaded"
    ] is False
    assert report["all_mandatory_gates_passed"] is False


def test_network_isolation_is_a_mandatory_outcome_isolation_gate() -> None:
    evidence = _passing_evidence()
    evidence["data_isolation"]["network_isolation_enforced"] = False

    report = evaluate_traditional_routing_conformance(evidence)

    assert report["gates"][
        "no_observed_outcome_or_fitted_target_parameter_is_loaded"
    ] is False
    assert report["decision"]["professional_runtime_certified"] is False


def _passing_evidence() -> dict[str, object]:
    cold = _identity_trace(
        feature_ids=(1, 2),
        downstream=(2, None),
        timestep_seconds=300.0,
        boundary_rates=np.full(12, 2.0),
        initial_step=0,
    )
    continuous = _identity_trace(
        feature_ids=(1, 2),
        downstream=(2, None),
        timestep_seconds=300.0,
        boundary_rates=np.arange(1.0, 11.0),
        initial_step=0,
    )
    prefix = _identity_trace(
        feature_ids=(1, 2),
        downstream=(2, None),
        timestep_seconds=300.0,
        boundary_rates=np.arange(1.0, 5.0),
        initial_step=0,
    )
    resumed = _identity_trace(
        feature_ids=(1, 2),
        downstream=(2, None),
        timestep_seconds=300.0,
        boundary_rates=np.arange(5.0, 11.0),
        initial_step=4,
    )
    pulse_cases = [
        _response_case(background, pulse, timestep, "pulse")
        for background, pulse, timestep in product(
            BACKGROUND_FLOWS_M3S,
            PULSE_RATES_M3S,
            TIMESTEPS_SECONDS,
        )
    ]
    step_cases = [
        _response_case(2.0, 10.0, timestep, "step")
        for timestep in TIMESTEPS_SECONDS
    ]
    return {
        "schema": TRADITIONAL_ROUTING_CONFORMANCE_EVIDENCE_SCHEMA,
        "candidate_id": "synthetic-test-double-not-a-professional-runtime",
        "candidate_registration": {
            "identity_matches": True,
            "candidate_registration_ready": True,
        },
        "source_initialization_audit": {
            "all_reads_dominated_by_assignment": True,
            "uninitialized_read_check_passed": True,
            "all_restart_state_variables_documented": True,
        },
        "abi_audit": {
            "signature_matches_registered_adapter": True,
            "input_arrays_remain_read_only": True,
            "feature_and_time_axes_preserved": True,
        },
        "data_isolation": {
            "network_isolation_enforced": True,
            "observed_discharge_loaded": False,
            "observed_action_loaded": False,
            "observed_forcing_loaded": False,
            "score_report_loaded": False,
            "target_parameters_fitted": 0,
            "synthetic_inputs_only": True,
        },
        "zero_input_trace": _identity_trace(
            feature_ids=(1,),
            downstream=(None,),
            timestep_seconds=300.0,
            boundary_rates=np.zeros(12),
            initial_step=0,
        ),
        "cold_process_traces": [deepcopy(cold), deepcopy(cold)],
        "restart_equivalence": {
            "continuous_trace": continuous,
            "prefix_trace": prefix,
            "resumed_trace": resumed,
        },
        "pulse_response_cases": pulse_cases,
        "step_response_cases": step_cases,
        "confluence_permutation": {
            "original_trace": _confluence_trace((1, 2, 3)),
            "permuted_trace": _confluence_trace((2, 1, 3)),
        },
    }


def _response_case(
    background: float,
    perturbation: float,
    timestep: float,
    excitation_kind: str,
) -> dict[str, object]:
    step_count = round(ROLLOUT_HOURS * 3600.0 / timestep)
    base = np.full(step_count, background)
    perturbed = base.copy()
    if excitation_kind == "pulse":
        perturbed[: round(3600.0 / timestep)] += perturbation
    else:
        perturbed += perturbation
    return {
        "case_id": f"{excitation_kind}:q{background}:p{perturbation}:dt{timestep}",
        "excitation_kind": excitation_kind,
        "background_flow_m3s": background,
        "perturbation_rate_m3s": perturbation,
        "timestep_seconds": timestep,
        "warmup_hours": WARMUP_HOURS,
        "rollout_hours": ROLLOUT_HOURS,
        "base_trace": _identity_trace(
            feature_ids=(1,),
            downstream=(None,),
            timestep_seconds=timestep,
            boundary_rates=base,
            initial_step=0,
            initial_state={"background_flow_m3s": background},
        ),
        "perturbed_trace": _identity_trace(
            feature_ids=(1,),
            downstream=(None,),
            timestep_seconds=timestep,
            boundary_rates=perturbed,
            initial_step=0,
            initial_state={"background_flow_m3s": background},
        ),
    }


def _identity_trace(
    *,
    feature_ids: tuple[int, ...],
    downstream: tuple[int | None, ...],
    timestep_seconds: float,
    boundary_rates: np.ndarray,
    initial_step: int,
    initial_state: dict[str, object] | None = None,
) -> dict[str, object]:
    count = len(feature_ids)
    boundary = np.zeros((len(boundary_rates), count), dtype=float)
    routed = np.zeros_like(boundary)
    boundary[:, 0] = boundary_rates
    routed[:] = boundary_rates[:, None]
    state = initial_state or {"step": initial_step}
    final = (
        {"step": initial_step + len(boundary_rates)}
        if initial_state is None
        else dict(initial_state)
    )
    return {
        "feature_ids": list(feature_ids),
        "downstream_feature_ids": list(downstream),
        "timestep_seconds": timestep_seconds,
        "geometry_identity": "synthetic-identity-router-fixture",
        "boundary_inflow_m3s": boundary.tolist(),
        "lateral_inflow_m3s": np.zeros_like(boundary).tolist(),
        "routed_discharge_m3s": routed.tolist(),
        "total_storage_m3": np.zeros(len(boundary_rates) + 1).tolist(),
        "serialized_initial_state": dict(state),
        "serialized_final_state": final,
    }


def _confluence_trace(feature_ids: tuple[int, int, int]) -> dict[str, object]:
    source_a, source_b, outlet = feature_ids
    steps = 8
    boundary = np.zeros((steps, 3), dtype=float)
    source_rates = {
        1: np.arange(1.0, steps + 1.0),
        2: np.full(steps, 2.0),
    }
    boundary[:, 0] = source_rates[source_a]
    boundary[:, 1] = source_rates[source_b]
    routed = boundary.copy()
    routed[:, 2] = boundary[:, 0] + boundary[:, 1]
    return {
        "feature_ids": list(feature_ids),
        "downstream_feature_ids": [outlet, outlet, None],
        "timestep_seconds": 300.0,
        "geometry_identity": "synthetic-two-to-one-confluence",
        "boundary_inflow_m3s": boundary.tolist(),
        "lateral_inflow_m3s": np.zeros_like(boundary).tolist(),
        "routed_discharge_m3s": routed.tolist(),
        "total_storage_m3": np.zeros(steps + 1).tolist(),
        "serialized_initial_state": {"storage_m3": 0.0},
        "serialized_final_state": {"storage_m3": 0.0},
        "source_ids": [source_a, source_b],
    }


def _repair_storage_for_mass(trace: dict[str, object]) -> None:
    boundary = np.asarray(trace["boundary_inflow_m3s"], dtype=float)
    lateral = np.asarray(trace["lateral_inflow_m3s"], dtype=float)
    routed = np.asarray(trace["routed_discharge_m3s"], dtype=float)
    timestep = float(trace["timestep_seconds"])
    delta = (boundary.sum(axis=1) + lateral.sum(axis=1) - routed[:, -1]) * timestep
    trace["total_storage_m3"] = np.concatenate(([0.0], np.cumsum(delta))).tolist()
