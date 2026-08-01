from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from scripts import evaluate_geospatial_kernel_online_expert_uncertainty as evaluate

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_online_expert_uncertainty_posthoc_report.json"
)


def test_frozen_online_uncertainty_report_recomputes_exactly() -> None:
    frozen = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    outputs, report = evaluate.compile_online_expert_uncertainty_posthoc(
        generated_at=datetime.fromisoformat(frozen["generated_at"]),
    )

    assert report == frozen
    for descriptor in frozen["implementation_artifacts"].values():
        body = (REPO_ROOT / descriptor["path"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == descriptor["sha256"]
        assert len(body) == descriptor["size_bytes"]
    for name, body in outputs.items():
        descriptor = frozen["outputs"][name]
        assert (REPO_ROOT / descriptor["path"]).read_bytes() == body
        assert hashlib.sha256(body).hexdigest() == descriptor["sha256"]


def test_uncertainty_comparison_preserves_point_model_tradeoff() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    interpretation = report["diagnostic_interpretation"]

    assert interpretation["window_horizon_comparison_count"] == 16
    assert interpretation["v5_lower_mean_interval_score_count"] == 3
    assert interpretation["selector_lower_mean_interval_score_count"] == 5
    assert interpretation["equal_mean_interval_score_count"] == 8
    assert interpretation["v5_coverage_at_or_above_target_count"] == 11
    assert interpretation["selector_coverage_at_or_above_target_count"] == 11
    assert interpretation["v5_minimum_coverage_minus_target"] == pytest.approx(
        -0.051229,
        abs=1e-6,
    )
    assert interpretation["signed_negative_observation_count"] == 418
    assert interpretation["v5_signed_negative_observation_covered_count"] == 414
    assert interpretation["selector_signed_negative_observation_covered_count"] == 414


def test_center_hill_interval_score_winners_change_by_window_and_horizon() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    primary = report["windows"]["center_hill_primary"]["comparison_by_horizon"]
    replication = report["windows"]["center_hill_replication"]["comparison_by_horizon"]

    assert [
        primary[str(horizon)]["v5_minus_selector_mean_interval_score_m3s"]
        for horizon in (1, 3, 6, 12)
    ] == pytest.approx([32.576793, 21.591675, 10.074473, -0.164507], abs=1e-6)
    assert [
        replication[str(horizon)]["v5_minus_selector_mean_interval_score_m3s"]
        for horizon in (1, 3, 6, 12)
    ] == pytest.approx([6.098374, 2.736371, -0.795538, -7.708599], abs=1e-6)


def test_uncertainty_replay_does_not_upgrade_claims_or_change_points() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert all(
        window["execution"]["future_target_observation_used_at_interval_inference"] is False
        and window["execution"]["point_predictions_modified"] is False
        for window in report["windows"].values()
    )
    assert report["information_boundary"]["evaluation_counts_as_fresh_validation"] is False
    assert report["claim_boundary"]["finite_sample_coverage_guarantee_claimed"] is False
    assert report["claim_boundary"]["uncertainty_candidate_admitted"] is False
    assert report["claim_boundary"]["geospatial_kernel_validated"] is False


def test_uncertainty_replay_rejects_wrong_source_contract(tmp_path: Path) -> None:
    payload = json.loads(evaluate.DEFAULT_SOURCE_REPORT.read_text(encoding="utf-8"))
    payload["status"] = "tampered"
    path = tmp_path / "source.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="source_report_invalid"):
        evaluate.compile_online_expert_uncertainty_posthoc(source_report_path=path)
