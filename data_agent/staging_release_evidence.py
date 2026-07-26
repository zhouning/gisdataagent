"""Verify protected provenance evidence and materialize a staging release.

This boundary verifies the artifact identity of ``provenance.json`` before its
OCI subject is used to build a Kubernetes release manifest. A successful
report authorizes staging apply only; it is not deployment or live evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .staging_deployment_bundle import (
    BUNDLE_SCHEMA,
    build_staging_bundle,
)
from .staging_provenance_evidence import (
    GITHUB_OIDC_ISSUER,
    PREDICATE_TYPE,
    PROTECTED_SOURCE_REF,
    PROVENANCE_EVIDENCE_SCHEMA,
    PUBLISH_WORKFLOW_PATH,
    REQUIRED_STAGING_EVIDENCE,
    SOURCE_REPOSITORY_PATTERN,
    provenance_evidence_fingerprint,
)
from .staging_registry_evidence import (
    DIGEST_PATTERN,
    SHA256_PATTERN,
    SOURCE_REVISION_PATTERN,
)

VERIFIED_RELEASE_SCHEMA = "gda.staging_verified_release_bundle.v1"
VERIFIER_WORKFLOW_PATH = ".github/workflows/verify-staging-provenance.yml"
REQUIRED_POST_APPLY_EVIDENCE = (
    "protected staging cluster and namespace identity",
    "server-side apply and rollout observation for this manifest fingerprint",
    "live schema, config, runtime, health, and readiness evidence",
    "live golden-slice evidence bound to the same release revision",
)

CommandRunner = Callable[[list[str]], str]


class StagingReleaseEvidenceError(RuntimeError):
    """Protected release evidence could not be verified safely."""


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise StagingReleaseEvidenceError("JSON input must be an object")
    return value


def _load_yaml_documents(path: Path) -> list[dict[str, Any]]:
    values = yaml.safe_load_all(path.read_text(encoding="utf-8"))
    documents = [value for value in values if isinstance(value, dict)]
    if not documents:
        raise StagingReleaseEvidenceError("template manifest has no resources")
    return documents


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
        raise StagingReleaseEvidenceError(
            "GitHub artifact attestation verifier is unavailable"
        ) from exc
    if completed.returncode != 0:
        raise StagingReleaseEvidenceError(
            "GitHub artifact attestation verification failed"
        )
    return completed.stdout


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _items(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _expected_publisher_policy(
    *, source_repository: str, source_revision: str
) -> dict[str, Any]:
    return {
        "source_repository": source_repository,
        "source_ref": PROTECTED_SOURCE_REF,
        "source_digest": source_revision,
        "signer_workflow": f"{source_repository}/{PUBLISH_WORKFLOW_PATH}",
        "signer_digest": source_revision,
        "oidc_issuer": GITHUB_OIDC_ISSUER,
        "deny_self_hosted_runners": True,
        "predicate_type": PREDICATE_TYPE,
    }


def _provenance_errors(
    provenance: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    source_repository: str,
    source_revision: str,
    verifier_revision: str,
) -> list[str]:
    errors: list[str] = []
    expected_repository = f"ghcr.io/{source_repository.lower()}"
    digest = str(provenance.get("digest") or "")
    expected_image = f"{expected_repository}@{digest}"

    if not SOURCE_REPOSITORY_PATTERN.fullmatch(source_repository):
        errors.append("source repository must be a canonical lowercase slug")
    if not SOURCE_REVISION_PATTERN.fullmatch(source_revision):
        errors.append("source revision must be a full lowercase Git SHA-1")
    if not SOURCE_REVISION_PATTERN.fullmatch(verifier_revision):
        errors.append("verifier revision must be a full lowercase Git SHA-1")
    if provenance.get("schema") != PROVENANCE_EVIDENCE_SCHEMA:
        errors.append("provenance evidence schema is unsupported")
    if provenance.get("status") != "provenance_verified":
        errors.append("provenance evidence status must be provenance_verified")
    if provenance.get("source_revision") != source_revision:
        errors.append("provenance source revision does not match release input")
    if provenance.get("verifier_revision") != verifier_revision:
        errors.append("provenance verifier revision does not match release input")
    if candidate.get("source_revision") != source_revision:
        errors.append("candidate source revision does not match release input")
    candidate_fingerprint = candidate.get("evidence_fingerprint")
    if (
        not isinstance(candidate_fingerprint, str)
        or not SHA256_PATTERN.fullmatch(candidate_fingerprint)
    ):
        errors.append("candidate evidence fingerprint must be sha256")
    if provenance.get("candidate_evidence_fingerprint") != candidate_fingerprint:
        errors.append("provenance evidence does not bind the candidate")
    registry_fingerprint = provenance.get("registry_evidence_fingerprint")
    if (
        not isinstance(registry_fingerprint, str)
        or not SHA256_PATTERN.fullmatch(registry_fingerprint)
    ):
        errors.append("registry evidence fingerprint must be sha256")
    if provenance.get("repository") != expected_repository:
        errors.append("provenance repository does not match source repository")
    if not DIGEST_PATTERN.fullmatch(digest):
        errors.append("provenance digest must be sha256")
    if provenance.get("image") != expected_image:
        errors.append("provenance image does not match repository and digest")
    if provenance.get("verification_policy") != _expected_publisher_policy(
        source_repository=source_repository,
        source_revision=source_revision,
    ):
        errors.append("publisher provenance verification policy drifted")
    count = provenance.get("verified_attestation_count")
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        errors.append("publisher attestation count must be positive")
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
    for field in (
        "staging_deployed",
        "live_cluster_verified",
        "production_promotion_allowed",
    ):
        if provenance.get(field) is not False:
            errors.append(f"provenance {field} must remain false before apply")
    if provenance.get("errors") != []:
        errors.append("provenance evidence contains errors")
    if provenance.get("required_staging_evidence") != list(
        REQUIRED_STAGING_EVIDENCE
    ):
        errors.append("provenance required staging evidence policy drifted")
    if provenance.get("evidence_fingerprint") != provenance_evidence_fingerprint(
        provenance
    ):
        errors.append("provenance evidence fingerprint does not match its content")
    return errors


def _artifact_verification_command(
    path: Path,
    *,
    source_repository: str,
    verifier_revision: str,
) -> list[str]:
    return [
        "gh",
        "attestation",
        "verify",
        str(path),
        "--repo",
        source_repository,
        "--signer-workflow",
        f"{source_repository}/{VERIFIER_WORKFLOW_PATH}",
        "--signer-digest",
        verifier_revision,
        "--source-ref",
        PROTECTED_SOURCE_REF,
        "--source-digest",
        verifier_revision,
        "--cert-oidc-issuer",
        GITHUB_OIDC_ISSUER,
        "--deny-self-hosted-runners",
        "--predicate-type",
        PREDICATE_TYPE,
        "--format",
        "json",
    ]


def _artifact_attestation_errors(
    raw: str, *, artifact_digest: str
) -> tuple[list[str], int]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ["gh attestation verify did not return JSON"], 0
    if not isinstance(payload, list) or not payload:
        return ["gh attestation verify returned no artifact attestations"], 0

    errors: list[str] = []
    matched = 0
    for entry in payload:
        statement = _mapping(
            _mapping(_mapping(entry).get("verificationResult")).get("statement")
        )
        if statement.get("predicateType") != PREDICATE_TYPE:
            errors.append("verified artifact predicate type does not match")
            continue
        if not any(
            _mapping(subject.get("digest")).get("sha256") == artifact_digest
            for subject in _items(statement.get("subject"))
        ):
            errors.append("verified artifact subject digest does not match evidence")
            continue
        matched += 1
    if matched == 0 and not errors:
        errors.append("no verified attestation matched the provenance artifact")
    return errors, matched


def build_verified_staging_release(
    template_documents: list[dict[str, Any]],
    candidate: Mapping[str, Any],
    platform_snapshot: Mapping[str, Any],
    *,
    provenance_path: Path,
    source_repository: str,
    source_revision: str,
    verifier_revision: str,
    run: CommandRunner | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Verify provenance artifact authority before building a release bundle."""
    artifact_bytes = provenance_path.read_bytes()
    provenance = json.loads(artifact_bytes)
    if not isinstance(provenance, dict):
        raise StagingReleaseEvidenceError(
            "provenance evidence JSON must be an object"
        )
    errors = _provenance_errors(
        provenance,
        candidate,
        source_repository=source_repository,
        source_revision=source_revision,
        verifier_revision=verifier_revision,
    )
    artifact_digest = hashlib.sha256(artifact_bytes).hexdigest()
    artifact_attestation_count = 0
    if not errors:
        raw = (run or _run_command)(
            _artifact_verification_command(
                provenance_path,
                source_repository=source_repository,
                verifier_revision=verifier_revision,
            )
        )
        artifact_errors, artifact_attestation_count = (
            _artifact_attestation_errors(raw, artifact_digest=artifact_digest)
        )
        errors.extend(artifact_errors)
        if hashlib.sha256(provenance_path.read_bytes()).hexdigest() != artifact_digest:
            errors.append("provenance artifact changed during verification")

    artifact_verified = not errors and artifact_attestation_count > 0
    documents: list[dict[str, Any]] = []
    base_report: dict[str, Any] | None = None
    if artifact_verified:
        documents, base_report = build_staging_bundle(
            template_documents,
            candidate,
            platform_snapshot,
            image=str(provenance.get("image") or ""),
        )
        errors.extend(str(error) for error in base_report.get("errors") or [])

    bundle_ready = bool(
        artifact_verified
        and base_report is not None
        and base_report.get("schema") == BUNDLE_SCHEMA
        and base_report.get("bundle_ready") is True
        and not errors
    )
    stable = {
        "schema": VERIFIED_RELEASE_SCHEMA,
        "source_revision": source_revision,
        "verifier_revision": verifier_revision,
        "candidate_evidence_fingerprint": candidate.get("evidence_fingerprint"),
        "provenance_evidence_fingerprint": provenance.get(
            "evidence_fingerprint"
        ),
        "provenance_artifact_sha256": artifact_digest,
        "provenance_artifact_attestation_count": artifact_attestation_count,
        "image": provenance.get("image"),
        "platform_fingerprint": (
            base_report.get("platform_fingerprint") if base_report else None
        ),
        "manifest_fingerprint": (
            base_report.get("manifest_fingerprint") if base_report else None
        ),
        "base_bundle_evidence_fingerprint": (
            base_report.get("evidence_fingerprint") if base_report else None
        ),
        "errors": errors,
        "bundle_ready": bundle_ready,
    }
    return documents if bundle_ready else [], {
        **stable,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "verified_for_staging_apply" if bundle_ready else "blocked",
        "provenance_evidence_artifact_verified": artifact_verified,
        "provenance_attestation_verified": artifact_verified,
        "registry_digest_verified": artifact_verified,
        "staging_deployed": False,
        "live_cluster_verified": False,
        "production_promotion_allowed": False,
        "required_post_apply_evidence": list(REQUIRED_POST_APPLY_EVIDENCE),
        "evidence_fingerprint": _canonical_sha256(stable),
    }


