from __future__ import annotations

import csv
import hashlib
import io
import json

import pytest

from data_agent.uwm.geospatial_kernel_v2.physical_residual_retention import (
    PHYSICAL_RESIDUAL_RETENTION_SCHEMA,
    physical_residual_retention_parameters_from_dict,
)
from scripts import evaluate_geospatial_kernel_action_innovation_cross_system as cross
from scripts import evaluate_geospatial_kernel_physical_residual_retention_transfer as retention


def _paths(tmp_path):
    return {
        "parameter_path": tmp_path / "parameters.json",
        "primary_prediction_path": tmp_path / "primary.csv",
        "replication_prediction_path": tmp_path / "replication.csv",
    }


def test_residual_retention_fits_source_only_and_transfers_four_weights(tmp_path) -> None:
    bodies, report = retention.compile_physical_residual_retention_transfer_posthoc(
        **_paths(tmp_path)
    )
    parameters = json.loads(bodies["parameters"])
    primary_rows = list(csv.DictReader(io.StringIO(bodies["primary_predictions"].decode())))
    replication_rows = list(csv.DictReader(io.StringIO(bodies["replication_predictions"].decode())))

    assert parameters["schema"] == PHYSICAL_RESIDUAL_RETENTION_SCHEMA
    assert parameters["free_parameter_count"] == 4
    assert parameters["source_system_id"] == "center_hill"
    assert parameters["source_outcomes_used_for_fit"] is True
    assert parameters["target_outcomes_used_for_fit"] is False
    assert parameters["weight_bounds_applied"] is False
    assert parameters["admitted"] is False
    expected = {
        "1": (2, 0.8752229735358447, 668),
        "3": (4, 0.5788704015044208, 666),
        "6": (7, 0.07817966206284103, 663),
        "12": (13, -0.31010903245272353, 657),
    }
    for horizon, (elapsed, weight, pair_count) in expected.items():
        value = parameters["weights_by_horizon"][horizon]
        assert value["elapsed_from_latest_observation_hours"] == elapsed
        assert value["weight"] == pytest.approx(weight)
        assert value["training_pair_count"] == pair_count
    assert report["source_fit_contract"]["target_system_id"] == "j_percy_priest"
    assert report["source_fit_contract"]["per_target_window_refit_performed"] is False
    assert report["source_fit_contract"]["same_parameters_used_across_target_windows"] is True
    assert report["claim_boundary"]["physical_residual_retention_admitted"] is False
    assert report["claim_boundary"]["physical_residual_retention_promoted"] is False
    assert report["claim_boundary"]["geospatial_kernel_validated"] is False
    assert report["claim_boundary"]["runtime_default_enabled"] is False
    assert report["promotion_gate"]["accuracy_requirement_passed"] is False
    assert report["promotion_gate"]["physical_residual_retention_promotion_gate_passed"] is False
    assert primary_rows and replication_rows
    assert {row["residual_retention_parameter_sha256"] for row in primary_rows} == {
        row["residual_retention_parameter_sha256"] for row in replication_rows
    }
    assert all(
        row["future_target_observation_used_for_correction"] == "False"
        for row in primary_rows + replication_rows
    )
    assert all(
        int(row["elapsed_from_latest_observation_hours"]) == int(row["horizon_hours"]) + 1
        for row in primary_rows + replication_rows
    )


def test_residual_retention_beats_ar1_but_not_raw_physics(tmp_path) -> None:
    _, report = retention.compile_physical_residual_retention_transfer_posthoc(**_paths(tmp_path))

    for name in ("primary_window", "replication_window"):
        comparison = report[name]["comparison"]
        assert comparison["retention_beats_constant_correction_all_horizons"] is True
        assert comparison["retention_beats_ar1_decay_all_horizons"] is True
        assert comparison["retention_beats_raw_physical_all_horizons"] is False
        assert comparison["retention_beats_raw_physical_horizons_hours"] == []
        assert comparison["retention_beats_arx_all_horizons"] is True
        assert comparison["retention_beats_wwm_all_horizons"] is True
        assert comparison["retention_beats_persistence_all_horizons"] is True
        assert all(
            value["retention_minus_ar1_decay_rmse_m3s"] < 0.0
            and value["retention_minus_raw_physical_rmse_m3s"] > 0.0
            for value in comparison["per_horizon"].values()
        )

    primary = report["primary_window"]["metrics_by_horizon"]
    replication = report["replication_window"]["metrics_by_horizon"]
    assert primary["12"]["physical_residual_retention"]["rmse_m3s"] == pytest.approx(
        28.347833603173495
    )
    assert replication["3"]["physical_residual_retention"]["rmse_m3s"] == pytest.approx(
        47.580440212112116
    )
    interpretation = report["diagnostic_interpretation"]
    assert interpretation["retention_beats_ar1_decay_all_horizons_in_both_windows"] is True
    assert interpretation["retention_beats_raw_physical_all_horizons_in_both_windows"] is False
    assert interpretation["negative_long_horizon_source_weight_is_phase_reversal_diagnostic"]
    assert interpretation["result_may_trigger_refit_on_these_windows"] is False


