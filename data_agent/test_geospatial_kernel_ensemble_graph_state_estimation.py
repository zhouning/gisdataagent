from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    BranchingManningNetworkTransportOperator,
    BranchingNetworkTransportConfig,
    CausalDischargeObservation,
    DirectedReachNetwork,
    ReachHydraulicGeometry,
)
from data_agent.uwm.geospatial_kernel_v2.ensemble_graph_state_estimation import (
    LocalizedEnsembleStateEstimator,
    LocalizedEnsembleStateEstimatorConfig,
)

ANALYSIS_TIME = datetime(2026, 8, 1, 0, tzinfo=UTC)


def _network(
    *, feature_ids: tuple[int, ...] = (30, 10, 20)
) -> DirectedReachNetwork:
    downstream = {30: None, 10: 30, 20: 30}
    full_length = {30: 1000.0, 10: 800.0, 20: 900.0}
    return DirectedReachNetwork(
        network_id="synthetic-y-ensemble-state",
        feature_ids=feature_ids,
        downstream_feature_ids=tuple(downstream[value] for value in feature_ids),
        full_lengths_m=tuple(full_length[value] for value in feature_ids),
        effective_lengths_m=tuple(full_length[value] for value in feature_ids),
        action_entry_feature_ids=(10,),
        provenance_id="synthetic:fixed-y-topology",
        evidence_level="derived",
        admitted=True,
    )


def _geometry(
    *, feature_ids: tuple[int, ...] = (30, 10, 20)
) -> ReachHydraulicGeometry:
    values = {
        30: (10.0, 2.0, 0.001, 0.04),
        10: (8.0, 2.0, 0.0015, 0.045),
        20: (9.0, 2.0, 0.0012, 0.042),
    }
    return ReachHydraulicGeometry(
        feature_ids=feature_ids,
        bottom_width_m=tuple(values[value][0] for value in feature_ids),
        side_slope_horizontal_per_vertical=tuple(
            values[value][1] for value in feature_ids
        ),
        bed_slope=tuple(values[value][2] for value in feature_ids),
        manning_n=tuple(values[value][3] for value in feature_ids),
        provenance_id="synthetic:fixed-y-geometry",
        evidence_level="derived",
        admitted_as_hydraulic_geometry=True,
    )


def _observation(**overrides: object) -> CausalDischargeObservation:
    values: dict[str, object] = {
        "feature_id": 30,
        "discharge_m3s": 7.0,
        "valid_at": ANALYSIS_TIME,
        "available_at": ANALYSIS_TIME,
        "quality_status": "approved",
        "provenance_id": "synthetic:gauge:30",
        "evidence_level": "authoritative",
    }
    values.update(overrides)
    return CausalDischargeObservation(**values)  # type: ignore[arg-type]


def _forecast() -> tuple[tuple[float, ...], ...]:
    return (
        (7000.0, 4000.0, 6000.0),
        (7500.0, 4500.0, 6000.0),
        (8000.0, 5000.0, 6000.0),
        (8500.0, 5500.0, 6000.0),
        (9000.0, 6000.0, 6000.0),
    )


def _estimator(radius_m: float = 5000.0) -> LocalizedEnsembleStateEstimator:
    return LocalizedEnsembleStateEstimator(
        LocalizedEnsembleStateEstimatorConfig(
            localization_radius_m=radius_m,
            maximum_observation_age_seconds=3600.0,
        )
    )


def _analyze(
    *, radius_m: float = 5000.0, feature_ids: tuple[int, ...] = (30, 10, 20)
):
    canonical = (30, 10, 20)
    forecast_by_feature = [
        {feature_id: row[index] for index, feature_id in enumerate(canonical)}
        for row in _forecast()
    ]
    forecast = tuple(
        tuple(row[feature_id] for feature_id in feature_ids)
        for row in forecast_by_feature
    )
    return _estimator(radius_m).analyze(
        network=_network(feature_ids=feature_ids),
        geometry=_geometry(feature_ids=feature_ids),
        forecast_storage_ensemble_m3=forecast,
        observations=(_observation(),),
        observation_error_std_m3s=(0.25,),
        analysis_time=ANALYSIS_TIME,
        provenance_id="synthetic:localized-ensemble-analysis",
    )


