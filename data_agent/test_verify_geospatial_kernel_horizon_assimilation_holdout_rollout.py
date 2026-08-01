import json
from datetime import datetime

import pytest

from scripts import verify_geospatial_kernel_horizon_assimilation_holdout_rollout as verify


def test_real_rollout_verifies_every_seal_gate_and_request_boundary() -> None:
    report = verify.verify_rollout(
        generated_at=datetime.fromisoformat("2026-08-01T03:30:00+00:00")
    )

    assert report["status"] == "pass_chronological_outcome_free_rollout_verification"
    assert report["seal_chain"] == {
        "joint_issue_seal_count": 56,
        "final_joint_issue_seal_sha256": (
            "49448d2230c47214d0f3b8cc4b8a969dfc5cbae8efcbfcb2dfe33a7a0ca712d5"
        ),
        "chronological_chain_verified": True,
        "all_issue_artifact_hashes_verified": True,
        "all_previous_seal_links_verified": True,
    }
    assert report["execution_gates"] == {
        "analysis_ledger_check_count": 448,
        "analysis_ledger_pass_count": 448,
        "physical_mass_balance_check_count": 5376,
        "physical_mass_balance_pass_count": 5376,
        "nominal_conformance_check_count": 112,
        "nominal_conformance_pass_count": 112,
        "maximum_nominal_conformance_error_m3s": 0.0,
        "raw_issue_observation_hash_check_count": 112,
        "next_canonical_state_hash_check_count": 112,
        "prediction_csv_reconstructed_exactly": True,
        "all_execution_gates_passed": True,
    }
    assert report["request_boundary"] == {
        "frozen_request_count_completed": 122,
        "static_request_count": 10,
        "issue_only_usgs_request_count": 112,
        "full_outcome_request_count": 0,
        "full_outcome_series_loaded": False,
    }


def test_real_observation_fallback_statistics_preserve_negative_values() -> None:
    report = verify.verify_rollout(
        generated_at=datetime.fromisoformat("2026-08-01T03:30:00+00:00")
    )

    assert report["observations"]["center_hill"] == {
        "issue_count": 56,
        "exact_timestamp_count": 56,
        "nonnegative_value_count": 56,
    }
    assert report["observations"]["j_percy_priest"] == {
        "issue_count": 56,
        "exact_timestamp_count": 56,
        "nonnegative_value_count": 50,
        "negative_value_count": 6,
    }
    assert report["claim_boundary"]["holdout_scored"] is False
    assert report["claim_boundary"]["candidate_promoted"] is False


def test_verifier_rejects_tampered_issue_artifact_hash(tmp_path) -> None:
    rollout = json.loads(verify.DEFAULT_ROLLOUT_REPORT.read_bytes())
    rollout["issue_artifacts"][0]["sha256"] = "0" * 64
    path = tmp_path / "tampered-rollout.json"
    path.write_text(json.dumps(rollout), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="horizon_holdout_verification_artifact_identity_mismatch",
    ):
        verify.verify_rollout(
            rollout_report_path=path,
            generated_at=datetime.fromisoformat("2026-08-01T03:30:00+00:00"),
        )


def test_verifier_rejects_scored_or_promoted_rollout_claim(tmp_path) -> None:
    rollout = json.loads(verify.DEFAULT_ROLLOUT_REPORT.read_bytes())
    rollout["claim_boundary"]["holdout_scored"] = True
    path = tmp_path / "prematurely-scored-rollout.json"
    path.write_text(json.dumps(rollout), encoding="utf-8")

    with pytest.raises(ValueError, match="horizon_holdout_verification_lineage_invalid"):
        verify.verify_rollout(
            rollout_report_path=path,
            generated_at=datetime.fromisoformat("2026-08-01T03:30:00+00:00"),
        )


def test_generated_verification_artifact_is_reconstructible() -> None:
    frozen = json.loads(verify.DEFAULT_OUTPUT.read_bytes())
    rebuilt = verify.verify_rollout(
        generated_at=datetime.fromisoformat(frozen["generated_at"])
    )

    assert rebuilt == frozen
