import csv
import hashlib
import io
import json

import pytest

from scripts.evaluate_geospatial_kernel_action_innovation_cross_system import (
    DEFAULT_INPUT_REPORT,
    compile_cross_system_posthoc,
)


def _paths(tmp_path):
    return {
        "transferred_parameter_path": tmp_path / "parameters.json",
        "prediction_path": tmp_path / "predictions.csv",
        "replication_prediction_path": tmp_path / "replication_predictions.csv",
    }


def test_cross_system_posthoc_is_zero_refit_and_never_validation(tmp_path) -> None:
    bodies, report = compile_cross_system_posthoc(**_paths(tmp_path))
    transferred = json.loads(bodies["transferred_parameters"])
    rows = list(csv.DictReader(io.StringIO(bodies["predictions"].decode("utf-8"))))

    assert report["system_id"] == "j_percy_priest"
    assert report["transfer_contract"]["coefficient_refit_performed"] is False
    assert report["transfer_contract"]["target_outcomes_used_for_parameter_fit"] is False
    assert report["transfer_contract"]["baseline_drift_unchanged"] is True
    assert report["transfer_contract"]["action_change_coefficient_unchanged"] is True
    assert report["transfer_contract"]["forcing_coefficient_unchanged"] is True
    assert report["transfer_contract"]["lag_hours_unchanged"] is True
    assert report["transfer_contract"]["lag_weights_unchanged"] is True
    assert transferred["support"]["network_id"].startswith("j-percy-priest:")
    assert transferred["support"]["lag_hours"] == [5, 6, 7]
    assert transferred["admitted"] is False
    assert report["information_boundary"][
        "target_outcomes_were_exposed_before_candidate_freeze"
    ] is True
    assert report["information_boundary"]["fresh_prospective_window_consumed"] is False
    assert report["claim_boundary"]["geospatial_kernel_validated"] is False
    assert report["claim_boundary"]["multi_system_generalization_validated"] is False
    assert report["claim_boundary"]["operational_forecast_validated"] is False
    assert report["claim_boundary"]["candidate_admitted"] is False
    assert report["claim_boundary"]["source_candidate_artifacts_unchanged"] is True
    assert report["claim_boundary"][
        "transferred_parameter_identity_is_separate_diagnostic_artifact"
    ] is True
    assert report["diagnostic_interpretation"][
        "zero_refit_transfer_supported"
    ] is False
    assert report["diagnostic_interpretation"][
        "failure_replicated_on_second_historical_window"
    ] is True
    assert report["diagnostic_interpretation"][
        "candidate_beats_persistence_horizons_hours"
    ] == [12]
    assert report["diagnostic_interpretation"][
        "result_may_trigger_refit_on_these_windows"
    ] is False
    assert report["diagnostic_interpretation"][
        "result_may_motivate_new_candidate_identity"
    ] is True
    assert report["claim_boundary"]["cross_system_failure_replicated"] is True
    assert report["replication_window"]["diagnostic_gate"][
        "cross_system_diagnostic_gate_passed"
    ] is False
    assert rows
    replication_rows = list(
        csv.DictReader(
            io.StringIO(bodies["replication_predictions"].decode("utf-8"))
        )
    )
    assert replication_rows
    assert {row["parameter_sha256"] for row in rows} == {
        row["parameter_sha256"] for row in replication_rows
    }
    assert all(row["future_outcome_observation_used"] == "False" for row in rows)
    assert all(row["operational_vintages_verified"] == "False" for row in rows)
    assert all(
        row["target_state_writeback_m3s"]
        == row["action_innovation_candidate_m3s"]
        for row in rows
    )


def test_cross_system_posthoc_outputs_are_deterministic_and_bound(tmp_path) -> None:
    paths = _paths(tmp_path)
    first_bodies, first_report = compile_cross_system_posthoc(**paths)
    second_bodies, second_report = compile_cross_system_posthoc(**paths)

    assert first_bodies == second_bodies
    assert first_report["metrics_by_horizon"] == second_report["metrics_by_horizon"]
    assert first_report["diagnostic_gate"] == second_report["diagnostic_gate"]
    for name, body in first_bodies.items():
        descriptor = first_report["outputs"][name]
        assert descriptor["sha256"] == hashlib.sha256(body).hexdigest()
        assert descriptor["size_bytes"] == len(body)


def test_cross_system_posthoc_rejects_tampered_source_descriptor(tmp_path) -> None:
    payload = json.loads(DEFAULT_INPUT_REPORT.read_text(encoding="utf-8"))
    payload["systems"]["j_percy_priest"]["action_values"]["sha256"] = "0" * 64
    tampered = tmp_path / "inputs.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        ValueError, match="cross_system_posthoc_artifact_identity_mismatch"
    ):
        compile_cross_system_posthoc(
            input_report_path=tampered,
            **_paths(tmp_path),
        )
