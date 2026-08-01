from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    component_lag_replication_assessment as replication,
)
from data_agent.uwm.geospatial_kernel_v2 import empirical_lag_support


def _support(
    supported: tuple[int, ...], *, detectable: bool = True
) -> empirical_lag_support.EmpiricalLagSupport:
    if not detectable:
        correlations = tuple(
            empirical_lag_support.LagCorrelationEvidence(lag, 72, 0.7) for lag in range(13)
        )
    else:
        best = supported[0]
        correlations = tuple(
            empirical_lag_support.LagCorrelationEvidence(
                lag,
                72,
                0.9 - 0.01 * supported.index(lag) if lag in supported else 0.7,
            )
            for lag in range(13)
        )
        assert best not in {0, 12}
    return empirical_lag_support.compile_empirical_lag_support(correlations)


def _event(
    rank: int,
    stratum: str,
    supported: tuple[int, ...],
    *,
    detectable: bool = True,
) -> replication.ComponentLagReplicationEventResult:
    return replication.ComponentLagReplicationEventResult(
        event_id=f"event-{rank}",
        selection_rank=rank,
        selection_stratum=stratum,
        lag_support=_support(supported, detectable=detectable),
    )


def _passing_events() -> tuple[replication.ComponentLagReplicationEventResult, ...]:
    return (
        _event(1, "high_increase", (5,)),
        _event(2, "high_decrease", (5, 6)),
        _event(3, "low_increase", (6, 7)),
        _event(4, "low_decrease", (6,)),
    )


def test_component_lag_replication_admits_support_membership_for_all_strata():
    result = replication.compile_component_lag_replication_assessment(_passing_events())

    assert result.high_flow_bidirectional_replication_passed is True
    assert result.low_flow_bidirectional_replication_passed is True
    assert result.cohort_replication_admitted is True
    assert result.failed_strata == ()
    result.require_cohort_replication()


def test_component_lag_replication_rejects_one_direction_without_partial_pass():
    events = list(_passing_events())
    events[1] = _event(2, "high_decrease", (6,))

    result = replication.compile_component_lag_replication_assessment(tuple(events))

    assert result.high_flow_bidirectional_replication_passed is False
    assert result.low_flow_bidirectional_replication_passed is True
    assert result.cohort_replication_admitted is False
    assert result.failed_strata == ("high_decrease",)
    with pytest.raises(ValueError, match="cohort_replication_not_admitted"):
        result.require_cohort_replication()


def test_component_lag_replication_rejects_undetectable_response():
    events = list(_passing_events())
    events[2] = _event(3, "low_increase", (), detectable=False)

    result = replication.compile_component_lag_replication_assessment(tuple(events))
    event = result.events[2]

    assert event.replication_passed is False
    assert event.rejection_reasons == (
        "event_response_not_detectable",
        "required_low_flow_lag_6h_not_supported",
    )


def test_component_lag_replication_requires_exact_frozen_strata_and_order():
    events = list(_passing_events())
    events[0], events[1] = events[1], events[0]

    with pytest.raises(ValueError, match="four_frozen_strata_required"):
        replication.compile_component_lag_replication_assessment(tuple(events))


def test_component_lag_replication_refuses_stronger_promotions_even_on_pass():
    result = replication.compile_component_lag_replication_assessment(_passing_events())

    for method, message in (
        (result.require_universal_lag, "not_universal_lag"),
        (result.override_stage30_falsification, "cannot_override_stage30"),
        (result.require_non_turbine_component_contrast, "contrast_unadmitted"),
        (result.require_causal_or_physical_relation, "causal_physical_unadmitted"),
        (result.promote_to_runtime_operator, "runtime_operator_unadmitted"),
    ):
        with pytest.raises(ValueError, match=message):
            method()


def test_component_lag_replication_report_preserves_claim_boundary():
    report = replication.compile_component_lag_replication_assessment(_passing_events()).as_dict()

    assert report["decision"]["cohort_replication_admitted"] is True
    assert report["decision"]["universal_lag_admitted"] is False
    assert report["decision"]["stage30_historical_falsification_overturned"] is False
    assert report["claim_boundary"]["support_membership_not_exact_hour_equality"] is True
    assert report["claim_boundary"]["event_reselection_allowed"] is False
