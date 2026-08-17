"""Validate the metadata-only governance gate for the first Chongqing source.

M3-30 selects the first candidate land-parcel source and records the governance
decisions required before content admission. The checked evidence is a
fail-closed decision baseline: every decision is pending, and it never reads
or copies source payloads or creates Landing, Run, scheduler, or provider
authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import chongqing_extraction_provenance as provenance
from . import chongqing_real_source_admission as admission

EVIDENCE_SCHEMA = "gda.chongqing_source_governance.v1"
VALIDATION_SCHEMA = "gda.chongqing_source_governance_validation.v1"
STATUS = "blocked_pending_governance_decisions"
SOURCE_ID = admission.SOURCE_ID
SOURCE_GROUP_ID = "bishan-planning-materials"
ASSET_ID = "bishan_land_use_dltb_local"
SOURCE_REF = f"source://{SOURCE_ID}/assets/{ASSET_ID}"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EVIDENCE_PATH = REPO_ROOT / (
    "docs/evidence/chongqing-source-governance-2026-08-17.json"
)

UPSTREAM_ADMISSION_EVIDENCE_SHA256 = (
    "a2196495d845d61be939c7fc36a7f05c3567e365599d2d04be0aab9c568459c1"
)
UPSTREAM_ADMISSION_FILE_SHA256 = (
    "9b5c20369c235f7e0a2f2cb0a21cee77f86981aa273bac196605a4803b05ce83"
)
UPSTREAM_PROVENANCE_EVIDENCE_SHA256 = (
    "b56ce0c036827d4338ab2cfae8f3fb4c9e1e78ec18aac243272f1f77801300ef"
)
UPSTREAM_PROVENANCE_FILE_SHA256 = provenance.EVIDENCE_FILE_SHA256
EVIDENCE_FILE_SHA256 = (
    "25bc5e2dfc5528f5556e7174f8c99fed7abaf30b9312528f5164c16bdf7cca9a"
)

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DECISION_FIELDS = (
    "owner",
    "license",
    "retention",
    "access",
    "privacy_sensitivity",
    "standard_version",
    "data_slo",
    "golden_result",
)
DECISION_RECORD_INVENTORY = {"status", "decision_ref", "attestation_sha256"}
DECISION_STATUSES = {"pending", "approved", "rejected"}

EVIDENCE_INVENTORY = {
    "schema",
    "status",
    "captured_at",
    "source_binding",
    "governance_decisions",
    "blockers",
    "admission_policy",
    "claims",
    "evidence_sha256",
}
SOURCE_BINDING_INVENTORY = {
    "source_id",
    "source_group_id",
    "asset_id",
    "source_ref",
    "upstream_admission_evidence_sha256",
    "upstream_admission_evidence_file_sha256",
    "upstream_provenance_evidence_sha256",
    "upstream_provenance_evidence_file_sha256",
    "archive_sha256",
    "extracted_payload_sha256",
    "source_payload_in_evidence",
    "absolute_source_paths_in_evidence",
}
ADMISSION_POLICY_INVENTORY = {
    "metadata_governance_record_allowed",
    "content_admission_requires_all_decisions",
    "content_admission_requires_derivation_provenance",
    "content_admission_requires_fresh_protected_attestation",
    "source_payload_copy_to_repository_forbidden",
    "local_profile_is_not_production_admission",
    "landing_authority_creation_allowed",
    "scheduler_submission_allowed",
    "provider_mutation_allowed",
}
CLAIMS = {
    "candidate_scope_selected",
    "governance_decisions_complete",
    "source_governance_approved",
    "source_content_admitted",
    "landing_authority_created",
    "resource_version_created",
    "platform_run_created",
    "scheduler_submission_authorized",
    "provider_mutation_authorized",
    "production_ingestion_verified",
    "production_ready",
}


class ChongqingSourceGovernanceError(RuntimeError):
    """The M3-30 governance evidence failed closed."""


def canonical_json_fingerprint(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("JSON document is not an object")
    return value


def _parse_time(value: Any) -> None:
    try:
        admission._parse_time(value)
    except admission.ChongqingRealSourceAdmissionError as exc:
        raise ChongqingSourceGovernanceError(str(exc)) from exc


def _expected_source_binding() -> dict[str, Any]:
    return {
        "source_id": SOURCE_ID,
        "source_group_id": SOURCE_GROUP_ID,
        "asset_id": ASSET_ID,
        "source_ref": SOURCE_REF,
        "upstream_admission_evidence_sha256": UPSTREAM_ADMISSION_EVIDENCE_SHA256,
        "upstream_admission_evidence_file_sha256": UPSTREAM_ADMISSION_FILE_SHA256,
        "upstream_provenance_evidence_sha256": UPSTREAM_PROVENANCE_EVIDENCE_SHA256,
        "upstream_provenance_evidence_file_sha256": UPSTREAM_PROVENANCE_FILE_SHA256,
        "archive_sha256": admission.EXPECTED_ARCHIVE_SHA256,
        "extracted_payload_sha256": admission.EXPECTED_EXTRACTED_PAYLOAD_SHA256,
        "source_payload_in_evidence": False,
        "absolute_source_paths_in_evidence": False,
    }


def _expected_governance_decisions() -> dict[str, dict[str, Any]]:
    return {
        field: {
            "status": "pending",
            "decision_ref": None,
            "attestation_sha256": None,
        }
        for field in DECISION_FIELDS
    }


def _expected_policy() -> dict[str, bool]:
    return {
        "metadata_governance_record_allowed": True,
        "content_admission_requires_all_decisions": True,
        "content_admission_requires_derivation_provenance": True,
        "content_admission_requires_fresh_protected_attestation": True,
        "source_payload_copy_to_repository_forbidden": True,
        "local_profile_is_not_production_admission": True,
        "landing_authority_creation_allowed": False,
        "scheduler_submission_allowed": False,
        "provider_mutation_allowed": False,
    }


def _expected_claims() -> dict[str, bool]:
    return {
        "candidate_scope_selected": True,
        "governance_decisions_complete": False,
        "source_governance_approved": False,
        "source_content_admitted": False,
        "landing_authority_created": False,
        "resource_version_created": False,
        "platform_run_created": False,
        "scheduler_submission_authorized": False,
        "provider_mutation_authorized": False,
        "production_ingestion_verified": False,
        "production_ready": False,
    }


def _expected_blockers() -> list[str]:
    return [f"governance:{field}_decision_pending" for field in DECISION_FIELDS] + [
        "derivation:provenance_attestation_pending",
        "source-governance:fresh_protected_attestation_pending",
    ]


def _path_or_payload_findings(value: Any, prefix: str = "") -> list[str]:
    findings = admission._sensitive_paths(value, prefix)
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "/Users/",
        "/private/",
        "Downloads/",
        "geometry_values",
        "od_rows",
        "flow_rows",
        "local_source_path",
    ):
        if forbidden in rendered:
            findings.append(f"forbidden:{forbidden}")
    return sorted(set(findings))


def validate_evidence(evidence: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(evidence) != EVIDENCE_INVENTORY:
        errors.append("M3-30 evidence inventory does not match")
    stable = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    if evidence.get("evidence_sha256") != canonical_json_fingerprint(stable):
        errors.append("M3-30 evidence fingerprint does not match")
    if evidence.get("schema") != EVIDENCE_SCHEMA or evidence.get("status") != STATUS:
        errors.append("M3-30 evidence schema or status does not match")
    try:
        _parse_time(evidence.get("captured_at"))
    except ChongqingSourceGovernanceError as exc:
        errors.append(str(exc))

    source = evidence.get("source_binding")
    if not isinstance(source, Mapping) or set(source) != SOURCE_BINDING_INVENTORY:
        errors.append("M3-30 source binding inventory does not match")
        source = {}
    for key, expected in _expected_source_binding().items():
        if source.get(key) != expected:
            errors.append(f"M3-30 source binding does not match: {key}")
    for key in (
        "upstream_admission_evidence_sha256",
        "upstream_admission_evidence_file_sha256",
        "upstream_provenance_evidence_sha256",
        "upstream_provenance_evidence_file_sha256",
        "archive_sha256",
        "extracted_payload_sha256",
    ):
        if not SHA256_PATTERN.fullmatch(str(source.get(key) or "")):
            errors.append(f"M3-30 source fingerprint is invalid: {key}")
    if not admission.SOURCE_REF_PATTERN.fullmatch(str(source.get("source_ref") or "")):
        errors.append("M3-30 source reference is invalid")

    decisions = evidence.get("governance_decisions")
    if not isinstance(decisions, Mapping) or set(decisions) != set(DECISION_FIELDS):
        errors.append("M3-30 governance decision inventory does not match")
        decisions = {}
    for field, expected in _expected_governance_decisions().items():
        record = decisions.get(field)
        if not isinstance(record, Mapping) or set(record) != DECISION_RECORD_INVENTORY:
            errors.append(f"M3-30 decision record does not match: {field}")
            continue
        if dict(record) != expected:
            errors.append(f"M3-30 decision remains unresolved: {field}")
        if record.get("status") not in DECISION_STATUSES:
            errors.append(f"M3-30 decision status is invalid: {field}")
        attestation = record.get("attestation_sha256")
        if attestation is not None and not SHA256_PATTERN.fullmatch(str(attestation)):
            errors.append(f"M3-30 decision attestation is invalid: {field}")

    blockers = evidence.get("blockers")
    if blockers != _expected_blockers():
        errors.append("M3-30 blocker inventory does not match")

    policy = evidence.get("admission_policy")
    if not isinstance(policy, Mapping) or set(policy) != ADMISSION_POLICY_INVENTORY:
        errors.append("M3-30 admission policy inventory does not match")
        policy = {}
    for key, expected in _expected_policy().items():
        if policy.get(key) is not expected:
            errors.append(f"M3-30 admission policy does not match: {key}")

    claims = evidence.get("claims")
    expected_claims = _expected_claims()
    if not isinstance(claims, Mapping) or set(claims) != CLAIMS:
        errors.append("M3-30 claims inventory does not match")
    else:
        for key, expected in expected_claims.items():
            if claims.get(key) is not expected:
                errors.append(f"M3-30 claim does not match: {key}")

    findings = _path_or_payload_findings(evidence)
    if findings:
        errors.append("M3-30 evidence contains a path or payload marker")
    return sorted(set(errors))


def build_validation_report(
    evidence_path: Path = DEFAULT_EVIDENCE_PATH,
) -> dict[str, Any]:
    try:
        file_sha256 = _file_sha256(evidence_path)
        evidence = _load_json_object(evidence_path)
        errors = validate_evidence(evidence)
        if EVIDENCE_FILE_SHA256 and file_sha256 != EVIDENCE_FILE_SHA256:
            errors.append("M3-30 evidence file fingerprint does not match")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        evidence = {}
        file_sha256 = None
        errors = [f"M3-30 evidence is unreadable: {type(exc).__name__}"]
    claims = evidence.get("claims")
    return {
        "schema": VALIDATION_SCHEMA,
        "status": "valid" if not errors else "invalid",
        "errors": sorted(set(errors)),
        "evidence_file_sha256": file_sha256,
        "evidence_sha256": evidence.get("evidence_sha256"),
        "source_id": evidence.get("source_binding", {}).get("source_id")
        if isinstance(evidence.get("source_binding"), Mapping)
        else None,
        "candidate_asset_id": evidence.get("source_binding", {}).get("asset_id")
        if isinstance(evidence.get("source_binding"), Mapping)
        else None,
        "pending_decision_count": sum(
            1
            for record in evidence.get("governance_decisions", {}).values()
            if isinstance(record, Mapping) and record.get("status") == "pending"
        )
        if isinstance(evidence.get("governance_decisions"), Mapping)
        else None,
        "source_governance_approved": (
            claims.get("source_governance_approved")
            if isinstance(claims, Mapping)
            else None
        ),
        "source_content_admitted": (
            claims.get("source_content_admitted") if isinstance(claims, Mapping) else None
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE_PATH)
    args = parser.parse_args(argv)
    try:
        report = build_validation_report(args.evidence)
    except ChongqingSourceGovernanceError as exc:
        print(f"Chongqing source governance: {exc}")
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
