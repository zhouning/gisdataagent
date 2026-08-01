from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    BranchingNetworkTransportConfig,
    CausalDischargeObservation,
    DirectedReachNetwork,
    ReachForcingSupport,
    ReachHydraulicGeometry,
    StockState,
)
from data_agent.uwm.geospatial_kernel_v2.ensemble_graph_state_estimation import (
    LocalizedEnsembleStateEstimator,
    LocalizedEnsembleStateEstimatorConfig,
)
from data_agent.uwm.geospatial_kernel_v2.ensemble_manning_forecast_cycle import (
    PhysicalEnsembleManningForecastCycle,
    build_graph_partition_physical_ensemble_design,
    build_symmetric_physical_ensemble_design,
)

REFERENCE_TIME = datetime(2026, 8, 1, 0, tzinfo=UTC)
ANALYSIS_TIME = REFERENCE_TIME + timedelta(hours=1)


def _network() -> DirectedReachNetwork:
    return DirectedReachNetwork(
        network_id="synthetic-y-physical-ensemble",
        feature_ids=(30, 10, 20),
        downstream_feature_ids=(None, 30, 30),
        full_lengths_m=(1000.0, 800.0, 900.0),
        effective_lengths_m=(1000.0, 800.0, 900.0),
        action_entry_feature_ids=(10,),
        provenance_id="synthetic:physical-ensemble-topology",
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
        provenance_id="synthetic:physical-ensemble-geometry",
        evidence_level="derived",
        admitted_as_hydraulic_geometry=True,
    )


def _cycle() -> PhysicalEnsembleManningForecastCycle:
    return PhysicalEnsembleManningForecastCycle(
        transport_config=BranchingNetworkTransportConfig(
            timestep_seconds=3600.0,
            integration_substep_seconds=300.0,
            operator_form_admitted=True,
            allow_unadmitted_components_for_diagnostics=True,
        ),
        state_estimator=LocalizedEnsembleStateEstimator(
            LocalizedEnsembleStateEstimatorConfig(
                localization_radius_m=5000.0,
                maximum_observation_age_seconds=0.0,
                allow_unadmitted_components_for_diagnostics=True,
            )
        ),
    )


def _execute(member_specs=None):
    network = _network()
    members = member_specs or build_symmetric_physical_ensemble_design(
        feature_ids=network.feature_ids,
        initial_storage_fraction=0.1,
        manning_n_fraction=0.1,
        forcing_fraction=0.2,
    )
    return _cycle().execute(
        network=network,
        base_geometry=_geometry(),
        initial_stock=StockState(
            (8000.0, 5000.0, 6000.0), "m3", "synthetic:initial-stock"
        ),
        member_specs=members,
        historical_action_m3s_by_step=((0.0, 4.0, 0.0),),
        historical_forcing_m3s_by_step=((0.2, 0.1, 0.15),),
        forecast_action_m3s_by_step=(
            (0.0, 5.0, 0.0),
            (0.0, 6.0, 0.0),
            (0.0, 4.0, 0.0),
        ),
        forecast_forcing_m3s_by_step=(
            (0.2, 0.1, 0.15),
            (0.25, 0.12, 0.18),
            (0.18, 0.08, 0.12),
        ),
        forcing_support=ReachForcingSupport(
            feature_ids=network.feature_ids,
            coverage_fractions=(1.0, 1.0, 1.0),
            support_method="synthetic-full-reach",
            provenance_id="synthetic:forcing-support",
            evidence_level="derived",
            admitted_as_spatial_support=True,
        ),
        observations=(
            CausalDischargeObservation(
                feature_id=30,
                discharge_m3s=6.0,
                valid_at=ANALYSIS_TIME,
                available_at=ANALYSIS_TIME,
                quality_status="approved",
                provenance_id="synthetic:issue-gauge",
                evidence_level="authoritative",
            ),
        ),
        observation_error_std_m3s=(0.25,),
        reference_time=REFERENCE_TIME,
        analysis_time=ANALYSIS_TIME,
        provenance_id="synthetic:physical-ensemble-cycle",
    )


