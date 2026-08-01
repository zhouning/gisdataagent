from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from scripts import (
    evaluate_geospatial_kernel_physical_online_residual_adaptation_cross_system as evaluate,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_physical_online_residual_adaptation_center_hill_posthoc_report.json"
)


def test_frozen_center_hill_online_adaptation_report_recomputes_exactly() -> None:
    frozen = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    bodies, report = evaluate.compile_cross_system_online_residual_adaptation_posthoc(
        generated_at=datetime.fromisoformat(frozen["generated_at"]),
    )

    assert report == frozen
    for name, body in bodies.items():
        descriptor = frozen["outputs"][name]
        path = REPO_ROOT / descriptor["path"]
        assert path.read_bytes() == body
        assert hashlib.sha256(body).hexdigest() == descriptor["sha256"]
        assert len(body) == descriptor["size_bytes"]


def test_fixed_v4_is_noninferior_but_not_strictly_better_on_center_hill() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    interpretation = report["diagnostic_interpretation"]

    assert interpretation["online_beats_raw_physical_all_horizons_in_both_windows"] is False
    assert interpretation["online_not_worse_than_raw_physical_all_horizons_in_both_windows"] is True
    assert interpretation["fixed_phase_lead_algorithm_no_regression_safety_gate_passed"] is True
    assert (
        interpretation["fixed_phase_lead_algorithm_survives_center_hill_historical_stress_test"]
        is False
    )
    assert interpretation["numerical_rmse_improvement_window_horizon_count"] == 4
    assert interpretation["unchanged_raw_physical_fallback_window_horizon_count"] == 4
    assert interpretation["numerical_rmse_regression_window_horizon_count"] == 0
    assert interpretation["hac_supported_squared_error_improvement_window_horizon_count"] == 1

    primary = report["primary_window"]["comparison"]["per_horizon"]
    replication = report["replication_window"]["comparison"]["per_horizon"]
    assert [
        primary[str(horizon)]["online_minus_raw_physical_rmse_m3s"] for horizon in (1, 3, 6, 12)
    ] == pytest.approx([-2.335758, 0.0, -3.719321, -1.954740], abs=1e-6)
    assert [
        replication[str(horizon)]["online_minus_raw_physical_rmse_m3s"] for horizon in (1, 3, 6, 12)
    ] == pytest.approx([0.0, 0.0, 0.0, -0.436408], abs=1e-6)


def test_center_hill_rows_apply_only_matured_evidence_and_never_reselect() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    activated_count = 0
    for descriptor in report["outputs"].values():
        path = REPO_ROOT / descriptor["path"]
        with path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            physical = float(row["physical_open_loop_m3s"])
            adapted = float(row["physical_online_residual_adaptation_m3s"])
            assert row["future_target_observation_used_for_correction"] == "False"
            assert row["mapping_reselected_on_center_hill"] == "False"
            if row["online_application_gate_passed"] == "True":
                activated_count += 1
                assert int(row["online_matured_sample_count"]) >= 24
                assert row["online_evidence_gate_passed"] == "True"
                assert row["online_shadow_performance_gate_passed"] == "True"
            else:
                assert adapted == physical
    assert activated_count > 0


def test_center_hill_diagnostic_preserves_posthoc_claim_boundary() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    contract = report["fixed_cross_system_contract"]
    assert contract["trajectory_predictor_horizon_by_target_horizon"] == {
        "1": 3,
        "3": 6,
        "6": 12,
    }
    assert contract["mapping_reselected_on_center_hill"] is False
    assert contract["parameter_state_transferred_between_systems"] is False
    assert report["promotion_gate"]["accuracy_requirement_passed"] is False
    assert report["promotion_gate"]["cross_system_online_adapter_promotion_gate_passed"] is False
    assert report["information_boundary"]["evaluation_counts_as_fresh_validation"] is False
    claims = report["claim_boundary"]
    assert claims["cross_system_algorithm_generalization_validated"] is False
    assert claims["geospatial_kernel_validated"] is False
    assert claims["runtime_default_enabled"] is False


def test_center_hill_diagnostic_rejects_wrong_upstream_contract(
    tmp_path: Path,
) -> None:
    payload = json.loads(evaluate.DEFAULT_SOURCE_REPORT.read_text(encoding="utf-8"))
    payload["status"] = "tampered"
    path = tmp_path / "source.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="source_report_invalid"):
        evaluate.compile_cross_system_online_residual_adaptation_posthoc(
            source_report_path=path,
        )
