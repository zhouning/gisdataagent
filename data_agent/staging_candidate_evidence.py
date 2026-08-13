"""Build fail-closed evidence for a CI-validated staging candidate.

Candidate evidence is deliberately weaker than live staging evidence. It can
prove that a source revision, locally built image, migration ledger, platform
configuration, runtime inventory, and test report agree in an ephemeral CI
environment. It can never claim that staging is deployed or permit production
promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CANDIDATE_SCHEMA = "gda.staging_candidate_evidence.v1"
PLATFORM_TRUTH_SCHEMA = "gda.platform_truth.v1"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
IMAGE_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
SOURCE_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_LIVE_EVIDENCE = (
    "registry image digest",
    "live staging deployment revision",
    "live schema/config/runtime fingerprints",
    "application and worker workload identity attestation",
    "live health/readiness and golden-slice verdict",
)


class StagingCandidateEvidenceError(RuntimeError):
    """A candidate evidence input could not be parsed."""


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise StagingCandidateEvidenceError("JSON evidence must be an object")
    return value


def _junit_count(attributes: dict[str, str], key: str) -> int:
    raw = attributes.get(key, "0")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise StagingCandidateEvidenceError(
            f"JUnit {key} count must be an integer"
        ) from exc
    if value < 0:
        raise StagingCandidateEvidenceError(
            f"JUnit {key} count must be non-negative"
        )
    return value


def load_junit_summary(path: Path) -> dict[str, int]:
    """Return aggregate JUnit counts without copying testcase contents."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise StagingCandidateEvidenceError("JUnit XML is invalid") from exc

    root_tag = root.tag.rsplit("}", 1)[-1]
    if root_tag == "testsuite":
        suites = [root]
    elif root_tag == "testsuites":
        suites = [
            child
            for child in root
            if child.tag.rsplit("}", 1)[-1] == "testsuite"
        ]
    else:
        raise StagingCandidateEvidenceError("JUnit root must be testsuite(s)")
    if not suites:
        raise StagingCandidateEvidenceError("JUnit report has no test suites")

    summary = {
        key: sum(_junit_count(suite.attrib, key) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    return summary


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_PATTERN.fullmatch(value))


def _valid_positive_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def build_candidate_evidence(
    schema_report: dict[str, Any],
    platform_snapshot: dict[str, Any],
    test_summary: dict[str, int],
    *,
    source_revision: str,
    image_id: str,
) -> dict[str, Any]:
    """Validate ephemeral CI evidence without claiming a live deployment."""
    errors: list[str] = []
    if not SOURCE_REVISION_PATTERN.fullmatch(source_revision):
        errors.append("source revision must be a full lowercase Git SHA-1")
    if not IMAGE_ID_PATTERN.fullmatch(image_id):
        errors.append("candidate image must use a local immutable sha256 image ID")

    catalog_fingerprint = schema_report.get("catalog_fingerprint")
    database_fingerprint = schema_report.get("database_fingerprint")
    catalog_count = schema_report.get("catalog_count")
    applied_count = schema_report.get("applied_count")
    if schema_report.get("status") != "in_sync":
        errors.append("candidate migration ledger must be in_sync")
    if not _valid_positive_count(catalog_count):
        errors.append("candidate migration catalog count must be positive")
    if applied_count != catalog_count:
        errors.append("candidate applied migration count must match the catalog")
    if not _valid_sha256(catalog_fingerprint) or not _valid_sha256(
        database_fingerprint
    ):
        errors.append("candidate schema fingerprints must be sha256 values")
    elif catalog_fingerprint != database_fingerprint:
        errors.append("candidate catalog and database fingerprints must match")
    for field in (
        "pending",
        "unknown_applied",
        "missing_checksums",
        "checksum_mismatches",
        "metadata_mismatches",
    ):
        if schema_report.get(field):
            errors.append(f"candidate migration report contains {field}")

    config = platform_snapshot.get("config")
    environment_access = platform_snapshot.get("environment_access")
    runtime = platform_snapshot.get("runtime")
    if platform_snapshot.get("schema") != PLATFORM_TRUTH_SCHEMA:
        errors.append("candidate platform snapshot schema is unsupported")
    if not isinstance(config, dict):
        errors.append("candidate platform config snapshot is missing")
        config = {}
    if not isinstance(environment_access, dict):
        errors.append("candidate environment access snapshot is missing")
        environment_access = {}
    if not isinstance(runtime, dict):
        errors.append("candidate runtime snapshot is missing")
        runtime = {}
    if config.get("profile") != "staging":
        errors.append("candidate config snapshot must use the staging profile")
    if config.get("strict") is not True:
        errors.append("candidate staging config must be strict")
    if config.get("valid") is not True or config.get("startup_allowed") is not True:
        errors.append("candidate staging config must be valid and startable")
    if not _valid_sha256(config.get("config_fingerprint")):
        errors.append("candidate config fingerprint must be sha256")
    if environment_access.get("matches_baseline") is not True:
        errors.append("candidate environment accesses must match the reviewed baseline")
    if environment_access.get("parse_errors"):
        errors.append("candidate environment access scan contains parse errors")
    if not _valid_sha256(environment_access.get("fingerprint")):
        errors.append("candidate environment access fingerprint must be sha256")
    if runtime.get("status") != "valid" or runtime.get("errors"):
        errors.append("candidate runtime contract must be valid")
    if runtime.get("matches_primitive_baseline") is not True:
        errors.append("candidate runtime primitives must match the reviewed baseline")
    if not _valid_sha256(runtime.get("inventory_fingerprint")):
        errors.append("candidate runtime fingerprint must be sha256")
    platform_fingerprint = platform_snapshot.get("platform_fingerprint")
    expected_platform_fingerprint = _canonical_sha256(
        {
            "config": config.get("config_fingerprint"),
            "environment_access": environment_access.get("fingerprint"),
            "runtime": runtime.get("inventory_fingerprint"),
        }
    )
    if not _valid_sha256(platform_fingerprint):
        errors.append("candidate platform fingerprint must be sha256")
    elif platform_fingerprint != expected_platform_fingerprint:
        errors.append("candidate platform fingerprint does not match its components")

    tests = test_summary.get("tests")
    if not _valid_positive_count(tests):
        errors.append("candidate JUnit report must contain tests")
    for field in ("failures", "errors"):
        value = test_summary.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value != 0:
            errors.append(f"candidate JUnit {field} must be zero")

    candidate_validated = not errors
    stable_evidence = {
        "schema": CANDIDATE_SCHEMA,
        "source_revision": source_revision,
        "image_id": image_id,
        "schema_fingerprint": database_fingerprint,
        "platform_fingerprint": platform_fingerprint,
        "config_fingerprint": config.get("config_fingerprint"),
        "environment_access_fingerprint": environment_access.get("fingerprint"),
        "runtime_fingerprint": runtime.get("inventory_fingerprint"),
        "tests": test_summary,
        "candidate_validated": candidate_validated,
        "errors": errors,
    }
    return {
        **stable_evidence,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "candidate_validated" if candidate_validated else "blocked",
        "candidate_scope": "ci_ephemeral_environment",
        "staging_deployed": False,
        "live_cluster_verified": False,
        "registry_digest_verified": False,
        "production_promotion_allowed": False,
        "required_live_evidence": list(REQUIRED_LIVE_EVIDENCE),
        "evidence_fingerprint": _canonical_sha256(stable_evidence),
    }


def _write_report(report: dict[str, Any], output: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--schema-report", type=Path, required=True)
    validate.add_argument("--platform-snapshot", type=Path, required=True)
    validate.add_argument("--junit", type=Path, required=True)
    validate.add_argument("--source-revision", required=True)
    validate.add_argument("--image-id", required=True)
    validate.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        report = build_candidate_evidence(
            _load_json_object(args.schema_report),
            _load_json_object(args.platform_snapshot),
            load_junit_summary(args.junit),
            source_revision=args.source_revision,
            image_id=args.image_id,
        )
    except (OSError, json.JSONDecodeError, StagingCandidateEvidenceError) as exc:
        report = {
            "schema": CANDIDATE_SCHEMA,
            "status": "error",
            "candidate_validated": False,
            "staging_deployed": False,
            "live_cluster_verified": False,
            "registry_digest_verified": False,
            "production_promotion_allowed": False,
            "error": f"candidate evidence input is invalid: {type(exc).__name__}",
        }
        _write_report(report, args.output)
        return 2

    _write_report(report, args.output)
    return 0 if report["candidate_validated"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
