"""Evaluate the protected attestation intake for Chongqing admission.

M3-32 consumes the metadata-only M3-31 readiness record and an external,
protected attestation bundle. It verifies binding, freshness and the complete
fifteen-item evidence inventory without reading or copying source payloads.
The evaluator only produces a report; it never creates Landing, ResourceVersion,
PlatformRun, scheduler or provider authority.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import chongqing_admission_readiness as readiness
from . import chongqing_real_source_admission as admission

ATTESTATION_SCHEMA = "gda.chongqing_protected_admission_attestation.v1"
REPORT_SCHEMA = "gda.chongqing_protected_admission_report.v1"
PROTECTED_ENVIRONMENT = "chongqing-admission-protected"
MAX_ATTESTATION_AGE = timedelta(hours=24)
MAX_ATTESTATION_LIFETIME = timedelta(days=7)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_READINESS_PATH = readiness.DEFAULT_EVIDENCE_PATH

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PLACEHOLDER_PATTERN = re.compile(
    r"(^|[-_.:/])(pending|placeholder|replace|tbd|todo|changeme)([-_.:/]|$)|[<>]",
    re.IGNORECASE,
)

EXPECTED_CHECKS = {
    "archive_hash_match",
    "extracted_hash_match",
    "derivation_evidence_complete",
    "governance_decisions_complete",
    "source_binding_match",
    "payload_and_path_free",
    "reviewer_approval",
    "provider_mutation_forbidden",
}
REQUIRED_ATTESTATION_KEYS = {
    "schema",
    "readiness_evidence_sha256",
    "readiness_evidence_file_sha256",
    "source_binding",
    "observed_at",
    "expires_at",
    "protected_environment",
    "verifier_identity",
    "evidence_uri",
    "requirements",
    "checks",
    "attestation_sha256",
}
REQUIRED_SOURCE_BINDING_KEYS = {"source_id", "source_group_id", "asset_id", "source_ref"}
REQUIRED_REQUIREMENT_RECORD_KEYS = {"status", "attestation_sha256"}


class ChongqingProtectedAdmissionError(RuntimeError):
    """The protected attestation intake failed closed."""


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


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _placeholder(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip() or bool(
        PLACEHOLDER_PATTERN.search(value.strip())
    )


def _safe_https_uri(value: Any) -> bool:
    if _placeholder(value):
        return False
    parsed = urlparse(str(value))
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return False
    hostname = parsed.hostname.lower()
    if hostname in {"localhost", "0.0.0.0", "::1"} or hostname.endswith(
        (".localhost", ".local", ".svc", ".cluster.local", ".example", ".invalid", ".test")
    ):
        return False
    if hostname in {"example.com", "example.net", "example.org"}:
        return False
    try:
        if ipaddress.ip_address(hostname).is_loopback:
            return False
    except ValueError:
        pass
    return True


def _expected_source_binding(readiness_evidence: Mapping[str, Any]) -> dict[str, Any]:
    source = _mapping(readiness_evidence.get("source_binding"))
    return {
        "source_id": source.get("source_id"),
        "source_group_id": source.get("source_group_id"),
        "asset_id": source.get("asset_id"),
        "source_ref": source.get("source_ref"),
    }


def _readiness_errors(
    readiness_evidence: Mapping[str, Any],
    readiness_file_sha256: str | None,
) -> list[str]:
    errors = readiness.validate_evidence(readiness_evidence)
    if readiness_file_sha256 != readiness.EVIDENCE_FILE_SHA256:
        errors.append("M3-31 readiness evidence file fingerprint does not match")
    return sorted(set(errors))


def _attestation_errors(
    attestation: Mapping[str, Any] | None,
    *,
    readiness_evidence: Mapping[str, Any],
    readiness_evidence_sha256: str,
    readiness_file_sha256: str | None,
    now: datetime,
    max_age: timedelta,
) -> list[str]:
    if attestation is None:
        return ["protected admission attestation is missing"]

    errors: list[str] = []
    if readiness._path_or_payload_findings(attestation):
        errors.append("protected admission attestation contains a path or payload marker")
    if set(attestation) != REQUIRED_ATTESTATION_KEYS:
        errors.append("protected admission attestation inventory does not match")
    stable = {key: value for key, value in attestation.items() if key != "attestation_sha256"}
    if attestation.get("attestation_sha256") != canonical_json_fingerprint(stable):
        errors.append("protected admission attestation fingerprint does not match")
    if attestation.get("schema") != ATTESTATION_SCHEMA:
        errors.append("protected admission attestation schema does not match")
    if attestation.get("readiness_evidence_sha256") != readiness_evidence_sha256:
        errors.append("protected admission attestation is not bound to M3-31 evidence")
    if attestation.get("readiness_evidence_file_sha256") != readiness_file_sha256:
        errors.append("protected admission attestation is not bound to M3-31 evidence file")
    if not SHA256_PATTERN.fullmatch(str(attestation.get("readiness_evidence_sha256") or "")):
        errors.append("protected admission readiness evidence fingerprint is invalid")
    if not SHA256_PATTERN.fullmatch(str(attestation.get("readiness_evidence_file_sha256") or "")):
        errors.append("protected admission readiness file fingerprint is invalid")

    source_binding = _mapping(attestation.get("source_binding"))
    if set(source_binding) != REQUIRED_SOURCE_BINDING_KEYS:
        errors.append("protected admission source binding inventory does not match")
    if dict(source_binding) != _expected_source_binding(readiness_evidence):
        errors.append("protected admission source binding does not match M3-31")
    if not admission.SOURCE_REF_PATTERN.fullmatch(str(source_binding.get("source_ref") or "")):
        errors.append("protected admission source reference is invalid")

    if attestation.get("protected_environment") != PROTECTED_ENVIRONMENT:
        errors.append("protected admission environment does not match")
    if _placeholder(attestation.get("verifier_identity")):
        errors.append("protected admission verifier identity is missing")
    if not _safe_https_uri(attestation.get("evidence_uri")):
        errors.append("protected admission evidence URI is invalid")

    try:
        observed_at = datetime.fromisoformat(str(attestation.get("observed_at")))
        expires_at = datetime.fromisoformat(str(attestation.get("expires_at")))
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise ValueError
        age = now - observed_at
        if age < timedelta(seconds=-30) or age > max_age:
            errors.append("protected admission attestation is outside the freshness window")
        if expires_at <= now or expires_at <= observed_at:
            errors.append("protected admission attestation has expired or invalid expiry")
        if expires_at - observed_at > MAX_ATTESTATION_LIFETIME:
            errors.append("protected admission attestation lifetime exceeds seven days")
    except ValueError:
        errors.append("protected admission attestation timestamps are invalid")

    requirements = _mapping(attestation.get("requirements"))
    if set(requirements) != set(readiness.REQUIREMENT_KEYS):
        errors.append("protected admission requirement inventory does not match")
    for key in readiness.REQUIREMENT_KEYS:
        record = _mapping(requirements.get(key))
        if set(record) != REQUIRED_REQUIREMENT_RECORD_KEYS:
            errors.append(f"protected admission requirement record does not match: {key}")
            continue
        if record.get("status") != "verified":
            errors.append(f"protected admission requirement is not verified: {key}")
        if not SHA256_PATTERN.fullmatch(str(record.get("attestation_sha256") or "")):
            errors.append(f"protected admission requirement attestation is invalid: {key}")

    checks = _mapping(attestation.get("checks"))
    if set(checks) != EXPECTED_CHECKS:
        errors.append("protected admission check inventory does not match")
    for check in sorted(EXPECTED_CHECKS):
        if checks.get(check) != "passed":
            errors.append(f"protected admission check did not pass: {check}")
    return sorted(set(errors))


def build_admission_report(
    *,
    readiness_path: Path | None = None,
    attestation: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    max_attestation_age: timedelta = MAX_ATTESTATION_AGE,
) -> dict[str, Any]:
    """Build a deterministic report without granting any write authority."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ChongqingProtectedAdmissionError("verification time must be timezone-aware")
    if max_attestation_age <= timedelta(0):
        raise ChongqingProtectedAdmissionError("attestation freshness window must be positive")

    path = (readiness_path or DEFAULT_READINESS_PATH).resolve()
    try:
        readiness_file_sha256 = _file_sha256(path)
        readiness_evidence = _load_json_object(path)
        readiness_evidence_sha256 = str(readiness_evidence.get("evidence_sha256") or "")
        readiness_errors = _readiness_errors(readiness_evidence, readiness_file_sha256)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        readiness_file_sha256 = None
        readiness_evidence = {}
        readiness_evidence_sha256 = ""
        readiness_errors = [f"M3-31 readiness evidence is unreadable: {type(exc).__name__}"]

    readiness_valid = not readiness_errors
    attestation_errors = _attestation_errors(
        attestation,
        readiness_evidence=readiness_evidence,
        readiness_evidence_sha256=readiness_evidence_sha256,
        readiness_file_sha256=readiness_file_sha256,
        now=current,
        max_age=max_attestation_age,
    )
    attestation_valid = readiness_valid and not attestation_errors
    admission_eligible = readiness_valid and attestation_valid
    stable = {
        "schema": REPORT_SCHEMA,
        "readiness_evidence_sha256": readiness_evidence_sha256 or None,
        "readiness_evidence_file_sha256": readiness_file_sha256,
        "readiness_valid": readiness_valid,
        "readiness_errors": readiness_errors,
        "attestation_fingerprint": (
            canonical_json_fingerprint(attestation) if attestation is not None else None
        ),
        "attestation_valid": attestation_valid,
        "attestation_errors": attestation_errors,
        "admission_eligible": admission_eligible,
        "content_admission_authorized": False,
        "source_content_admitted": False,
        "landing_authority_created": False,
        "resource_version_created": False,
        "platform_run_created": False,
        "scheduler_submission_authorized": False,
        "provider_mutation_authorized": False,
        "production_ready": False,
    }
    return {**stable, "report_fingerprint": canonical_json_fingerprint(stable)}


