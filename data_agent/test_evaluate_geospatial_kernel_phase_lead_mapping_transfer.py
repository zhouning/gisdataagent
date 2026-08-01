from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from scripts import evaluate_geospatial_kernel_phase_lead_mapping_transfer as transfer

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_phase_lead_mapping_transfer_posthoc_report.json"
)


def test_frozen_phase_lead_mapping_transfer_report_recomputes_exactly() -> None:
    frozen = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    recomputed = transfer.compile_phase_lead_mapping_transfer_posthoc(
        generated_at=datetime.fromisoformat(frozen["generated_at"]),
    )

    assert recomputed == frozen
    for descriptor in frozen["implementation_artifacts"].values():
        path = REPO_ROOT / descriptor["path"]
        body = path.read_bytes()
        assert hashlib.sha256(body).hexdigest() == descriptor["sha256"]
        assert len(body) == descriptor["size_bytes"]


def test_primary_selected_mapping_repeats_in_later_historical_window() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert report["selected_mapping_by_primary_window"] == {
        "1": 3,
        "3": 6,
        "6": 12,
    }
    assert report["replication_best_mapping"] == {
        "1": 3,
        "3": 6,
        "6": 12,
    }
    interpretation = report["diagnostic_interpretation"]
    assert interpretation["primary_selected_mapping_matches_v4_fixed_mapping"] is True
    assert (
        interpretation["primary_selected_mapping_matches_replication_best_for_nontrivial_targets"]
        is True
    )
    assert interpretation["full_predictor_ranking_replicated_for_nontrivial_targets"] is True
    assert (
        interpretation["selected_mapping_beats_raw_physical_all_horizons_in_both_windows"] is True
    )
    assert (
        interpretation["phase_lead_hypothesis_survives_historical_temporal_transfer_diagnostic"]
        is True
    )
    assert interpretation["routing_celerity_error_identified"] is False

    one_hour = report["candidate_results_by_target_horizon"]["1"]
    assert [row["predictor_horizon_hours"] for row in one_hour] == [3, 6, 12]
    assert [
        row["primary_window"]["online_minus_raw_physical_rmse_m3s"] for row in one_hour
    ] == pytest.approx([-8.202601, -3.449971, -0.008625], abs=1e-6)
    assert [
        row["replication_window"]["online_minus_raw_physical_rmse_m3s"] for row in one_hour
    ] == pytest.approx([-14.988356, -4.885123, 0.033020], abs=1e-6)


def test_mapping_transfer_report_preserves_posthoc_claim_boundary() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert (
        report["diagnostic_interpretation"][
            "causal_maturity_ordering_passed_for_all_candidate_replays"
        ]
        is True
    )
    boundary = report["information_boundary"]
    assert boundary["both_historical_target_windows_exposed_before_diagnostic_design"] is True
    assert boundary["replication_window_is_fresh_prospective_validation"] is False
    assert boundary["diagnostic_may_promote_candidate"] is False
    claims = report["claim_boundary"]
    assert claims["phase_lead_mapping_admitted"] is False
    assert claims["geospatial_kernel_validated"] is False
    assert claims["runtime_default_enabled"] is False


def test_mapping_transfer_rejects_wrong_upstream_report_contract(
    tmp_path: Path,
) -> None:
    payload = json.loads(transfer.DEFAULT_COMPARISON_REPORT.read_text(encoding="utf-8"))
    payload["status"] = "tampered"
    path = tmp_path / "comparison.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="comparison_report_invalid"):
        transfer.compile_phase_lead_mapping_transfer_posthoc(
            comparison_report_path=path,
        )
