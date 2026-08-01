import hashlib
import json

import pytest

from scripts.freeze_geospatial_kernel_action_innovation_candidate import (
    DEFAULT_CANDIDATE_REPORT,
    REPO_ROOT,
    compile_freeze,
)


def test_freeze_binds_candidate_and_keeps_runtime_disabled() -> None:
    payload = compile_freeze()

    assert payload["status"] == "frozen_bounded_candidate_not_admitted"
    assert payload["operator_lock"]["supported_forecast_horizons_hours"] == [1, 3, 6, 12]
    assert payload["operator_lock"]["per_window_refit_permitted"] is False
    assert payload["operator_lock"]["arbitrary_long_rollout_supported"] is False
    assert payload["causal_runtime_contract"]["future_outlet_observations_permitted"] is False
    assert payload["causal_runtime_contract"]["unregistered_horizon_policy"] == "reject"
    assert payload["issue_time_input_contract"]["operational_forecast_claim_permitted"] is False
    assert payload["admission_contract"]["runtime_default_enabled"] is False
    assert payload["admission_contract"]["admission_gate_passed"] is False
    assert payload["admission_contract"]["fresh_prospective_evidence_required"] is True
    assert payload["admission_contract"]["multi_system_evidence_required"] is True
    assert payload["claim_boundary"]["geospatial_kernel_validated"] is False


def test_freeze_artifact_descriptors_bind_existing_bytes() -> None:
    payload = compile_freeze()

    for descriptor in payload["candidate_artifacts"].values():
        body = (REPO_ROOT / descriptor["path"]).read_bytes()
        assert descriptor["sha256"] == hashlib.sha256(body).hexdigest()
        assert descriptor["size_bytes"] == len(body)


def test_freeze_rejects_candidate_report_with_inflated_admission(tmp_path) -> None:
    report = json.loads(DEFAULT_CANDIDATE_REPORT.read_bytes())
    report["aggregate_gate"]["admission_gate_passed"] = True
    path = tmp_path / "inflated-candidate-report.json"
    path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match="candidate_report_not_freezable"):
        compile_freeze(candidate_report_path=path)
