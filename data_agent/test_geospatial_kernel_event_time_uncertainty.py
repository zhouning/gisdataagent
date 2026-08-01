from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2.event_time_uncertainty import (
    ClosedTemporalInterval,
    EventTimePhysicsCompatibility,
    EventTimeUncertaintyReconciliation,
    ObservationSupportUncertainty,
    compile_relative_event_delay_envelope,
)


def _support(source=1.0, target=1.0):
    return ObservationSupportUncertainty(
        source, target, "end", "end", True
    )


def _envelope(lags=(5, 6, 7), *, event="union"):
    return compile_relative_event_delay_envelope(
        "center-hill-tailwater-to-stonewall",
        "center-hill-tailwater-to-stonewall-path",
        lags,
        _support(),
        f"test:{event}",
    )


def test_end_labeled_supports_compile_event_offset_sets():
    value = _support()

    assert value.source_event_offset_hours == (-1.0, 0.0)
    assert value.target_event_offset_hours == (-1.0, 0.0)
    assert value.delay_interval_for_label_shift(5) == (
        ClosedTemporalInterval(4.0, 6.0)
    )


def test_asymmetric_supports_preserve_directional_delay_bounds():
    value = _support(source=1.0, target=0.5)

    assert value.delay_interval_for_label_shift(5) == (
        ClosedTemporalInterval(4.5, 6.0)
    )


def test_adjacent_discrete_lags_merge_only_after_support_dilation():
    value = _envelope()

    assert value.label_shifts_hours == (5, 6, 7)
    assert value.intervals == (ClosedTemporalInterval(4.0, 8.0),)
    assert value.nonempty is True


def test_nonadjacent_lags_preserve_disconnected_delay_sets():
    value = _envelope((2, 6))

    assert value.intervals == (
        ClosedTemporalInterval(1.0, 3.0),
        ClosedTemporalInterval(5.0, 7.0),
    )


def test_empty_empirical_support_remains_empty_after_dilation():
    value = _envelope((), event="empty")

    assert value.intervals == ()
    assert value.nonempty is False


def test_support_envelope_is_not_itself_an_admitted_physical_delay():
    with pytest.raises(ValueError, match="is_not_physical_delay"):
        _envelope().require_physical_event_delay()


def test_physics_gap_is_measured_after_maximum_support_uncertainty():
    value = EventTimePhysicsCompatibility(
        _envelope(),
        "gravity_wave_time",
        ClosedTemporalInterval(1.1636556564598701, 1.2434852223876611),
        True,
        False,
        False,
    )

    assert value.measurement_support_overlap is False
    assert value.minimum_separation_hours == pytest.approx(
        2.756514777612339
    )
    assert value.physical_comparison_admitted is False


def test_measurement_overlap_cannot_override_semantic_refusal():
    value = EventTimePhysicsCompatibility(
        _envelope(),
        "gravity_wave_time",
        ClosedTemporalInterval(7.5, 9.0),
        True,
        False,
        True,
    )

    assert value.measurement_support_overlap is True
    assert value.overlapping_intervals == (
        ClosedTemporalInterval(7.5, 8.0),
    )
    assert value.physical_comparison_admitted is False
    with pytest.raises(ValueError, match="physical_comparison_unadmitted"):
        value.require_physical_comparison()


def test_empty_event_blocks_cross_event_uncertainty_intersection():
    union = _envelope()
    compatibility = EventTimePhysicsCompatibility(
        union,
        "gravity_wave_time",
        ClosedTemporalInterval(1.0, 2.0),
        True,
        False,
        False,
    )
    value = EventTimeUncertaintyReconciliation(
        (
            _envelope((5, 6, 7), event="one"),
            _envelope((6, 7), event="two"),
            _envelope((7,), event="three"),
            _envelope((), event="four"),
        ),
        union,
        (compatibility,),
        False,
    )

    assert value.all_events_have_nonempty_support is False
    assert value.common_event_delay_intervals == ()
    assert value.physical_response_time_admitted is False
    with pytest.raises(ValueError, match="common_delay_unadmitted"):
        value.require_common_event_delay_intervals()


def test_runtime_promotion_always_fails_closed():
    union = _envelope()
    value = EventTimeUncertaintyReconciliation(
        (_envelope((), event="empty"),),
        union,
        (
            EventTimePhysicsCompatibility(
                union,
                "gravity_wave_time",
                ClosedTemporalInterval(1.0, 2.0),
                True,
                False,
                False,
            ),
        ),
        False,
    )

    with pytest.raises(ValueError, match="runtime_transition_unadmitted"):
        value.promote_to_runtime_transition()
