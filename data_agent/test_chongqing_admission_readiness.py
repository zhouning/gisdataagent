import json
from copy import deepcopy

from data_agent import chongqing_admission_readiness as readiness


def _evidence() -> dict:
    return json.loads(readiness.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))


def _rehash(value: dict) -> None:
    stable = {key: item for key, item in value.items() if key != "evidence_sha256"}
    value["evidence_sha256"] = readiness.canonical_json_fingerprint(stable)


def test_checked_readiness_profile_is_valid_but_blocked():
    evidence = _evidence()

    assert readiness.validate_evidence(evidence) == []
    report = readiness.build_validation_report()

    assert report["status"] == "valid"
    assert report["candidate_asset_id"] == "bishan_land_use_dltb_local"
    assert report["pending_requirement_count"] == 15
    assert report["admission_eligible"] is False
    assert report["source_content_admitted"] is False


def test_readiness_binds_all_three_upstream_evidence_layers():
    source = _evidence()["source_binding"]

    assert source["upstream_admission_evidence_sha256"] == (
        "a2196495d845d61be939c7fc36a7f05c3567e365599d2d04be0aab9c568459c1"
    )
    assert source["upstream_provenance_evidence_sha256"] == (
        "b56ce0c036827d4338ab2cfae8f3fb4c9e1e78ec18aac243272f1f77801300ef"
    )
    assert source["upstream_governance_evidence_sha256"] == (
        "97cf11ab8938c048dce9db903d1a4f30758f208dec6dad1a08b740a4a8fe7b6f"
    )


def test_required_evidence_is_partitioned_by_authority_boundary():
    requirements = _evidence()["required_evidence"]

    assert all(
        requirements[key]["source"] == "derivation"
        for key in readiness.REQUIREMENT_KEYS[:6]
    )
    assert all(
        requirements[key]["source"] == "governance"
        for key in readiness.REQUIREMENT_KEYS[6:14]
    )
    assert requirements["fresh_protected_attestation"]["source"] == "protected"
    assert all(record["status"] == "missing" for record in requirements.values())


def test_rehash_cannot_turn_readiness_into_admission():
    evidence = deepcopy(_evidence())
    evidence["claims"]["admission_eligible"] = True
    evidence["claims"]["source_content_admitted"] = True
    _rehash(evidence)

    errors = readiness.validate_evidence(evidence)

    assert "M3-31 claim does not match: admission_eligible" in errors
    assert "M3-31 claim does not match: source_content_admitted" in errors


def test_requirement_attestation_must_be_a_sha256():
    evidence = deepcopy(_evidence())
    evidence["required_evidence"]["owner_decision"]["attestation_sha256"] = "not-a-sha"
    _rehash(evidence)

    errors = readiness.validate_evidence(evidence)

    assert "M3-31 requirement attestation is invalid: owner_decision" in errors


def test_upstream_governance_fingerprint_cannot_drift():
    evidence = deepcopy(_evidence())
    evidence["source_binding"]["upstream_governance_evidence_sha256"] = "0" * 64
    _rehash(evidence)

    errors = readiness.validate_evidence(evidence)

    assert "M3-31 source binding does not match: upstream_governance_evidence_sha256" in errors


def test_path_or_payload_marker_is_rejected_even_after_rehash():
    evidence = deepcopy(_evidence())
    evidence["required_evidence"]["owner_decision"]["attestation_sha256"] = (
        "/private/approval.json"
    )
    _rehash(evidence)

    errors = readiness.validate_evidence(evidence)

    assert "M3-31 evidence contains a path or payload marker" in errors


def test_policy_keeps_all_side_effect_authority_false():
    policy = _evidence()["admission_policy"]

    assert policy["metadata_readiness_record_allowed"] is True
    assert policy["content_admission_authorized"] is False
    assert policy["landing_authority_creation_allowed"] is False
    assert policy["resource_version_creation_allowed"] is False
    assert policy["platform_run_creation_allowed"] is False
    assert policy["scheduler_submission_allowed"] is False
    assert policy["provider_mutation_allowed"] is False


def test_validator_report_is_path_free():
    report = readiness.build_validation_report()
    rendered = json.dumps(report, ensure_ascii=False)

    assert "/private/" not in rendered
    assert "/Users/" not in rendered
