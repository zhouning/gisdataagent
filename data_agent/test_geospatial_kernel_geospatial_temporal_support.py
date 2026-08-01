from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2.geospatial_temporal_support import (
    ContinuousTemporalSupport,
    DiscreteTemporalSupport,
    GeospatialTemporalSupportReconciliation,
    compile_temporal_support_compatibility,
)


def _empirical(hours=(5, 6, 7)):
    return DiscreteTemporalSupport(
        "center-hill-tailwater-to-stonewall",
        "empirical_downstream_response_lag",
        hours,
        "stage32:test",
        True,
    )


def _physics(
    *,
    lower=15.5,
    central=16.0,
    upper=16.8,
    admitted=False,
):
    return ContinuousTemporalSupport(
        "manning-envelope",
        "center-hill-tailwater-to-stonewall-path",
        "manning_kinematic_centroid_time",
        lower,
        central,
        upper,
        "public-state:test",
        True,
        False,
        admitted,
    )


def test_discrete_empirical_support_requires_typed_sorted_hours():
    value = _empirical()

    assert value.supported_hours == (5, 6, 7)
    assert value.as_dict()["physical_time_admitted"] is False
    with pytest.raises(ValueError, match="discrete_temporal_support_invalid"):
        _empirical((6, 5))


def test_continuous_physics_support_requires_ordered_finite_interval():
    value = _physics()

    assert value.quantity == "manning_kinematic_centroid_time"
    assert value.as_dict()["support_interval_hours"] == [15.5, 16.8]
    with pytest.raises(ValueError, match="continuous_temporal_support_invalid"):
        _physics(lower=17.0, central=16.0, upper=15.0)


def test_nonoverlapping_support_reports_minimum_separation():
    value = compile_temporal_support_compatibility(
        _empirical(),
        _physics(),
        same_spatial_path=True,
    )

    assert value.overlapping_empirical_hours == ()
    assert value.numerical_overlap is False
    assert value.minimum_separation_hours == pytest.approx(8.5)
    assert value.physical_consistency_admitted is False


def test_numerical_overlap_does_not_promote_unadmitted_physics():
    value = compile_temporal_support_compatibility(
        _empirical(),
        _physics(lower=5.5, central=6.0, upper=6.5),
        same_spatial_path=True,
    )

    assert value.overlapping_empirical_hours == (6,)
    assert value.minimum_separation_hours == 0.0
    assert value.physical_consistency_admitted is False
    with pytest.raises(ValueError, match="physical_consistency_unadmitted"):
        value.require_physical_consistency()


def test_admitted_physics_still_requires_same_path():
    physics = _physics(
        lower=5.5,
        central=6.0,
        upper=6.5,
        admitted=True,
    )
    wrong_path = compile_temporal_support_compatibility(
        _empirical(),
        physics,
        same_spatial_path=False,
    )
    same_path = compile_temporal_support_compatibility(
        _empirical(),
        physics,
        same_spatial_path=True,
    )

    assert wrong_path.physical_consistency_admitted is False
    assert same_path.require_physical_consistency() == (6,)


def test_reconciliation_requires_common_empirical_support_for_admission():
    empirical = _empirical()
    compatibility = compile_temporal_support_compatibility(
        empirical,
        _physics(
            lower=5.5,
            central=6.0,
            upper=6.5,
            admitted=True,
        ),
        same_spatial_path=True,
    )
    rejected = GeospatialTemporalSupportReconciliation(
        empirical.relation_id,
        compatibility.physics.path_id,
        empirical,
        (compatibility,),
        False,
    )
    admitted = GeospatialTemporalSupportReconciliation(
        empirical.relation_id,
        compatibility.physics.path_id,
        empirical,
        (compatibility,),
        True,
    )

    assert rejected.physics_consistency_admitted is False
    with pytest.raises(ValueError, match="physics_consistency_unadmitted"):
        rejected.require_physics_consistent_support()
    assert admitted.require_physics_consistent_support() == (6,)


def test_reconciliation_runtime_promotion_always_fails_closed():
    empirical = _empirical()
    compatibility = compile_temporal_support_compatibility(
        empirical,
        _physics(),
        same_spatial_path=True,
    )
    value = GeospatialTemporalSupportReconciliation(
        empirical.relation_id,
        compatibility.physics.path_id,
        empirical,
        (compatibility,),
        False,
    )

    with pytest.raises(ValueError, match="runtime_transition_unadmitted"):
        value.promote_to_runtime_transition()
