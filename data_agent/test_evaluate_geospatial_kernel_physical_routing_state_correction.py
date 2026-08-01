from __future__ import annotations

import csv
import hashlib
import io
import json

import pytest

from scripts import evaluate_geospatial_kernel_action_innovation_cross_system as cross
from scripts import evaluate_geospatial_kernel_physical_routing_state_correction as physical


def _paths(tmp_path):
    return {
        "primary_prediction_path": tmp_path / "primary.csv",
        "replication_prediction_path": tmp_path / "replication.csv",
    }


def test_physical_state_correction_reuses_sealed_predictions_and_never_admits(
    tmp_path,
) -> None:
    primary_raw = _physical_descriptor(physical.DEFAULT_PRIMARY_PHYSICAL_REPORT)
    replication_raw = _physical_descriptor(physical.DEFAULT_REPLICATION_PHYSICAL_REPORT)
    before = {
        "primary": hashlib.sha256(cross._read_verified(primary_raw)).hexdigest(),
        "replication": hashlib.sha256(cross._read_verified(replication_raw)).hexdigest(),
    }

    bodies, report = physical.compile_physical_routing_state_correction_posthoc(**_paths(tmp_path))
    rows = list(csv.DictReader(io.StringIO(bodies["primary_predictions"].decode())))

    assert report["comparator_contract"]["fitted_parameter_count"] == 0
    assert report["comparator_contract"]["parameter_fit_performed"] is False
    assert report["comparator_contract"]["per_window_refit_performed"] is False
    assert report["comparator_contract"]["future_target_observation_used_for_correction"] is False
    assert report["comparator_contract"]["raw_physical_prediction_sha256_verified"] is True
    assert (
        report["claim_boundary"]["traditional_physical_router_posthoc_comparison_executed"] is True
    )
    assert report["claim_boundary"]["professional_baseline_admitted"] is False
    assert report["claim_boundary"]["geospatial_kernel_validated"] is False
    assert report["claim_boundary"]["runtime_default_enabled"] is False
    assert report["information_boundary"]["evaluation_counts_as_fresh_validation"] is False
    assert report["t_route_mc_decision"]["promotion_gate_passed"] is False
    assert (
        report["t_route_mc_decision"]["derived_initialized_runtime_professional_baseline_eligible"]
        is False
    )
    assert report["operator_identity"]["same_operator_form_across_windows"] is False
    assert report["primary_window"]["execution"]["raw_physical_prediction_count"] == 672
    assert report["replication_window"]["execution"]["raw_physical_prediction_count"] == 672
    scope = report["scoring_scope_boundary"]
    assert scope["raw_physical_beats_original_immediate_prior_hour_persistence"] is False
    assert scope["raw_physical_beats_wwm_latency_matched_persistence_all_horizons"] is True
    assert scope["horizon_1_latest_state_age_at_target_hours"] == 2
    assert scope["persistence_results_are_not_contradictory"] is True
    assert rows
    assert all(row["future_target_observation_used_for_correction"] == "False" for row in rows)
    assert all(row["physical_parameter_refit_performed"] == "False" for row in rows)
    for row in rows:
        expected = max(
            0.0,
            float(row["physical_open_loop_m3s"]) + float(row["latest_observation_residual_m3s"]),
        )
        assert float(row["physical_state_corrected_m3s"]) == pytest.approx(expected)

    after = {
        "primary": hashlib.sha256(cross._read_verified(primary_raw)).hexdigest(),
        "replication": hashlib.sha256(cross._read_verified(replication_raw)).hexdigest(),
    }
    assert (
        before
        == after
        == {
            "primary": primary_raw["sha256"],
            "replication": replication_raw["sha256"],
        }
    )


