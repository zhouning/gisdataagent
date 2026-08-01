from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    public_reach_geometry_response as response,
)


def _audit():
    return response.compile_public_reach_geometry_response_audit()


def test_stage25_uses_exactly_the_twenty_temporal_holdout_states():
    value = _audit()
    temporal_ids = value.source.cohort_measurement_ids["temporal_holdout"]

    assert len(value.responses) == 20
    assert tuple(item.measurement_id for item in value.responses) == temporal_ids
    assert value.responses[0].time == "2023-02-10T15:04:14+00:00"
    assert value.responses[-1].time == "2026-03-27T14:14:47+00:00"


def test_stage25_keeps_state_mass_flux_velocity_and_convection_identical():
    value = _audit()

    for item in value.responses:
        rectangle = item.state_conditioned_rectangle
        candidate = item.bridge_trapezoid_candidate
        assert rectangle.physical_area_flux_m3s == item.observed_state.discharge_m3s
        assert candidate.physical_area_flux_m3s == item.observed_state.discharge_m3s
        assert rectangle.convective_momentum_flux_m4s2 == (
            candidate.convective_momentum_flux_m4s2
        )
        assert item.observed_state.mean_velocity_mps == pytest.approx(
            item.observed_state.discharge_m3s / item.observed_state.area_m2
        )


def test_stage25_identical_state_hll_flux_reduces_to_physical_flux():
    value = _audit()

    for item in value.responses:
        for diagnostic in (
            item.state_conditioned_rectangle,
            item.bridge_trapezoid_candidate,
        ):
            assert diagnostic.hll_area_flux_m3s == pytest.approx(
                diagnostic.physical_area_flux_m3s, abs=1e-10
            )
            assert diagnostic.hll_momentum_flux_m4s2 == pytest.approx(
                diagnostic.physical_momentum_flux_m4s2, abs=1e-10
            )
            assert diagnostic.hll_wave_regime == "subcritical_or_transcritical"


def test_stage25_bridge_candidate_is_deeper_with_material_pressure_response():
    value = _audit()
    report = value.as_dict()
    distributions = report["response_distributions"]

    assert all(
        item.bridge_trapezoid_candidate.depth_m
        > item.state_conditioned_rectangle.depth_m
        for item in value.responses
    )
    assert distributions["depth"]["median"] == pytest.approx(
        0.20416979174731897
    )
    assert distributions["hydrostatic_pressure_integral"][
        "median"
    ] == pytest.approx(0.13402682814644606)
    assert distributions["physical_momentum_flux"]["median"] == pytest.approx(
        0.13222639942034164
    )
    assert distributions["gravity_wave_celerity"][
        "maximum_absolute"
    ] == pytest.approx(0.05017056886492699)
    assert report["hydrostatic_geometry_response_is_material"] is True


def test_stage25_candidate_stage_inverse_remains_close_on_temporal_holdout():
    distribution = _audit().as_dict()["response_distributions"][
        "bridge_candidate_stage_error_m"
    ]

    assert distribution["median"] == pytest.approx(-0.010783595686156833)
    assert distribution["maximum_absolute"] < 0.18


def test_stage25_does_not_invent_spatial_neighbors_or_admit_runtime_geometry():
    value = _audit()
    report = value.as_dict()

    with pytest.raises(
        ValueError,
        match="public_reach_geometry_response_is_state_diagnostic_only",
    ):
        value.require_runtime_geometry_rollout()
    with pytest.raises(
        ValueError,
        match="public_reach_geometry_response_not_reach_wide_transfer",
    ):
        value.require_reach_wide_geometry_transfer()
    with pytest.raises(
        ValueError,
        match="public_reach_geometry_response_not_confluence_geometry",
    ):
        value.require_confluence_patch_geometry()
    assert report["comparison_contract"][
        "temporal_records_treated_as_adjacent_spatial_cells"
    ] is False
    assert report["claim_boundary"]["dynamic_time_advance_performed"] is False
    assert report["decision"]["operator_admitted"] is False


def test_compiled_stage25_report_passes_without_runtime_admission():
    from scripts import (
        compile_geotransport_stage25_public_geometry_response_gates as gates,
    )

    report = gates.compile_report()

    assert report["all_gates_passed"] is True
    assert len(report["gates"]) == 20
    assert all(report["gates"].values())
    assert report["decision"][
        "geometry_contract_changes_hydrodynamic_response"
    ] is True
    assert report["decision"]["mass_flux_changes_when_state_is_fixed"] is False
    assert report["decision"][
        "stage24_bridge_geometry_admitted_for_runtime"
    ] is False
    assert report["decision"]["operator_admitted"] is False
