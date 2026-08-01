from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from scripts import evaluate_geospatial_kernel_physical_online_expert_blend as evaluate

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_physical_online_expert_blend_posthoc_report.json"
)


def test_frozen_online_expert_blend_report_recomputes_exactly() -> None:
    frozen = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    bodies, report = evaluate.compile_physical_online_expert_blend_posthoc(
        generated_at=datetime.fromisoformat(frozen["generated_at"]),
    )

    assert report == frozen
    for name, body in bodies.items():
        descriptor = frozen["outputs"][name]
        path = REPO_ROOT / descriptor["path"]
        assert path.read_bytes() == body
        assert hashlib.sha256(body).hexdigest() == descriptor["sha256"]
        assert len(body) == descriptor["size_bytes"]


def test_blend_improves_raw_physical_without_regressing_v4() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    interpretation = report["diagnostic_interpretation"]

    assert interpretation["blend_beats_raw_physical_all_horizons_in_all_four_windows"] is True
    assert interpretation["blend_not_worse_than_v4_all_horizons_in_all_four_windows"] is True
    assert interpretation["numerical_rmse_improvement_vs_raw_physical_window_horizon_count"] == 16
    assert interpretation["numerical_rmse_regression_vs_raw_physical_window_horizon_count"] == 0
    assert interpretation["numerical_rmse_improvement_vs_v4_window_horizon_count"] == 8
    assert interpretation["numerical_rmse_regression_vs_v4_window_horizon_count"] == 0
    assert interpretation["hac_supported_squared_error_improvement_vs_raw_physical_count"] == 13
    assert interpretation["hac_supported_squared_error_improvement_vs_v4_count"] == 8
    assert interpretation["online_expert_blend_accuracy_gate_passed_posthoc"] is True


def test_blend_keeps_jpp_v4_and_improves_both_center_hill_windows() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    windows = report["windows"]

    for name in ("j_percy_priest_primary", "j_percy_priest_replication"):
        assert windows[name]["execution"]["expert_blend_activated_prediction_count"] == 0
        for values in windows[name]["comparison"]["per_horizon"].values():
            assert values["blend_minus_v4_rmse_m3s"] == 0.0

    primary = windows["center_hill_primary"]
    replication = windows["center_hill_replication"]
    assert primary["execution"]["expert_blend_activated_prediction_count"] > 0
    assert replication["execution"]["expert_blend_activated_prediction_count"] > 0
    assert [
        primary["comparison"]["per_horizon"][str(horizon)]["blend_minus_raw_physical_rmse_m3s"]
        for horizon in (1, 3, 6, 12)
    ] == pytest.approx(
        [-52.551707, -42.684641, -31.064714, -18.794128],
        abs=1e-6,
    )
    assert [
        replication["comparison"]["per_horizon"][str(horizon)]["blend_minus_raw_physical_rmse_m3s"]
        for horizon in (1, 3, 6, 12)
    ] == pytest.approx(
        [-16.043197, -10.641364, -8.099306, -4.393677],
        abs=1e-6,
    )
    assert primary["comparison"]["blend_beats_wwm_all_horizons"] is False
    assert replication["comparison"]["blend_beats_wwm_all_horizons"] is False


def test_blend_rows_apply_only_matured_shadow_verified_evidence() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    activated = 0
    for descriptor in report["outputs"].values():
        path = REPO_ROOT / descriptor["path"]
        with path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            baseline = float(row["physical_online_residual_adaptation_m3s"])
            blended = float(row["physical_online_expert_blend_m3s"])
            assert row["future_target_observation_used_for_blend"] == "False"
            assert row["parameter_state_transferred_between_windows"] == "False"
            if row["online_expert_application_gate_passed"] == "True":
                activated += 1
                assert int(row["online_expert_matured_sample_count"]) >= 24
                assert row["online_expert_evidence_gate_passed"] == "True"
                assert row["online_expert_shadow_performance_gate_passed"] == "True"
                assert 0.0 <= float(row["online_expert_applied_weight"]) <= 1.0
            else:
                assert blended == baseline
    assert activated > 0


def test_blend_accuracy_does_not_override_posthoc_promotion_boundary() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert report["promotion_gate"]["accuracy_requirement_passed"] is True
    assert report["promotion_gate"]["fresh_prospective_design_passed"] is False
    assert report["promotion_gate"]["online_expert_blend_promotion_gate_passed"] is False
    assert (
        report["information_boundary"]["all_four_target_windows_exposed_before_blend_design"]
        is True
    )
    assert report["information_boundary"]["evaluation_counts_as_fresh_validation"] is False
    claims = report["claim_boundary"]
    assert claims["online_expert_blend_admitted"] is False
    assert claims["cross_system_algorithm_generalization_validated"] is False
    assert claims["geospatial_kernel_validated"] is False
    assert claims["runtime_default_enabled"] is False


def test_blend_rejects_wrong_source_report_contract(tmp_path: Path) -> None:
    payload = json.loads(evaluate.DEFAULT_JPP_REPORT.read_text(encoding="utf-8"))
    payload["status"] = "tampered"
    path = tmp_path / "jpp.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="source_report_invalid"):
        evaluate.compile_physical_online_expert_blend_posthoc(
            jpp_report_path=path,
        )
