import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

from data_agent import chongqing_admission_readiness as readiness
from data_agent import chongqing_protected_admission as protected

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def _readiness() -> dict:
    return json.loads(readiness.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))


def _attestation() -> dict:
    evidence = _readiness()
    source = evidence["source_binding"]
    value = {
        "schema": protected.ATTESTATION_SCHEMA,
        "readiness_evidence_sha256": evidence["evidence_sha256"],
        "readiness_evidence_file_sha256": readiness.EVIDENCE_FILE_SHA256,
        "source_binding": {
            key: source[key]
            for key in ("source_id", "source_group_id", "asset_id", "source_ref")
        },
        "observed_at": "2026-08-17T11:45:00Z",
        "expires_at": "2026-08-18T11:45:00Z",
        "protected_environment": protected.PROTECTED_ENVIRONMENT,
        "verifier_identity": "protected-admission-verifier@platform",
        "evidence_uri": "https://attestations.gisplatform.com/admission/2026-08-17",
        "requirements": {
            key: {"status": "verified", "attestation_sha256": "a" * 64}
            for key in readiness.REQUIREMENT_KEYS
        },
        "checks": {key: "passed" for key in protected.EXPECTED_CHECKS},
    }
    stable = dict(value)
    value["attestation_sha256"] = protected.canonical_json_fingerprint(stable)
    return value


def test_pending_profile_is_valid_but_protected_attestation_is_missing():
    report = protected.build_admission_report(now=NOW)

    assert report["readiness_valid"] is True
    assert report["attestation_valid"] is False
    assert report["admission_eligible"] is False
    assert report["attestation_errors"] == [
        "protected admission attestation is missing"
    ]
    assert report["content_admission_authorized"] is False
    assert report["production_ready"] is False


def test_complete_attestation_only_passes_the_readiness_evaluation():
    report = protected.build_admission_report(attestation=_attestation(), now=NOW)

    assert report["readiness_valid"] is True
    assert report["attestation_valid"] is True
    assert report["admission_eligible"] is True
    assert report["content_admission_authorized"] is False
    assert report["source_content_admitted"] is False
    assert report["landing_authority_created"] is False
    assert report["resource_version_created"] is False
    assert report["platform_run_created"] is False
    assert report["scheduler_submission_authorized"] is False
    assert report["provider_mutation_authorized"] is False
    assert report["production_ready"] is False
    assert protected.verify_report_integrity(report) == []


def test_attestation_binding_drift_fails_closed():
    attestation = _attestation()
    attestation["source_binding"]["asset_id"] = "other_asset"
    attestation["attestation_sha256"] = protected.canonical_json_fingerprint(
        {key: value for key, value in attestation.items() if key != "attestation_sha256"}
    )

    report = protected.build_admission_report(attestation=attestation, now=NOW)

    assert report["admission_eligible"] is False
    assert "protected admission source binding does not match M3-31" in report[
        "attestation_errors"
    ]


def test_stale_attestation_fails_closed():
    attestation = _attestation()
    attestation["observed_at"] = "2026-08-15T11:45:00Z"
    attestation["attestation_sha256"] = protected.canonical_json_fingerprint(
        {key: value for key, value in attestation.items() if key != "attestation_sha256"}
    )

    report = protected.build_admission_report(attestation=attestation, now=NOW)

    assert report["admission_eligible"] is False
    assert "protected admission attestation is outside the freshness window" in report[
        "attestation_errors"
    ]


def test_requirement_path_marker_and_missing_check_fail_closed():
    attestation = deepcopy(_attestation())
    attestation["requirements"]["owner_decision"]["attestation_sha256"] = "/private/owner.json"
    attestation["checks"].pop("reviewer_approval")
    attestation["attestation_sha256"] = protected.canonical_json_fingerprint(
        {key: value for key, value in attestation.items() if key != "attestation_sha256"}
    )

    report = protected.build_admission_report(attestation=attestation, now=NOW)

    assert report["admission_eligible"] is False
    assert "protected admission attestation contains a path or payload marker" in report[
        "attestation_errors"
    ]
    assert "protected admission check inventory does not match" in report[
        "attestation_errors"
    ]


def test_report_tampering_cannot_create_authority():
    report = protected.build_admission_report(attestation=_attestation(), now=NOW)
    report["content_admission_authorized"] = True

    assert "protected admission report fingerprint does not match" in (
        protected.verify_report_integrity(report)
    )


def test_attestation_lifetime_is_bounded():
    attestation = _attestation()
    attestation["expires_at"] = (NOW + timedelta(days=8)).isoformat()
    attestation["attestation_sha256"] = protected.canonical_json_fingerprint(
        {key: value for key, value in attestation.items() if key != "attestation_sha256"}
    )

    report = protected.build_admission_report(attestation=attestation, now=NOW)

    assert "protected admission attestation lifetime exceeds seven days" in report[
        "attestation_errors"
    ]
