from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    FiniteVolumeKinematicWaveOperator,
    KinematicWaveConfig,
    LinearReferencedPath,
    ReachHydraulicGeometry,
)
from data_agent.uwm.geospatial_kernel_v2.kinematic_wave import _manning_celerity


REPO_ROOT = Path(__file__).resolve().parents[1]


def _contracts() -> tuple[LinearReferencedPath, ReachHydraulicGeometry]:
    path = LinearReferencedPath(
        "kw-test",
        (101, 102),
        (1200.0, 800.0),
        (0.0, 0.0),
        (1200.0, 800.0),
        "kw-test:path",
        "derived",
    )
    geometry = ReachHydraulicGeometry(
        (101, 102),
        (10.0, 12.0),
        (2.0, 1.5),
        (0.002, 0.001),
        (0.035, 0.04),
        "kw-test:geometry",
        "derived",
        True,
    )
    return path, geometry


def _operator(*, timestep: float = 300.0, target: float = 500.0):
    path, geometry = _contracts()
    return FiniteVolumeKinematicWaveOperator(
        path,
        geometry,
        KinematicWaveConfig(
            timestep_seconds=timestep,
            target_cell_length_m=target,
            cfl_number=0.8,
            path_admitted=True,
            operator_form_admitted=False,
            allow_unadmitted_components_for_diagnostics=True,
        ),
    )


def test_kinematic_wave_subdivides_reaches_on_stable_cell_axis() -> None:
    operator = _operator(target=500.0)
    state = operator.zero_state(provenance_id="kw:zero")

    assert operator.reach_cell_counts == (3, 2)
    assert state.cell_feature_ids == (101, 101, 101, 102, 102)
    assert state.cell_index_within_reach == (0, 1, 2, 0, 1)
    assert state.cell_volume_m3 == (0.0,) * 5


def test_kinematic_wave_uniform_discharge_is_steady_and_conservative() -> None:
    operator = _operator()
    state = operator.uniform_discharge_state(20.0, provenance_id="kw:steady")
    result = operator.step(
        state,
        boundary_inflow_m3s=20.0,
        provenance_id="kw:steady:step",
    )

    assert result.next_state.cell_volume_m3 == pytest.approx(
        state.cell_volume_m3, rel=1e-11, abs=1e-9
    )
    assert result.reach_mean_outflow_m3s == pytest.approx((20.0, 20.0))
    assert abs(result.global_mass_balance_residual_m3) <= (
        result.numeric_mass_tolerance_m3
    )
    assert result.maximum_courant_number <= 0.8 + 1e-12
    assert result.diagnostic_only is True


def test_kinematic_wave_boundary_pulse_preserves_nonnegative_mass() -> None:
    operator = _operator(timestep=3600.0, target=250.0)
    state = operator.zero_state(provenance_id="kw:pulse:zero")
    result = operator.step(
        state,
        boundary_inflow_m3s=10.0,
        provenance_id="kw:pulse:step",
    )

    volume = np.asarray(result.next_state.cell_volume_m3)
    assert (volume >= 0.0).all()
    assert result.input_volume_m3 == 36_000.0
    assert result.final_storage_m3 + result.outlet_volume_m3 == pytest.approx(
        36_000.0, abs=result.numeric_mass_tolerance_m3
    )
    assert result.integration_substep_count > 1
    assert result.maximum_courant_number <= 0.8 + 1e-12


def test_kinematic_wave_celerity_has_finite_dry_limit() -> None:
    celerity = _manning_celerity(
        np.asarray([0.0, np.nextafter(0.0, 1.0), 1e-300, 1.0]),
        np.full(4, 10.0),
        np.full(4, 2.0),
        np.full(4, 0.002),
        np.full(4, 0.035),
    )

    assert np.isfinite(celerity).all()
    assert (celerity >= 0.0).all()
    assert celerity[0] == 0.0


