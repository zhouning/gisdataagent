import json
from copy import deepcopy
from datetime import UTC, datetime

import pytest

from data_agent import metadata_fabric_protected_real_feature_reexecution_gate as gate

EVALUATED_AT = datetime(2026, 7, 31, 6, 45, tzinfo=UTC)


def _checked_decision() -> dict:
    return json.loads(gate.DEFAULT_DECISION_PATH.read_text(encoding="utf-8"))


def _ready_identity_report(attestation: dict) -> dict:
    report = gate.identity_gate.build_identity_readiness_report(now=EVALUATED_AT)
    report["profile_blockers"] = []
    report["ready_for_protected_verification"] = True
    report["attestation_valid"] = True
    report["attestation_errors"] = []
    report["attestation_fingerprint"] = gate.canonical_json_fingerprint(attestation)
    for claim in gate.identity_gate.REPORT_CLAIMS:
        report[claim] = True
    stable = {key: value for key, value in report.items() if key != "report_fingerprint"}
    report["report_fingerprint"] = gate.identity_gate.recovery._canonical_sha256(stable)
    assert gate.identity_gate.verify_report_integrity(report) == []
    return report


def _ready_object_store_report(attestation: dict) -> dict:
    report = gate.object_store_gate.build_object_store_readiness_report(
        now=EVALUATED_AT
    )
    report["profile_blockers"] = []
    report["ready_for_protected_verification"] = True
    report["attestation_valid"] = True
    report["attestation_errors"] = []
    report["attestation_fingerprint"] = gate.canonical_json_fingerprint(attestation)
    for claim in gate.object_store_gate.REPORT_CLAIMS:
        report[claim] = True
    stable = {key: value for key, value in report.items() if key != "report_fingerprint"}
    report["report_fingerprint"] = gate.object_store_gate.recovery._canonical_sha256(
        stable
    )
    assert gate.object_store_gate.verify_report_integrity(report) == []
    return report


def test_contract_binds_real_predecessor_and_keeps_execution_closed():
    contract = gate.build_contract_report()

    assert contract["status"] == "valid"
    assert contract["errors"] == []
    assert contract["source_binding"]["source_evidence_sha256"] == (
        gate.SOURCE_EVIDENCE_SHA256
    )
    assert contract["source_binding"]["feature_count"] == 20
    assert contract["source_binding"]["platform_run_status"] == "succeeded"
    assert contract["requires_protected_identity_attestation"] is True
    assert contract["requires_protected_object_store_attestation"] is True
    assert contract["fresh_protected_ingestion_required"] is True
    assert contract["local_material_promotion_forbidden"] is True
    assert contract["scheduler_submission_authorized"] is False
    assert contract["provider_mutation_authorized"] is False
    assert contract["production_ready"] is False


def test_checked_pending_decision_is_valid_and_exposes_exact_blockers():
    decision = _checked_decision()
    validation = gate.build_validation_report()

    assert gate.validate_decision(decision) == []
    assert validation["status"] == "valid"
    assert validation["errors"] == []
    assert decision["status"] == gate.BLOCKED_STATUS
    assert decision["ready_for_protected_reexecution"] is False
    assert decision["production_profiles_valid"] is True
    assert len(decision["identity_report"]["profile_blockers"]) == 40
    assert len(decision["object_store_report"]["profile_blockers"]) == 43
    assert len(decision["blockers"]) == 85
    assert decision["identity_attestation"] is None
    assert decision["object_store_attestation"] is None


def test_composition_requires_both_gates_and_one_source_revision(monkeypatch):
    identity_attestation = {"source_revision": "a" * 40}
    object_store_attestation = {"source_revision": "a" * 40}
    identity_report = _ready_identity_report(identity_attestation)
    object_store_report = _ready_object_store_report(object_store_attestation)
    monkeypatch.setattr(
        gate.identity_gate,
        "build_identity_readiness_report",
        lambda **_: deepcopy(identity_report),
    )
    monkeypatch.setattr(
        gate.object_store_gate,
        "build_object_store_readiness_report",
        lambda **_: deepcopy(object_store_report),
    )

    decision = gate.build_decision(
        identity_attestation=identity_attestation,
        object_store_attestation=object_store_attestation,
        now=EVALUATED_AT,
    )

    assert decision["status"] == gate.READY_STATUS
    assert decision["ready_for_protected_reexecution"] is True
    assert decision["protected_tenant_controls_attested"] is True
    assert decision["cross_gate_source_revision_aligned"] is True
    assert decision["blockers"] == []
    assert decision["scheduler_submission_authorized"] is False
    assert decision["provider_mutation_authorized"] is False
    assert decision["production_ingestion_verified"] is False
    assert decision["production_ready"] is False

    mismatched = gate.build_decision(
        identity_attestation=identity_attestation,
        object_store_attestation={"source_revision": "b" * 40},
        now=EVALUATED_AT,
    )
    assert mismatched["status"] == gate.BLOCKED_STATUS
    assert mismatched["ready_for_protected_reexecution"] is False
    assert "cross_gate:source_revision_mismatch" in mismatched["blockers"]


def test_source_evidence_file_drift_fails_closed(tmp_path):
    drifted = tmp_path / "source.json"
    drifted.write_bytes(gate.DEFAULT_SOURCE_EVIDENCE_PATH.read_bytes() + b"\n")

    with pytest.raises(
        gate.ProtectedRealFeatureReexecutionGateError,
        match="source evidence file fingerprint does not match",
    ):
        gate.build_source_binding(drifted)


def test_outer_rehash_cannot_hide_nested_tampering_or_overclaim():
    decision = _checked_decision()
    decision["identity_report"]["profile_fingerprint"] = "0" * 64
    decision["local_material_promotion_allowed"] = True
    stable = {
        key: value for key, value in decision.items() if key != "decision_sha256"
    }
    decision["decision_sha256"] = gate.canonical_json_fingerprint(stable)

    errors = gate.validate_decision(decision)

    assert "M3-26 decision does not match current bound inputs" in errors
    assert "identity readiness report fingerprint does not match" in errors
    assert "M3-26 decision may not claim local_material_promotion_allowed" in errors


def test_checked_decision_contains_no_local_path_or_feature_payload():
    rendered = gate.DEFAULT_DECISION_PATH.read_text(encoding="utf-8")
    decision = json.loads(rendered)

    assert "/Users/" not in rendered
    assert "Downloads/" not in rendered
    assert "geometry_values" not in rendered
    assert decision["local_retained_material_dependency"] is False
    assert decision["source_payload_dependency"] is False
    assert decision["fresh_protected_ingestion_required"] is True


def test_wrapper_is_strict_and_invokes_gate():
    wrapper = (
        gate.REPO_ROOT
        / "scripts/metadata-fabric-protected-real-feature-reexecution-gate.sh"
    )
    text = wrapper.read_text(encoding="utf-8")

    assert "set -euo pipefail" in text
    assert "metadata_fabric_protected_real_feature_reexecution_gate" in text
