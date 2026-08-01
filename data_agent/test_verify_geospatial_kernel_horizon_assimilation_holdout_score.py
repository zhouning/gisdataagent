import json

import pytest

from scripts import verify_geospatial_kernel_horizon_assimilation_holdout_score as verify


def test_independent_score_reconstruction_passes() -> None:
    report = verify.verify_score()

    assert report["status"] == "pass_single_score_independent_reconstruction"
    assert report["score_reconstruction"] == {
        "case_count": 448,
        "scored_cases_reconstructed_exactly": True,
        "system_horizon_group_count": 8,
        "group_metrics_and_gates_reconstructed_exactly": True,
        "minimum_sample_gate_pass_count": 8,
        "passed_group_count": 3,
        "failed_group_count": 5,
        "structural_tie_groups": ["center_hill:3h", "j_percy_priest:3h"],
        "formal_candidate_support_gate_passed": False,
    }
    assert report["execution_audit"]["logical_outcome_request_count"] == 2
    assert report["execution_audit"]["remote_outcome_attempt_count"] == 2
    assert report["execution_audit"]["formal_score_execution_count"] == 1
    assert report["execution_audit"]["verifier_called_formal_scorer"] is False


def test_independent_verifier_rejects_tampered_aggregate(tmp_path) -> None:
    payload = json.loads(verify.DEFAULT_SCORE.read_bytes())
    payload["aggregate_gate"]["passed_group_count"] = 4
    path = tmp_path / "tampered-score.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="horizon_holdout_verification_aggregate_gate_mismatch",
    ):
        verify.verify_score(score_path=path)
