from __future__ import annotations

import csv
import hashlib
import io
import json

import pytest

from data_agent.uwm.geospatial_kernel_v2.physical_action_innovation import (
    PHYSICAL_ACTION_INNOVATION_SCHEMA,
    physical_action_innovation_parameters_from_dict,
)
from scripts import evaluate_geospatial_kernel_action_innovation_cross_system as cross
from scripts import evaluate_geospatial_kernel_physical_action_innovation_transfer as hybrid


def _paths(tmp_path):
    return {
        "parameter_path": tmp_path / "parameters.json",
        "source_wwm_prediction_path": tmp_path / "source_wwm.csv",
        "replication_source_wwm_prediction_path": tmp_path / "replication_source_wwm.csv",
        "primary_prediction_path": tmp_path / "primary.csv",
        "replication_prediction_path": tmp_path / "replication.csv",
    }


def test_physical_action_innovation_fits_source_only_and_freezes_one_scale(
    tmp_path,
) -> None:
    bodies, report = hybrid.compile_physical_action_innovation_transfer_posthoc(**_paths(tmp_path))
    parameters = json.loads(bodies["parameters"])
    source_rows = list(csv.DictReader(io.StringIO(bodies["source_wwm_predictions"].decode())))
    primary_rows = list(csv.DictReader(io.StringIO(bodies["primary_predictions"].decode())))
    replication_rows = list(csv.DictReader(io.StringIO(bodies["replication_predictions"].decode())))

    assert parameters["schema"] == PHYSICAL_ACTION_INNOVATION_SCHEMA
    assert parameters["innovation_scale_coefficient"] == pytest.approx(1.2481236194557912)
    assert parameters["training_pair_count"] == 2626
    assert parameters["source_system_id"] == "center_hill"
    assert parameters["physical_routing_is_primary_trajectory"] is True
    assert parameters["wwm_absolute_discharge_used_as_primary_trajectory"] is False
    assert parameters["source_outcomes_used_for_fit"] is True
    assert parameters["target_outcomes_used_for_fit"] is False
    assert parameters["admitted"] is False
    contract = report["source_fit_contract"]
    assert contract["free_parameter_count"] == 1
    assert contract["target_system_id"] == "j_percy_priest"
    assert contract["per_target_window_refit_performed"] is False
    assert contract["same_parameter_used_across_target_windows"] is True
    diagnostic = report["replication_source_diagnostic"]
    assert diagnostic["innovation_scale_coefficient"] == pytest.approx(0.3691829319273314)
    assert diagnostic["coefficient_minus_frozen_parameter"] == pytest.approx(-0.8789406875284598)
    assert diagnostic["used_for_target_prediction"] is False
    assert report["claim_boundary"]["physical_action_innovation_admitted"] is False
    assert report["claim_boundary"]["geospatial_kernel_validated"] is False
    assert report["claim_boundary"]["runtime_default_enabled"] is False
    assert report["promotion_gate"]["accuracy_requirement_passed"] is False
    assert report["promotion_gate"]["physical_action_innovation_promotion_gate_passed"] is False
    assert source_rows and all(row["system_id"] == "center_hill" for row in source_rows)
    assert primary_rows and replication_rows
    assert {row["physical_action_innovation_parameter_sha256"] for row in primary_rows} == {
        row["physical_action_innovation_parameter_sha256"] for row in replication_rows
    }
    assert all(
        row["future_target_observation_used_for_correction"] == "False"
        for row in primary_rows + replication_rows
    )


def test_source_gain_does_not_transfer_over_raw_physics(tmp_path) -> None:
    _, report = hybrid.compile_physical_action_innovation_transfer_posthoc(**_paths(tmp_path))

    source = report["source_fit_diagnostic"]["comparison"]
    assert source["hybrid_beats_raw_physical_all_horizons"] is True
    assert source["hybrid_beats_raw_physical_horizons_hours"] == [1, 3, 6, 12]
    for name in ("primary_window", "replication_window"):
        comparison = report[name]["comparison"]
        assert comparison["hybrid_beats_raw_physical_all_horizons"] is False
        assert comparison["hybrid_beats_raw_physical_horizons_hours"] == []
        assert comparison["hybrid_beats_wwm_all_horizons"] is True
        assert comparison["hybrid_beats_arx_all_horizons"] is True
        assert comparison["hybrid_beats_residual_retention_all_horizons"] is False
        assert comparison["hybrid_beats_residual_retention_horizons_hours"] == [1, 3]
        assert all(
            value["hybrid_minus_raw_physical_rmse_m3s"] > 0.0
            for value in comparison["per_horizon"].values()
        )

    primary = report["primary_window"]["metrics_by_horizon"]
    replication = report["replication_window"]["metrics_by_horizon"]
    assert primary["12"]["physical_action_innovation"]["rmse_m3s"] == pytest.approx(
        38.388400217386575
    )
    assert replication["6"]["physical_action_innovation"]["rmse_m3s"] == pytest.approx(
        48.228939799523225
    )
    interpretation = report["diagnostic_interpretation"]
    assert interpretation["existing_wwm_innovation_is_transferable_missing_physics"] is False
    assert interpretation["raw_physical_remains_required_minimum_physical_bar"] is True
    assert interpretation["result_may_trigger_refit_on_these_windows"] is False


