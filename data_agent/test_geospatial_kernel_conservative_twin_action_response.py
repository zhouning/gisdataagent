from datetime import UTC, datetime, timedelta

import pytest

from data_agent.uwm.geospatial_kernel_v2.branching_network import (
    BranchingManningNetworkTransportOperator,
    BranchingNetworkTransportConfig,
    DirectedReachNetwork,
)
from data_agent.uwm.geospatial_kernel_v2.conservative_twin_action_response import (
    ConservativeTwinActionStepInput,
    ConservativeTwinManningActionResponseKernel,
)
from data_agent.uwm.geospatial_kernel_v2.contracts import (
    ActionBoundaryFlux,
    ForcingFlux,
    ReachHydraulicGeometry,
    StockState,
)

ISSUE = datetime(2026, 8, 1, tzinfo=UTC)


def _kernel() -> tuple[
    ConservativeTwinManningActionResponseKernel,
    ReachHydraulicGeometry,
    StockState,
]:
    network = DirectedReachNetwork(
        network_id="twin-test",
        feature_ids=(101, 102),
        downstream_feature_ids=(102, None),
        full_lengths_m=(1200.0, 1800.0),
        effective_lengths_m=(1200.0, 1800.0),
        action_entry_feature_ids=(101,),
        provenance_id="test-network",
        evidence_level="derived",
        admitted=True,
    )
    geometry = ReachHydraulicGeometry(
        feature_ids=network.feature_ids,
        bottom_width_m=(18.0, 22.0),
        side_slope_horizontal_per_vertical=(2.0, 2.0),
        bed_slope=(0.0015, 0.001),
        manning_n=(0.035, 0.04),
        provenance_id="test-geometry",
        evidence_level="derived",
        admitted_as_hydraulic_geometry=True,
    )
    operator = BranchingManningNetworkTransportOperator(
        network,
        BranchingNetworkTransportConfig(
            timestep_seconds=3600.0,
            integration_substep_seconds=300.0,
            operator_form_admitted=True,
        ),
    )
    initial = StockState(
        values=(40_000.0, 60_000.0),
        unit="m3",
        provenance_id="common-observed-initial-state",
    )
    return ConservativeTwinManningActionResponseKernel(operator), geometry, initial


def _steps(
    baseline_release_m3s: float,
    scenario_release_m3s: float,
    *,
    count: int = 8,
) -> tuple[ConservativeTwinActionStepInput, ...]:
    rows = []
    for index in range(count):
        start = ISSUE + timedelta(hours=index)
        rows.append(
            ConservativeTwinActionStepInput(
                support_start=start,
                support_end=start + timedelta(hours=1),
                inputs_available_at=ISSUE,
                baseline_action=ActionBoundaryFlux(
                    values=(baseline_release_m3s, 0.0),
                    unit="m3 s-1",
                    provenance_id=f"baseline:{index}",
                ),
                scenario_action=ActionBoundaryFlux(
                    values=(scenario_release_m3s, 0.0),
                    unit="m3 s-1",
                    provenance_id=f"scenario:{index}",
                ),
                forcing=ForcingFlux(
                    values=(0.4, 0.7),
                    unit="m3 s-1",
                    provenance_id=f"common-forcing:{index}",
                    modeled=True,
                ),
            )
        )
    return tuple(rows)


def test_twin_rollout_closes_differential_mass_balance_without_clipping() -> None:
    kernel, geometry, initial = _kernel()
    result = kernel.forecast(
        initial,
        geometry,
        _steps(12.0, 17.0),
        issue_time=ISSUE,
    )

    assert result.all_mass_balances_passed is True
    assert result.source_operator_admitted is True
    assert result.cumulative_incremental_action_input_volume_m3 == pytest.approx(5.0 * 3600.0 * 8)
    assert (
        result.cumulative_incremental_outlet_volume_m3 + result.final_incremental_storage_m3
    ) == pytest.approx(
        result.cumulative_incremental_action_input_volume_m3,
        abs=result.cumulative_differential_mass_balance_tolerance_m3,
    )
    assert all(step.incremental_outlet_mean_flow_m3s >= 0.0 for step in result.steps)
    payload = result.as_dict()
    assert payload["output_response_clipped"] is False
    assert payload["new_fitted_parameter_count"] == 0
    assert payload["future_outcomes_used"] is False
    assert payload["claim_boundary"]["counterfactual_release_effect_causally_validated"] is False