def test_kinematic_wave_rejects_unadmitted_operator_without_diagnostic_flag() -> None:
    path, geometry = _contracts()
    with pytest.raises(ValueError, match="kinematic_wave_unadmitted_component_not_allowed"):
        FiniteVolumeKinematicWaveOperator(
            path,
            geometry,
            KinematicWaveConfig(timestep_seconds=300.0),
        )


def test_kinematic_wave_state_axis_is_fail_closed() -> None:
    operator = _operator()
    state = operator.zero_state(provenance_id="kw:zero")
    wrong = type(state)(
        tuple(reversed(state.cell_feature_ids)),
        state.cell_index_within_reach,
        state.cell_volume_m3,
        "kw:wrong",
    )
    with pytest.raises(ValueError, match="kinematic_wave_state_cell_axis_mismatch"):
        operator.step(
            wrong,
            boundary_inflow_m3s=0.0,
            provenance_id="kw:wrong:step",
        )


def test_kinematic_wave_response_matrix_freezes_diagnostic_boundary() -> None:
    path = REPO_ROOT / (
        "benchmarks/geotransport_v0_1/"
        "kinematic_wave_response_matrix_report.json"
    )
    body = path.read_bytes()
    report = json.loads(body)

    assert hashlib.sha256(body).hexdigest() == (
        "5331a93555d43ec40cc5ea017615b26fb42ad0f6ae87403b65242be87322fdf6"
    )
    assert report["schema"] == (
        "gwm.geotransport.kinematic_wave_response_matrix.v1"
    )
    assert len(report["cases"]) == 27
    assert sum(len(case["resolutions"]) for case in report["cases"]) == 81

    gates = report["gates"]
    assert gates["all_step_mass_identities_passed"]
    assert gates["all_response_mass_identities_passed"]
    assert gates["all_states_nonnegative_finite"]
    assert gates["all_negative_lobes_within_tolerance"]
    assert gates["all_cfl_limits_respected"]
    assert gates["primary_resolution_timestep_stability"]
    assert gates["primary_to_fine_spatial_stability"]
    assert not gates["spatial_refinement_error_nonincreasing"]
    assert not gates["all_registered_diagnostic_gates_passed"]

    temporal = report["temporal_timestep_stability"]
    spatial = report["spatial_subdivision_stability"]
    assert temporal["comparison_count"] == 54
    assert temporal["all_comparisons_passed"]
    assert spatial["primary_to_fine"]["comparison_count"] == 81
    assert spatial["primary_to_fine"]["all_comparisons_passed"]
    assert sum(
        not item["passed"]
        for item in spatial["refinement_trend"]["comparisons"]
    ) == 2
    assert report["operator_contract"]["diagnostic_only"] is True
    assert report["claim_boundary"]["operator_form_admitted"] is False
    assert report["data_isolation"]["observed_discharge_loaded"] is False


def test_kinematic_wave_analytic_shock_converges_without_promotion() -> None:
    path = REPO_ROOT / (
        "benchmarks/geotransport_v0_1/"
        "kinematic_wave_analytic_shock_report.json"
    )
    body = path.read_bytes()
    report = json.loads(body)

    assert hashlib.sha256(body).hexdigest() == (
        "ff792f0dad1f4119696fcd35482e250c2478a58621422683f0f77f0a0e174d7a"
    )
    assert report["schema"] == (
        "gwm.geotransport.kinematic_wave_analytic_shock.v1"
    )
    assert report["analytic_solution"]["lax_entropy_condition"] is True
    assert report["gates"]["all_registered_analytic_gates_passed"]
    assert report["convergence"]["comparison_count"] == 3
    errors = [
        item["normalized_l1_area_error"] for item in report["resolutions"]
    ]
    assert errors == sorted(errors, reverse=True)
    assert all(
        item["state_bounded_by_riemann_states"]
        for item in report["resolutions"]
    )
    assert report["claim_boundary"][
        "finite_volume_consistency_supported"
    ]
    assert report["claim_boundary"]["operator_form_admitted"] is False
    assert report["data_isolation"]["external_data_loaded"] is False
