from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    ActionBoundaryFlux,
    BranchingManningNetworkTransportOperator,
    BranchingNetworkTransportConfig,
    CausalDischargeObservation,
    CausalObservationUpdateConfig,
    CausalStateDependentManningForecastClosure,
    DirectedReachNetwork,
    ForcingFlux,
    ForecastClosedBranchingTransportOperator,
    ForecastClosureConfig,
    GraphStateUpdateParameters,
    ObservedInternalBoundaryReplacement,
    ReachHydraulicGeometry,
    StateDependentManningClosureParameters,
    StockState,
)
from data_agent.uwm.geospatial_kernel_v2.graph_state_estimation import (
    DETERMINISTIC_DISTANCE_LOCALIZED_GAIN_SEMANTICS,
    DETERMINISTIC_MAINSTEM_GAIN_SEMANTICS,
)

ISSUE_TIME = datetime(2022, 4, 1, 1, tzinfo=timezone.utc)


def _network() -> DirectedReachNetwork:
    return DirectedReachNetwork(
        network_id="synthetic-y",
        feature_ids=(30, 10, 20),
        downstream_feature_ids=(None, 30, 30),
        full_lengths_m=(1000.0, 800.0, 900.0),
        effective_lengths_m=(1000.0, 800.0, 900.0),
        action_entry_feature_ids=(10,),
        provenance_id="synthetic:fixed-topology",
        evidence_level="derived",
        admitted=True,
    )


def _geometry() -> ReachHydraulicGeometry:
    return ReachHydraulicGeometry(
        feature_ids=(30, 10, 20),
        bottom_width_m=(10.0, 8.0, 9.0),
        side_slope_horizontal_per_vertical=(2.0, 2.0, 2.0),
        bed_slope=(0.001, 0.0015, 0.0012),
        manning_n=(0.04, 0.045, 0.042),
        provenance_id="synthetic:geometry",
        evidence_level="derived",
        admitted_as_hydraulic_geometry=True,
    )


def _stock() -> StockState:
    return StockState(
        values=(8000.0, 5000.0, 6000.0),
        unit="m3",
        provenance_id="synthetic:prior",
    )


def _parameters(
    *,
    intercept: tuple[float, ...] = (0.0, 0.0, 0.0),
    slope: tuple[float, ...] = (0.0, 0.0, 0.0),
) -> StateDependentManningClosureParameters:
    return StateDependentManningClosureParameters(
        feature_ids=(30, 10, 20),
        reference_storage_m3=(8000.0, 5000.0, 6000.0),
        log_roughness_intercept=intercept,
        log_roughness_storage_slope=slope,
        training_system_ids=("public-development-system",),
        training_data_start=datetime(2020, 1, 1, tzinfo=timezone.utc),
        training_data_end=datetime(2020, 2, 1, tzinfo=timezone.utc),
        provenance_id="synthetic:frozen-parameters",
        evidence_level="derived",
        admitted=True,
        outcome_calibrated=True,
    )


def _closure(
    parameters: StateDependentManningClosureParameters | None = None,
    graph_parameters: GraphStateUpdateParameters | None = None,
) -> CausalStateDependentManningForecastClosure:
    return CausalStateDependentManningForecastClosure(
        parameters or _parameters(),
        ForecastClosureConfig(
            observation_update=CausalObservationUpdateConfig(
                analysis_gain=0.5,
                maximum_observation_age_seconds=7200.0,
            ),
            minimum_roughness_multiplier=0.5,
            maximum_roughness_multiplier=2.0,
        ),
        graph_state_update_parameters=graph_parameters,
    )


