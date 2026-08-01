from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from data_agent.uwm.geospatial_kernel_v2.conservative_edge_flux_innovation import (
    ConservativeEdgeFluxInnovationConfig,
    ConservativeEdgeFluxInnovationOperator,
    EdgeFluxInnovation,
)
from data_agent.uwm.geospatial_kernel_v2.conservative_flux import (
    ConservativeFluxConfig,
    ConservativeFluxOperator,
)
from data_agent.uwm.geospatial_kernel_v2.contracts import (
    ActionBoundaryFlux,
    BoundaryOperator,
    EdgeFlux,
    EvidenceStructure,
    GeoComplex,
    HierarchyOperator,
    MetricStructure,
    StockState,
)

ISSUE = datetime(2024, 1, 1, 12, tzinfo=UTC)


def _complex(*, admitted=(True, True), evidence=("derived", "derived")) -> GeoComplex:
    return GeoComplex(
        B=BoundaryOperator(
            node_keys=("upstream", "middle", "downstream"),
            edge_keys=("upstream-middle", "middle-downstream"),
            source_indices=(0, 1),
            target_indices=(1, 2),
        ),
        H=HierarchyOperator(
            parent_keys=("basin",),
            node_parent_indices=(0, 0, 0),
            aggregation_weights=(1.0, 1.0, 1.0),
        ),
        M=MetricStructure(
            node_measure=(1.0, 1.0, 1.0),
            edge_capacity_per_second=(5.0, 5.0),
            edge_travel_time_seconds=(3600.0, 3600.0),
        ),
        E=EvidenceStructure(
            edge_admitted=admitted,
            edge_source_ids=("nldi:1", "nldi:2"),
            evidence_level=evidence,
        ),
        crs="EPSG:5070",
    )


def _operator(complex_: GeoComplex | None = None) -> ConservativeEdgeFluxInnovationOperator:
    base = ConservativeFluxOperator(
        complex_ or _complex(),
        ConservativeFluxConfig(
            stock_unit="m3",
            flux_unit="m3 s-1",
            timestep_seconds=1.0,
        ),
    )
    return ConservativeEdgeFluxInnovationOperator(
        base,
        ConservativeEdgeFluxInnovationConfig(allow_unadmitted_innovation_for_diagnostics=True),
    )


def _innovation(values=(1.0, 0.0), **changes) -> EdgeFluxInnovation:
    fields = {
        "edge_keys": ("upstream-middle", "middle-downstream"),
        "values": values,
        "unit": "m3 s-1",
        "valid_at": ISSUE + timedelta(hours=1),
        "available_at": ISSUE,
        "provenance_id": "learned-edge-innovation:test",
        "evidence_level": "candidate",
        "admitted": False,
        "causal_inputs_verified": True,
        "future_target_observation_used": False,
    }
    fields.update(changes)
    return EdgeFluxInnovation(**fields)


def test_positive_edge_innovation_moves_stock_without_external_mass() -> None:
    result = _operator().step(
        StockState((10.0, 0.0, 0.0), "m3", "state"),
        EdgeFlux((2.0, 0.0), "m3 s-1", "physical-base"),
        _innovation(),
        issue_time=ISSUE,
    )

    assert result.base_counterfactual.next_stock.values == pytest.approx((8.0, 2.0, 0.0))
    assert result.hybrid.next_stock.values == pytest.approx((7.0, 3.0, 0.0))
    assert result.realized_applied_edge_flux_delta == pytest.approx((1.0, 0.0))
    assert result.state_delta_due_to_innovation == pytest.approx((-1.0, 1.0, 0.0))
    assert result.state_delta_global_sum == pytest.approx(0.0)
    assert result.external_mass_introduced_by_innovation_m3 == 0.0
    assert result.topology_unchanged is True
    assert result.diagnostic_only is True
    assert result.as_dict()["innovation_mass_ledger"]["global_zero_external_mass_passed"] is True