def test_state_correction_is_negative_but_physical_router_sets_new_accuracy_bar(
    tmp_path,
) -> None:
    _, report = physical.compile_physical_routing_state_correction_posthoc(**_paths(tmp_path))

    for name in ("primary_window", "replication_window"):
        comparison = report[name]["comparison"]
        assert comparison["state_corrected_beats_raw_physical_all_horizons"] is False
        assert comparison["state_corrected_beats_raw_physical_horizons_hours"] == []
        assert comparison["state_corrected_beats_arx_all_horizons"] is True
        assert comparison["state_corrected_beats_wwm_all_horizons"] is True
        assert comparison["state_corrected_beats_persistence_all_horizons"] is True
        assert all(
            value["raw_physical_minus_persistence_rmse_m3s"] < 0.0
            for value in comparison["per_horizon"].values()
        )

    primary = report["primary_window"]["metrics_by_horizon"]["12"]
    replication = report["replication_window"]["metrics_by_horizon"]["12"]
    assert primary["physical_open_loop"]["rmse_m3s"] == pytest.approx(27.31792846978277)
    assert primary["physical_state_corrected"]["rmse_m3s"] == pytest.approx(37.56415634789377)
    assert replication["physical_open_loop"]["rmse_m3s"] == pytest.approx(35.870618066122496)
    assert replication["physical_state_corrected"]["rmse_m3s"] == pytest.approx(47.21187566003608)
    interpretation = report["diagnostic_interpretation"]
    assert (
        interpretation["state_correction_beats_raw_physical_all_horizons_in_both_windows"] is False
    )
    assert interpretation["state_correction_beats_wwm_all_horizons_in_both_windows"] is True
    assert interpretation["result_may_trigger_refit_on_these_windows"] is False


def test_future_target_outcome_cannot_change_physical_forecasts() -> None:
    arx_report = json.loads(physical.DEFAULT_ARX_REPORT.read_text())
    source = cross._read_verified(arx_report["outputs"]["primary_predictions"])
    physical_report = json.loads(physical.DEFAULT_PRIMARY_PHYSICAL_REPORT.read_text())
    descriptor = physical_report["systems"][cross.SYSTEM_ID]["prediction_artifact"]
    physical_body = cross._read_verified(descriptor)

    original_body, _ = physical._compile_window(
        arx_prediction_body=source,
        physical_prediction_body=physical_body,
        physical_value_column="kernel_full_subnetwork_m3s",
        physical_prediction_sha256=descriptor["sha256"],
        physical_operator="BranchingManningNetworkTransportOperator",
    )
    mutated_source = _mutate_target_outcomes(source)
    mutated_body, _ = physical._compile_window(
        arx_prediction_body=mutated_source,
        physical_prediction_body=physical_body,
        physical_value_column="kernel_full_subnetwork_m3s",
        physical_prediction_sha256=descriptor["sha256"],
        physical_operator="BranchingManningNetworkTransportOperator",
    )
    original_rows = list(csv.DictReader(io.StringIO(original_body.decode())))
    mutated_rows = list(csv.DictReader(io.StringIO(mutated_body.decode())))
    forecast_columns = (
        "physical_open_loop_m3s",
        "physical_state_corrected_m3s",
        "physical_at_latest_observation_m3s",
        "latest_observation_residual_m3s",
        "state_correction_clipped",
    )

    assert [row["observed_discharge_m3s"] for row in original_rows] != [
        row["observed_discharge_m3s"] for row in mutated_rows
    ]
    assert [tuple(row[column] for column in forecast_columns) for row in original_rows] == [
        tuple(row[column] for column in forecast_columns) for row in mutated_rows
    ]


def test_physical_state_correction_outputs_are_deterministic_and_bound(
    tmp_path,
) -> None:
    paths = _paths(tmp_path)
    first_bodies, first_report = physical.compile_physical_routing_state_correction_posthoc(**paths)
    second_bodies, second_report = physical.compile_physical_routing_state_correction_posthoc(
        **paths
    )

    assert first_bodies == second_bodies
    assert first_report["primary_window"] == second_report["primary_window"]
    assert first_report["replication_window"] == second_report["replication_window"]
    for name, body in first_bodies.items():
        descriptor = first_report["outputs"][name]
        assert descriptor["sha256"] == hashlib.sha256(body).hexdigest()
        assert descriptor["size_bytes"] == len(body)


def test_physical_state_correction_rejects_tampered_sealed_prediction(
    tmp_path,
) -> None:
    payload = json.loads(physical.DEFAULT_PRIMARY_PHYSICAL_REPORT.read_text(encoding="utf-8"))
    payload["systems"][cross.SYSTEM_ID]["prediction_artifact"]["sha256"] = "0" * 64
    tampered = tmp_path / "physical_rollout.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="cross_system_posthoc_artifact_identity_mismatch"):
        physical.compile_physical_routing_state_correction_posthoc(
            primary_physical_report_path=tampered,
            **_paths(tmp_path),
        )


def _physical_descriptor(report_path):
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return report["systems"][cross.SYSTEM_ID]["prediction_artifact"]


def _mutate_target_outcomes(body: bytes) -> bytes:
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))
    for row in rows:
        if row["observed_discharge_m3s"]:
            row["observed_discharge_m3s"] = str(float(row["observed_discharge_m3s"]) + 10_000.0)
    return cross._encode_rows(rows)
