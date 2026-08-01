from __future__ import annotations

import numpy as np
import pytest

from data_agent.uwm.geospatial_kernel_v2.transport_response_families import (
    AnalyticTransportFamilyCase,
    evaluate_transport_family_profile,
)


def _case(family: str, **overrides):
    values = {
        "case_id": f"test:{family}",
        "family": family,
        "initial_volume_m3": 1_000.0,
        "initial_center_m": 0.0,
        "initial_standard_deviation_m": 100.0,
        "elapsed_seconds": 300.0,
    }
    if family == "kinematic":
        values["advection_celerity_mps"] = 2.0
    elif family == "diffusive":
        values["advection_celerity_mps"] = 2.0
        values["diffusion_coefficient_m2s"] = 25.0
    else:
        values["gravity_wave_celerity_mps"] = 4.0
    values.update(overrides)
    return AnalyticTransportFamilyCase(**values)


def test_kinematic_reference_translates_without_spreading():
    case = _case("kinematic")

    assert case.expected_centroid_m == 600.0
    assert case.expected_variance_m2 == 10_000.0
    assert len(case.components) == 1


def test_diffusive_reference_spreads_and_has_kinematic_zero_diffusion_limit():
    case = _case("diffusive")
    zero_diffusion = _case("diffusive", diffusion_coefficient_m2s=0.0)
    kinematic = _case("kinematic")
    coordinates = np.linspace(-2_000.0, 2_000.0, 4001)

    assert case.expected_centroid_m == 600.0
    assert case.expected_variance_m2 == 25_000.0
    assert np.array_equal(
        zero_diffusion.profile_incremental_area_m2(coordinates),
        kinematic.profile_incremental_area_m2(coordinates),
    )


def test_local_inertial_reference_retains_second_order_wave_memory():
    case = _case("local_inertial")

    assert len(case.components) == 2
    assert [value.center_m for value in case.components] == [-1_200.0, 1_200.0]
    assert case.expected_centroid_m == 0.0
    assert case.expected_variance_m2 == 1_450_000.0


def test_all_families_reduce_to_initial_gaussian_at_zero_time():
    coordinates = np.linspace(-1_000.0, 1_000.0, 2001)
    profiles = [
        _case(family, elapsed_seconds=0.0).profile_incremental_area_m2(coordinates)
        for family in ("kinematic", "diffusive", "local_inertial")
    ]

    assert np.array_equal(profiles[0], profiles[1])
    assert np.array_equal(profiles[0], profiles[2])


def test_sampled_analytic_profile_passes_volume_centroid_and_variance_gates():
    case = _case("local_inertial")
    coordinates = np.linspace(-6_000.0, 6_000.0, 12_001)
    profile = case.profile_incremental_area_m2(coordinates)
    result = evaluate_transport_family_profile(
        case,
        coordinates_m=coordinates,
        profile_incremental_area_m2=profile,
        maximum_relative_volume_error=1e-10,
        maximum_absolute_centroid_error_m=1e-8,
        maximum_relative_variance_error=1e-10,
    )

    assert result.all_gates_passed is True
    assert result.integrated_volume_m3 == pytest.approx(1_000.0)


def test_profile_gate_reports_mass_failure_without_relabelling_family():
    case = _case("kinematic")
    coordinates = np.linspace(-3_000.0, 3_000.0, 6_001)
    profile = 0.9 * case.profile_incremental_area_m2(coordinates)
    result = evaluate_transport_family_profile(
        case,
        coordinates_m=coordinates,
        profile_incremental_area_m2=profile,
        maximum_relative_volume_error=1e-3,
        maximum_absolute_centroid_error_m=1e-8,
        maximum_relative_variance_error=1e-10,
    )

    assert result.family == "kinematic"
    assert result.volume_gate_passed is False
    assert result.all_gates_passed is False


@pytest.mark.parametrize(
    ("family", "overrides", "message"),
    [
        ("kinematic", {"diffusion_coefficient_m2s": 1.0}, "diffusion_must_be_zero"),
        ("diffusive", {"diffusion_coefficient_m2s": -1.0}, "coefficient_invalid"),
        ("local_inertial", {"gravity_wave_celerity_mps": 0.0}, "celerity_contract"),
    ],
)
def test_family_case_rejects_equation_parameter_mismatch(family, overrides, message):
    with pytest.raises(ValueError, match=message):
        _case(family, **overrides)


def test_compiled_family_protocol_is_outcome_independent_and_not_admission():
    from scripts.compile_geotransport_transport_response_family_gates import (
        compile_gates,
    )

    report = compile_gates()

    assert report["gates"]["all_sampled_profile_gates_passed"] is True
    assert report["gates"]["all_limiting_gates_passed"] is True
    assert report["data_isolation"]["observation_values_read"] is False
    assert report["claim_boundary"]["candidate_operator_implemented"] is False
    assert report["claim_boundary"]["candidate_operator_admitted"] is False