def test_twin_rollout_preserves_release_order_for_positive_and_negative_changes() -> None:
    kernel, geometry, initial = _kernel()
    lower = kernel.forecast(
        initial,
        geometry,
        _steps(12.0, 8.0),
        issue_time=ISSUE,
    )
    baseline = kernel.forecast(
        initial,
        geometry,
        _steps(12.0, 12.0),
        issue_time=ISSUE,
    )
    upper = kernel.forecast(
        initial,
        geometry,
        _steps(12.0, 17.0),
        issue_time=ISSUE,
    )

    assert all(step.incremental_outlet_mean_flow_m3s <= 0.0 for step in lower.steps)
    assert all(step.incremental_outlet_mean_flow_m3s == 0.0 for step in baseline.steps)
    assert all(step.incremental_outlet_mean_flow_m3s >= 0.0 for step in upper.steps)
    assert all(
        low.scenario_outlet_mean_flow_m3s
        <= middle.scenario_outlet_mean_flow_m3s
        <= high.scenario_outlet_mean_flow_m3s
        for low, middle, high in zip(lower.steps, baseline.steps, upper.steps, strict=True)
    )


def test_twin_rollout_continues_from_both_full_storage_states() -> None:
    kernel, geometry, initial = _kernel()
    one_shot = kernel.forecast(
        initial,
        geometry,
        _steps(12.0, 17.0),
        issue_time=ISSUE,
    )
    first = kernel.forecast(
        initial,
        geometry,
        _steps(12.0, 17.0, count=4),
        issue_time=ISSUE,
    )
    continuation_steps = _steps(12.0, 17.0)[4:]
    baseline_continuation = kernel.forecast(
        first.baseline_final_state,
        geometry,
        tuple(
            ConservativeTwinActionStepInput(
                support_start=step.support_start,
                support_end=step.support_end,
                inputs_available_at=ISSUE + timedelta(hours=4),
                baseline_action=step.baseline_action,
                scenario_action=step.baseline_action,
                forcing=step.forcing,
            )
            for step in continuation_steps
        ),
        issue_time=ISSUE + timedelta(hours=4),
    )
    scenario_continuation = kernel.forecast(
        first.scenario_final_state,
        geometry,
        tuple(
            ConservativeTwinActionStepInput(
                support_start=step.support_start,
                support_end=step.support_end,
                inputs_available_at=ISSUE + timedelta(hours=4),
                baseline_action=step.scenario_action,
                scenario_action=step.scenario_action,
                forcing=step.forcing,
            )
            for step in continuation_steps
        ),
        issue_time=ISSUE + timedelta(hours=4),
    )

    assert baseline_continuation.baseline_final_state.values == pytest.approx(
        one_shot.baseline_final_state.values
    )
    assert scenario_continuation.scenario_final_state.values == pytest.approx(
        one_shot.scenario_final_state.values
    )


def test_twin_rollout_rejects_future_inputs_and_noncontiguous_support() -> None:
    kernel, geometry, initial = _kernel()
    future = _steps(12.0, 17.0, count=1)[0]
    future = ConservativeTwinActionStepInput(
        support_start=future.support_start,
        support_end=future.support_end,
        inputs_available_at=ISSUE + timedelta(seconds=1),
        baseline_action=future.baseline_action,
        scenario_action=future.scenario_action,
        forcing=future.forcing,
    )
    with pytest.raises(ValueError, match="future_input_forbidden"):
        kernel.forecast(initial, geometry, (future,), issue_time=ISSUE)

    first, second = _steps(12.0, 17.0, count=2)
    gap = ConservativeTwinActionStepInput(
        support_start=second.support_start + timedelta(hours=1),
        support_end=second.support_end + timedelta(hours=1),
        inputs_available_at=second.inputs_available_at,
        baseline_action=second.baseline_action,
        scenario_action=second.scenario_action,
        forcing=second.forcing,
    )
    with pytest.raises(ValueError, match="support_not_contiguous"):
        kernel.forecast(initial, geometry, (first, gap), issue_time=ISSUE)
