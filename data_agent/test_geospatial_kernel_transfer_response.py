import hashlib
import json
from pathlib import Path

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    analyze_dynamic_transfer_response,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_transfer_response_interpolates_volume_quantiles_and_closes_mass() -> None:
    result = analyze_dynamic_transfer_response(
        (0.0, 1.0, 2.0, 1.0),
        timestep_seconds=1.0,
        input_volume_m3=4.0,
        final_incremental_storage_m3=0.0,
    )

    assert result.mass_balance_passed is True
    assert result.positive_outlet_volume_m3 == 4.0
    assert result.net_recovered_fraction == 1.0
    assert result.center_of_positive_response_seconds == pytest.approx(2.5)
    assert result.peak_positive_interval_end_seconds == 3.0
    assert dict(result.within_window_positive_volume_quantile_seconds) == {
        "t01": pytest.approx(1.04),
        "t05": pytest.approx(1.2),
        "t50": pytest.approx(2.5),
        "t95": pytest.approx(3.8),
    }
    assert dict(result.input_recovery_quantile_seconds) == {
        "t01": pytest.approx(1.04),
        "t05": pytest.approx(1.2),
        "t50": pytest.approx(2.5),
        "t95": pytest.approx(3.8),
    }


def test_transfer_response_reports_negative_lobe_without_clipping() -> None:
    result = analyze_dynamic_transfer_response(
        (1.0, -0.2),
        timestep_seconds=1.0,
        input_volume_m3=0.8,
        final_incremental_storage_m3=0.0,
        absolute_mass_tolerance_m3=1e-12,
        negative_lobe_relative_tolerance=1e-12,
    )

    assert result.positive_outlet_volume_m3 == 1.0
    assert result.negative_outlet_volume_m3 == pytest.approx(0.2)
    assert result.net_outlet_volume_m3 == pytest.approx(0.8)
    assert result.mass_balance_passed is True
    assert result.negative_lobe_within_tolerance is False
    assert result.minimum_response_m3s == -0.2


def test_transfer_response_marks_unrecovered_input_quantile_as_null() -> None:
    result = analyze_dynamic_transfer_response(
        (0.1, 0.1),
        timestep_seconds=1.0,
        input_volume_m3=1.0,
        final_incremental_storage_m3=0.8,
    )

    assert result.mass_balance_passed is True
    assert dict(result.input_recovery_quantile_seconds)["t50"] is None
    assert dict(result.within_window_positive_volume_quantile_seconds)[
        "t50"
    ] == pytest.approx(1.0)


@pytest.mark.parametrize(
    "response,kwargs,error",
    [
        ((), {}, "nonempty_finite_vector"),
        ((1.0,), {"timestep_seconds": 0.0}, "timestep_and_input"),
        ((float("nan"),), {}, "nonempty_finite_vector"),
    ],
)
def test_transfer_response_rejects_invalid_inputs(
    response: tuple[float, ...], kwargs: dict[str, float], error: str
) -> None:
    arguments = {
        "timestep_seconds": 1.0,
        "input_volume_m3": 1.0,
        "final_incremental_storage_m3": 0.0,
        **kwargs,
    }
    with pytest.raises(ValueError, match=error):
        analyze_dynamic_transfer_response(response, **arguments)


def test_smith_fork_v2_response_quantiles_are_frozen_and_outcome_free() -> None:
    path = REPO_ROOT / (
        "benchmarks/geotransport_v0_1/"
        "smith_fork_boundary_transfer_impulse_v2_report.json"
    )
    body = path.read_bytes()
    report = json.loads(body)

    assert hashlib.sha256(body).hexdigest() == (
        "f3daaca5059f9c8628d4380d788fa7006bd120df3a0d3123ba0a5a59aa231898"
    )
    assert report["certification_gates"][
        "all_outcome_free_response_gates_passed"
    ]
    metrics = report["dynamic_transfer_response"]
    assert metrics["input_recovery_quantile_seconds"]["t01"] == pytest.approx(
        22030.94400073649
    )
    assert metrics["input_recovery_quantile_seconds"]["t50"] == pytest.approx(
        62493.32336344276
    )
    assert metrics["input_recovery_quantile_seconds"]["t95"] == pytest.approx(
        172793.64703871898
    )
    assert metrics["negative_outlet_volume_m3"] == 0.0
    assert report["data_isolation"]["observed_outlet_discharge_used"] is False
    assert report["claim_boundary"]["transfer_dynamics_validated"] is False


def test_troute_mc_response_matrix_freezes_failed_promotion_gate() -> None:
    path = REPO_ROOT / (
        "benchmarks/geotransport_v0_1/"
        "t_route_mc_response_matrix_report.json"
    )
    body = path.read_bytes()
    report = json.loads(body)

    assert hashlib.sha256(body).hexdigest() == (
        "d84b1b34c4dc3874fedc4f0cd012815fb342b948fb726abe610dbe3a02d4b075"
    )
    assert len(report["cases"]) == 27
    assert report["gates"]["all_nonlinear_case_mass_identities_passed"]
    assert report["gates"]["nonlinear_timestep_stability"]
    assert not report["gates"][
        "all_official_mc_negative_lobes_within_tolerance"
    ]
    assert not report["gates"]["official_mc_timestep_stability"]
    assert not report["gates"]["all_registered_matrix_gates_passed"]
    assert report["data_isolation"]["observed_discharge_loaded"] is False
    assert not report["claim_boundary"][
        "professional_transfer_operator_certified"
    ]