def test_parameter_body_is_locked_before_target_comparison_rows_load(tmp_path, monkeypatch) -> None:
    events = []
    comparison = json.loads(hybrid.DEFAULT_COMPARISON_REPORT.read_text())
    target_path = comparison["outputs"]["primary_predictions"]["path"]
    original_read_verified = hybrid.cross._read_verified
    original_json_body = hybrid._json_body

    def tracking_read_verified(descriptor):
        if descriptor.get("path") == target_path:
            events.append("target_comparison_rows_load")
        return original_read_verified(descriptor)

    def tracking_json_body(value):
        if value.get("schema") == PHYSICAL_ACTION_INNOVATION_SCHEMA:
            events.append("parameter_body_compile")
        return original_json_body(value)

    monkeypatch.setattr(hybrid.cross, "_read_verified", tracking_read_verified)
    monkeypatch.setattr(hybrid, "_json_body", tracking_json_body)

    hybrid.compile_physical_action_innovation_transfer_posthoc(**_paths(tmp_path))

    assert events == ["parameter_body_compile", "target_comparison_rows_load"]


def test_future_target_outcome_cannot_change_hybrid_forecasts(tmp_path) -> None:
    bodies, _ = hybrid.compile_physical_action_innovation_transfer_posthoc(**_paths(tmp_path))
    parameters = physical_action_innovation_parameters_from_dict(json.loads(bodies["parameters"]))
    comparison = json.loads(hybrid.DEFAULT_COMPARISON_REPORT.read_text())
    source = cross._read_verified(comparison["outputs"]["primary_predictions"])
    parameter_sha256 = hashlib.sha256(bodies["parameters"]).hexdigest()

    original_body, _ = hybrid._compile_target_window(
        source_body=source,
        parameters=parameters,
        parameter_sha256=parameter_sha256,
    )
    mutated_body, _ = hybrid._compile_target_window(
        source_body=_mutate_target_outcomes(source),
        parameters=parameters,
        parameter_sha256=parameter_sha256,
    )
    original_rows = list(csv.DictReader(io.StringIO(original_body.decode())))
    mutated_rows = list(csv.DictReader(io.StringIO(mutated_body.decode())))
    forecast_columns = (
        "physical_action_innovation_m3s",
        "raw_action_innovation_m3s",
        "innovation_scale_coefficient",
        "scaled_action_innovation_m3s",
        "physical_action_innovation_clipped",
    )

    assert [row["observed_discharge_m3s"] for row in original_rows] != [
        row["observed_discharge_m3s"] for row in mutated_rows
    ]
    assert [tuple(row[column] for column in forecast_columns) for row in original_rows] == [
        tuple(row[column] for column in forecast_columns) for row in mutated_rows
    ]


def test_physical_action_innovation_outputs_are_deterministic_and_bound(tmp_path) -> None:
    paths = _paths(tmp_path)
    first_bodies, first_report = hybrid.compile_physical_action_innovation_transfer_posthoc(**paths)
    second_bodies, second_report = hybrid.compile_physical_action_innovation_transfer_posthoc(
        **paths
    )

    assert first_bodies == second_bodies
    assert first_report["parameter_lock"] == second_report["parameter_lock"]
    assert first_report["source_fit_diagnostic"] == second_report["source_fit_diagnostic"]
    assert first_report["primary_window"] == second_report["primary_window"]
    assert first_report["replication_window"] == second_report["replication_window"]
    for name, body in first_bodies.items():
        descriptor = first_report["outputs"][name]
        assert descriptor["sha256"] == hashlib.sha256(body).hexdigest()
        assert descriptor["size_bytes"] == len(body)


def test_physical_action_innovation_rejects_tampered_source_physical_descriptor(
    tmp_path,
) -> None:
    payload = json.loads(hybrid.DEFAULT_SOURCE_PHYSICAL_REPORT.read_text(encoding="utf-8"))
    payload["systems"][hybrid.SOURCE_SYSTEM_ID]["prediction_artifact"]["sha256"] = "0" * 64
    tampered = tmp_path / "source_physical.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="cross_system_posthoc_artifact_identity_mismatch"):
        hybrid.compile_physical_action_innovation_transfer_posthoc(
            source_physical_report_path=tampered,
            **_paths(tmp_path),
        )


def _mutate_target_outcomes(body: bytes) -> bytes:
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))
    for row in rows:
        if row["observed_discharge_m3s"]:
            row["observed_discharge_m3s"] = str(float(row["observed_discharge_m3s"]) + 10_000.0)
    return cross._encode_rows(rows)
