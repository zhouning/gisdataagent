from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2 import empirical_lag_support
from data_agent.uwm.geospatial_kernel_v2 import (
    public_identifiable_response_evidence as stage31,
)


def _compile(event):
    return empirical_lag_support.compile_empirical_lag_support(
        tuple(
            empirical_lag_support.LagCorrelationEvidence(
                value.lag_hours,
                value.pair_count,
                value.pearson_r,
            )
            for value in event.lag_diagnostics
        )
    )


def test_empirical_lag_support_preserves_stage31_discrete_sets():
    events = stage31.compile_public_identifiable_response_evidence().events
    supports = [_compile(value) for value in events]

    assert [value.supported_lags_hours for value in supports] == [
        (5, 6),
        (5, 6),
        (6,),
        (5, 6),
    ]
    assert [value.support_interval_hours for value in supports] == [
        (5, 6),
        (5, 6),
        (6, 6),
        (5, 6),
    ]
    assert [value.exact_hour_resolved for value in supports] == [
        False,
        False,
        True,
        False,
    ]


def test_empirical_lag_support_rejects_weak_response():
    candidates = tuple(
        empirical_lag_support.LagCorrelationEvidence(
            lag,
            72,
            0.4 + 0.01 * lag if lag <= 6 else 0.46 - 0.01 * (lag - 6),
        )
        for lag in range(13)
    )

    support = empirical_lag_support.compile_empirical_lag_support(candidates)

    assert support.best_lag_hours == 6
    assert support.response_detectable is False
    assert support.supported_lags_hours == ()
    with pytest.raises(ValueError, match="response_not_detectable"):
        support.require_empirical_support_set()


def test_empirical_lag_support_exact_and_set_access_are_distinct():
    events = stage31.compile_public_identifiable_response_evidence().events
    broad = _compile(events[0])
    exact = _compile(events[2])

    assert broad.require_empirical_support_set() == (5, 6)
    with pytest.raises(ValueError, match="exact_hour_not_resolved"):
        broad.require_exact_hour()
    assert exact.require_empirical_support_set() == (6,)
    assert exact.require_exact_hour() == 6


def test_empirical_graph_relation_binds_support_without_physical_promotion():
    event = stage31.compile_public_identifiable_response_evidence().events[0]
    relation = empirical_lag_support.EmpiricalGraphRelationLagSupport(
        "CETT1-CENTER_HILL",
        "operational_tailwater_zone",
        "USGS-03424860",
        18421703,
        "empirical_downstream_response",
        event.event_id,
        _compile(event),
    )

    report = relation.as_dict()
    assert report["source"]["spatial_role"] == "operational_tailwater_zone"
    assert report["target"]["comid"] == 18421703
    assert report["lag_support"]["supported_lags_hours"] == [5, 6]
    with pytest.raises(ValueError, match="not_hydraulic_edge_time"):
        relation.require_hydraulic_edge_travel_time()
    with pytest.raises(ValueError, match="runtime_transition_unadmitted"):
        relation.promote_to_runtime_transition()


def test_empirical_lag_support_refuses_physical_and_runtime_use():
    event = stage31.compile_public_identifiable_response_evidence().events[2]
    support = _compile(event)

    with pytest.raises(ValueError, match="not_physical_travel_time"):
        support.require_physical_travel_time()
    with pytest.raises(ValueError, match="runtime_delay_unadmitted"):
        support.promote_to_runtime_delay()