def verify_report_integrity(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if readiness._path_or_payload_findings(report):
        errors.append("protected admission report contains a path or payload marker")
    if report.get("schema") != REPORT_SCHEMA:
        errors.append("protected admission report schema does not match")
    stable = {key: value for key, value in report.items() if key != "report_fingerprint"}
    if report.get("report_fingerprint") != canonical_json_fingerprint(stable):
        errors.append("protected admission report fingerprint does not match")
    if report.get("production_ready") is not False:
        errors.append("protected admission report may not claim production readiness")
    for key in (
        "content_admission_authorized",
        "source_content_admitted",
        "landing_authority_created",
        "resource_version_created",
        "platform_run_created",
        "scheduler_submission_authorized",
        "provider_mutation_authorized",
    ):
        if report.get(key) is not False:
            errors.append(f"protected admission report may not claim authority: {key}")
    expected_eligible = report.get("readiness_valid") is True and report.get(
        "attestation_valid"
    ) is True
    if report.get("admission_eligible") is not expected_eligible:
        errors.append("protected admission eligibility is inconsistent")
    return sorted(set(errors))


def _write_report(report: Mapping[str, Any], output: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(rendered, end="")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--readiness", type=Path, default=DEFAULT_READINESS_PATH)
    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--readiness", type=Path, default=DEFAULT_READINESS_PATH)
    evaluate_parser.add_argument("--attestation", type=Path, required=True)
    evaluate_parser.add_argument("--output", type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "validate":
            report = build_admission_report(readiness_path=args.readiness)
            _write_report(report, None)
            return 0 if report["readiness_valid"] else 1
        if args.command == "evaluate":
            attestation = _load_json_object(args.attestation)
            report = build_admission_report(
                readiness_path=args.readiness,
                attestation=attestation,
            )
            _write_report(report, args.output)
            return 0 if report["admission_eligible"] else 1
        report = _load_json_object(args.input)
        errors = verify_report_integrity(report)
        _write_report({"verified": not errors, "errors": errors}, None)
        return 0 if not errors else 1
    except (
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        ChongqingProtectedAdmissionError,
    ) as exc:
        print(f"Chongqing protected admission: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
