import csv
import hashlib
import io
import json

import pytest

from scripts.evaluate_geospatial_kernel_action_innovation_candidate import (
    compile_candidate,
)


def _paths(tmp_path):
    return {
        "parameter_output_path": tmp_path / "parameters.json",
        "development_prediction_path": tmp_path / "development.csv",
        "january_prediction_path": tmp_path / "january.csv",
        "d3_prediction_path": tmp_path / "d3.csv",
    }


def test_action_innovation_candidate_fits_only_original_development_rows(tmp_path) -> None:
    bodies, report = compile_candidate(**_paths(tmp_path))
    parameters = json.loads(bodies["parameters"])

    assert parameters["training_sample_count"] == 160
    assert parameters["baseline_drift_m3s_per_hour"] == pytest.approx(-1.0346407218186344)
    assert parameters["action_change_coefficient"] == pytest.approx(0.32988884961354664)
    assert parameters["forcing_coefficient"] == pytest.approx(0.714133532750197)
    assert parameters["state_persistence_coefficient_fixed"] == 1.0
    assert parameters["asymptotic_stability_claimed"] is False
    assert report["kernel"]["fit"]["design_rank"] == 3
    assert report["kernel"]["fit"]["design_condition_number"] == pytest.approx(42.31174249904882)
    assert (
        report["selection_boundary"]["fit_uses_first_168_original_development_hours_only"] is True
    )
    assert report["selection_boundary"]["fit_uses_temporal_transfer_outcomes"] is False
    assert report["parameter_lock"]["all_evaluations_use_deserialized_parameter_artifact"] is True
    assert report["parameter_lock"]["per_window_refit_performed"] is False


def test_candidate_passes_development_and_posthoc_windows_without_admission(tmp_path) -> None:
    bodies, report = compile_candidate(**_paths(tmp_path))

    assert report["aggregate_gate"] == {
        "development_gate_passed": True,
        "both_posthoc_temporal_window_gates_passed": True,
        "candidate_diagnostic_gate_passed": True,
        "admission_gate_passed": False,
    }
    expected = {
        "january_temporal_holdout": {
            "counts": {"1": 502, "3": 500, "6": 497, "12": 491},
            "rmse": {"1": 9.604262493454396, "12": 43.60932343653482},
        },
        "february_d3": {
            "counts": {"1": 663, "3": 661, "6": 658, "12": 652},
            "rmse": {"1": 20.370158746158733, "12": 70.34280834748138},
        },
    }
    for window_id, expected_values in expected.items():
        result = report["posthoc_temporal_diagnostics"][window_id]
        assert (
            result["scoring"]["common_complete_case_count_by_horizon"] == expected_values["counts"]
        )
        assert result["metrics_by_horizon"]["1"]["candidate"]["rmse_m3s"] == pytest.approx(
            expected_values["rmse"]["1"]
        )
        assert result["metrics_by_horizon"]["12"]["candidate"]["rmse_m3s"] == pytest.approx(
            expected_values["rmse"]["12"]
        )
        assert result["hard_gate"]["window_diagnostic_gate_passed"] is True
    assert (
        report["selection_boundary"][
            "architecture_revised_after_prior_mvp_transfer_outcomes_were_seen"
        ]
        is True
    )
    assert report["claim_boundary"]["geospatial_kernel_validated"] is False
    assert report["claim_boundary"]["action_innovation_closure_admitted_as_default"] is False
    assert report["selection_boundary"]["new_target_data_acquired"] is False

    for name in (
        "development_predictions",
        "january_temporal_holdout_predictions",
        "february_d3_predictions",
    ):
        rows = list(csv.DictReader(io.StringIO(bodies[name].decode("utf-8"))))
        assert all(row["future_outcome_observation_used"] == "False" for row in rows)
        assert all(
            float(row["target_state_writeback_m3s"])
            == float(row["action_innovation_candidate_m3s"])
            for row in rows
            if row["action_innovation_candidate_m3s"]
        )


def test_candidate_output_descriptors_bind_exact_bodies(tmp_path) -> None:
    paths = _paths(tmp_path)
    bodies, report = compile_candidate(**paths)

    for name, body in bodies.items():
        descriptor = report["outputs"][name]
        path = paths[
            {
                "parameters": "parameter_output_path",
                "development_predictions": "development_prediction_path",
                "january_temporal_holdout_predictions": "january_prediction_path",
                "february_d3_predictions": "d3_prediction_path",
            }[name]
        ]
        assert descriptor["path"] == str(path.resolve())
        assert descriptor["sha256"] == hashlib.sha256(body).hexdigest()
        assert descriptor["size_bytes"] == len(body)