def _graph_parameters(
    *,
    observation_feature_ids: tuple[int, ...] = (30,),
    gain_rows: tuple[tuple[float, ...], ...] = ((0.0, 0.5, 0.25),),
) -> GraphStateUpdateParameters:
    return GraphStateUpdateParameters(
        feature_ids=(30, 10, 20),
        observation_feature_ids=observation_feature_ids,
        reference_storage_m3=(8000.0, 5000.0, 6000.0),
        log_storage_gain_rows=gain_rows,
        training_system_ids=("public-modeled-state-development",),
        training_data_start=datetime(2020, 1, 1, tzinfo=timezone.utc),
        training_data_end=datetime(2020, 2, 1, tzinfo=timezone.utc),
        provenance_id="synthetic:nwm-modeled-covariance",
        evidence_level="derived",
        admitted=True,
        modeled_state_based=True,
        possible_nudging=True,
        outcome_calibrated=False,
    )


def _transport() -> BranchingManningNetworkTransportOperator:
    return BranchingManningNetworkTransportOperator(
        _network(),
        BranchingNetworkTransportConfig(
            timestep_seconds=3600.0,
            integration_substep_seconds=300.0,
            operator_form_admitted=True,
        ),
    )


def _observation(**overrides: object) -> CausalDischargeObservation:
    values: dict[str, object] = {
        "feature_id": 30,
        "discharge_m3s": 8.0,
        "valid_at": ISSUE_TIME - timedelta(hours=1),
        "available_at": ISSUE_TIME - timedelta(minutes=50),
        "quality_status": "approved",
        "provenance_id": "usgs:synthetic-approved",
        "evidence_level": "authoritative",
    }
    values.update(overrides)
    return CausalDischargeObservation(**values)  # type: ignore[arg-type]


def test_identity_forecast_closure_preserves_state_geometry_and_topology() -> None:
    network = _network()
    topology_before = network.as_dict()

    result = _closure().prepare(
        network,
        _stock(),
        _geometry(),
        issue_time=ISSUE_TIME,
    )

    assert result.analysis_stock.values == _stock().values
    assert result.effective_geometry.manning_n == _geometry().manning_n
    assert result.applied_roughness_multiplier == (1.0, 1.0, 1.0)
    assert result.analysis_increment_m3 == (0.0, 0.0, 0.0)
    assert result.closure_admitted is True
    assert network.as_dict() == topology_before


def test_forecast_closure_bounds_state_dependent_constitutive_residual() -> None:
    result = _closure(
        _parameters(
            intercept=(10.0, -10.0, 0.0),
            slope=(2.0, -2.0, 0.0),
        )
    ).prepare(
        _network(),
        _stock(),
        _geometry(),
        issue_time=ISSUE_TIME,
        observations=(_observation(),),
    )

    assert result.applied_roughness_multiplier[0] == pytest.approx(2.0)
    assert result.applied_roughness_multiplier[1] == pytest.approx(0.5)
    assert result.applied_roughness_multiplier[2] == pytest.approx(1.0)
    assert result.residual_clipped == (True, True, False)
    assert result.analysis_increment_m3[0] != 0.0
    assert result.observation_updates[0].admitted is True
    assert result.as_dict()["residual_mass_role"] == (
        "bounded_constitutive_rate_law_only_no_external_source_sink"
    )


def test_graph_state_update_is_low_rank_dag_bounded_and_explicitly_accounted() -> None:
    network = _network()
    topology_before = network.as_dict()
    result = _closure(graph_parameters=_graph_parameters()).prepare(
        network,
        _stock(),
        _geometry(),
        issue_time=ISSUE_TIME,
        observations=(_observation(),),
    )

    assert result.graph_state_update_parameters is not None
    assert result.graph_state_update_parameters.rank == 1
    assert result.observation_updates[0].graph_updated_feature_count == 2
    assert result.graph_analysis_increment_m3[0] == 0.0
    assert result.graph_analysis_increment_m3[1] != 0.0
    assert result.graph_analysis_increment_m3[2] != 0.0
    assert sum(result.analysis_increment_m3) == pytest.approx(
        sum(result.analysis_stock.values) - sum(_stock().values)
    )
    assert result.closure_admitted is True
    assert network.as_dict() == topology_before


