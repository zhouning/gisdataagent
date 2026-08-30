"""Build the only evidence bundle eligible for a protected staging apply.

The builder revalidates candidate, registry, and provenance evidence and binds
their stable fingerprints to one immutable OCI subject. A valid bundle grants
only staging apply admission. It cannot claim a live deployment or authorize
production promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .staging_provenance_evidence import (
    GITHUB_OIDC_ISSUER,
    PREDICATE_TYPE,
    PROTECTED_SOURCE_REF,
    PROVENANCE_EVIDENCE_SCHEMA,
    PUBLISH_WORKFLOW_PATH,
    REQUIRED_STAGING_EVIDENCE,
    SOURCE_REPOSITORY_PATTERN,
    provenance_evidence_fingerprint,
    registry_evidence_errors,
)
from .staging_registry_evidence import (
    DIGEST_PATTERN,
    SHA256_PATTERN,
    SOURCE_REVISION_PATTERN,
    candidate_evidence_errors,
)

RELEASE_EVIDENCE_SCHEMA = "gda.staging_release_evidence.v2"
RELEASE_STABLE_FIELDS = (
    "schema",
    "source_revision",
    "verifier_revision",
    "candidate_evidence_fingerprint",
    "registry_evidence_fingerprint",
    "provenance_evidence_fingerprint",
    "repository",
    "digest",
    "image",
    "schema_fingerprint",
    "platform_fingerprint",
    "config_fingerprint",
    "environment_access_fingerprint",
    "runtime_fingerprint",
    "runtime_privilege_fingerprint",
    "staging_apply_allowed",
    "errors",
)
REQUIRED_POST_APPLY_EVIDENCE = (
    "protected cluster and namespace identity",
    "strict live platform and runtime-privilege fingerprints bound to the Deployment",
    "live schema, rollout, health, and golden-slice evidence",
)


class StagingReleaseEvidenceError(RuntimeError):
    """A staging release evidence input could not be parsed safely."""


def _canonical_sha256(value: object) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def release_evidence_fingerprint(value: Mapping[str, Any]) -> str:
    """Return the canonical fingerprint of a staging release report."""
    stable = {field: value.get(field) for field in RELEASE_STABLE_FIELDS}
    return _canonical_sha256(stable)


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise StagingReleaseEvidenceError("JSON evidence must be an object")
    return value


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_PATTERN.fullmatch(value))


def _provenance_errors(
    provenance: Mapping[str, Any],
    registry: Mapping[str, Any],
    *,
    source_repository: str,
    source_revision: str,
    verifier_revision: str,
) -> list[str]:
    errors: list[str] = []
    if provenance.get("schema") != PROVENANCE_EVIDENCE_SCHEMA:
        errors.append("provenance evidence schema is unsupported")
    if provenance.get("status") != "provenance_verified":
        errors.append("provenance status must be provenance_verified")
    for field in (
        "provenance_attestation_verified",
        "registry_digest_verified",
        "repository_identity_verified",
        "signer_workflow_identity_verified",
        "source_revision_verified",
        "github_oidc_issuer_verified",
        "hosted_runner_verified",
    ):
        if provenance.get(field) is not True:
            errors.append(f"provenance {field} must be true")
    count = provenance.get("verified_attestation_count")
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        errors.append("provenance verified attestation count must be positive")
    if provenance.get("source_revision") != source_revision:
        errors.append("provenance source revision does not match the release")
    if provenance.get("verifier_revision") != verifier_revision:
        errors.append("provenance verifier revision does not match the release")
    for field in ("repository", "digest", "image"):
        if provenance.get(field) != registry.get(field):
            errors.append(f"provenance {field} does not match registry evidence")
    if provenance.get("candidate_evidence_fingerprint") != registry.get(
        "candidate_evidence_fingerprint"
    ):
        errors.append("provenance candidate fingerprint does not match registry")
    if provenance.get("registry_evidence_fingerprint") != registry.get(
        "evidence_fingerprint"
    ):
        errors.append("provenance registry fingerprint does not match registry")
    runtime_privilege_fingerprint = registry.get(
        "runtime_privilege_fingerprint"
    )
    if provenance.get("runtime_privilege_fingerprint") != (
        runtime_privilege_fingerprint
    ):
        errors.append(
            "provenance runtime privilege fingerprint does not match registry"
        )
    if not _valid_sha256(runtime_privilege_fingerprint):
        errors.append("registry runtime privilege fingerprint must be sha256")
    expected_policy = {
        "source_repository": source_repository,
        "source_ref": PROTECTED_SOURCE_REF,
        "source_digest": source_revision,
        "signer_workflow": f"{source_repository}/{PUBLISH_WORKFLOW_PATH}",
        "signer_digest": source_revision,
        "oidc_issuer": GITHUB_OIDC_ISSUER,
        "deny_self_hosted_runners": True,
        "predicate_type": PREDICATE_TYPE,
    }
    if provenance.get("verification_policy") != expected_policy:
        errors.append("provenance verification policy does not match the release")
    if provenance.get("errors") != []:
        errors.append("provenance evidence contains errors")
    if provenance.get("required_staging_evidence") != list(
        REQUIRED_STAGING_EVIDENCE
    ):
        errors.append("provenance required staging evidence policy does not match")
    if provenance.get("evidence_fingerprint") != provenance_evidence_fingerprint(
        provenance
    ):
        errors.append("provenance evidence fingerprint does not match its content")
    for field in (
        "staging_deployed",
        "live_cluster_verified",
        "production_promotion_allowed",
    ):
        if provenance.get(field) is not False:
            errors.append(f"provenance {field} must remain false before apply")
    return errors


def build_staging_release_evidence(
    candidate: Mapping[str, Any],
    registry: Mapping[str, Any],
    provenance: Mapping[str, Any],
    *,
    source_repository: str,
    source_revision: str,
    verifier_revision: str,
) -> dict[str, Any]:
    """Revalidate and bind all pre-deployment evidence for staging only."""
    errors: list[str] = []
    if not SOURCE_REPOSITORY_PATTERN.fullmatch(source_repository):
        errors.append("source repository must be a canonical lowercase slug")
    if not SOURCE_REVISION_PATTERN.fullmatch(source_revision):
        errors.append("source revision must be a full lowercase Git SHA-1")
    if not SOURCE_REVISION_PATTERN.fullmatch(verifier_revision):
        errors.append("verifier revision must be a full lowercase Git SHA-1")

    errors.extend(
        f"candidate: {error}" for error in candidate_evidence_errors(candidate)
    )
    errors.extend(
        f"registry: {error}"
        for error in registry_evidence_errors(
            registry,
            source_repository=source_repository,
            source_revision=source_revision,
        )
    )
    errors.extend(
        f"provenance: {error}"
        for error in _provenance_errors(
            provenance,
            registry,
            source_repository=source_repository,
            source_revision=source_revision,
            verifier_revision=verifier_revision,
        )
    )

    candidate_fingerprint = candidate.get("evidence_fingerprint")
    if registry.get("candidate_evidence_fingerprint") != candidate_fingerprint:
        errors.append("release candidate fingerprint does not match registry")
    if provenance.get("candidate_evidence_fingerprint") != candidate_fingerprint:
        errors.append("release candidate fingerprint does not match provenance")
    runtime_privilege_fingerprint = candidate.get(
        "runtime_privilege_fingerprint"
    )
    if registry.get("runtime_privilege_fingerprint") != (
        runtime_privilege_fingerprint
    ):
        errors.append(
            "release runtime privilege fingerprint does not match registry"
        )
    if provenance.get("runtime_privilege_fingerprint") != (
        runtime_privilege_fingerprint
    ):
        errors.append(
            "release runtime privilege fingerprint does not match provenance"
        )
    if candidate.get("source_revision") != source_revision:
        errors.append("release source revision does not match candidate")
    for field in (
        "schema_fingerprint",
        "platform_fingerprint",
        "config_fingerprint",
        "environment_access_fingerprint",
        "runtime_fingerprint",
        "runtime_privilege_fingerprint",
    ):
        if not _valid_sha256(candidate.get(field)):
            errors.append(f"release candidate {field} must be sha256")
    digest = registry.get("digest")
    if not isinstance(digest, str) or not DIGEST_PATTERN.fullmatch(digest):
        errors.append("release registry digest must be sha256")

    allowed = not errors
    stable = {
        "schema": RELEASE_EVIDENCE_SCHEMA,
        "source_revision": source_revision,
        "verifier_revision": verifier_revision,
        "candidate_evidence_fingerprint": candidate_fingerprint,
        "registry_evidence_fingerprint": registry.get("evidence_fingerprint"),
        "provenance_evidence_fingerprint": provenance.get(
            "evidence_fingerprint"
        ),
        "repository": registry.get("repository"),
        "digest": digest,
        "image": registry.get("image"),
        "schema_fingerprint": candidate.get("schema_fingerprint"),
        "platform_fingerprint": candidate.get("platform_fingerprint"),
        "config_fingerprint": candidate.get("config_fingerprint"),
        "environment_access_fingerprint": candidate.get(
            "environment_access_fingerprint"
        ),
        "runtime_fingerprint": candidate.get("runtime_fingerprint"),
        "runtime_privilege_fingerprint": candidate.get(
            "runtime_privilege_fingerprint"
        ),
        "staging_apply_allowed": allowed,
        "errors": errors,
    }
    return {
        **stable,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "staging_release_admitted" if allowed else "blocked",
        "registry_digest_verified": allowed,
        "provenance_attestation_verified": allowed,
        "staging_deployed": False,
        "live_cluster_verified": False,
        "golden_slice_verified": False,
        "promotion_authority_verified": False,
        "production_promotion_allowed": False,
        "required_post_apply_evidence": list(REQUIRED_POST_APPLY_EVIDENCE),
        "evidence_fingerprint": release_evidence_fingerprint(stable),
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
    build = subparsers.add_parser("build")
    build.add_argument("--candidate-evidence", type=Path, required=True)
    build.add_argument("--registry-evidence", type=Path, required=True)
    build.add_argument("--provenance-evidence", type=Path, required=True)
    build.add_argument("--source-repository", required=True)
    build.add_argument("--source-revision", required=True)
    build.add_argument("--verifier-revision", required=True)
    build.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        report = build_staging_release_evidence(
            _load_json_object(args.candidate_evidence),
            _load_json_object(args.registry_evidence),
            _load_json_object(args.provenance_evidence),
            source_repository=args.source_repository,
            source_revision=args.source_revision,
            verifier_revision=args.verifier_revision,
        )
    except (OSError, json.JSONDecodeError, StagingReleaseEvidenceError) as exc:
        report = {
            "schema": RELEASE_EVIDENCE_SCHEMA,
            "status": "error",
            "staging_apply_allowed": False,
            "staging_deployed": False,
            "live_cluster_verified": False,
            "production_promotion_allowed": False,
            "error": f"release evidence input is invalid: {type(exc).__name__}",
        }
        _write_report(report, args.output)
        return 2

    _write_report(report, args.output)
    return 0 if report["staging_apply_allowed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
