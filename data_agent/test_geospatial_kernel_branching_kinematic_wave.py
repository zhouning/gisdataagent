from __future__ import annotations

import numpy as np
import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    ActionBoundaryFlux,
    BranchingFiniteVolumeKinematicWaveOperator,
    BranchingKinematicWaveConfig,
    DirectedReachNetwork,
    ForcingFlux,
    ReachForcingSupport,
    ReachHydraulicGeometry,
)


def _network(*, partial_outlet: bool = False) -> DirectedReachNetwork:
    return DirectedReachNetwork(
        network_id="branching-kw-test",
        feature_ids=(30, 10, 20),
        downstream_feature_ids=(None, 30, 30),
        full_lengths_m=(2000.0, 1000.0, 1000.0),
        effective_lengths_m=(
            1000.0 if partial_outlet else 2000.0,
            1000.0,
            1000.0,
        ),
        action_entry_feature_ids=(10, 20),
        provenance_id="branching-kw-test:network",
        evidence_level="derived",
        admitted=True,
    )


def _geometry() -> ReachHydraulicGeometry:
    return ReachHydraulicGeometry(
        feature_ids=(30, 10, 20),
        bottom_width_m=(10.0, 10.0, 10.0),
        side_slope_horizontal_per_vertical=(2.0, 2.0, 2.0),
        bed_slope=(0.002, 0.002, 0.002),
        manning_n=(0.035, 0.035, 0.035),
        provenance_id="branching-kw-test:geometry",
        evidence_level="derived",
        admitted_as_hydraulic_geometry=True,
    )


def _operator(
    *, partial_outlet: bool = False, admitted: bool = False
) -> BranchingFiniteVolumeKinematicWaveOperator:
    return BranchingFiniteVolumeKinematicWaveOperator(
        _network(partial_outlet=partial_outlet),
        _geometry(),
        BranchingKinematicWaveConfig(
            timestep_seconds=600.0,
            target_cell_length_m=500.0,
            cfl_number=0.8,
            operator_form_admitted=admitted,
            allow_unadmitted_components_for_diagnostics=not admitted,
        ),
    )


def test_branching_kinematic_wave_compiles_stable_cell_and_confluence_axes() -> None:
    operator = _operator()
    state = operator.zero_state(provenance_id="branching-kw-test:zero")

    assert operator.network.topological_feature_ids == (10, 20, 30)
    assert operator.reach_cell_counts == (4, 2, 2)
    assert state.cell_feature_ids == (30, 30, 30, 30, 10, 10, 20, 20)
    assert state.cell_index_within_reach == (0, 1, 2, 3, 0, 1, 0, 1)
    assert operator.upstream_reach_indices == ((1, 2), (), ())


def test_branching_kinematic_wave_preserves_uniform_confluence_flow() -> None:
    operator = _operator()
    state = operator.discharge_state(
        (3.0, 1.0, 2.0), provenance_id="branching-kw-test:steady"
    )
    result = operator.step(
        state,
        action=ActionBoundaryFlux(
            (0.0, 1.0, 2.0), "m3 s-1", "branching-kw-test:action"
        ),
        provenance_id="branching-kw-test:steady:step",
    )

    assert result.next_state.cell_volume_m3 == pytest.approx(
        state.cell_volume_m3, rel=1e-11, abs=1e-8
    )
    assert result.reach_mean_outflow_m3s == pytest.approx((3.0, 1.0, 2.0))
    assert result.action_input_volume_m3 == 1800.0
    assert result.final_network_storage_m3 + result.outlet_volume_m3 == (
        pytest.approx(result.initial_network_storage_m3 + 1800.0)
    )
    assert result.maximum_courant_number <= 0.8 + 1e-12
    assert result.diagnostic_only is True


def test_branching_kinematic_wave_cold_start_is_positive_and_conservative() -> None:
    operator = _operator()
    result = operator.step(
        operator.zero_state(provenance_id="branching-kw-test:zero"),
        action=ActionBoundaryFlux(
            (0.0, 1.0, 0.0), "m3 s-1", "branching-kw-test:action"
        ),
        forcing=ForcingFlux(
            (0.0, 0.0, 2.0),
            "m3 s-1",
            "branching-kw-test:q-lateral",
            modeled=True,
        ),
        provenance_id="branching-kw-test:cold:step",
    )

    volume = np.asarray(result.next_state.cell_volume_m3)
    assert (volume >= 0.0).all()
    assert result.action_input_volume_m3 == 600.0
    assert result.distributed_forcing_volume_m3 == 1200.0
    assert result.final_network_storage_m3 + result.outlet_volume_m3 == (
        pytest.approx(1800.0, abs=result.numeric_mass_tolerance_m3)
    )
    assert abs(result.global_mass_balance_residual_m3) <= (
        result.numeric_mass_tolerance_m3
    )
    assert result.maximum_courant_number <= 0.8 + 1e-12
    assert result.independent_end_to_end_prediction is True


def test_branching_kinematic_wave_partial_forcing_requires_admitted_support() -> None:
    operator = _operator(partial_outlet=True)
    forcing = ForcingFlux(
        (1.0, 0.0, 0.0),
        "m3 s-1",
        "branching-kw-test:q-lateral",
        modeled=True,
    )
    state = operator.zero_state(provenance_id="branching-kw-test:zero")
    with pytest.raises(
        ValueError, match="branching_kinematic_unadmitted_component_not_allowed"
    ):
        BranchingFiniteVolumeKinematicWaveOperator(
            _network(partial_outlet=True),
            _geometry(),
            BranchingKinematicWaveConfig(
                timestep_seconds=600.0,
                target_cell_length_m=500.0,
                operator_form_admitted=True,
            ),
        ).step(
            state,
            forcing=forcing,
            provenance_id="branching-kw-test:unsupported",
        )

    support = ReachForcingSupport(
        feature_ids=(30, 10, 20),
        coverage_fractions=(0.5, 1.0, 1.0),
        support_method="synthetic-length-fraction",
        provenance_id="branching-kw-test:support",
        evidence_level="derived",
        admitted_as_spatial_support=True,
    )
    admitted = _operator(partial_outlet=True, admitted=True)
    result = admitted.step(
        admitted.zero_state(provenance_id="branching-kw-test:zero"),
        forcing=forcing,
        forcing_support=support,
        provenance_id="branching-kw-test:supported",
    )

    assert result.distributed_forcing_volume_m3 == 300.0
    assert result.forcing_support_admitted is True
    assert result.branching_kinematic_wave_admitted is True
    assert result.diagnostic_only is False


def test_branching_kinematic_wave_rejects_action_outside_declared_entry() -> None:
    operator = _operator()
    with pytest.raises(ValueError, match="branching_kinematic_action_outside_entry"):
        operator.step(
            operator.zero_state(provenance_id="branching-kw-test:zero"),
            action=ActionBoundaryFlux(
                (1.0, 0.0, 0.0),
                "m3 s-1",
                "branching-kw-test:bad-action",
            ),
            provenance_id="branching-kw-test:bad-action:step",
        )
