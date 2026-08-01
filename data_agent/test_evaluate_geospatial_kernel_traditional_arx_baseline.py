import csv
import hashlib
import io
import json

import pytest

from scripts import evaluate_geospatial_kernel_traditional_arx_baseline as arx


def _paths(tmp_path):
    return {
        "parameter_path": tmp_path / "parameters.json",
        "primary_prediction_path": tmp_path / "primary.csv",
        "replication_prediction_path": tmp_path / "replication.csv",
    }


def test_traditional_arx_uses_matched_source_fit_and_never_admits(tmp_path) -> None:
    bodies, report = arx.compile_traditional_arx_posthoc(**_paths(tmp_path))
    parameters = json.loads(bodies["parameters"])
    rows = list(
        csv.DictReader(
            io.StringIO(bodies["replication_predictions"].decode("utf-8"))
        )
    )

    assert parameters["intercept_m3s"] == pytest.approx(4.461125413775087)
    assert parameters["autoregressive_coefficient"] == pytest.approx(
        0.9423431036513937
    )
    assert parameters["action_level_coefficient"] == pytest.approx(
        0.035331089570226085
    )
    assert parameters["forcing_coefficient"] == pytest.approx(0.7731862149391386)
    assert parameters["lag_hours"] == [5, 6, 7]
    assert parameters["training_sample_count"] == 161
    assert parameters["asymptotically_stable"] is True
    assert parameters["target_outcomes_used_for_fit"] is False
    assert parameters["admitted"] is False
    contract = report["baseline_contract"]
    assert contract["free_parameter_count"] == 4
    assert contract["source_fit_hour_count"] == 168
    assert contract["same_source_fit_window_as_wwm"] is True
    assert contract["same_action_lag_hours_as_wwm"] is True
    assert contract["same_action_lag_weights_as_wwm"] is True
    assert contract["same_target_rows_as_wwm"] is True
    assert contract["per_target_window_refit_performed"] is False
    assert report["claim_boundary"]["arx_parameters_admitted"] is False
    assert report["claim_boundary"]["wwm_candidate_admitted"] is False
    assert report["claim_boundary"]["geospatial_kernel_validated"] is False
    assert report["claim_boundary"]["runtime_default_enabled"] is False
    assert rows
    assert all(row["future_outcome_observation_used"] == "False" for row in rows)
    assert all(row["operational_vintages_verified"] == "False" for row in rows)
    assert len({row["arx_parameter_sha256"] for row in rows}) == 1


def test_traditional_arx_posthoc_result_exposes_simple_baseline_gap(tmp_path) -> None:
    _, report = arx.compile_traditional_arx_posthoc(**_paths(tmp_path))
    primary = report["primary_window"]["comparison"]
    replication = report["replication_window"]["comparison"]

    assert primary["arx_beats_persistence_all_horizons"] is True
    assert primary["arx_beats_wwm_all_horizons"] is False
    assert replication["arx_beats_persistence_all_horizons"] is True
    assert replication["arx_beats_wwm_all_horizons"] is True
    assert primary["per_horizon"]["12"]["arx_minus_wwm_rmse_m3s"] == pytest.approx(
        2.4360276958309584
    )
    assert all(
        value["arx_minus_wwm_rmse_m3s"] < 0.0
        for value in replication["per_horizon"].values()
    )
    assert report["diagnostic_interpretation"][
        "arx_beats_persistence_all_horizons_in_both_windows"
    ] is True
    assert report["diagnostic_interpretation"][
        "t_route_mc_physical_baseline_still_required"
    ] is True
    assert report["information_boundary"][
        "evaluation_counts_as_fresh_validation"
    ] is False


def test_arx_parameters_compile_before_target_outcome_load(tmp_path, monkeypatch) -> None:
    events = []
    original_load_json = arx.cross._load_json
    original_json_body = arx._json_body

    def tracking_load_json(path):
        if path == arx.DEFAULT_PRIMARY_OUTCOME_REPORT:
            events.append("target_outcome_load")
        return original_load_json(path)

    def tracking_json_body(value):
        if value.get("schema") == arx.CLASSICAL_ARX_SCHEMA:
            events.append("arx_parameter_compile")
        return original_json_body(value)

    monkeypatch.setattr(arx.cross, "_load_json", tracking_load_json)
    monkeypatch.setattr(arx, "_json_body", tracking_json_body)

    arx.compile_traditional_arx_posthoc(**_paths(tmp_path))

    assert events == ["arx_parameter_compile", "target_outcome_load"]


def test_traditional_arx_outputs_are_deterministic_and_bound(tmp_path) -> None:
    paths = _paths(tmp_path)
    first_bodies, first_report = arx.compile_traditional_arx_posthoc(**paths)
    second_bodies, second_report = arx.compile_traditional_arx_posthoc(**paths)

    assert first_bodies == second_bodies
    assert first_report["parameter_lock"] == second_report["parameter_lock"]
    assert first_report["primary_window"] == second_report["primary_window"]
    assert first_report["replication_window"] == second_report["replication_window"]
    for name, body in first_bodies.items():
        descriptor = first_report["outputs"][name]
        assert descriptor["sha256"] == hashlib.sha256(body).hexdigest()
        assert descriptor["size_bytes"] == len(body)


@pytest.mark.parametrize("descriptor", ["source_parameters", "target_action"])
def test_traditional_arx_rejects_tampered_descriptors(tmp_path, descriptor) -> None:
    paths = _paths(tmp_path)
    if descriptor == "source_parameters":
        payload = json.loads(arx.DEFAULT_FREEZE.read_text(encoding="utf-8"))
        payload["candidate_artifacts"]["parameters"]["sha256"] = "0" * 64
        tampered = tmp_path / "freeze.json"
        tampered.write_text(json.dumps(payload), encoding="utf-8")
        kwargs = {"freeze_path": tampered}
    else:
        payload = json.loads(
            arx.DEFAULT_PRIMARY_INPUT_REPORT.read_text(encoding="utf-8")
        )
        payload["systems"][arx.cross.SYSTEM_ID]["action_values"]["sha256"] = (
            "0" * 64
        )
        tampered = tmp_path / "inputs.json"
        tampered.write_text(json.dumps(payload), encoding="utf-8")
        kwargs = {"primary_input_report_path": tampered}

    with pytest.raises(
        ValueError, match="cross_system_posthoc_artifact_identity_mismatch"
    ):
        arx.compile_traditional_arx_posthoc(**paths, **kwargs)
