"""Validate the fail-closed readiness contract before Chongqing admission.

M3-31 binds the M3-28 physical baseline, M3-29 derivation-gap record and
M3-30 governance baseline into one metadata-only admission readiness profile.
The checked profile records every missing external requirement and never reads
or copies source payloads or creates Landing, Run, scheduler or provider
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
from . import chongqing_source_governance as governance

EVIDENCE_SCHEMA = "gda.chongqing_admission_readiness.v1"
VALIDATION_SCHEMA = "gda.chongqing_admission_readiness_validation.v1"
STATUS = "blocked_pending_protected_admission_attestation"
SOURCE_ID = admission.SOURCE_ID
SOURCE_GROUP_ID = governance.SOURCE_GROUP_ID
ASSET_ID = governance.ASSET_ID
SOURCE_REF = governance.SOURCE_REF

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EVIDENCE_PATH = REPO_ROOT / (
    "docs/evidence/chongqing-admission-readiness-2026-08-17.json"
)

UPSTREAM_ADMISSION_EVIDENCE_SHA256 = (
    "a2196495d845d61be939c7fc36a7f05c3567e365599d2d04be0aab9c568459c1"
)
UPSTREAM_ADMISSION_FILE_SHA256 = admission.EVIDENCE_FILE_SHA256
UPSTREAM_PROVENANCE_EVIDENCE_SHA256 = (
    "b56ce0c036827d4338ab2cfae8f3fb4c9e1e78ec18aac243272f1f77801300ef"
)
UPSTREAM_PROVENANCE_FILE_SHA256 = provenance.EVIDENCE_FILE_SHA256
UPSTREAM_GOVERNANCE_EVIDENCE_SHA256 = (
    "97cf11ab8938c048dce9db903d1a4f30758f208dec6dad1a08b740a4a8fe7b6f"
)
UPSTREAM_GOVERNANCE_FILE_SHA256 = governance.EVIDENCE_FILE_SHA256
EVIDENCE_FILE_SHA256 = (
    "c595065e152988529ff12e2301d59caebb31d2889658a676c9d1f8239e6f8372"
)

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
REQUIREMENT_KEYS = (
    "operator_identity",
    "tool_version",
    "command_digest",
    "modified_entry_manifest",
    "additional_entry_manifest",
    "archive_to_working_set_attestation",
    "owner_decision",
    "license_decision",
    "retention_decision",
    "access_decision",
    "privacy_sensitivity_decision",
    "standard_version_decision",
    "data_slo_decision",
    "golden_result_decision",
    "fresh_protected_attestation",
)
REQUIREMENT_RECORD_INVENTORY = {"source", "status", "attestation_sha256"}
REQUIREMENT_STATUSES = {"missing", "provided", "verified", "rejected"}

EVIDENCE_INVENTORY = {
    "schema",
    "status",
    "captured_at",
    "source_binding",
    "required_evidence",
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
    "upstream_governance_evidence_sha256",
    "upstream_governance_evidence_file_sha256",
    "archive_sha256",
    "extracted_payload_sha256",
    "source_payload_in_evidence",
    "absolute_source_paths_in_evidence",
}
ADMISSION_POLICY_INVENTORY = {
    "metadata_readiness_record_allowed",
    "admission_requires_complete_derivation",
    "admission_requires_complete_governance",
    "admission_requires_fresh_protected_attestation",
    "source_payload_copy_to_repository_forbidden",
    "local_profile_is_not_production_admission",
    "content_admission_authorized",
    "landing_authority_creation_allowed",
    "resource_version_creation_allowed",
    "platform_run_creation_allowed",
    "scheduler_submission_allowed",
    "provider_mutation_allowed",
}
CLAIMS = {
    "upstream_evidence_bound",
    "derivation_attestation_complete",
    "governance_decisions_complete",
    "fresh_protected_attestation_valid",
    "admission_eligible",
    "source_content_admitted",
    "landing_authority_created",
    "resource_version_created",
    "platform_run_created",
    "scheduler_submission_authorized",
    "provider_mutation_authorized",
    "production_ingestion_verified",
    "production_ready",
}


class ChongqingAdmissionReadinessError(RuntimeError):
    """The M3-31 readiness evidence failed closed."""


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
        raise ChongqingAdmissionReadinessError(str(exc)) from exc


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
        "upstream_governance_evidence_sha256": UPSTREAM_GOVERNANCE_EVIDENCE_SHA256,
        "upstream_governance_evidence_file_sha256": UPSTREAM_GOVERNANCE_FILE_SHA256,
        "archive_sha256": admission.EXPECTED_ARCHIVE_SHA256,
        "extracted_payload_sha256": admission.EXPECTED_EXTRACTED_PAYLOAD_SHA256,
        "source_payload_in_evidence": False,
        "absolute_source_paths_in_evidence": False,
    }


def _requirement_source(key: str) -> str:
    if key in REQUIREMENT_KEYS[:6]:
        return "derivation"
    if key in REQUIREMENT_KEYS[6:14]:
        return "governance"
    return "protected"


def _expected_requirements() -> dict[str, dict[str, Any]]:
    return {
        key: {
            "source": _requirement_source(key),
            "status": "missing",
            "attestation_sha256": None,
        }
        for key in REQUIREMENT_KEYS
    }


def _expected_blockers() -> list[str]:
    return [f"admission:{key}_missing" for key in REQUIREMENT_KEYS]


def _expected_policy() -> dict[str, bool]:
    return {
        "metadata_readiness_record_allowed": True,
        "admission_requires_complete_derivation": True,
        "admission_requires_complete_governance": True,
        "admission_requires_fresh_protected_attestation": True,
        "source_payload_copy_to_repository_forbidden": True,
        "local_profile_is_not_production_admission": True,
        "content_admission_authorized": False,
        "landing_authority_creation_allowed": False,
        "resource_version_creation_allowed": False,
        "platform_run_creation_allowed": False,
        "scheduler_submission_allowed": False,
        "provider_mutation_allowed": False,
    }


def _expected_claims() -> dict[str, bool]:
    return {
        "upstream_evidence_bound": True,
        "derivation_attestation_complete": False,
        "governance_decisions_complete": False,
        "fresh_protected_attestation_valid": False,
        "admission_eligible": False,
        "source_content_admitted": False,
        "landing_authority_created": False,
        "resource_version_created": False,
        "platform_run_created": False,
        "scheduler_submission_authorized": False,
        "provider_mutation_authorized": False,
        "production_ingestion_verified": False,
        "production_ready": False,
    }


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
        errors.append("M3-31 evidence inventory does not match")
    stable = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    if evidence.get("evidence_sha256") != canonical_json_fingerprint(stable):
        errors.append("M3-31 evidence fingerprint does not match")
    if evidence.get("schema") != EVIDENCE_SCHEMA or evidence.get("status") != STATUS:
        errors.append("M3-31 evidence schema or status does not match")
    try:
        _parse_time(evidence.get("captured_at"))
    except ChongqingAdmissionReadinessError as exc:
        errors.append(str(exc))

    source = evidence.get("source_binding")
    if not isinstance(source, Mapping) or set(source) != SOURCE_BINDING_INVENTORY:
        errors.append("M3-31 source binding inventory does not match")
        source = {}
    for key, expected in _expected_source_binding().items():
        if source.get(key) != expected:
            errors.append(f"M3-31 source binding does not match: {key}")
    for key in (
        "upstream_admission_evidence_sha256",
        "upstream_admission_evidence_file_sha256",
        "upstream_provenance_evidence_sha256",
        "upstream_provenance_evidence_file_sha256",
        "upstream_governance_evidence_sha256",
        "upstream_governance_evidence_file_sha256",
        "archive_sha256",
        "extracted_payload_sha256",
    ):
        if not SHA256_PATTERN.fullmatch(str(source.get(key) or "")):
            errors.append(f"M3-31 source fingerprint is invalid: {key}")
    if not admission.SOURCE_REF_PATTERN.fullmatch(str(source.get("source_ref") or "")):
        errors.append("M3-31 source reference is invalid")

    requirements = evidence.get("required_evidence")
    if not isinstance(requirements, Mapping) or set(requirements) != set(REQUIREMENT_KEYS):
        errors.append("M3-31 required evidence inventory does not match")
        requirements = {}
    for key, expected in _expected_requirements().items():
        record = requirements.get(key)
        if not isinstance(record, Mapping) or set(record) != REQUIREMENT_RECORD_INVENTORY:
            errors.append(f"M3-31 requirement record does not match: {key}")
            continue
        if dict(record) != expected:
            errors.append(f"M3-31 requirement remains unresolved: {key}")
        if record.get("status") not in REQUIREMENT_STATUSES:
            errors.append(f"M3-31 requirement status is invalid: {key}")
        attestation = record.get("attestation_sha256")
        if attestation is not None and not SHA256_PATTERN.fullmatch(str(attestation)):
            errors.append(f"M3-31 requirement attestation is invalid: {key}")

    if evidence.get("blockers") != _expected_blockers():
        errors.append("M3-31 blocker inventory does not match")

    policy = evidence.get("admission_policy")
    if not isinstance(policy, Mapping) or set(policy) != ADMISSION_POLICY_INVENTORY:
        errors.append("M3-31 admission policy inventory does not match")
        policy = {}
    for key, expected in _expected_policy().items():
        if policy.get(key) is not expected:
            errors.append(f"M3-31 admission policy does not match: {key}")

    claims = evidence.get("claims")
    expected_claims = _expected_claims()
    if not isinstance(claims, Mapping) or set(claims) != CLAIMS:
        errors.append("M3-31 claims inventory does not match")
    else:
        for key, expected in expected_claims.items():
            if claims.get(key) is not expected:
                errors.append(f"M3-31 claim does not match: {key}")

    if _path_or_payload_findings(evidence):
        errors.append("M3-31 evidence contains a path or payload marker")
    return sorted(set(errors))


def build_validation_report(
    evidence_path: Path = DEFAULT_EVIDENCE_PATH,
) -> dict[str, Any]:
    try:
        file_sha256 = _file_sha256(evidence_path)
        evidence = _load_json_object(evidence_path)
        errors = validate_evidence(evidence)
        if EVIDENCE_FILE_SHA256 and file_sha256 != EVIDENCE_FILE_SHA256:
            errors.append("M3-31 evidence file fingerprint does not match")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        evidence = {}
        file_sha256 = None
        errors = [f"M3-31 evidence is unreadable: {type(exc).__name__}"]
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
        "pending_requirement_count": sum(
            1
            for record in evidence.get("required_evidence", {}).values()
            if isinstance(record, Mapping) and record.get("status") == "missing"
        )
        if isinstance(evidence.get("required_evidence"), Mapping)
        else None,
        "admission_eligible": (
            claims.get("admission_eligible") if isinstance(claims, Mapping) else None
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
    except ChongqingAdmissionReadinessError as exc:
        print(f"Chongqing admission readiness: {exc}")
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
