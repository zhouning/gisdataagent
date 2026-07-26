"""Independently verify a staging registry subject's GitHub provenance.

The verifier invokes ``gh attestation verify`` with a fixed identity policy.
Success verifies the OCI subject and its publisher identity, but does not prove
that staging was deployed or authorize production promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .staging_registry_evidence import (
    DIGEST_PATTERN,
    GHCR_REPOSITORY_PATTERN,
    IMAGE_ID_PATTERN,
    REGISTRY_EVIDENCE_SCHEMA,
    REQUIRED_PROVENANCE,
    SHA256_PATTERN,
    SOURCE_REVISION_PATTERN,
    registry_evidence_fingerprint,
)

PROVENANCE_EVIDENCE_SCHEMA = "gda.staging_provenance_evidence.v1"
PREDICATE_TYPE = "https://slsa.dev/provenance/v1"
GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
PROTECTED_SOURCE_REF = "refs/heads/main"
PUBLISH_WORKFLOW_PATH = ".github/workflows/cd-staging.yml"
SOURCE_REPOSITORY_PATTERN = re.compile(
    r"^[a-z0-9](?:[a-z0-9._-]{0,99})/"
    r"[a-z0-9](?:[a-z0-9._-]{0,99})$"
)
REQUIRED_STAGING_EVIDENCE = (
    "verify the provenance evidence artifact identity before consumption",
    "bind the verified OCI subject to a protected staging release bundle",
    "collect live staging observation and golden-slice evidence after apply",
)

CommandRunner = Callable[[list[str]], str]


class StagingProvenanceEvidenceError(RuntimeError):
    """Protected provenance evidence could not be verified safely."""


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise StagingProvenanceEvidenceError(
            "registry evidence JSON must be an object"
        )
    return payload


def _run_command(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            check=False,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise StagingProvenanceEvidenceError(
            "GitHub attestation verifier is unavailable"
        ) from exc
    if completed.returncode != 0:
        raise StagingProvenanceEvidenceError(
            "GitHub attestation verification failed without usable evidence"
        )
    return completed.stdout


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _items(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _registry_errors(
    registry: Mapping[str, Any],
    *,
    source_repository: str,
    source_revision: str,
) -> list[str]:
    errors: list[str] = []
    expected_repository = f"ghcr.io/{source_repository.lower()}"
    digest = str(registry.get("digest") or "")
    expected_image = f"{expected_repository}@{digest}"

    if not SOURCE_REPOSITORY_PATTERN.fullmatch(source_repository):
        errors.append("source repository must be a canonical lowercase slug")
    if not SOURCE_REVISION_PATTERN.fullmatch(source_revision):
        errors.append("source revision must be a full lowercase Git SHA-1")
    if registry.get("schema") != REGISTRY_EVIDENCE_SCHEMA:
        errors.append("registry evidence schema is unsupported")
    if registry.get("status") != "registry_subject_bound":
        errors.append("registry evidence status must be registry_subject_bound")
    if registry.get("registry_subject_bound") is not True:
        errors.append("registry subject was not bound")
    if registry.get("registry_push_observed") is not True:
        errors.append("registry push was not observed")
    if registry.get("source_revision") != source_revision:
        errors.append("registry source revision does not match the protected run")
    if registry.get("repository") != expected_repository:
        errors.append("registry repository does not match the source repository")
    if not GHCR_REPOSITORY_PATTERN.fullmatch(expected_repository):
        errors.append("derived GHCR repository is invalid")
    if not DIGEST_PATTERN.fullmatch(digest):
        errors.append("registry digest must be sha256")
    if registry.get("image") != expected_image:
        errors.append("registry image does not match repository and digest")
    local_image_id = str(registry.get("local_image_id") or "")
    if not IMAGE_ID_PATTERN.fullmatch(local_image_id):
        errors.append("registry local image ID must be sha256")
    candidate_fingerprint = registry.get("candidate_evidence_fingerprint")
    if not isinstance(candidate_fingerprint, str) or not SHA256_PATTERN.fullmatch(
        candidate_fingerprint
    ):
        errors.append("candidate evidence fingerprint must be sha256")
    if registry.get("errors") != []:
        errors.append("registry evidence contains errors")
    if registry.get("required_provenance") != list(REQUIRED_PROVENANCE):
        errors.append("registry required provenance policy does not match")
    if registry.get("evidence_fingerprint") != registry_evidence_fingerprint(
        registry
    ):
        errors.append("registry evidence fingerprint does not match its content")
    for field in (
        "provenance_attestation_verified",
        "registry_digest_verified",
        "staging_deployed",
        "live_cluster_verified",
        "production_promotion_allowed",
    ):
        if registry.get(field) is not False:
            errors.append(f"registry {field} must remain false before verification")
    return errors


def _verification_command(
    *,
    image: str,
    source_repository: str,
    source_revision: str,
) -> list[str]:
    signer_workflow = f"{source_repository}/{PUBLISH_WORKFLOW_PATH}"
    return [
        "gh",
        "attestation",
        "verify",
        f"oci://{image}",
        "--repo",
        source_repository,
        "--signer-workflow",
        signer_workflow,
        "--signer-digest",
        source_revision,
        "--source-ref",
        PROTECTED_SOURCE_REF,
        "--source-digest",
        source_revision,
        "--cert-oidc-issuer",
        GITHUB_OIDC_ISSUER,
        "--deny-self-hosted-runners",
        "--predicate-type",
        PREDICATE_TYPE,
        "--format",
        "json",
    ]


def _attestation_errors(
    raw: str,
    *,
    repository: str,
    digest: str,
) -> tuple[list[str], int]:
    errors: list[str] = []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ["gh attestation verify did not return JSON"], 0
    if not isinstance(payload, list) or not payload:
        return ["gh attestation verify returned no attestations"], 0

    expected_digest = digest.removeprefix("sha256:")
    matched = 0
    for entry in payload:
        result = _mapping(_mapping(entry).get("verificationResult"))
        statement = _mapping(result.get("statement"))
        if statement.get("predicateType") != PREDICATE_TYPE:
            errors.append("verified attestation predicate type does not match")
            continue
        subject_matches = any(
            subject.get("name") == repository
            and _mapping(subject.get("digest")).get("sha256")
            == expected_digest
            for subject in _items(statement.get("subject"))
        )
        if not subject_matches:
            errors.append("verified attestation subject does not match OCI image")
            continue
        matched += 1
    if matched == 0 and not errors:
        errors.append("no verified attestation matched the OCI subject")
    return errors, matched


def verify_registry_provenance(
    registry: Mapping[str, Any],
    *,
    source_repository: str,
    source_revision: str,
    run: CommandRunner | None = None,
) -> dict[str, Any]:
    """Verify the bound OCI subject with a fixed GitHub identity policy."""
    errors = _registry_errors(
        registry,
        source_repository=source_repository,
        source_revision=source_revision,
    )
    repository = str(registry.get("repository") or "")
    digest = str(registry.get("digest") or "")
    image = str(registry.get("image") or "")
    matched = 0
    if not errors:
        raw = (run or _run_command)(
            _verification_command(
                image=image,
                source_repository=source_repository,
                source_revision=source_revision,
            )
        )
        attestation_errors, matched = _attestation_errors(
            raw,
            repository=repository,
            digest=digest,
        )
        errors.extend(attestation_errors)

    verified = not errors and matched > 0
    signer_workflow = f"{source_repository}/{PUBLISH_WORKFLOW_PATH}"
    policy = {
        "source_repository": source_repository,
        "source_ref": PROTECTED_SOURCE_REF,
        "source_digest": source_revision,
        "signer_workflow": signer_workflow,
        "signer_digest": source_revision,
        "oidc_issuer": GITHUB_OIDC_ISSUER,
        "deny_self_hosted_runners": True,
        "predicate_type": PREDICATE_TYPE,
    }
    stable = {
        "schema": PROVENANCE_EVIDENCE_SCHEMA,
        "source_revision": source_revision,
        "candidate_evidence_fingerprint": registry.get(
            "candidate_evidence_fingerprint"
        ),
        "registry_evidence_fingerprint": registry.get("evidence_fingerprint"),
        "repository": repository,
        "digest": digest,
        "image": image,
        "verification_policy": policy,
        "verified_attestation_count": matched,
        "provenance_attestation_verified": verified,
        "registry_digest_verified": verified,
        "errors": errors,
    }
    return {
        **stable,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "provenance_verified" if verified else "blocked",
        "repository_identity_verified": verified,
        "signer_workflow_identity_verified": verified,
        "source_revision_verified": verified,
        "github_oidc_issuer_verified": verified,
        "hosted_runner_verified": verified,
        "staging_deployed": False,
        "live_cluster_verified": False,
        "production_promotion_allowed": False,
        "required_staging_evidence": list(REQUIRED_STAGING_EVIDENCE),
        "evidence_fingerprint": _canonical_sha256(stable),
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
    verify = subparsers.add_parser("verify")
    verify.add_argument("--registry-evidence", type=Path, required=True)
    verify.add_argument("--source-repository", required=True)
    verify.add_argument("--source-revision", required=True)
    verify.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        report = verify_registry_provenance(
            _load_json_object(args.registry_evidence),
            source_repository=args.source_repository,
            source_revision=args.source_revision,
        )
    except (
        OSError,
        json.JSONDecodeError,
        StagingProvenanceEvidenceError,
    ) as exc:
        report = {
            "schema": PROVENANCE_EVIDENCE_SCHEMA,
            "status": "error",
            "provenance_attestation_verified": False,
            "registry_digest_verified": False,
            "staging_deployed": False,
            "live_cluster_verified": False,
            "production_promotion_allowed": False,
            "error": f"provenance verification failed: {type(exc).__name__}",
        }
        _write_report(report, args.output)
        return 2

    _write_report(report, args.output)
    return 0 if report["provenance_attestation_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
