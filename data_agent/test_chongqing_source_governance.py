import json
from copy import deepcopy

from data_agent import chongqing_source_governance as governance


def _evidence() -> dict:
    return json.loads(governance.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))


def _rehash(value: dict) -> None:
    stable = {key: item for key, item in value.items() if key != "evidence_sha256"}
    value["evidence_sha256"] = governance.canonical_json_fingerprint(stable)


def test_checked_governance_baseline_is_valid_but_blocked():
    evidence = _evidence()

    assert governance.validate_evidence(evidence) == []
    report = governance.build_validation_report()

    assert report["status"] == "valid"
    assert report["candidate_asset_id"] == "bishan_land_use_dltb_local"
    assert report["pending_decision_count"] == 8
    assert report["source_governance_approved"] is False
    assert report["source_content_admitted"] is False


def test_governance_binds_both_upstream_evidence_layers():
    source = _evidence()["source_binding"]

    assert source["upstream_admission_evidence_sha256"] == (
        "a2196495d845d61be939c7fc36a7f05c3567e365599d2d04be0aab9c568459c1"
    )
    assert source["upstream_provenance_evidence_sha256"] == (
        "b56ce0c036827d4338ab2cfae8f3fb4c9e1e78ec18aac243272f1f77801300ef"
    )


def test_all_required_governance_decisions_are_pending():
    decisions = _evidence()["governance_decisions"]

    assert tuple(decisions) == governance.DECISION_FIELDS
    assert all(record["status"] == "pending" for record in decisions.values())
    assert all(record["decision_ref"] is None for record in decisions.values())
    assert all(record["attestation_sha256"] is None for record in decisions.values())


def test_rehash_cannot_turn_governance_into_admission():
    evidence = deepcopy(_evidence())
    evidence["claims"]["governance_decisions_complete"] = True
    evidence["claims"]["source_governance_approved"] = True
    evidence["claims"]["source_content_admitted"] = True
    _rehash(evidence)

    errors = governance.validate_evidence(evidence)

    assert "M3-30 claim does not match: governance_decisions_complete" in errors
    assert "M3-30 claim does not match: source_governance_approved" in errors
    assert "M3-30 claim does not match: source_content_admitted" in errors


def test_decision_attestation_must_be_a_sha256():
    evidence = deepcopy(_evidence())
    evidence["governance_decisions"]["owner"]["attestation_sha256"] = "not-a-sha"
    _rehash(evidence)

    errors = governance.validate_evidence(evidence)

    assert "M3-30 decision attestation is invalid: owner" in errors


def test_upstream_provenance_fingerprint_cannot_drift():
    evidence = deepcopy(_evidence())
    evidence["source_binding"]["upstream_provenance_evidence_sha256"] = "0" * 64
    _rehash(evidence)

    errors = governance.validate_evidence(evidence)

    assert "M3-30 source binding does not match: upstream_provenance_evidence_sha256" in errors


def test_path_or_payload_marker_is_rejected_even_after_rehash():
    evidence = deepcopy(_evidence())
    evidence["governance_decisions"]["owner"]["decision_ref"] = "/private/approval.txt"
    _rehash(evidence)

    errors = governance.validate_evidence(evidence)

    assert "M3-30 evidence contains a path or payload marker" in errors


def test_policy_keeps_all_side_effect_authority_false():
    policy = _evidence()["admission_policy"]

    assert policy["metadata_governance_record_allowed"] is True
    assert policy["landing_authority_creation_allowed"] is False
    assert policy["scheduler_submission_allowed"] is False
    assert policy["provider_mutation_allowed"] is False


def test_validator_report_is_path_free():
    report = governance.build_validation_report()
    rendered = json.dumps(report, ensure_ascii=False)

    assert "/private/" not in rendered
    assert "/Users/" not in rendered
