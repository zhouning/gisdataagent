import csv
import hashlib
import io
import json

import pytest

from scripts import (
    evaluate_geospatial_kernel_scale_normalized_action_innovation as scale,
)


def _paths(tmp_path):
    return {
        "parameter_path": tmp_path / "parameters.json",
        "candidate_identity_path": tmp_path / "identity.json",
        "prediction_path": tmp_path / "predictions.csv",
    }


def test_scale_normalized_successor_locks_only_drift_and_never_admits(
    tmp_path,
) -> None:
    bodies, report = scale.compile_scale_normalized_successor(**_paths(tmp_path))
    parameters = json.loads(bodies["parameters"])
    identity = json.loads(bodies["candidate_identity"])
    rows = list(
        csv.DictReader(io.StringIO(bodies["predictions"].decode("utf-8")))
    )

    assert parameters["source_action_scale"]["scale_m3s"] == pytest.approx(
        334.198255167
    )
    assert parameters["target_action_scale"]["scale_m3s"] == pytest.approx(
        130.2574943
    )
    assert parameters["scale_ratio"] == pytest.approx(0.38976114412958224)
    assert parameters["scaled_baseline_drift_m3s_per_hour"] == pytest.approx(
        -0.40326275174962606
    )
    base = parameters["base_target_parameters"]
    assert base["action_change_coefficient"] == pytest.approx(0.32988884570396676)
    assert base["forcing_coefficient"] == pytest.approx(0.7141335342714641)
    assert base["support"]["lag_hours"] == [5, 6, 7]
    assert parameters["action_change_coefficient_unchanged"] is True
    assert parameters["forcing_coefficient_unchanged"] is True
    assert parameters["lag_support_unchanged"] is True
    assert parameters["target_outcome_values_used"] is False
    assert parameters["admitted"] is False

    assert identity["operator_lock"][
        "target_outcomes_used_for_scale_or_parameters"
    ] is False
    assert identity["admission_contract"]["candidate_admitted"] is False
    assert identity["admission_contract"]["runtime_default_enabled"] is False
    assert identity["claim_boundary"]["geospatial_kernel_validated"] is False
    assert report["selection_boundary"][
        "target_outcomes_used_for_scale_or_parameter_selection"
    ] is False
    assert report["selection_boundary"][
        "evaluation_counts_as_fresh_validation"
    ] is False
    assert report["claim_boundary"]["scale_normalized_candidate_admitted"] is False
    assert report["claim_boundary"]["runtime_default_enabled"] is False
    assert rows
    assert all(row["future_outcome_observation_used"] == "False" for row in rows)
    assert all(row["operational_vintages_verified"] == "False" for row in rows)


def test_scale_normalized_successor_records_posthoc_falsification(tmp_path) -> None:
    _, report = scale.compile_scale_normalized_successor(**_paths(tmp_path))
    comparison = report["comparison_to_unscaled_candidate"]

    assert report["status"] == "scale_normalized_successor_posthoc_gate_failed"
    assert comparison["all_horizons_improved"] is False
    assert comparison["clipped_step_count_reduction"] == 363
    assert all(
        values["scaled_minus_unscaled_rmse_m3s"] > 0.0
        for values in comparison["metrics_by_horizon"].values()
    )
    assert report["diagnostic_interpretation"][
        "posthoc_scale_normalization_supported"
    ] is False
    assert report["diagnostic_interpretation"]["clipping_reduced"] is True
    assert report["claim_boundary"][
        "posthoc_scale_normalization_supported"
    ] is False


def test_candidate_identity_is_compiled_before_outcome_document_load(
    tmp_path, monkeypatch
) -> None:
    events = []
    original_load_json = scale.cross._load_json
    original_json_body = scale._json_body

    def tracking_load_json(path):
        if path == scale.DEFAULT_EVALUATION_OUTCOME_REPORT:
            events.append("outcome_document_load")
        return original_load_json(path)

    def tracking_json_body(value):
        if value.get("schema") == scale.IDENTITY_SCHEMA:
            events.append("candidate_identity_compiled")
        return original_json_body(value)

    monkeypatch.setattr(scale.cross, "_load_json", tracking_load_json)
    monkeypatch.setattr(scale, "_json_body", tracking_json_body)

    scale.compile_scale_normalized_successor(**_paths(tmp_path))

    assert events == ["candidate_identity_compiled", "outcome_document_load"]


def test_scale_normalized_outputs_are_deterministic_and_bound(tmp_path) -> None:
    paths = _paths(tmp_path)
    first_bodies, first_report = scale.compile_scale_normalized_successor(**paths)
    second_bodies, second_report = scale.compile_scale_normalized_successor(**paths)

    assert first_bodies == second_bodies
    assert first_report["scale_contract"] == second_report["scale_contract"]
    assert first_report["evaluation"] == second_report["evaluation"]
    assert first_report["comparison_to_unscaled_candidate"] == second_report[
        "comparison_to_unscaled_candidate"
    ]
    assert first_report["candidate_identity_sha256"] == hashlib.sha256(
        first_bodies["candidate_identity"]
    ).hexdigest()
    for name, body in first_bodies.items():
        descriptor = first_report["outputs"][name]
        assert descriptor["sha256"] == hashlib.sha256(body).hexdigest()
        assert descriptor["size_bytes"] == len(body)


@pytest.mark.parametrize("descriptor", ["source_parameters", "target_action"])
def test_scale_normalized_successor_rejects_tampered_descriptors(
    tmp_path, descriptor
) -> None:
    paths = _paths(tmp_path)
    if descriptor == "source_parameters":
        payload = json.loads(scale.DEFAULT_FREEZE.read_text(encoding="utf-8"))
        payload["candidate_artifacts"]["parameters"]["sha256"] = "0" * 64
        tampered = tmp_path / "freeze.json"
        tampered.write_text(json.dumps(payload), encoding="utf-8")
        kwargs = {"freeze_path": tampered}
    else:
        payload = json.loads(
            scale.DEFAULT_SCALE_INPUT_REPORT.read_text(encoding="utf-8")
        )
        payload["systems"][scale.cross.SYSTEM_ID]["action_values"]["sha256"] = (
            "0" * 64
        )
        tampered = tmp_path / "scale-inputs.json"
        tampered.write_text(json.dumps(payload), encoding="utf-8")
        kwargs = {"scale_input_report_path": tampered}

    with pytest.raises(
        ValueError, match="cross_system_posthoc_artifact_identity_mismatch"
    ):
        scale.compile_scale_normalized_successor(**paths, **kwargs)