def test_symmetric_design_explicitly_spans_three_physical_uncertainties() -> None:
    members = build_symmetric_physical_ensemble_design(
        feature_ids=(30, 10, 20),
        initial_storage_fraction=0.1,
        manning_n_fraction=0.1,
        forcing_fraction=0.2,
    )

    assert len(members) == 7
    assert members[0].member_id == "nominal"
    assert members[0].nominal is True
    assert sum(value.nominal for value in members) == 1
    assert {value.member_id for value in members} == {
        "nominal",
        "initial_storage_low",
        "initial_storage_high",
        "manning_n_low",
        "manning_n_high",
        "modeled_forcing_low",
        "modeled_forcing_high",
    }


def test_graph_partition_design_adds_spatial_rank_without_inflating_variance() -> None:
    symmetric = build_symmetric_physical_ensemble_design(
        feature_ids=_network().feature_ids,
        initial_storage_fraction=0.1,
        manning_n_fraction=0.1,
        forcing_fraction=0.2,
    )
    structured = build_graph_partition_physical_ensemble_design(
        network=_network(),
        initial_storage_fraction=0.1,
        manning_n_fraction=0.1,
        forcing_fraction=0.2,
        graph_partition_mode_count=1,
    )

    assert len(structured) == 13
    assert sum(member.nominal for member in structured) == 1
    for attribute, fraction in (
        ("initial_storage_multiplier_by_feature", 0.1),
        ("manning_n_multiplier_by_feature", 0.1),
        ("forcing_multiplier_by_feature", 0.2),
    ):
        symmetric_values = np.asarray(
            [getattr(member, attribute) for member in symmetric]
        )
        structured_values = np.asarray(
            [getattr(member, attribute) for member in structured]
        )
        assert structured_values.mean(axis=0) == pytest.approx((1.0,) * 3)
        assert structured_values.var(axis=0, ddof=1) == pytest.approx(
            (fraction**2 / 3.0,) * 3
        )
        assert structured_values.var(axis=0, ddof=1) == pytest.approx(
            symmetric_values.var(axis=0, ddof=1)
        )
    storage_anomalies = np.asarray(
        [member.initial_storage_multiplier_by_feature for member in structured]
    ) - 1.0
    assert np.linalg.matrix_rank(storage_anomalies) == 2
    assert any(
        len(set(member.initial_storage_multiplier_by_feature)) > 1
        for member in structured
    )


def test_graph_partition_design_is_deterministic_and_rejects_invalid_counts() -> None:
    kwargs = {
        "network": _network(),
        "initial_storage_fraction": 0.1,
        "manning_n_fraction": 0.1,
        "forcing_fraction": 0.2,
        "graph_partition_mode_count": 1,
    }
    assert build_graph_partition_physical_ensemble_design(
        **kwargs
    ) == build_graph_partition_physical_ensemble_design(**kwargs)

    for invalid in (0, 3, True):
        with pytest.raises(ValueError, match="graph_partition_ensemble_mode_count"):
            build_graph_partition_physical_ensemble_design(
                **{**kwargs, "graph_partition_mode_count": invalid}
            )


