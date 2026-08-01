import csv
import hashlib
import io
import json

from scripts.evaluate_geospatial_kernel_action_innovation_uncertainty import (
    compile_uncertainty_candidate,
)


def _paths(tmp_path):
    return {
        "parameter_output_path": tmp_path / "parameters.json",
        "development_prediction_path": tmp_path / "development.csv",
        "january_prediction_path": tmp_path / "january.csv",
        "d3_prediction_path": tmp_path / "d3.csv",
    }


def test_uncertainty_calibration_uses_only_post_fit_development_rows(tmp_path) -> None:
    bodies, report = compile_uncertainty_candidate(**_paths(tmp_path))
    parameters = json.loads(bodies["parameters"])

    assert parameters["calibration_sample_count"] == [475, 475, 475, 475]
    assert parameters["target_marginal_coverage"] == 0.9
    assert (
        report["calibration"]["point_training_outcomes_reused_for_uncertainty_calibration"] is False
    )
    assert report["selection_boundary"]["uncertainty_fit_uses_january_outcomes"] is False
    assert report["selection_boundary"]["uncertainty_fit_uses_february_d3_outcomes"] is False
    assert report["calibration_gate"]["calibration_complete"] is True
    assert report["calibration_gate"]["admission_gate_passed"] is False


def test_uncertainty_posthoc_diagnostics_do_not_inflate_claims(tmp_path) -> None:
    _, report = compile_uncertainty_candidate(**_paths(tmp_path))

    assert report["status"] == (
        "uncertainty_candidate_calibrated_posthoc_diagnostics_complete_not_validated"
    )
    assert report["statistical_claim_boundary"] == {
        "time_series_exchangeability_claimed": False,
        "finite_sample_coverage_guarantee_claimed": False,
        "conditional_coverage_guarantee_claimed": False,
        "posthoc_coverage_is_validation": False,
        "empirical_horizon_specific_residual_envelope_implemented": True,
    }
    assert report["operational_claim_boundary"]["operational_forecast_validated"] is False
    assert report["operational_claim_boundary"]["uncertainty_candidate_admitted"] is False


def test_uncertainty_outputs_bind_exact_interval_rows(tmp_path) -> None:
    paths = _paths(tmp_path)
    bodies, report = compile_uncertainty_candidate(**paths)
    parameter_hash = hashlib.sha256(bodies["parameters"]).hexdigest()

    for name in (
        "development_intervals",
        "january_temporal_holdout_intervals",
        "february_d3_intervals",
    ):
        body = bodies[name]
        rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))
        assert rows
        assert all(row["uncertainty_parameter_sha256"] == parameter_hash for row in rows)
        assert all(row["future_outcome_observation_used_at_inference"] == "False" for row in rows)
        descriptor = report["outputs"][name]
        assert descriptor["sha256"] == hashlib.sha256(body).hexdigest()
        assert descriptor["size_bytes"] == len(body)


def test_uncertainty_radii_and_coverage_are_horizon_specific(tmp_path) -> None:
    bodies, report = compile_uncertainty_candidate(**_paths(tmp_path))
    parameters = json.loads(bodies["parameters"])

    radii = parameters["absolute_error_radius_m3s"]
    assert radii == sorted(radii)
    assert all(value > 0.0 for value in radii)
    for window in (
        report["calibration"]["evaluation"],
        *report["posthoc_temporal_diagnostics"].values(),
    ):
        for horizon in ("1", "3", "6", "12"):
            metrics = window["metrics_by_horizon"][horizon]
            assert metrics["sample_count"] >= 475
            assert 0.0 <= metrics["empirical_marginal_coverage"] <= 1.0
            assert metrics["mean_interval_width_m3s"] > 0.0
