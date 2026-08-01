from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    public_reach_local_perturbation as perturbation,
)


def _audit():
    return perturbation.compile_public_reach_local_perturbation_audit()


def test_stage26_anchors_twenty_observations_to_declared_synthetic_patterns():
    value = _audit()

    assert len(value.perturbations) == 20
    for item in value.perturbations:
        assert item.input_state.area_m2 == pytest.approx(
            tuple(item.anchor_area_m2 * value for value in (1.05, 1.0, 0.95, 1.0))
        )
        assert item.input_state.discharge_m3s == pytest.approx(
            tuple(
                item.anchor_discharge_m3s * value
                for value in (1.0, 1.05, 1.0, 0.95)
            )
        )
        assert item.reversed_input_state.area_m2 == (
            item.input_state.area_m2[2:] + item.input_state.area_m2[:2]
        )


def test_stage26_uses_shared_stable_timestep_and_respects_cfl():
    value = _audit()

    for item in value.perturbations:
        rectangle = item.state_conditioned_rectangle
        candidate = item.bridge_trapezoid_candidate
        assert item.shared_timestep_seconds == min(
            rectangle.geometry_stable_timestep_seconds,
            candidate.geometry_stable_timestep_seconds,
        )
        assert rectangle.forward.maximum_courant_number <= 0.4 + 1e-12
        assert candidate.forward.maximum_courant_number <= 0.4 + 1e-12


def test_stage26_periodic_steps_conserve_mass_and_momentum():
    value = _audit()

    for item in value.perturbations:
        for step in (
            item.state_conditioned_rectangle,
            item.bridge_trapezoid_candidate,
        ):
            assert step.forward.volume_balance_error_m3 == pytest.approx(
                0.0, abs=1e-10
            )
            assert (
                step.forward.discharge_integral_balance_error_m4s
                == pytest.approx(0.0, abs=1e-10)
            )
            assert step.forward.minimum_area_m2 > 0.0
            assert step.forward.finite_state is True


def test_stage26_perturbation_reversal_is_exactly_translation_covariant():
    value = _audit()

    for item in value.perturbations:
        for step in (
            item.state_conditioned_rectangle,
            item.bridge_trapezoid_candidate,
        ):
            assert step.reversal_area_covariance_error_m2 == 0.0
            assert step.reversal_discharge_covariance_error_m3s == 0.0


def test_stage26_geometry_difference_propagates_into_one_step_state():
    report = _audit().as_dict()
    distributions = report["response_distributions"]

    assert distributions["shared_timestep_seconds"]["minimum"] == pytest.approx(
        5.040041865848004
    )
    assert distributions["shared_timestep_seconds"]["maximum"] == pytest.approx(
        8.578232202780596
    )
    assert distributions["maximum_area_geometry_response_relative"][
        "maximum"
    ] == pytest.approx(0.0009066378095856008)
    assert distributions["maximum_discharge_geometry_response_relative"][
        "median"
    ] == pytest.approx(0.00788003566391872)
    assert distributions["maximum_discharge_geometry_response_relative"][
        "maximum"
    ] == pytest.approx(0.046401506602369795)
    assert report[
        "transition_response_is_material_for_at_least_one_anchor"
    ] is True
    assert report["limiting_geometry_counts"] == {
        "stage24_bridge_trapezoid_candidate": 15,
        "state_conditioned_observed_rectangle": 5,
    }


def test_stage26_claim_boundaries_reject_observed_or_runtime_relabeling():
    value = _audit()
    report = value.as_dict()

    with pytest.raises(
        ValueError, match="public_reach_local_perturbation_is_manufactured"
    ):
        value.require_observed_spatial_rollout()
    with pytest.raises(
        ValueError, match="public_reach_local_perturbation_grid_is_numerical"
    ):
        value.require_real_reach_discretization()
    with pytest.raises(
        ValueError, match="public_reach_local_perturbation_operator_unadmitted"
    ):
        value.require_runtime_operator()
    assert report["perturbation_contract"]["anchor_state_observed"] is True
    assert report["perturbation_contract"]["perturbed_states_observed"] is False
    assert report["claim_boundary"][
        "periodic_ring_represents_real_reach"
    ] is False
    assert report["decision"]["operator_admitted"] is False


def test_compiled_stage26_report_passes_without_real_reach_admission():
    from scripts import (
        compile_geotransport_stage26_public_local_perturbation_gates as gates,
    )

    report = gates.compile_report()

    assert report["all_gates_passed"] is True
    assert len(report["gates"]) == 20
    assert all(report["gates"].values())
    assert report["decision"]["local_hll_transition_exercised"] is True
    assert report["decision"]["periodic_mass_and_momentum_conserved"] is True
    assert report["decision"]["observed_spatial_rollout_completed"] is False
    assert report["decision"]["real_reach_grid_admitted"] is False
    assert report["decision"]["operator_admitted"] is False
