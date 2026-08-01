from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2.contracts import TemporalSupport
from data_agent.uwm.geospatial_kernel_v2.temporal_response_semantics import (
    GeospatialResponseSemanticReconciliation,
    ResponseTimeSemantics,
    TemporalFieldSemantics,
    compile_response_semantic_compatibility,
)


def _source_field():
    return TemporalFieldSemantics(
        "cwms-center-hill-release",
        "operational_tailwater_zone",
        "discharge",
        "m3/s",
        "interval_average",
        TemporalSupport(
            "interval_mean",
            3600.0,
            "end",
            "cwms:timeseries-doc",
            "authoritative",
        ),
        None,
        None,
        "cwms:center-hill",
    )


def _target_field():
    return TemporalFieldSemantics(
        "usgs-stonewall-hourly",
        "observed_outlet_node",
        "discharge",
        "m3/s",
        "instantaneous_sample_mean",
        TemporalSupport(
            "interval_sample_mean",
            3600.0,
            "end",
            "usgs:00011:two-samples",
            "derived",
        ),
        1800.0,
        2,
        "usgs:03424860",
    )


def _response(quantity: str, *, admitted: bool = False):
    values = {
        "empirical_downstream_response_lag": (
            "discharge_series",
            "interval_end_label_step",
            "windowed_linear_association_peak",
            False,
            True,
        ),
        "gravity_wave_time": (
            "hydraulic_disturbance",
            "physical_boundary_perturbation",
            "first_signal_arrival",
            True,
            False,
        ),
        "manning_kinematic_centroid_time": (
            "discharge_perturbation",
            "physical_boundary_perturbation",
            "response_centroid",
            True,
            False,
        ),
        "advective_residence_time": (
            "water_mass",
            "material_injection",
            "material_exit_centroid",
            True,
            False,
        ),
    }
    carrier, source, target, state, outcome = values[quantity]
    return ResponseTimeSemantics(
        quantity,
        "center-hill-tailwater-to-stonewall-path",
        carrier,
        source,
        target,
        state,
        outcome,
        admitted,
        f"test:{quantity}",
    )


def test_source_field_is_authoritative_end_labeled_interval_average():
    value = _source_field()

    assert value.statistic == "interval_average"
    assert value.temporal_support.kind == "interval_mean"
    assert value.temporal_support.timestamp_position == "end"
    value.require_continuous_interval_average()


def test_target_field_is_derived_mean_of_two_instantaneous_samples():
    value = _target_field()

    assert value.statistic == "instantaneous_sample_mean"
    assert value.native_sampling_interval_seconds == 1800.0
    assert value.native_samples_per_compiled_support == 2
    with pytest.raises(ValueError, match="continuous_interval_average_unadmitted"):
        value.require_continuous_interval_average()


def test_fields_admit_hour_label_shift_but_not_physical_equivalence():
    source = _source_field()
    target = _target_field()

    assert source.require_label_shift_grid(target) == 3600.0
    with pytest.raises(
        ValueError, match="physical_observation_equivalence_unadmitted"
    ):
        source.require_physical_observation_equivalence(target)


def test_interval_average_does_not_identify_actuation_instant():
    with pytest.raises(ValueError, match="actuation_instant_unadmitted"):
        _source_field().require_actuation_instant()


def test_field_statistic_and_temporal_support_must_agree():
    with pytest.raises(ValueError, match="statistic_support_mismatch"):
        TemporalFieldSemantics(
            "bad",
            "outlet",
            "discharge",
            "m3/s",
            "interval_average",
            _target_field().temporal_support,
            None,
            None,
            "test:bad",
        )


@pytest.mark.parametrize(
    ("quantity", "carrier", "functional"),
    [
        ("gravity_wave_time", "hydraulic_disturbance", "first_signal_arrival"),
        (
            "manning_kinematic_centroid_time",
            "discharge_perturbation",
            "response_centroid",
        ),
        ("advective_residence_time", "water_mass", "material_exit_centroid"),
    ],
)
def test_physics_time_quantities_retain_distinct_process_semantics(
    quantity, carrier, functional
):
    value = _response(quantity)

    assert value.carrier == carrier
    assert value.target_response_functional == functional
    assert value.outcome_derived is False


def test_same_path_and_time_dimension_do_not_make_processes_substitutable():
    empirical = _response("empirical_downstream_response_lag")
    value = compile_response_semantic_compatibility(
        empirical,
        _response("gravity_wave_time", admitted=True),
        same_spatial_path=True,
        numerical_overlap=True,
    )

    assert value.semantic_equivalence_admitted is False
    assert value.physical_response_comparison_admitted is False
    assert value.rejection_reasons == (
        "transport_carrier_mismatch",
        "source_event_marker_mismatch",
        "target_response_functional_mismatch",
    )


def test_current_physics_candidates_also_retain_admission_and_overlap_refusals():
    value = compile_response_semantic_compatibility(
        _response("empirical_downstream_response_lag"),
        _response("advective_residence_time"),
        same_spatial_path=True,
        numerical_overlap=False,
    )

    assert "candidate_physical_response_time_unadmitted" in (
        value.rejection_reasons
    )
    assert "numerical_support_disjoint" in value.rejection_reasons
    with pytest.raises(ValueError, match="physical_comparison_unadmitted"):
        value.require_physical_response_comparison()


def test_reconciliation_admits_label_grid_and_rejects_physical_runtime_use():
    empirical = _response("empirical_downstream_response_lag")
    compatibilities = tuple(
        compile_response_semantic_compatibility(
            empirical,
            _response(quantity),
            same_spatial_path=True,
            numerical_overlap=False,
        )
        for quantity in (
            "gravity_wave_time",
            "manning_kinematic_centroid_time",
            "advective_residence_time",
        )
    )
    value = GeospatialResponseSemanticReconciliation(
        _source_field(),
        _target_field(),
        empirical,
        compatibilities,
        False,
    )

    assert value.require_label_shift_grid_seconds() == 3600.0
    assert value.physical_response_time_admitted is False
    with pytest.raises(ValueError, match="physical_time_unadmitted"):
        value.require_physical_response_time()
    with pytest.raises(ValueError, match="runtime_transition_unadmitted"):
        value.promote_to_runtime_transition()
