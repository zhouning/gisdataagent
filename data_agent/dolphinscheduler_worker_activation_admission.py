"""Admit one protected staging worker activation from attested evidence.

The verifier is deliberately side-effect free. It validates GitHub run and
artifact identity plus the exact Kubernetes manifest that a separate protected
workflow may apply. It never reads credentials or invokes Kubernetes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from .dolphinscheduler_worker_activation import (
    ACTIVATION_SCHEMA,
    IMMUTABLE_IMAGE_PATTERN,
)
from .dolphinscheduler_worker_deployment import (
    DEPLOYMENT_NAME,
    build_deployment_report,
)
from .dolphinscheduler_worker_staging import (
    MANIFEST_REPORT_SCHEMA,
    READINESS_SCHEMA,
    RESOURCE_UID_PATTERN,
    readiness_evidence_fingerprint,
    release_evidence_errors,
)

RUN_REPORT_SCHEMA = "gda.dolphinscheduler_worker_readiness_run.v1"
ARTIFACT_REPORT_SCHEMA = "gda.dolphinscheduler_worker_readiness_artifact.v1"
ADMISSION_SCHEMA = "gda.dolphinscheduler_worker_activation_admission.v1"
READINESS_WORKFLOW_PATH = (
    ".github/workflows/verify-staging-dolphinscheduler-worker.yml"
)
READINESS_ARTIFACT_PREFIX = "staging-dolphinscheduler-worker-readiness-"
SOURCE_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SOURCE_REPOSITORY_PATTERN = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})/"
    r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})$"
)
ARTIFACT_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
ALLOWED_RESOURCES = {
    ("Deployment", DEPLOYMENT_NAME),
    ("ServiceAccount", DEPLOYMENT_NAME),
    ("NetworkPolicy", "postgres-access"),
}
READY_LIVE_ERRORS = {
    "worker Deployment is not present",
    "worker Deployment remains intentionally scaled to zero",
}
ADMISSION_STABLE_FIELDS = (
    "schema",
    "status",
    "source_repository",
    "readiness_run_id",
    "readiness_revision",
    "readiness_artifact_id",
    "readiness_artifact_digest",
    "environment",
    "namespace",
    "cluster_uid",
    "namespace_uid",
    "release_evidence_fingerprint",
    "readiness_evidence_fingerprint",
    "activation_config_fingerprint",
    "secret_attestation_fingerprint",
    "manifest_sha256",
    "image",
    "requested_replicas",
    "single_replica_apply_allowed",
    "deployed",
    "live_worker_verified",
    "automatic_scale_allowed",
    "promotion_authority_verified",
    "production_promotion_allowed",
    "errors",
)


class DolphinSchedulerWorkerActivationAdmissionError(RuntimeError):
    """Activation admission input could not be parsed safely."""


def _canonical_sha256(value: object) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DolphinSchedulerWorkerActivationAdmissionError(
            "JSON evidence is unavailable or invalid"
        ) from exc
    if not isinstance(value, dict):
        raise DolphinSchedulerWorkerActivationAdmissionError(
            "JSON evidence must be an object"
        )
    return value


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _positive_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return int(value)
    return None


def _write_json(report: Mapping[str, Any], output: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def build_readiness_run_report(
    run: Mapping[str, Any],
    *,
    expected_run_id: int | str,
    source_repository: str,
) -> dict[str, Any]:
    """Validate the GitHub Actions run allowed to supply readiness evidence."""
    errors: list[str] = []
    run_id = _positive_integer(run.get("id"))
    expected_id = _positive_integer(expected_run_id)
    if expected_id is None:
        errors.append("expected readiness run ID must be a positive integer")
    if run_id != expected_id:
        errors.append("readiness run ID does not match the requested run")
    if not SOURCE_REPOSITORY_PATTERN.fullmatch(source_repository):
        errors.append("source repository must be a canonical repository slug")
    if run.get("event") != "workflow_dispatch":
        errors.append("readiness run event must be workflow_dispatch")
    if run.get("status") != "completed":
        errors.append("readiness run status must be completed")
    if run.get("conclusion") != "success":
        errors.append("readiness run conclusion must be success")
    if run.get("head_branch") != "main":
        errors.append("readiness run head branch must be main")
    source_revision = run.get("head_sha")
    if not isinstance(source_revision, str) or not SOURCE_REVISION_PATTERN.fullmatch(
        source_revision
    ):
        errors.append("readiness run source revision must be a full Git SHA")
        source_revision = None
    if run.get("path") != READINESS_WORKFLOW_PATH:
        errors.append("readiness run workflow path is not protected")
    for field in ("repository", "head_repository"):
        if _mapping(run.get(field)).get("full_name") != source_repository:
            errors.append(f"readiness run {field} does not match the source repository")

    return {
        "schema": RUN_REPORT_SCHEMA,
        "status": "valid" if not errors else "invalid",
        "source_repository": source_repository,
        "run_id": run_id,
        "source_revision": source_revision,
        "workflow_path": run.get("path"),
        "artifact_name": (
            f"{READINESS_ARTIFACT_PREFIX}{expected_id}"
            if expected_id is not None
            else None
        ),
        "errors": errors,
    }


def build_readiness_artifact_report(
    artifacts_payload: Mapping[str, Any],
    *,
    run_report: Mapping[str, Any],
) -> dict[str, Any]:
    """Select the exact unexpired readiness artifact and bind its digest."""
    errors: list[str] = []
    if run_report.get("schema") != RUN_REPORT_SCHEMA or run_report.get(
        "status"
    ) != "valid":
        errors.append("readiness run admission is invalid")
    artifacts = artifacts_payload.get("artifacts")
    if not isinstance(artifacts, list):
        artifacts = []
        errors.append("readiness artifact response must contain an artifact list")
    expected_name = run_report.get("artifact_name")
    matches = [
        artifact
        for artifact in artifacts
        if isinstance(artifact, Mapping) and artifact.get("name") == expected_name
    ]
    if len(matches) != 1:
        errors.append("exactly one readiness artifact must match the requested run")
    artifact = matches[0] if len(matches) == 1 else {}
    artifact_id = _positive_integer(artifact.get("id"))
    if artifact_id is None:
        errors.append("readiness artifact ID must be a positive integer")
    size = _positive_integer(artifact.get("size_in_bytes"))
    if size is None:
        errors.append("readiness artifact must not be empty")
    if artifact.get("expired") is not False:
        errors.append("readiness artifact must be unexpired")
    digest = artifact.get("digest")
    if not isinstance(digest, str) or not ARTIFACT_DIGEST_PATTERN.fullmatch(digest):
        errors.append("readiness artifact digest is invalid")
        digest = None
    workflow_run = _mapping(artifact.get("workflow_run"))
    if _positive_integer(workflow_run.get("id")) != run_report.get("run_id"):
        errors.append("readiness artifact run ID does not match the run")
    if workflow_run.get("head_branch") != "main":
        errors.append("readiness artifact head branch must be main")
    if workflow_run.get("head_sha") != run_report.get("source_revision"):
        errors.append("readiness artifact source revision does not match the run")

    return {
        "schema": ARTIFACT_REPORT_SCHEMA,
        "status": "valid" if not errors else "invalid",
        "run_id": run_report.get("run_id"),
        "source_revision": run_report.get("source_revision"),
        "artifact_id": artifact_id,
        "artifact_name": expected_name,
        "artifact_size": size,
        "artifact_digest": digest,
        "errors": errors,
    }


def _manifest_errors(
    manifest_path: Path,
    *,
    expected_namespace: str,
    expected_image: str,
    manifest_report: Mapping[str, Any],
) -> tuple[list[str], str | None, int | None]:
    errors: list[str] = []
    try:
        loaded = list(yaml.safe_load_all(manifest_path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError) as exc:
        return [f"activation manifest is unavailable or invalid: {type(exc).__name__}"], None, None
    documents = [value for value in loaded if isinstance(value, dict)]
    resources = [
        (
            document.get("kind"),
            _mapping(document.get("metadata")).get("name"),
        )
        for document in documents
    ]
    if len(loaded) != 3 or len(documents) != 3 or set(resources) != ALLOWED_RESOURCES:
        errors.append("activation manifest resources are not exactly allowlisted")
    if len(resources) != len(set(resources)):
        errors.append("activation manifest resources must be unique")
    for document in documents:
        if _mapping(document.get("metadata")).get("namespace") != expected_namespace:
            errors.append("activation manifest resource namespace does not match staging")

    deployment_report = build_deployment_report(
        manifest_path,
        network_policy_path=manifest_path,
        expected_replicas=1,
    )
    errors.extend(
        f"activation manifest: {error}"
        for error in deployment_report.get("errors") or []
    )
    deployment = next(
        (
            document
            for document in documents
            if document.get("kind") == "Deployment"
            and _mapping(document.get("metadata")).get("name") == DEPLOYMENT_NAME
        ),
        {},
    )
    spec = _mapping(deployment.get("spec"))
    replicas = spec.get("replicas")
    if isinstance(replicas, bool) or replicas != 1:
        errors.append("activation manifest must request exactly one replica")
    pod_spec = _mapping(_mapping(spec.get("template")).get("spec"))
    images = [
        item.get("image")
        for field in ("containers", "initContainers")
        for item in (pod_spec.get(field) or [])
        if isinstance(item, Mapping)
    ]
    if not images or any(
        not isinstance(image, str) or not IMMUTABLE_IMAGE_PATTERN.fullmatch(image)
        for image in images
    ):
        errors.append("activation manifest images must use immutable sha256 digests")
    if set(images) != {expected_image}:
        errors.append("activation manifest images do not match the admitted release")

    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if manifest_report.get("manifest_sha256") != manifest_sha256:
        errors.append("activation manifest digest does not match its report")
    return errors, manifest_sha256, replicas if isinstance(replicas, int) else None


def build_activation_admission(
    *,
    run: Mapping[str, Any],
    artifact: Mapping[str, Any],
    activation: Mapping[str, Any],
    readiness: Mapping[str, Any],
    release: Mapping[str, Any],
    manifest_report: Mapping[str, Any],
    manifest_path: Path,
    expected_run_id: int | str,
    source_repository: str,
    expected_namespace: str,
    expected_cluster_uid: str,
    expected_namespace_uid: str,
) -> dict[str, Any]:
    """Build a fail-closed verdict for one exact single-replica apply."""
    errors: list[str] = []
    run_report = build_readiness_run_report(
        run,
        expected_run_id=expected_run_id,
        source_repository=source_repository,
    )
    errors.extend(f"run: {error}" for error in run_report["errors"])
    artifact_report = build_readiness_artifact_report(
        {"artifacts": [artifact]},
        run_report=run_report,
    )
    errors.extend(f"artifact: {error}" for error in artifact_report["errors"])
    errors.extend(
        f"release: {error}" for error in release_evidence_errors(release)
    )

    if readiness.get("schema") != READINESS_SCHEMA:
        errors.append("readiness evidence schema is unsupported")
    if readiness.get("status") != "ready_for_activation":
        errors.append("readiness status must be ready_for_activation")
    if readiness.get("activation_ready") is not True:
        errors.append("readiness activation_ready must be true")
    if readiness.get("deployed") is not False:
        errors.append("readiness must prove the worker is not deployed")
    if readiness.get("live_cluster_verified") is not True:
        errors.append("readiness must verify the protected staging cluster")
    if readiness.get("live_worker_verified") is not False:
        errors.append("readiness must not claim a live worker before activation")
    if readiness.get("errors") != []:
        errors.append("readiness evidence must not contain admission errors")
    live_errors = readiness.get("live_errors")
    if not isinstance(live_errors, list) or not live_errors or not set(
        live_errors
    ).issubset(READY_LIVE_ERRORS):
        errors.append("readiness live state is not an allowed inactive worker state")
    for field in (
        "automatic_scale_allowed",
        "promotion_authority_verified",
        "production_promotion_allowed",
    ):
        if readiness.get(field) is not False:
            errors.append(f"readiness {field} must remain false")
    if readiness.get("environment") != "staging":
        errors.append("readiness environment must be staging")
    if readiness.get("namespace") != expected_namespace:
        errors.append("readiness namespace does not match staging")
    for label, expected, observed in (
        (
            "cluster",
            expected_cluster_uid,
            readiness.get("cluster_uid"),
        ),
        (
            "namespace",
            expected_namespace_uid,
            readiness.get("namespace_uid"),
        ),
    ):
        if not isinstance(expected, str) or not RESOURCE_UID_PATTERN.fullmatch(
            expected
        ):
            errors.append(f"expected {label} UID is invalid")
        if observed != expected:
            errors.append(f"readiness {label} UID does not match protected staging")
    if readiness.get("evidence_fingerprint") != readiness_evidence_fingerprint(
        readiness
    ):
        errors.append("readiness evidence fingerprint does not match its content")
    if readiness.get("release_evidence_fingerprint") != release.get(
        "evidence_fingerprint"
    ):
        errors.append("readiness release fingerprint does not match the release")

    if activation.get("schema") != ACTIVATION_SCHEMA:
        errors.append("activation evidence schema is unsupported")
    if activation.get("status") != "ready_for_activation":
        errors.append("activation status must be ready_for_activation")
    if activation.get("activation_ready") is not True or activation.get(
        "errors"
    ) != []:
        errors.append("activation evidence must be ready without errors")
    for field in ("deployed", "live_cluster_verified", "production_promotion_allowed"):
        if activation.get(field) is not False:
            errors.append(f"activation {field} must remain false")
    if activation.get("environment") != "staging":
        errors.append("activation environment must be staging")
    if activation.get("namespace") != expected_namespace:
        errors.append("activation namespace does not match staging")
    if activation.get("requested_replicas") != 1:
        errors.append("activation evidence must request exactly one replica")
    if activation.get("image_digest") != release.get("image"):
        errors.append("activation image does not match the admitted release")
    if readiness.get("activation_config_fingerprint") != activation.get(
        "config_fingerprint"
    ):
        errors.append("readiness config fingerprint does not match activation")
    if readiness.get("secret_attestation_fingerprint") != activation.get(
        "secret_attestation_fingerprint"
    ):
        errors.append("readiness Secret attestation does not match activation")

    if manifest_report.get("schema") != MANIFEST_REPORT_SCHEMA:
        errors.append("activation manifest report schema is unsupported")
    if manifest_report.get("status") != "rendered" or manifest_report.get(
        "errors"
    ) != []:
        errors.append("activation manifest report must be rendered without errors")
    if manifest_report.get("namespace") != expected_namespace:
        errors.append("activation manifest report namespace does not match staging")
    if manifest_report.get("deployment_name") != DEPLOYMENT_NAME:
        errors.append("activation manifest report deployment name is invalid")
    if manifest_report.get("requested_replicas") != 1:
        errors.append("activation manifest report must request exactly one replica")
    if manifest_report.get("image") != release.get("image"):
        errors.append("activation manifest report image does not match the release")
    if manifest_report.get("release_evidence_fingerprint") != release.get(
        "evidence_fingerprint"
    ):
        errors.append("activation manifest report release fingerprint is invalid")
    for field in ("automatic_scale_allowed", "production_promotion_allowed"):
        if manifest_report.get(field) is not False:
            errors.append(f"activation manifest report {field} must remain false")

    manifest_errors, manifest_sha256, requested_replicas = _manifest_errors(
        manifest_path,
        expected_namespace=expected_namespace,
        expected_image=str(release.get("image") or ""),
        manifest_report=manifest_report,
    )
    errors.extend(manifest_errors)
    activation_manifest = _mapping(_mapping(activation.get("files")).get("manifest"))
    if activation_manifest.get("sha256") != manifest_sha256:
        errors.append("activation evidence manifest digest does not match the artifact")

    allowed = not errors
    stable = {
        "schema": ADMISSION_SCHEMA,
        "status": "authorized_for_single_replica_apply" if allowed else "blocked",
        "source_repository": source_repository,
        "readiness_run_id": run_report.get("run_id"),
        "readiness_revision": run_report.get("source_revision"),
        "readiness_artifact_id": artifact_report.get("artifact_id"),
        "readiness_artifact_digest": artifact_report.get("artifact_digest"),
        "environment": "staging",
        "namespace": expected_namespace,
        "cluster_uid": readiness.get("cluster_uid"),
        "namespace_uid": readiness.get("namespace_uid"),
        "release_evidence_fingerprint": release.get("evidence_fingerprint"),
        "readiness_evidence_fingerprint": readiness.get("evidence_fingerprint"),
        "activation_config_fingerprint": activation.get("config_fingerprint"),
        "secret_attestation_fingerprint": activation.get(
            "secret_attestation_fingerprint"
        ),
        "manifest_sha256": manifest_sha256,
        "image": release.get("image"),
        "requested_replicas": requested_replicas,
        "single_replica_apply_allowed": allowed,
        "deployed": False,
        "live_worker_verified": False,
        "automatic_scale_allowed": False,
        "promotion_authority_verified": False,
        "production_promotion_allowed": False,
        "errors": errors,
    }
    return {
        **stable,
        "evidence_fingerprint": _canonical_sha256(
            {field: stable.get(field) for field in ADMISSION_STABLE_FIELDS}
        ),
    }


def _selected_artifact(
    artifacts_payload: Mapping[str, Any], expected_name: Any
) -> Mapping[str, Any]:
    artifacts = artifacts_payload.get("artifacts")
    if not isinstance(artifacts, list):
        return {}
    matches = [
        value
        for value in artifacts
        if isinstance(value, Mapping) and value.get("name") == expected_name
    ]
    return matches[0] if len(matches) == 1 else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_run = subparsers.add_parser("validate-run")
    validate_run.add_argument("--run-metadata", type=Path, required=True)
    validate_run.add_argument("--expected-run-id", required=True)
    validate_run.add_argument("--source-repository", required=True)
    validate_run.add_argument("--output", type=Path)

    validate_artifact = subparsers.add_parser("validate-artifact")
    validate_artifact.add_argument("--artifacts-metadata", type=Path, required=True)
    validate_artifact.add_argument("--run-report", type=Path, required=True)
    validate_artifact.add_argument("--output", type=Path)

    admit = subparsers.add_parser("admit")
    admit.add_argument("--run-metadata", type=Path, required=True)
    admit.add_argument("--artifacts-metadata", type=Path, required=True)
    admit.add_argument("--activation-evidence", type=Path, required=True)
    admit.add_argument("--readiness-evidence", type=Path, required=True)
    admit.add_argument("--release-evidence", type=Path, required=True)
    admit.add_argument("--manifest-report", type=Path, required=True)
    admit.add_argument("--manifest", type=Path, required=True)
    admit.add_argument("--expected-run-id", required=True)
    admit.add_argument("--source-repository", required=True)
    admit.add_argument("--expected-namespace", required=True)
    admit.add_argument("--expected-cluster-uid", required=True)
    admit.add_argument("--expected-namespace-uid", required=True)
    admit.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.command == "validate-run":
            report = build_readiness_run_report(
                _load_json_object(args.run_metadata),
                expected_run_id=args.expected_run_id,
                source_repository=args.source_repository,
            )
        elif args.command == "validate-artifact":
            report = build_readiness_artifact_report(
                _load_json_object(args.artifacts_metadata),
                run_report=_load_json_object(args.run_report),
            )
        else:
            run = _load_json_object(args.run_metadata)
            artifacts = _load_json_object(args.artifacts_metadata)
            run_report = build_readiness_run_report(
                run,
                expected_run_id=args.expected_run_id,
                source_repository=args.source_repository,
            )
            report = build_activation_admission(
                run=run,
                artifact=_selected_artifact(
                    artifacts,
                    run_report.get("artifact_name"),
                ),
                activation=_load_json_object(args.activation_evidence),
                readiness=_load_json_object(args.readiness_evidence),
                release=_load_json_object(args.release_evidence),
                manifest_report=_load_json_object(args.manifest_report),
                manifest_path=args.manifest,
                expected_run_id=args.expected_run_id,
                source_repository=args.source_repository,
                expected_namespace=args.expected_namespace,
                expected_cluster_uid=args.expected_cluster_uid,
                expected_namespace_uid=args.expected_namespace_uid,
            )
    except DolphinSchedulerWorkerActivationAdmissionError as exc:
        report = {
            "schema": ADMISSION_SCHEMA,
            "status": "blocked",
            "single_replica_apply_allowed": False,
            "deployed": False,
            "automatic_scale_allowed": False,
            "promotion_authority_verified": False,
            "production_promotion_allowed": False,
            "errors": [str(exc)],
        }
    _write_json(report, args.output)
    return 0 if report["status"] in {
        "valid",
        "authorized_for_single_replica_apply",
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())