def test_graph_partition_design_covaries_with_feature_order() -> None:
    reordered_network = DirectedReachNetwork(
        network_id="synthetic-y-physical-ensemble-reordered",
        feature_ids=(10, 30, 20),
        downstream_feature_ids=(30, None, 30),
        full_lengths_m=(800.0, 1000.0, 900.0),
        effective_lengths_m=(800.0, 1000.0, 900.0),
        action_entry_feature_ids=(10,),
        provenance_id="synthetic:physical-ensemble-topology-reordered",
        evidence_level="derived",
        admitted=True,
    )
    common = {
        "initial_storage_fraction": 0.1,
        "manning_n_fraction": 0.1,
        "forcing_fraction": 0.2,
        "graph_partition_mode_count": 1,
    }
    baseline = build_graph_partition_physical_ensemble_design(
        network=_network(), **common
    )
    reordered = build_graph_partition_physical_ensemble_design(
        network=reordered_network, **common
    )

    baseline_by_id = {member.member_id: member for member in baseline}
    reordered_by_id = {member.member_id: member for member in reordered}
    assert set(baseline_by_id) == set(reordered_by_id)
    for member_id, member in baseline_by_id.items():
        candidate = reordered_by_id[member_id]
        for attribute in (
            "initial_storage_multiplier_by_feature",
            "manning_n_multiplier_by_feature",
            "forcing_multiplier_by_feature",
        ):
            baseline_map = dict(
                zip(_network().feature_ids, getattr(member, attribute), strict=True)
            )
            reordered_map = dict(
                zip(
                    reordered_network.feature_ids,
                    getattr(candidate, attribute),
                    strict=True,
                )
            )
            assert reordered_map == baseline_map


def test_graph_partition_design_accepts_feature_aligned_amplitudes() -> None:
    fractions = {
        "initial_storage_multiplier_by_feature": np.asarray((0.0, 0.1, 0.2)),
        "manning_n_multiplier_by_feature": np.asarray((0.2, 0.3, 0.4)),
        "forcing_multiplier_by_feature": np.asarray((0.5, 0.0, 0.25)),
    }
    members = build_graph_partition_physical_ensemble_design(
        network=_network(),
        initial_storage_fraction=fractions[
            "initial_storage_multiplier_by_feature"
        ],
        manning_n_fraction=fractions["manning_n_multiplier_by_feature"],
        forcing_fraction=fractions["forcing_multiplier_by_feature"],
        graph_partition_mode_count=1,
    )

    assert len(members) == 13
    for attribute, fraction_by_feature in fractions.items():
        values = np.asarray([getattr(member, attribute) for member in members])
        assert values.mean(axis=0) == pytest.approx((1.0,) * 3)
        assert values.var(axis=0, ddof=1) == pytest.approx(
            fraction_by_feature**2 / 3.0
        )


@pytest.mark.parametrize(
    "fractions",
    ((0.1, 0.2), (0.0, 0.0, 0.0), (0.1, 1.0, 0.2)),
)
def test_graph_partition_design_rejects_invalid_feature_amplitudes(
    fractions: tuple[float, ...],
) -> None:
    with pytest.raises(ValueError, match="graph_partition_ensemble_fraction"):
        build_graph_partition_physical_ensemble_design(
            network=_network(),
            initial_storage_fraction=fractions,
            manning_n_fraction=0.1,
            forcing_fraction=0.2,
            graph_partition_mode_count=1,
        )


def test_physical_ensemble_cycle_closes_analysis_and_transition_ledgers() -> None:
    result = _execute()
    sources = dict(result.uncertainty_sources_varied)
    analysis = result.state_analysis.as_dict()

    assert sources == {
        "initial_storage": True,
        "manning_roughness": True,
        "modeled_forcing": True,
        "boundary_action": False,
    }
    assert result.member_ids[0] == "nominal"
    assert result.state_analysis.ensemble_member_count == 7
    assert result.state_analysis.mass_accounting_passed is True
    assert analysis["claim_boundary"]["components_admitted"] is False
    assert result.physical_mass_balance_check_count_by_member == (4,) * 7
    assert result.physical_mass_balance_pass_count_by_member == (4,) * 7
    assert result.all_physical_mass_balances_passed is True
    assert len(result.outlet_flow_ensemble_m3s_by_horizon) == 3
    assert all(len(row) == 7 for row in result.outlet_flow_ensemble_m3s_by_horizon)


def test_graph_partition_members_complete_the_full_physical_cycle() -> None:
    members = build_graph_partition_physical_ensemble_design(
        network=_network(),
        initial_storage_fraction=0.1,
        manning_n_fraction=0.1,
        forcing_fraction=0.2,
        graph_partition_mode_count=1,
    )
    result = _execute(members)

    assert result.state_analysis.ensemble_member_count == 13
    assert result.physical_mass_balance_check_count_by_member == (4,) * 13
    assert result.physical_mass_balance_pass_count_by_member == (4,) * 13
    assert result.all_physical_mass_balances_passed is True
    assert all(
        len(row) == 13 for row in result.outlet_flow_ensemble_m3s_by_horizon
    )


