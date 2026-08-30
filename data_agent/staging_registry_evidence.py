"""Bind a validated candidate to an observed immutable registry digest.

The report proves internal field consistency only. It does not verify the
registry's identity or a provenance attestation; a protected runner must do
that against the OCI subject before staging apply.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .staging_candidate_evidence import CANDIDATE_SCHEMA

# v2 makes the runtime privilege observation an explicit part of the
# candidate-to-registry binding. A registry artifact must not rely on a
# separately downloaded candidate file to prove the runtime ACL contract.
REGISTRY_EVIDENCE_SCHEMA = "gda.staging_registry_evidence.v2"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
SOURCE_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
IMAGE_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
GHCR_REPOSITORY_PATTERN = re.compile(
    r"^ghcr\.io/[a-z0-9](?:[a-z0-9._-]{0,127})"
    r"(?:/[a-z0-9](?:[a-z0-9._-]{0,127}))*$"
)
CANDIDATE_STABLE_FIELDS = (
    "schema",
    "source_revision",
    "image_id",
    "schema_fingerprint",
    "platform_fingerprint",
    "config_fingerprint",
    "environment_access_fingerprint",
    "runtime_fingerprint",
    "runtime_privilege_fingerprint",
    "tests",
    "candidate_validated",
    "errors",
)
REQUIRED_PROVENANCE = (
    "verify the OCI subject with GitHub artifact attestation",
    "verify the attestation repository and workflow identity",
    "bind the verified subject to a protected staging release bundle",
)
REGISTRY_STABLE_FIELDS = (
    "schema",
    "source_revision",
    "candidate_evidence_fingerprint",
    "runtime_privilege_fingerprint",
    "local_image_id",
    "repository",
    "digest",
    "image",
    "registry_subject_bound",
    "errors",
)


class StagingRegistryEvidenceError(RuntimeError):
    """Registry evidence input could not be parsed safely."""


def _canonical_sha256(value: object) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise StagingRegistryEvidenceError("JSON evidence must be an object")
    return value


def registry_evidence_fingerprint(value: Mapping[str, Any]) -> str:
    """Return the canonical fingerprint of a registry binding report."""
    stable = {field: value.get(field) for field in REGISTRY_STABLE_FIELDS}
    return _canonical_sha256(stable)


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def candidate_evidence_errors(candidate: Mapping[str, Any]) -> list[str]:
    """Return fail-closed validation errors for candidate evidence."""
    errors: list[str] = []
    if candidate.get("schema") != CANDIDATE_SCHEMA:
        errors.append("candidate evidence schema is unsupported")
    if candidate.get("candidate_validated") is not True:
        errors.append("candidate evidence was not validated")
    if candidate.get("status") != "candidate_validated":
        errors.append("candidate status must be candidate_validated")
    source_revision = str(candidate.get("source_revision") or "")
    if not SOURCE_REVISION_PATTERN.fullmatch(source_revision):
        errors.append("candidate source revision must be a full lowercase Git SHA-1")
    image_id = str(candidate.get("image_id") or "")
    if not IMAGE_ID_PATTERN.fullmatch(image_id):
        errors.append("candidate image ID must be an immutable local sha256 ID")
    for field in (
        "schema_fingerprint",
        "platform_fingerprint",
        "config_fingerprint",
        "environment_access_fingerprint",
        "runtime_fingerprint",
        "runtime_privilege_fingerprint",
        "evidence_fingerprint",
    ):
        value = candidate.get(field)
        if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
            errors.append(f"candidate {field} must be sha256")
    if candidate.get("errors") != []:
        errors.append("candidate evidence contains errors")
    tests = candidate.get("tests")
    if not isinstance(tests, Mapping):
        tests = {}
    if not _positive_int(tests.get("tests")):
        errors.append("candidate test summary must contain tests")
    for field in ("failures", "errors"):
        if tests.get(field) != 0:
            errors.append(f"candidate test summary {field} must be zero")
    skipped = tests.get("skipped")
    if (
        not isinstance(skipped, int)
        or isinstance(skipped, bool)
        or skipped < 0
    ):
        errors.append("candidate test summary skipped count is invalid")
    stable = {field: candidate.get(field) for field in CANDIDATE_STABLE_FIELDS}
    if candidate.get("evidence_fingerprint") != _canonical_sha256(stable):
        errors.append("candidate evidence fingerprint does not match its content")
    for field in (
        "staging_deployed",
        "live_cluster_verified",
        "registry_digest_verified",
        "production_promotion_allowed",
    ):
        if candidate.get(field) is not False:
            errors.append(f"candidate {field} must remain false")
    return errors


def build_registry_evidence(
    candidate: Mapping[str, Any],
    *,
    source_revision: str,
    local_image_id: str,
    repository: str,
    digest: str,
    expected_repository: str,
) -> dict[str, Any]:
    """Build a non-authoritative candidate-to-registry binding report."""
    errors = candidate_evidence_errors(candidate)
    if source_revision != candidate.get("source_revision"):
        errors.append("registry source revision does not match the candidate")
    if not SOURCE_REVISION_PATTERN.fullmatch(source_revision):
        errors.append("registry source revision must be a full lowercase Git SHA-1")
    if local_image_id != candidate.get("image_id"):
        errors.append("registry local image ID does not match the candidate")
    if not IMAGE_ID_PATTERN.fullmatch(local_image_id):
        errors.append("registry local image ID must be sha256")
    if repository != expected_repository:
        errors.append("registry repository does not match the protected target")
    if repository != repository.lower():
        errors.append("registry repository must be lowercase")
    if not GHCR_REPOSITORY_PATTERN.fullmatch(repository):
        errors.append("registry repository must be a canonical ghcr.io path")
    if not GHCR_REPOSITORY_PATTERN.fullmatch(expected_repository):
        errors.append("protected expected registry repository is invalid")
    if not DIGEST_PATTERN.fullmatch(digest):
        errors.append("registry digest must be sha256")

    image = f"{repository}@{digest}"
    bound = not errors
    stable = {
        "schema": REGISTRY_EVIDENCE_SCHEMA,
        "source_revision": source_revision,
        "candidate_evidence_fingerprint": candidate.get("evidence_fingerprint"),
        "runtime_privilege_fingerprint": candidate.get(
            "runtime_privilege_fingerprint"
        ),
        "local_image_id": local_image_id,
        "repository": repository,
        "digest": digest,
        "image": image,
        "registry_subject_bound": bound,
        "errors": errors,
    }
    return {
        **stable,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "registry_subject_bound" if bound else "blocked",
        "registry_push_observed": bound,
        "provenance_attestation_verified": False,
        "registry_digest_verified": False,
        "staging_deployed": False,
        "live_cluster_verified": False,
        "production_promotion_allowed": False,
        "required_provenance": list(REQUIRED_PROVENANCE),
        "evidence_fingerprint": registry_evidence_fingerprint(stable),
    }


def _write_report(report: Mapping[str, Any], output: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--candidate-evidence", type=Path, required=True)
    validate.add_argument("--source-revision", required=True)
    validate.add_argument("--local-image-id", required=True)
    validate.add_argument("--repository", required=True)
    validate.add_argument("--digest", required=True)
    validate.add_argument("--expected-repository", required=True)
    validate.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        report = build_registry_evidence(
            _load_json_object(args.candidate_evidence),
            source_revision=args.source_revision,
            local_image_id=args.local_image_id,
            repository=args.repository,
            digest=args.digest,
            expected_repository=args.expected_repository,
        )
    except (OSError, json.JSONDecodeError, StagingRegistryEvidenceError) as exc:
        report = {
            "schema": REGISTRY_EVIDENCE_SCHEMA,
            "status": "error",
            "registry_subject_bound": False,
            "provenance_attestation_verified": False,
            "registry_digest_verified": False,
            "staging_deployed": False,
            "live_cluster_verified": False,
            "production_promotion_allowed": False,
            "error": f"registry evidence input is invalid: {type(exc).__name__}",
        }
        _write_report(report, args.output)
        return 2

    _write_report(report, args.output)
    return 0 if report["registry_subject_bound"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
