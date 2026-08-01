from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from scripts import evaluate_geospatial_kernel_online_expert_traditional_baselines as evaluate

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_online_expert_traditional_baselines_posthoc_report.json"
)


def test_frozen_traditional_online_baseline_report_recomputes_exactly() -> None:
    frozen = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    bodies, report = evaluate.compile_online_expert_traditional_baselines_posthoc(
        generated_at=datetime.fromisoformat(frozen["generated_at"]),
    )

    assert report == frozen
    metric_artifact = frozen["implementation_artifacts"]["online_expert_evaluation"]
    metric_path = REPO_ROOT / metric_artifact["path"]
    metric_body = metric_path.read_bytes()
    assert hashlib.sha256(metric_body).hexdigest() == metric_artifact["sha256"]
    assert len(metric_body) == metric_artifact["size_bytes"]
    for name, body in bodies.items():
        descriptor = frozen["outputs"][name]
        path = REPO_ROOT / descriptor["path"]
        assert path.read_bytes() == body
        assert hashlib.sha256(body).hexdigest() == descriptor["sha256"]
        assert len(body) == descriptor["size_bytes"]


def test_traditional_selector_and_v5_have_a_real_tradeoff() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    interpretation = report["diagnostic_interpretation"]

    assert interpretation["selector_beats_raw_physical_all_horizons_in_all_four_windows"] is True
    assert interpretation["selector_not_worse_than_v4_all_horizons_in_all_four_windows"] is True
    assert interpretation["selector_not_worse_than_v5_all_horizons_in_all_four_windows"] is False
    assert interpretation["selector_rmse_improvement_vs_raw_physical_count"] == 16
    assert interpretation["selector_rmse_improvement_vs_v5_count"] == 5
    assert interpretation["selector_rmse_regression_vs_v5_count"] == 3
    assert interpretation["selector_rmse_equal_to_v5_count"] == 8
    assert interpretation["selector_strictly_dominates_v5"] is False
    assert interpretation["v5_strictly_dominates_selector"] is False
    assert interpretation["traditional_selector_and_v5_have_empirical_tradeoff"] is True


def test_external_regret_preserves_the_cross_window_tradeoff() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    interpretation = report["diagnostic_interpretation"]

    assert interpretation["v5_lower_final_average_external_regret_window_count"] == 1
    assert interpretation["selector_lower_final_average_external_regret_window_count"] == 1
    assert interpretation["v5_selector_equal_final_average_external_regret_window_count"] == 2
    assert interpretation["external_regret_result_is_posthoc"] is True
    expected = {
        "center_hill_primary": {
            "v5": 486.59136992569285,
            "selector": 221.32899209960115,
        },
        "center_hill_replication": {
            "v5": 23.652082116696665,
            "selector": 41.65527804120486,
        },
        "j_percy_priest_primary": {"v5": 0.0, "selector": 0.0},
        "j_percy_priest_replication": {"v5": 0.0, "selector": 0.0},
    }
    for name, values in expected.items():
        diagnostic = report["windows"][name]["external_regret_to_best_fixed_constituent"]
        assert diagnostic["comparison_selected_after_outcome_access"] is True
        assert diagnostic[
            "equal_horizon_macro_mean_final_average_external_regret_m6s2"
        ] == pytest.approx(values)


def test_warmup_ablations_fail_to_replace_v5_or_selector() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    interpretation = report["warmup_ablation_interpretation"]

    assert interpretation["counts"] == {
        "coefficient_lcb_blend": {
            "v4": {"improvement": 8, "regression": 2},
            "v5": {"improvement": 5, "regression": 5},
            "selector": {"improvement": 3, "regression": 6},
        },
        "loss_gated_lcb_blend": {
            "v4": {"improvement": 8, "regression": 0},
            "v5": {"improvement": 5, "regression": 3},
            "selector": {"improvement": 0, "regression": 7},
        },
        "loss_gated_ols_blend": {
            "v4": {"improvement": 8, "regression": 0},
            "v5": {"improvement": 5, "regression": 3},
            "selector": {"improvement": 1, "regression": 4},
        },
    }
    assert interpretation["coefficient_lcb_breaks_v4_nonregression"] is True
    assert interpretation["loss_gated_lcb_strictly_dominated_by_selector"] is True
    assert interpretation["loss_gated_ols_dominates_v5_and_selector"] is False
    assert interpretation["any_ablation_admitted_as_new_candidate"] is False
    assert interpretation["prospective_primary_candidate_changed"] is False
    assert report["claim_boundary"]["warmup_ablation_supports_replacing_v5"] is False