def test_graph_state_update_can_label_deterministic_mainstem_gain_without_outcome_fit() -> None:
    parameters = replace(
        _graph_parameters(gain_rows=((0.0, 1.0, 1.0),)),
        gain_semantics=DETERMINISTIC_MAINSTEM_GAIN_SEMANTICS,
    )

    result = _closure(graph_parameters=parameters).prepare(
        _network(),
        _stock(),
        _geometry(),
        issue_time=ISSUE_TIME,
        observations=(_observation(),),
    )

    assert result.graph_state_update_parameters is not None
    assert result.graph_state_update_parameters.outcome_calibrated is False
    assert (
        result.graph_state_update_parameters.as_dict()["gain_semantics"]
        == DETERMINISTIC_MAINSTEM_GAIN_SEMANTICS
    )


def test_distance_localized_graph_gain_cannot_claim_outcome_calibration() -> None:
    with pytest.raises(
        ValueError,
        match="deterministic_graph_state_update_cannot_be_outcome_calibrated",
    ):
        replace(
            _graph_parameters(),
            gain_semantics=DETERMINISTIC_DISTANCE_LOCALIZED_GAIN_SEMANTICS,
            outcome_calibrated=True,
        )


def test_graph_state_update_rejects_support_outside_gauge_upstream_dag() -> None:
    graph = _graph_parameters(
        observation_feature_ids=(20,),
        gain_rows=((0.0, 0.5, 0.0),),
    )
    with pytest.raises(
        ValueError,
        match="graph_state_update_support_outside_observation_upstream_dag",
    ):
        _closure(graph_parameters=graph).prepare(
            _network(),
            _stock(),
            _geometry(),
            issue_time=ISSUE_TIME,
            observations=(_observation(feature_id=20),),
        )


def test_forecast_closure_fails_closed_on_temporal_leakage() -> None:
    closure = _closure()
    future_parameter = replace(
        _parameters(),
        training_data_end=ISSUE_TIME,
    )
    with pytest.raises(
        ValueError,
        match="forecast_closure_training_data_not_before_issue_time",
    ):
        _closure(future_parameter).prepare(
            _network(),
            _stock(),
            _geometry(),
            issue_time=ISSUE_TIME,
        )

    with pytest.raises(
        ValueError,
        match="observation_not_yet_available_at_analysis_time",
    ):
        closure.prepare(
            _network(),
            _stock(),
            _geometry(),
            issue_time=ISSUE_TIME,
            observations=(_observation(available_at=ISSUE_TIME + timedelta(minutes=1)),),
        )

    with pytest.raises(
        ValueError,
        match="forecast_closure_one_observation_per_feature_required",
    ):
        closure.prepare(
            _network(),
            _stock(),
            _geometry(),
            issue_time=ISSUE_TIME,
            observations=(_observation(), _observation(provenance_id="duplicate")),
        )


def test_identity_closed_transport_matches_unchanged_branching_solver() -> None:
    transport = _transport()
    stock = _stock()
    geometry = _geometry()
    action = ActionBoundaryFlux(
        values=(0.0, 2.0, 0.0),
        unit="m3 s-1",
        provenance_id="synthetic:action",
    )
    forcing = ForcingFlux(
        values=(1.0, 0.5, 0.25),
        unit="m3 s-1",
        provenance_id="synthetic:forcing",
        modeled=True,
    )

    direct = transport.step(stock, geometry, action=action, forcing=forcing)
    closed = ForecastClosedBranchingTransportOperator(
        transport,
        _closure(),
    ).step(
        stock,
        geometry,
        issue_time=ISSUE_TIME,
        action=action,
        forcing=forcing,
    )

    assert closed.transport.next_stock.values == pytest.approx(
        direct.next_stock.values,
        abs=1e-10,
    )
    assert closed.outlet_mean_flow_m3s == pytest.approx(
        direct.outlet_mean_flow_m3s,
        abs=1e-12,
    )
    assert abs(closed.forecast_cycle_mass_balance_residual_m3) <= (
        closed.forecast_cycle_mass_tolerance_m3
    )
    assert closed.forecast_admitted is True


