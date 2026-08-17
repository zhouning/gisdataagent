"""Validate the metadata-only M3-29 extraction provenance boundary.

M3-28 observed an archive and an extracted working set but intentionally left
their derivation provenance unresolved. M3-29 records that gap as immutable,
path-free evidence. It never reads or copies the source payload and never
authorizes content admission, Landing, scheduling, provider mutation, or
production ingestion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import chongqing_real_source_admission as admission

EVIDENCE_SCHEMA = "gda.chongqing_extraction_provenance.v1"
VALIDATION_SCHEMA = "gda.chongqing_extraction_provenance_validation.v1"
STATUS = "blocked_pending_derivation_attestation"
SOURCE_ID = admission.SOURCE_ID

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EVIDENCE_PATH = REPO_ROOT / (
    "docs/evidence/chongqing-extraction-provenance-2026-08-17.json"
)

UPSTREAM_EVIDENCE_SHA256 = (
    "a2196495d845d61be939c7fc36a7f05c3567e365599d2d04be0aab9c568459c1"
)
UPSTREAM_EVIDENCE_FILE_SHA256 = (
    "9b5c20369c235f7e0a2f2cb0a21cee77f86981aa273bac196605a4803b05ce83"
)
EVIDENCE_FILE_SHA256 = "cfae0478c76452a155e8af42ec8499e4e7876a49c1dbb98648526025cb154360"

SHA256_PATTERN = admission.SHA256_PATTERN

EVIDENCE_INVENTORY = {
    "schema",
    "status",
    "captured_at",
    "source_binding",
    "comparison",
    "derivation",
    "missing_evidence",
    "claims",
    "evidence_sha256",
}
SOURCE_BINDING_INVENTORY = {
    "source_id",
    "upstream_admission_evidence_sha256",
    "upstream_admission_evidence_file_sha256",
    "archive_sha256",
    "archive_scope_entry_count",
    "archive_scope_size_bytes",
    "extracted_payload_sha256",
    "extracted_file_count",
    "extracted_size_bytes",
}
COMPARISON_INVENTORY = {
    "exact_match_count",
    "modified_entry_count",
    "missing_entry_count",
    "additional_extracted_file_count",
    "archive_extracted_entry_multiset_verified",
}
DERIVATION_INVENTORY = {
    "comparison_algorithm",
    "comparison_scope",
    "derivation_status",
    "operator_identity_recorded",
    "tool_version_recorded",
    "command_digest_recorded",
    "modified_entry_manifest_recorded",
    "additional_entry_manifest_recorded",
    "archive_to_working_set_attestation",
    "source_payload_in_evidence",
    "absolute_source_paths_in_evidence",
}
CLAIMS = {
    "comparison_observed",
    "derivation_provenance_complete",
    "source_content_admitted",
    "landing_authority_created",
    "resource_version_created",
    "platform_run_created",
    "scheduler_submission_authorized",
    "provider_mutation_authorized",
    "production_ingestion_verified",
    "production_ready",
}

MISSING_EVIDENCE = [
    "derivation:operator_identity_missing",
    "derivation:tool_version_missing",
    "derivation:command_digest_missing",
    "derivation:modified_entry_manifest_missing",
    "derivation:additional_entry_manifest_missing",
    "derivation:archive_to_working_set_attestation_missing",
]


class ChongqingExtractionProvenanceError(RuntimeError):
    """The M3-29 provenance evidence failed closed."""


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
        raise ChongqingExtractionProvenanceError(str(exc)) from exc


def _expected_source_binding() -> dict[str, Any]:
    return {
        "source_id": SOURCE_ID,
        "upstream_admission_evidence_sha256": UPSTREAM_EVIDENCE_SHA256,
        "upstream_admission_evidence_file_sha256": UPSTREAM_EVIDENCE_FILE_SHA256,
        "archive_sha256": admission.EXPECTED_ARCHIVE_SHA256,
        "archive_scope_entry_count": admission.EXPECTED_ARCHIVE_SCOPE_ENTRY_COUNT,
        "archive_scope_size_bytes": admission.EXPECTED_ARCHIVE_SCOPE_SIZE_BYTES,
        "extracted_payload_sha256": admission.EXPECTED_EXTRACTED_PAYLOAD_SHA256,
        "extracted_file_count": admission.EXPECTED_EXTRACTED_FILE_COUNT,
        "extracted_size_bytes": admission.EXPECTED_EXTRACTED_SIZE_BYTES,
    }


def _expected_comparison() -> dict[str, Any]:
    return {
        "exact_match_count": admission.EXPECTED_ARCHIVE_EXACT_MATCH_COUNT,
        "modified_entry_count": admission.EXPECTED_ARCHIVE_MODIFIED_COUNT,
        "missing_entry_count": admission.EXPECTED_ARCHIVE_MISSING_COUNT,
        "additional_extracted_file_count": admission.EXPECTED_EXTRACTED_ADDITIONAL_COUNT,
        "archive_extracted_entry_multiset_verified": False,
    }


def _expected_derivation() -> dict[str, Any]:
    return {
        "comparison_algorithm": "relative-path-plus-zip-size-crc32",
        "comparison_scope": "archive-01-sample-scope-vs-extracted-working-set",
        "derivation_status": "comparison_only",
        "operator_identity_recorded": False,
        "tool_version_recorded": False,
        "command_digest_recorded": False,
        "modified_entry_manifest_recorded": False,
        "additional_entry_manifest_recorded": False,
        "archive_to_working_set_attestation": False,
        "source_payload_in_evidence": False,
        "absolute_source_paths_in_evidence": False,
    }


def _expected_claims() -> dict[str, bool]:
    return {
        "comparison_observed": True,
        "derivation_provenance_complete": False,
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
        errors.append("M3-29 evidence inventory does not match")
    stable = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    if evidence.get("evidence_sha256") != canonical_json_fingerprint(stable):
        errors.append("M3-29 evidence fingerprint does not match")
    if evidence.get("schema") != EVIDENCE_SCHEMA or evidence.get("status") != STATUS:
        errors.append("M3-29 evidence schema or status does not match")
    try:
        _parse_time(evidence.get("captured_at"))
    except ChongqingExtractionProvenanceError as exc:
        errors.append(str(exc))

    source = evidence.get("source_binding")
    if not isinstance(source, Mapping) or set(source) != SOURCE_BINDING_INVENTORY:
        errors.append("M3-29 source binding inventory does not match")
        source = {}
    for key, expected in _expected_source_binding().items():
        if source.get(key) != expected:
            errors.append(f"M3-29 source binding does not match: {key}")
    for key in (
        "upstream_admission_evidence_sha256",
        "upstream_admission_evidence_file_sha256",
        "archive_sha256",
        "extracted_payload_sha256",
    ):
        if not SHA256_PATTERN.fullmatch(str(source.get(key) or "")):
            errors.append(f"M3-29 source fingerprint is invalid: {key}")

    comparison = evidence.get("comparison")
    if not isinstance(comparison, Mapping) or set(comparison) != COMPARISON_INVENTORY:
        errors.append("M3-29 comparison inventory does not match")
        comparison = {}
    for key, expected in _expected_comparison().items():
        if comparison.get(key) != expected:
            errors.append(f"M3-29 comparison does not match: {key}")

    derivation = evidence.get("derivation")
    if not isinstance(derivation, Mapping) or set(derivation) != DERIVATION_INVENTORY:
        errors.append("M3-29 derivation inventory does not match")
        derivation = {}
    for key, expected in _expected_derivation().items():
        if derivation.get(key) != expected:
            errors.append(f"M3-29 derivation does not match: {key}")

    if evidence.get("missing_evidence") != MISSING_EVIDENCE:
        errors.append("M3-29 missing evidence inventory does not match")

    claims = evidence.get("claims")
    expected_claims = _expected_claims()
    if not isinstance(claims, Mapping) or set(claims) != CLAIMS:
        errors.append("M3-29 claims inventory does not match")
    else:
        for key, expected in expected_claims.items():
            if claims.get(key) is not expected:
                errors.append(f"M3-29 claim does not match: {key}")

    findings = _path_or_payload_findings(evidence)
    if findings:
        errors.append("M3-29 evidence contains a path or payload marker")
    return sorted(set(errors))


def build_validation_report(
    evidence_path: Path = DEFAULT_EVIDENCE_PATH,
) -> dict[str, Any]:
    try:
        file_sha256 = _file_sha256(evidence_path)
        evidence = _load_json_object(evidence_path)
        errors = validate_evidence(evidence)
        if EVIDENCE_FILE_SHA256 and file_sha256 != EVIDENCE_FILE_SHA256:
            errors.append("M3-29 evidence file fingerprint does not match")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        evidence = {}
        file_sha256 = None
        errors = [f"M3-29 evidence is unreadable: {type(exc).__name__}"]
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
        "missing_evidence_count": len(evidence.get("missing_evidence", [])),
        "derivation_verified": (
            claims.get("derivation_provenance_complete")
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
    except ChongqingExtractionProvenanceError as exc:
        print(f"Chongqing extraction provenance: {exc}")
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
