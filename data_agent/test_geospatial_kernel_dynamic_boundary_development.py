import csv
import hashlib
import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_ROOT = REPO_ROOT / "benchmarks/geotransport_v0_1"
DATA_ROOT = REPO_ROOT / "data/geotransport_v0_1"


def _load(path: Path) -> dict:
    return json.loads(path.read_bytes())


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_public_boundary_history_and_upstream_holdout_are_frozen() -> None:
    history = _load(BENCHMARK_ROOT / "smith_fork_boundary_history_report.json")
    transition = _load(
        BENCHMARK_ROOT / "smith_fork_boundary_transition_report.json"
    )
    assert history["status"] == "pass_public_boundary_history_acquired"
    assert history["summary"]["complete_fit_hour_count"] == 5719
    assert history["summary"]["complete_holdout_hour_count"] == 2338
    assert history["claim_boundary"]["operational_vintage_verified"] is False
    assert transition["registered_gates"]["all_horizons_holdout_gate_passed"]
    assert transition["fit"]["outlet_target_fitted_parameter_count"] == 0
    assert transition["fit"]["stationary"] is True
    assert transition["fit"]["lag1_coefficient"] == pytest.approx(
        1.5941528104239209
    )
    assert transition["fit"]["lag2_coefficient"] == pytest.approx(
        -0.5967174695567611
    )
    for horizon in (1, 3, 6, 12, 24):
        values = transition["metrics_by_horizon"][str(horizon)]
        assert (
            values["autoregressive_log_boundary"]["rmse_m3s"]
            < values["causal_persistence"]["rmse_m3s"]
        )


def test_dynamic_downstream_gate_fails_without_leakage_or_mass_error() -> None:
    report_path = BENCHMARK_ROOT / "center_hill_dynamic_internal_boundary_report.json"
    report = _load(report_path)
    predictions_path = DATA_ROOT / (
        "center_hill_dynamic_internal_boundary/predictions.csv"
    )
    assert _sha(report_path) == (
        "596c6895d4bc73ca6afe4ee11cef8d10cce9f8616fa42bc1faf883cd93ee9fea"
    )
    assert _sha(predictions_path) == (
        "02123360d27163c5a62512ad267cfd6cf4b5ff3e5f6ab5593fe353bce190b119"
    )
    rows = list(csv.DictReader(predictions_path.open(encoding="utf-8")))
    assert len(rows) == 2400
    assert report["registered_gates"]["mass_gate_passed"] is True
    assert report["registered_gates"]["development_gate_passed"] is False
    assert report["diagnostics"]["future_observation_update_count"] == 0
    assert report["information_boundary"]["future_smith_fork_observation_used"] is False
    assert report["data_isolation"]["outlet_target_fitted_parameters"] == 0
    assert report["claim_boundary"]["geospatial_kernel_validated"] is False
    assert report["registered_gates"]["per_horizon"]["24"][
        "candidate_beats_held_boundary_rmse"
    ]
    for horizon in (1, 3, 6, 12):
        assert not report["registered_gates"]["per_horizon"][str(horizon)][
            "candidate_beats_held_boundary_rmse"
        ]


def test_boundary_skill_transfer_isolated_and_impulse_conserves() -> None:
    skill = _load(
        BENCHMARK_ROOT
        / "smith_fork_boundary_skill_transfer_diagnostic_report.json"
    )
    impulse = _load(
        BENCHMARK_ROOT / "smith_fork_boundary_transfer_impulse_report.json"
    )
    assert skill["diagnosis"][
        "boundary_forecast_beats_persistence_all_horizons"
    ]
    assert not skill["diagnosis"][
        "downstream_beats_held_boundary_all_core_horizons"
    ]
    assert skill["diagnosis"]["failure_location"] == (
        "spatial_support_or_downstream_dynamic_transfer"
    )
    assert impulse["path"]["feature_count"] == 12
    assert impulse["path"]["effective_length_m"] == pytest.approx(
        21719.64120377765
    )
    assert impulse["path"]["nwm_initial_velocity_travel_time_prior_hours"] == (
        pytest.approx(19.249957738787977)
    )
    assert impulse["impulse"]["peak_response_hour"] == 14
    assert impulse["impulse"]["response_center_of_mass_hour_within_window"] == (
        pytest.approx(22.00749758241208)
    )
    assert impulse["impulse"]["recovered_fraction"] == pytest.approx(
        0.9992419963541649
    )
    assert impulse["conservation"]["passed"] is True
    assert impulse["data_isolation"]["observed_outlet_discharge_used"] is False
