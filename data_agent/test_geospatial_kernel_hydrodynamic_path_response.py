from __future__ import annotations

import math

import pytest

from data_agent.test_geospatial_kernel_manning_path_response import (
    _geometry,
    _network,
)
from data_agent.uwm.geospatial_kernel_v2.hydrodynamic_path_response import (
    HYDRODYNAMIC_PATH_RESPONSE_SCHEMA,
    STANDARD_GRAVITY_MPS2,
    HydrodynamicPathResponseDiagnostic,
)


def _analyze(discharge: tuple[float, ...]):
    return HydrodynamicPathResponseDiagnostic(_network(), _geometry()).analyze(
        discharge,
        start_feature_id=10,
        end_feature_id=30,
        path_id="test:hydrodynamic:10-to-30",
        provenance_id="test:state",
        evidence_level="candidate",
        outcome_calibrated=False,
    )


def test_hydrodynamic_scale_reconstructs_trapezoid_and_physical_quantities():
    result = _analyze((20.0, 10.0, 30.0))
    reach = result.reaches[0]
    bottom_width = 8.0
    side_slope = 2.0
    bed_slope = 0.003

    assert reach.area_m2 == pytest.approx(
        reach.depth_m * (bottom_width + side_slope * reach.depth_m)
    )
    assert reach.top_width_m == pytest.approx(
        bottom_width + 2.0 * side_slope * reach.depth_m
    )
    assert reach.gravity_wave_celerity_mps == pytest.approx(
        math.sqrt(STANDARD_GRAVITY_MPS2 * reach.area_m2 / reach.top_width_m)
    )
    assert reach.hydraulic_diffusivity_m2s == pytest.approx(
        reach.discharge_m3s / (2.0 * bed_slope * reach.top_width_m)
    )
    assert reach.manning_centroid_travel_time_seconds == pytest.approx(
        reach.effective_length_m / reach.manning_dq_da_celerity_mps
    )
    assert reach.froude_number == pytest.approx(
        reach.mean_velocity_mps / reach.gravity_wave_celerity_mps
    )


def test_hydrodynamic_path_aggregates_gravity_time_and_diffusive_variance():
    result = _analyze((20.0, 10.0, 30.0))

    assert result.feature_ids == (10, 30)
    assert result.gravity_wave_travel_time_seconds == pytest.approx(
        sum(value.gravity_wave_travel_time_seconds or 0.0 for value in result.reaches)
    )
    assert result.diffusive_first_passage_standard_deviation_seconds == pytest.approx(
        math.sqrt(
            sum(
                value.diffusive_first_passage_variance_seconds2 or 0.0
                for value in result.reaches
            )
        )
    )
    assert result.gravity_to_manning_time_ratio == pytest.approx(
        result.gravity_wave_travel_time_seconds
        / result.manning_centroid_travel_time_seconds
    )
    assert result.as_dict()["schema"] == HYDRODYNAMIC_PATH_RESPONSE_SCHEMA
    assert result.as_dict()["gravity_wave_time_admitted_as_flood_wave_lag"] is False
    assert 0.0 <= result.supercritical_effective_length_fraction <= 1.0
    assert 0.0 <= result.supercritical_manning_time_fraction <= 1.0
    assert 0.0 <= result.supercritical_gravity_time_fraction <= 1.0


def test_hydrodynamic_path_is_state_dependent():
    low = _analyze((5.0, 5.0, 5.0))
    high = _analyze((50.0, 50.0, 50.0))

    assert high.gravity_wave_travel_time_seconds < low.gravity_wave_travel_time_seconds
    assert high.reaches[0].depth_m > low.reaches[0].depth_m


def test_zero_flow_is_explicitly_nonpropagating_without_infinite_values():
    result = _analyze((20.0, 0.0, 30.0))
    reach = result.reaches[0]

    assert result.nonpropagating_feature_ids == (10,)
    assert result.finite_path_scales_available is False
    assert result.gravity_wave_travel_time_seconds is None
    assert result.diffusive_first_passage_standard_deviation_seconds is None
    assert reach.depth_m == 0.0
    assert reach.gravity_wave_celerity_mps == 0.0
    assert reach.froude_number is None
    assert reach.reach_peclet_number is None
    assert reach.gravity_wave_travel_time_seconds is None
    assert reach.diffusive_first_passage_variance_seconds2 is None


def test_hydrodynamic_path_rejects_geometry_axis_mismatch():
    geometry = _geometry()
    from data_agent.uwm.geospatial_kernel_v2.contracts import ReachHydraulicGeometry

    mismatch = ReachHydraulicGeometry(
        feature_ids=(10, 20, 30),
        bottom_width_m=(8.0, 6.0, 10.0),
        side_slope_horizontal_per_vertical=(2.0, 2.0, 2.0),
        bed_slope=(0.003, 0.004, 0.002),
        manning_n=(0.035, 0.035, 0.035),
        provenance_id=geometry.provenance_id,
        evidence_level=geometry.evidence_level,
        admitted_as_hydraulic_geometry=True,
    )
    with pytest.raises(ValueError, match="hydrodynamic_path_geometry_axis_mismatch"):
        HydrodynamicPathResponseDiagnostic(_network(), mismatch)


def test_public_hydrodynamic_envelopes_select_no_simplified_operator():
    from scripts.compile_geotransport_hydrodynamic_scale_envelope import (
        compile_envelopes,
    )

    report, outputs = compile_envelopes()
    systems = {row["system_id"]: row for row in report["systems"]}

    assert len(outputs) == 2
    assert all(
        row["quality"]["finite_path_scale_hour_count"] == 672
        for row in systems.values()
    )
    assert all(
        row["envelopes"]["gravity_wave_travel_time_hours_q05_q50_q95"][1]
        < row["envelopes"][
            "manning_centroid_travel_time_hours_q05_q50_q95"
        ][1]
        for row in systems.values()
    )
    assert all(
        row["envelopes"][
            "diffusive_first_passage_standard_deviation_hours_q05_q50_q95"
        ][1]
        > row["envelopes"][
            "manning_centroid_travel_time_hours_q05_q50_q95"
        ][1]
        for row in systems.values()
    )
    assert all(
        row["envelopes"][
            "supercritical_effective_length_fraction_q05_q50_q95"
        ][1]
        < 0.05
        for row in systems.values()
    )
    assert report["claim_boundary"]["candidate_operator_implemented"] is False
    assert report["claim_boundary"]["candidate_operator_admitted"] is False