def test_analysis_increment_is_accounted_outside_transition_flux() -> None:
    stock = _stock()
    closed = ForecastClosedBranchingTransportOperator(
        _transport(),
        _closure(),
    ).step(
        stock,
        _geometry(),
        issue_time=ISSUE_TIME,
        observations=(_observation(),),
    )

    assert closed.analysis_increment_m3 != 0.0
    assert closed.transition_input_volume_m3 == 0.0
    assert closed.transport.total_input_volume_m3 == 0.0
    assert (
        closed.final_storage_m3
        + closed.outlet_volume_m3
        - closed.prior_storage_m3
        - closed.analysis_increment_m3
    ) == pytest.approx(closed.forecast_cycle_mass_balance_residual_m3)
    assert (
        closed.as_dict()["forecast_cycle_mass_ledger"]["analysis_increment_is_transition_flux"]
        is False
    )


def test_closed_transport_accounts_for_displaced_internal_boundary_outflow() -> None:
    boundary = ObservedInternalBoundaryReplacement(
        feature_ids=(30,),
        values=(4.0,),
        unit="m3 s-1",
        provenance_id="usgs:synthetic:available-boundary",
        evidence_level="derived",
        admitted=True,
        archive_revised=False,
        operational_vintage_verified=True,
    )
    closed = ForecastClosedBranchingTransportOperator(
        _transport(),
        _closure(),
    ).step(
        _stock(),
        _geometry(),
        issue_time=ISSUE_TIME,
        internal_boundary=boundary,
    )

    assert closed.transition_input_volume_m3 == pytest.approx(4.0 * 3600.0)
    assert closed.transition_displaced_upstream_volume_m3 > 0.0
    assert closed.transition_displaced_upstream_volume_m3 == pytest.approx(
        closed.transport.displaced_upstream_outflow_volume_m3
    )
    assert (
        closed.final_storage_m3
        + closed.outlet_volume_m3
        + closed.transition_displaced_upstream_volume_m3
        - closed.prior_storage_m3
        - closed.analysis_increment_m3
        - closed.transition_input_volume_m3
    ) == pytest.approx(closed.forecast_cycle_mass_balance_residual_m3)
    assert abs(closed.forecast_cycle_mass_balance_residual_m3) <= (
        closed.forecast_cycle_mass_tolerance_m3
    )


def test_candidate_parameters_require_explicit_diagnostic_mode() -> None:
    with pytest.raises(
        ValueError,
        match="candidate_forecast_closure_parameters_cannot_be_admitted",
    ):
        replace(_parameters(), evidence_level="candidate")

    candidate = replace(
        _parameters(),
        evidence_level="candidate",
        admitted=False,
    )
    with pytest.raises(
        ValueError,
        match="unadmitted_forecast_closure_components_require_diagnostic_mode",
    ):
        _closure(candidate).prepare(
            _network(),
            _stock(),
            _geometry(),
            issue_time=ISSUE_TIME,
        )


def test_nonfinite_derived_residual_fails_before_bound_projection() -> None:
    extreme = _parameters(
        intercept=(0.0, 0.0, 0.0),
        slope=(1e308, 0.0, 0.0),
    )
    with pytest.raises(
        RuntimeError,
        match="forecast_closure_nonfinite_constitutive_residual",
    ):
        _closure(extreme).prepare(
            _network(),
            StockState(
                values=(1e308, 5000.0, 6000.0),
                unit="m3",
                provenance_id="synthetic:extreme-state",
            ),
            _geometry(),
            issue_time=ISSUE_TIME,
        )


def test_recursive_forecast_provenance_remains_bounded() -> None:
    operator = ForecastClosedBranchingTransportOperator(
        _transport(),
        _closure(),
    )
    state = _stock()
    for offset in range(48):
        result = operator.step(
            state,
            _geometry(),
            issue_time=ISSUE_TIME + timedelta(hours=offset),
        )
        state = result.transport.next_stock

    assert len(state.provenance_id) < 800
    assert "stock=" in result.closure.analysis_stock.provenance_id