def test_negative_innovation_cannot_reverse_authoritative_edge() -> None:
    result = _operator().step(
        StockState((10.0, 0.0, 0.0), "m3", "state"),
        EdgeFlux((2.0, 0.0), "m3 s-1", "physical-base"),
        _innovation(values=(-3.0, 0.0)),
        issue_time=ISSUE,
    )

    assert result.raw_combined_edge_flux == pytest.approx((-1.0, 0.0))
    assert result.combined_edge_flux_before_projection == pytest.approx((0.0, 0.0))
    assert result.authoritative_direction_clipped_edges == (True, False)
    assert result.state_delta_due_to_innovation == pytest.approx((2.0, -2.0, 0.0))
    assert result.state_delta_global_sum == pytest.approx(0.0)


def test_capacity_projection_records_realized_not_requested_innovation() -> None:
    result = _operator().step(
        StockState((20.0, 0.0, 0.0), "m3", "state"),
        EdgeFlux((4.0, 0.0), "m3 s-1", "physical-base"),
        _innovation(values=(10.0, 0.0)),
        issue_time=ISSUE,
    )

    assert result.requested_innovation_edge_flux == pytest.approx((10.0, 0.0))
    assert result.hybrid.applied_edge_flux == pytest.approx((5.0, 0.0))
    assert result.realized_applied_edge_flux_delta == pytest.approx((1.0, 0.0))
    assert result.hybrid.capacity_limited_edges == (True, False)


def test_external_channels_are_identical_in_base_and_hybrid_counterfactuals() -> None:
    action = ActionBoundaryFlux((1.0, 0.0, 0.0), "m3 s-1", "dam-action")
    result = _operator().step(
        StockState((10.0, 0.0, 0.0), "m3", "state"),
        EdgeFlux((2.0, 0.0), "m3 s-1", "physical-base"),
        _innovation(),
        issue_time=ISSUE,
        action=action,
    )

    assert result.base_counterfactual.applied_action_flux == (1.0, 0.0, 0.0)
    assert result.hybrid.applied_action_flux == (1.0, 0.0, 0.0)
    assert result.state_delta_global_sum == pytest.approx(0.0)


def test_innovation_rejects_axis_temporal_and_admission_violations() -> None:
    stock = StockState((10.0, 0.0, 0.0), "m3", "state")
    base = EdgeFlux((2.0, 0.0), "m3 s-1", "physical-base")
    operator = _operator()

    with pytest.raises(ValueError, match="edge_axis_mismatch"):
        operator.step(
            stock,
            base,
            _innovation(edge_keys=("wrong", "middle-downstream")),
            issue_time=ISSUE,
        )
    with pytest.raises(ValueError, match="not_available_at_issue"):
        operator.step(
            stock,
            base,
            _innovation(available_at=ISSUE + timedelta(seconds=1)),
            issue_time=ISSUE,
        )
    with pytest.raises(ValueError, match="admission_invalid"):
        replace(_innovation(), admitted=True)
    with pytest.raises(ValueError, match="future_target_observation_forbidden"):
        replace(_innovation(), future_target_observation_used=True)


def test_innovation_time_axis_is_causal_and_forecast_facing() -> None:
    with pytest.raises(
        ValueError,
        match="edge_flux_innovation_available_after_valid_time",
    ):
        _innovation(
            valid_at=ISSUE,
            available_at=ISSUE + timedelta(seconds=1),
        )

    with pytest.raises(
        ValueError,
        match="edge_flux_innovation_valid_before_issue",
    ):
        _operator().step(
            StockState((10.0, 0.0, 0.0), "m3", "state"),
            EdgeFlux((2.0, 0.0), "m3 s-1", "physical-base"),
            _innovation(
                valid_at=ISSUE - timedelta(seconds=1),
                available_at=ISSUE - timedelta(hours=1),
            ),
            issue_time=ISSUE,
        )


def test_innovation_rejects_unadmitted_or_candidate_edges() -> None:
    stock = StockState((10.0, 0.0, 0.0), "m3", "state")
    base = EdgeFlux((0.0, 0.0), "m3 s-1", "physical-base")
    with pytest.raises(ValueError, match="on_unadmitted_edge"):
        _operator(_complex(admitted=(False, True))).step(
            stock,
            base,
            _innovation(),
            issue_time=ISSUE,
        )

    admitted = _innovation(
        evidence_level="derived",
        admitted=True,
        causal_inputs_verified=True,
    )
    with pytest.raises(ValueError, match="candidate_edge"):
        _operator(_complex(evidence=("candidate", "derived"))).step(
            stock,
            base,
            admitted,
            issue_time=ISSUE,
        )