def test_selector_wins_earlier_center_hill_but_not_all_replication_horizons() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    primary = report["windows"]["center_hill_primary"]["comparison"]
    replication = report["windows"]["center_hill_replication"]["comparison"]

    assert [
        primary["per_horizon"][str(horizon)]["selector_minus_v5_rmse_m3s"]
        for horizon in (1, 3, 6, 12)
    ] == pytest.approx([-4.959410, -3.109677, -2.574357, -2.245504], abs=1e-6)
    assert [
        replication["per_horizon"][str(horizon)]["selector_minus_v5_rmse_m3s"]
        for horizon in (1, 3, 6, 12)
    ] == pytest.approx([-0.601976, 0.443023, 0.270176, 1.108628], abs=1e-6)
    for name in ("j_percy_priest_primary", "j_percy_priest_replication"):
        comparison = report["windows"][name]["comparison"]
        assert all(
            values["selector_minus_v5_rmse_m3s"] == 0.0
            for values in comparison["per_horizon"].values()
        )
        assert report["windows"][name]["execution"]["wwm_selected_prediction_count"] == 0


def test_traditional_selector_uses_only_matured_losses() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    selected_count = 0
    for descriptor in report["outputs"].values():
        path = REPO_ROOT / descriptor["path"]
        with path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            v4 = float(row["physical_online_residual_adaptation_m3s"])
            selector = float(row["evidence_gated_follow_the_leader_m3s"])
            expected_equal = 0.5 * (v4 + float(row["action_innovation_wwm_m3s"]))
            assert float(row["fixed_equal_expert_blend_m3s"]) == pytest.approx(expected_equal)
            alternative_delta = float(row["action_innovation_wwm_m3s"]) - v4
            for prefix in (
                "coefficient_lcb",
                "loss_gated_lcb",
                "loss_gated_ols",
            ):
                weight = float(row[f"{prefix}_weight"])
                prediction = float(row[f"{prefix}_blend_m3s"])
                assert 0.0 <= weight <= 1.0
                assert prediction == pytest.approx(max(0.0, v4 + weight * alternative_delta))
            if float(row["coefficient_lcb_weight"]) > 0.0:
                assert int(row["online_expert_matured_sample_count"]) >= 24
            assert row["future_target_observation_used_for_selector"] == "False"
            assert row["selector_state_transferred_between_windows"] == "False"
            if row["selector_wwm_selected"] == "True":
                selected_count += 1
                assert int(row["selector_matured_sample_count"]) >= 24
                assert selector == float(row["action_innovation_wwm_m3s"])
            else:
                assert selector == v4
                assert float(row["loss_gated_lcb_weight"]) == 0.0
                assert float(row["loss_gated_ols_weight"]) == 0.0
    assert selected_count > 0


def test_traditional_comparison_preserves_posthoc_claim_boundary() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert report["promotion_gate"]["traditional_baseline_comparison_completed"] is True
    assert report["promotion_gate"]["fresh_prospective_design_passed"] is False
    assert report["promotion_gate"]["traditional_baseline_or_v5_promoted"] is False
    assert report["information_boundary"]["evaluation_counts_as_fresh_validation"] is False
    claims = report["claim_boundary"]
    assert claims["v5_algorithmic_superiority_validated"] is False
    assert claims["traditional_selector_admitted"] is False
    assert claims["geospatial_kernel_validated"] is False


def test_traditional_comparison_rejects_wrong_source_contract(
    tmp_path: Path,
) -> None:
    payload = json.loads(evaluate.DEFAULT_SOURCE_REPORT.read_text(encoding="utf-8"))
    payload["status"] = "tampered"
    path = tmp_path / "source.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="source_report_invalid"):
        evaluate.compile_online_expert_traditional_baselines_posthoc(
            source_report_path=path,
        )