def _write_report(report: Mapping[str, Any], path: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def _write_manifest(documents: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump_all(documents, explicit_start=True, sort_keys=False),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--template-manifest", type=Path, required=True)
    build.add_argument("--candidate-evidence", type=Path, required=True)
    build.add_argument("--platform-snapshot", type=Path, required=True)
    build.add_argument("--provenance-evidence", type=Path, required=True)
    build.add_argument("--source-repository", required=True)
    build.add_argument("--source-revision", required=True)
    build.add_argument("--verifier-revision", required=True)
    build.add_argument("--manifest-output", type=Path, required=True)
    build.add_argument("--report-output", type=Path)
    args = parser.parse_args(argv)

    try:
        documents, report = build_verified_staging_release(
            _load_yaml_documents(args.template_manifest),
            _load_json_object(args.candidate_evidence),
            _load_json_object(args.platform_snapshot),
            provenance_path=args.provenance_evidence,
            source_repository=args.source_repository,
            source_revision=args.source_revision,
            verifier_revision=args.verifier_revision,
        )
    except (
        OSError,
        json.JSONDecodeError,
        yaml.YAMLError,
        StagingReleaseEvidenceError,
    ) as exc:
        report = {
            "schema": VERIFIED_RELEASE_SCHEMA,
            "status": "error",
            "bundle_ready": False,
            "provenance_evidence_artifact_verified": False,
            "provenance_attestation_verified": False,
            "registry_digest_verified": False,
            "staging_deployed": False,
            "live_cluster_verified": False,
            "production_promotion_allowed": False,
            "error": f"verified staging release failed: {type(exc).__name__}",
        }
        _write_report(report, args.report_output)
        return 2

    if report["bundle_ready"]:
        _write_manifest(documents, args.manifest_output)
    _write_report(report, args.report_output)
    return 0 if report["bundle_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
