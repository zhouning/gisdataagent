import json
from copy import deepcopy

from data_agent import chongqing_extraction_provenance as provenance


def _evidence() -> dict:
    return json.loads(provenance.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))


def _rehash(value: dict) -> None:
    stable = {key: item for key, item in value.items() if key != "evidence_sha256"}
    value["evidence_sha256"] = provenance.canonical_json_fingerprint(stable)


def test_checked_provenance_is_valid_but_derivation_blocked():
    evidence = _evidence()

    assert provenance.validate_evidence(evidence) == []
    report = provenance.build_validation_report()

    assert report["status"] == "valid"
    assert report["derivation_verified"] is False
    assert report["source_content_admitted"] is False
    assert report["missing_evidence_count"] == 6


def test_provenance_reuses_m3_28_fingerprints_and_comparison_counts():
    evidence = _evidence()

    assert evidence["source_binding"] == {
        "archive_scope_entry_count": 532,
        "archive_scope_size_bytes": 694147946,
        "archive_sha256": "2043b60c2f4f7f32a31388a634fae4ac28534990e205aa86b8df0e4b64dcbbca",
        "extracted_file_count": 584,
        "extracted_payload_sha256": "e7e81e4f53f9f174792f500fbfdfde6bee30ec03beac8cbd91771fe09f548ea6",
        "extracted_size_bytes": 700610744,
        "source_id": "chongqing-planning-institute-sample",
        "upstream_admission_evidence_file_sha256": "9b5c20369c235f7e0a2f2cb0a21cee77f86981aa273bac196605a4803b05ce83",
        "upstream_admission_evidence_sha256": "a2196495d845d61be939c7fc36a7f05c3567e365599d2d04be0aab9c568459c1",
    }
    assert evidence["comparison"] == {
        "additional_extracted_file_count": 52,
        "archive_extracted_entry_multiset_verified": False,
        "exact_match_count": 526,
        "missing_entry_count": 0,
        "modified_entry_count": 6,
    }


def test_missing_derivation_evidence_is_explicit_and_ordered():
    assert provenance.MISSING_EVIDENCE == [
        "derivation:operator_identity_missing",
        "derivation:tool_version_missing",
        "derivation:command_digest_missing",
        "derivation:modified_entry_manifest_missing",
        "derivation:additional_entry_manifest_missing",
        "derivation:archive_to_working_set_attestation_missing",
    ]


def test_rehash_cannot_turn_provenance_into_admission():
    evidence = deepcopy(_evidence())
    evidence["claims"]["derivation_provenance_complete"] = True
    evidence["claims"]["source_content_admitted"] = True
    evidence["derivation"]["archive_to_working_set_attestation"] = True
    _rehash(evidence)

    errors = provenance.validate_evidence(evidence)

    assert "M3-29 claim does not match: derivation_provenance_complete" in errors
    assert "M3-29 claim does not match: source_content_admitted" in errors
    assert "M3-29 derivation does not match: archive_to_working_set_attestation" in errors


def test_upstream_admission_fingerprint_cannot_drift():
    evidence = deepcopy(_evidence())
    evidence["source_binding"]["upstream_admission_evidence_sha256"] = "0" * 64
    _rehash(evidence)

    errors = provenance.validate_evidence(evidence)

    assert "M3-29 source binding does not match: upstream_admission_evidence_sha256" in errors


def test_path_or_payload_marker_is_rejected_even_after_rehash():
    evidence = deepcopy(_evidence())
    evidence["derivation"]["local_source_path"] = "/private/source.zip"
    _rehash(evidence)

    errors = provenance.validate_evidence(evidence)

    assert "M3-29 evidence contains a path or payload marker" in errors


def test_checked_file_fingerprint_rejects_rehashed_copy(tmp_path):
    evidence = deepcopy(_evidence())
    evidence["captured_at"] = "2026-08-17T09:00:00Z"
    _rehash(evidence)
    path = tmp_path / "provenance.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False), encoding="utf-8")

    report = provenance.build_validation_report(path)

    assert report["status"] == "invalid"
    assert "M3-29 evidence file fingerprint does not match" in report["errors"]


def test_all_authority_claims_remain_false():
    claims = _evidence()["claims"]

    assert claims["comparison_observed"] is True
    assert all(
        claims[key] is False
        for key in provenance.CLAIMS
        if key != "comparison_observed"
    )


def test_validator_report_is_path_free():
    report = provenance.build_validation_report()
    rendered = json.dumps(report, ensure_ascii=False)

    assert "/private/" not in rendered
    assert "/Users/" not in rendered