def test_covariance_driven_update_reduces_innovation_and_accounts_mass() -> None:
    result = _analyze()
    prior = np.asarray(result.forecast_storage_ensemble_m3, dtype=float)
    analysis = np.asarray(result.analysis_storage_ensemble_m3, dtype=float)
    prior_observation = np.asarray(
        result.forecast_observation_ensemble_m3s, dtype=float
    ).mean(axis=0)[0]
    analysis_observation = np.asarray(
        result.analysis_observation_ensemble_m3s, dtype=float
    ).mean(axis=0)[0]

    assert abs(7.0 - analysis_observation) < abs(7.0 - prior_observation)
    assert analysis[:, 0].mean() > prior[:, 0].mean()
    assert analysis[:, 1].mean() > prior[:, 1].mean()
    assert analysis[:, 2] == pytest.approx(prior[:, 2])
    assert result.mass_accounting_passed is True
    assert result.maximum_absolute_mass_accounting_residual_m3 < 1e-9
    assert result.as_dict()["mass_adjustment_ledger"][
        "analysis_increment_is_transition_flux"
    ] is False
    assert result.as_dict()["claim_boundary"]["estimator_candidate_admitted"] is False


def test_compact_graph_localization_blocks_distant_spurious_update() -> None:
    result = _analyze(radius_m=800.0)
    prior = np.asarray(result.forecast_storage_ensemble_m3, dtype=float)
    analysis = np.asarray(result.analysis_storage_ensemble_m3, dtype=float)

    assert result.graph_distance_m_by_observation[0] == (0.0, 900.0, 950.0)
    assert result.localization_taper_by_observation[0] == (1.0, 0.0, 0.0)
    assert analysis[:, 0].mean() > prior[:, 0].mean()
    assert analysis[:, 1] == pytest.approx(prior[:, 1])
    assert analysis[:, 2] == pytest.approx(prior[:, 2])


def test_multigauge_joint_analysis_reduces_both_observation_innovations() -> None:
    result = _estimator().analyze(
        network=_network(),
        geometry=_geometry(),
        forecast_storage_ensemble_m3=_forecast(),
        observations=(
            _observation(),
            _observation(
                feature_id=10,
                discharge_m3s=6.0,
                provenance_id="synthetic:gauge:10",
            ),
        ),
        observation_error_std_m3s=(0.25, 0.25),
        analysis_time=ANALYSIS_TIME,
        provenance_id="synthetic:joint-multigauge-analysis",
    )
    prior = np.asarray(result.forecast_observation_ensemble_m3s).mean(axis=0)
    analysis = np.asarray(result.analysis_observation_ensemble_m3s).mean(axis=0)
    observed = np.asarray(result.observed_discharge_m3s)

    assert bool((np.abs(observed - analysis) < np.abs(observed - prior)).all())
    assert np.isfinite(result.observation_covariance_condition_number)
    assert len(result.localized_kalman_gain_by_observation) == 2
    assert result.mass_accounting_passed is True


def test_analysis_is_feature_order_covariant() -> None:
    canonical = _analyze()
    permuted = _analyze(feature_ids=(20, 30, 10))
    canonical_mean = dict(
        zip(canonical.feature_ids, canonical.analysis_mean_stock.values, strict=True)
    )
    permuted_mean = dict(
        zip(permuted.feature_ids, permuted.analysis_mean_stock.values, strict=True)
    )

    assert permuted_mean == pytest.approx(canonical_mean)
    assert permuted.mass_accounting_passed is True


def test_analysis_stock_runs_through_conservative_manning_transport() -> None:
    analysis = _analyze()
    operator = BranchingManningNetworkTransportOperator(
        _network(),
        BranchingNetworkTransportConfig(
            timestep_seconds=3600.0,
            integration_substep_seconds=300.0,
            operator_form_admitted=True,
        ),
    )

    forecast_step = operator.step(analysis.forecast_mean_stock, _geometry())
    analysis_step = operator.step(analysis.analysis_mean_stock, _geometry())

    assert abs(forecast_step.global_mass_balance_residual_m3) <= (
        forecast_step.numeric_mass_tolerance_m3
    )
    assert abs(analysis_step.global_mass_balance_residual_m3) <= (
        analysis_step.numeric_mass_tolerance_m3
    )
    assert analysis_step.outlet_mean_flow_m3s > forecast_step.outlet_mean_flow_m3s
    assert analysis_step.diagnostic_only is False


def test_causal_boundary_and_api_isolation_fail_closed() -> None:
    parameters = set(inspect.signature(LocalizedEnsembleStateEstimator.analyze).parameters)
    assert not parameters.intersection({"target", "outcome", "score", "loss"})
    unavailable = _observation(
        valid_at=ANALYSIS_TIME,
        available_at=ANALYSIS_TIME + timedelta(seconds=1),
    )

    with pytest.raises(
        ValueError, match="ensemble_state_observation_not_yet_available"
    ):
        _estimator().analyze(
            network=_network(),
            geometry=_geometry(),
            forecast_storage_ensemble_m3=_forecast(),
            observations=(unavailable,),
            observation_error_std_m3s=(0.25,),
            analysis_time=ANALYSIS_TIME,
            provenance_id="synthetic:unavailable-observation",
        )
