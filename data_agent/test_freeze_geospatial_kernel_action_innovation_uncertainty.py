import hashlib
import json

import pytest

from scripts.freeze_geospatial_kernel_action_innovation_uncertainty import (
    DEFAULT_UNCERTAINTY_REPORT,
    REPO_ROOT,
    compile_freeze,
)


def test_uncertainty_freeze_locks_radii_without_admission() -> None:
    payload = compile_freeze()

    assert payload["status"] == "frozen_uncertainty_candidate_not_admitted"
    assert payload["uncertainty_lock"]["horizons_hours"] == [1, 3, 6, 12]
    assert payload["uncertainty_lock"]["target_marginal_coverage"] == 0.9
    assert payload["uncertainty_lock"]["per_window_recalibration_permitted"] is False
    assert (
        payload["statistical_claim_boundary"]["finite_sample_coverage_guarantee_claimed"] is False
    )
    assert payload["prospective_evaluation_contract"]["fresh_prospective_window_required"] is True
    assert payload["admission_contract"]["uncertainty_candidate_admitted"] is False
    assert payload["admission_contract"]["runtime_default_enabled"] is False


def test_uncertainty_freeze_artifacts_bind_existing_bytes() -> None:
    payload = compile_freeze()

    for descriptor in payload["candidate_artifacts"].values():
        body = (REPO_ROOT / descriptor["path"]).read_bytes()
        assert descriptor["sha256"] == hashlib.sha256(body).hexdigest()
        assert descriptor["size_bytes"] == len(body)


def test_uncertainty_freeze_rejects_inflated_coverage_claim(tmp_path) -> None:
    report = json.loads(DEFAULT_UNCERTAINTY_REPORT.read_bytes())
    report["statistical_claim_boundary"]["finite_sample_coverage_guarantee_claimed"] = True
    path = tmp_path / "inflated-uncertainty-report.json"
    path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match="uncertainty_report_not_freezable"):
        compile_freeze(uncertainty_report_path=path)