def test_cycle_produces_nonzero_forecast_spread_and_reduces_issue_innovation() -> None:
    result = _execute()
    forecast_observation = np.asarray(
        result.state_analysis.forecast_observation_ensemble_m3s
    ).mean(axis=0)[0]
    analysis_observation = np.asarray(
        result.state_analysis.analysis_observation_ensemble_m3s
    ).mean(axis=0)[0]
    observed = result.state_analysis.observed_discharge_m3s[0]

    assert abs(observed - analysis_observation) < abs(observed - forecast_observation)
    assert result.state_analysis.forecast_observation_ensemble_m3s[3] != (
        result.state_analysis.forecast_observation_ensemble_m3s[4]
    )
    assert all(np.std(row) > 0.0 for row in result.outlet_flow_ensemble_m3s_by_horizon)
    p05 = np.asarray(result.outlet_flow_p05_m3s_by_horizon)
    median = np.asarray(result.outlet_flow_median_m3s_by_horizon)
    p95 = np.asarray(result.outlet_flow_p95_m3s_by_horizon)
    assert bool((p05 < median).all())
    assert bool((median < p95).all())


def test_cycle_rejects_an_ensemble_missing_required_forcing_uncertainty() -> None:
    network = _network()
    members = build_symmetric_physical_ensemble_design(
        feature_ids=network.feature_ids,
        initial_storage_fraction=0.1,
        manning_n_fraction=0.1,
        forcing_fraction=0.2,
    )[:5]

    with pytest.raises(
        ValueError, match="physical_ensemble_cycle_required_uncertainty_missing"
    ):
        _cycle().execute(
            network=network,
            base_geometry=_geometry(),
            initial_stock=StockState(
                (8000.0, 5000.0, 6000.0), "m3", "synthetic:initial-stock"
            ),
            member_specs=members,
            historical_action_m3s_by_step=((0.0, 4.0, 0.0),),
            historical_forcing_m3s_by_step=((0.2, 0.1, 0.15),),
            forecast_action_m3s_by_step=((0.0, 5.0, 0.0),),
            forecast_forcing_m3s_by_step=((0.2, 0.1, 0.15),),
            forcing_support=ReachForcingSupport(
                feature_ids=network.feature_ids,
                coverage_fractions=(1.0, 1.0, 1.0),
                support_method="synthetic-full-reach",
                provenance_id="synthetic:forcing-support",
                evidence_level="derived",
                admitted_as_spatial_support=True,
            ),
            observations=(
                CausalDischargeObservation(
                    feature_id=30,
                    discharge_m3s=6.0,
                    valid_at=ANALYSIS_TIME,
                    available_at=ANALYSIS_TIME,
                    quality_status="approved",
                    provenance_id="synthetic:issue-gauge",
                    evidence_level="authoritative",
                ),
            ),
            observation_error_std_m3s=(0.25,),
            reference_time=REFERENCE_TIME,
            analysis_time=ANALYSIS_TIME,
            provenance_id="synthetic:missing-forcing-uncertainty",
        )


def test_cycle_is_deterministic_and_accepts_no_outcome_or_loss() -> None:
    parameters = set(inspect.signature(PhysicalEnsembleManningForecastCycle.execute).parameters)
    assert not parameters.intersection({"target", "outcome", "score", "loss"})
    first = _execute().as_dict()
    second = _execute().as_dict()

    assert first == second
    assert first["data_isolation"] == {
        "future_target_argument_accepted": False,
        "score_or_loss_argument_accepted": False,
        "future_target_used": False,
        "scores_computed": False,
    }
    assert first["claim_boundary"]["candidate_admitted"] is False
    assert first["claim_boundary"]["superiority_claim_supported"] is False
