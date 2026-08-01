from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from scripts import (
    evaluate_geospatial_kernel_physical_online_residual_adaptation as evaluate,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_physical_online_residual_adaptation_posthoc_report.json"
)


def test_frozen_online_adaptation_report_recomputes_exactly() -> None:
    frozen = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    bodies, report = evaluate.compile_physical_online_residual_adaptation_posthoc(
        generated_at=datetime.fromisoformat(frozen["generated_at"]),
    )

    assert report == frozen
    for name, body in bodies.items():
        descriptor = frozen["outputs"][name]
        path = REPO_ROOT / descriptor["path"]
        assert path.read_bytes() == body
        assert hashlib.sha256(body).hexdigest() == descriptor["sha256"]
        assert len(body) == descriptor["size_bytes"]


def test_online_adaptation_is_safe_relative_to_raw_and_better_than_old_wwm() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert report["diagnostic_interpretation"][
        "online_not_worse_than_raw_physical_all_horizons_in_both_windows"
    ] is True
    assert report["diagnostic_interpretation"][
        "online_beats_source_fitted_retention_all_horizons_in_both_windows"
    ] is True
    assert report["diagnostic_interpretation"][
        "online_beats_wwm_all_horizons_in_both_windows"
    ] is True
    assert report["diagnostic_interpretation"][
        "online_beats_raw_physical_all_horizons_in_both_windows"
    ] is True
    assert report["promotion_gate"][
        "online_residual_adaptation_promotion_gate_passed"
    ] is False
    assert report["promotion_gate"]["accuracy_requirement_passed"] is True
    assert report["information_boundary"][
        "phase_lead_horizon_mapping_selected_after_target_outcome_exposure"
    ] is True
    interpretation = report["diagnostic_interpretation"]
    assert interpretation["numerical_rmse_improvement_window_horizon_count"] == 8
    assert interpretation[
        "hac_supported_squared_error_improvement_window_horizon_count"
    ] == 5
    assert interpretation["window_horizon_comparison_count"] == 8
    for window_name in ("primary_window", "replication_window"):
        comparison = report[window_name]["comparison"]
        assert comparison["online_not_worse_than_raw_physical_all_horizons"] is True
        assert comparison["online_beats_raw_physical_all_horizons"] is True
        assert comparison["online_beats_source_fitted_retention_all_horizons"] is True
        assert comparison["online_beats_wwm_all_horizons"] is True
        diagnostics = report[window_name]["paired_loss_diagnostic_by_horizon"]
        assert set(diagnostics) == {"1", "3", "6", "12"}
        for values in diagnostics.values():
            assert values["formal_diebold_mariano_claimed"] is False


def test_prediction_rows_apply_only_matured_shadow_verified_short_horizon_evidence() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    activated_count = 0
    for descriptor in report["outputs"].values():
        path = REPO_ROOT / descriptor["path"]
        with path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            horizon = int(row["horizon_hours"])
            physical = float(row["physical_open_loop_m3s"])
            adapted = float(row["physical_online_residual_adaptation_m3s"])
            if row["online_application_gate_passed"] == "True":
                activated_count += 1
                assert int(row["online_matured_sample_count"]) >= 24
                assert row["online_evidence_gate_passed"] == "True"
                assert row["online_shadow_performance_gate_passed"] == "True"
                if horizon == 12:
                    assert row["online_correction_mode"] == "mean_physical_error"
                    assert float(row["online_applied_weight"]) == 0.0
                else:
                    assert row["online_correction_mode"] == (
                        "phase_lead_physical_trajectory_change"
                    )
                    assert float(row["online_applied_bias_m3s"]) == 0.0
                    assert float(
                        row["online_physical_trajectory_change_m3s"]
                    ) == pytest.approx(
                        float(row["online_predictor_physical_target_m3s"])
                        - float(row["physical_at_latest_observation_m3s"])
                    )
                    assert int(
                        row["online_predictor_forecast_horizon_hours"]
                    ) > horizon
            if row["online_application_gate_passed"] == "False":
                assert adapted == physical
            assert row["future_target_observation_used_for_correction"] == "False"
    assert activated_count > 0


def test_online_update_includes_finite_signed_discharge_observations() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    for window_name in ("primary_window", "replication_window"):
        execution = report[window_name]["execution"]
        assert execution[
            "finite_negative_outcome_queued_for_online_update_count"
        ] > 0
        assert execution["nonfinite_outcome_excluded_from_online_update_count"] == 0
        assert execution["future_target_observation_used_before_availability"] is False


def test_evaluator_rejects_wrong_upstream_report_contract(tmp_path: Path) -> None:
    payload = json.loads(evaluate.DEFAULT_COMPARISON_REPORT.read_text(encoding="utf-8"))
    payload["status"] = "tampered"
    path = tmp_path / "comparison.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="comparison_report_invalid"):
        evaluate.compile_physical_online_residual_adaptation_posthoc(
            comparison_report_path=path,
        )