def test_parameter_body_is_locked_before_target_comparison_rows_load(tmp_path, monkeypatch) -> None:
    events = []
    comparison = json.loads(retention.DEFAULT_COMPARISON_REPORT.read_text())
    target_path = comparison["outputs"]["primary_predictions"]["path"]
    original_read_verified = retention.cross._read_verified
    original_json_body = retention._json_body

    def tracking_read_verified(descriptor):
        if descriptor.get("path") == target_path:
            events.append("target_comparison_rows_load")
        return original_read_verified(descriptor)

    def tracking_json_body(value):
        if value.get("schema") == PHYSICAL_RESIDUAL_RETENTION_SCHEMA:
            events.append("parameter_body_compile")
        return original_json_body(value)

    monkeypatch.setattr(retention.cross, "_read_verified", tracking_read_verified)
    monkeypatch.setattr(retention, "_json_body", tracking_json_body)

    retention.compile_physical_residual_retention_transfer_posthoc(**_paths(tmp_path))

    assert events == ["parameter_body_compile", "target_comparison_rows_load"]


def test_future_target_outcome_cannot_change_retention_forecasts(tmp_path) -> None:
    bodies, _ = retention.compile_physical_residual_retention_transfer_posthoc(**_paths(tmp_path))
    parameters = physical_residual_retention_parameters_from_dict(json.loads(bodies["parameters"]))
    comparison = json.loads(retention.DEFAULT_COMPARISON_REPORT.read_text())
    source = cross._read_verified(comparison["outputs"]["primary_predictions"])
    parameter_sha256 = hashlib.sha256(bodies["parameters"]).hexdigest()

    original_body, _ = retention._compile_window(
        source_body=source,
        parameters=parameters,
        parameter_sha256=parameter_sha256,
    )
    mutated_body, _ = retention._compile_window(
        source_body=_mutate_target_outcomes(source),
        parameters=parameters,
        parameter_sha256=parameter_sha256,
    )
    original_rows = list(csv.DictReader(io.StringIO(original_body.decode())))
    mutated_rows = list(csv.DictReader(io.StringIO(mutated_body.decode())))
    forecast_columns = (
        "physical_residual_retention_m3s",
        "residual_retention_weight",
        "elapsed_from_latest_observation_hours",
        "residual_retention_clipped",
    )

    assert [row["observed_discharge_m3s"] for row in original_rows] != [
        row["observed_discharge_m3s"] for row in mutated_rows
    ]
    assert [tuple(row[column] for column in forecast_columns) for row in original_rows] == [
        tuple(row[column] for column in forecast_columns) for row in mutated_rows
    ]


def test_residual_retention_outputs_are_deterministic_and_bound(tmp_path) -> None:
    paths = _paths(tmp_path)
    first_bodies, first_report = retention.compile_physical_residual_retention_transfer_posthoc(
        **paths
    )
    second_bodies, second_report = retention.compile_physical_residual_retention_transfer_posthoc(
        **paths
    )

    assert first_bodies == second_bodies
    assert first_report["parameter_lock"] == second_report["parameter_lock"]
    assert first_report["primary_window"] == second_report["primary_window"]
    assert first_report["replication_window"] == second_report["replication_window"]
    for name, body in first_bodies.items():
        descriptor = first_report["outputs"][name]
        assert descriptor["sha256"] == hashlib.sha256(body).hexdigest()
        assert descriptor["size_bytes"] == len(body)


def test_residual_retention_rejects_tampered_source_physical_descriptor(tmp_path) -> None:
    payload = json.loads(retention.DEFAULT_SOURCE_PHYSICAL_REPORT.read_text(encoding="utf-8"))
    payload["systems"][retention.SOURCE_SYSTEM_ID]["prediction_artifact"]["sha256"] = "0" * 64
    tampered = tmp_path / "source_physical.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="cross_system_posthoc_artifact_identity_mismatch"):
        retention.compile_physical_residual_retention_transfer_posthoc(
            source_physical_report_path=tampered,
            **_paths(tmp_path),
        )


def _mutate_target_outcomes(body: bytes) -> bytes:
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))
    for row in rows:
        if row["observed_discharge_m3s"]:
            row["observed_discharge_m3s"] = str(float(row["observed_discharge_m3s"]) + 10_000.0)
    return cross._encode_rows(rows)
