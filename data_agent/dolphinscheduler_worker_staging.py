"""Render and verify protected staging evidence for the managed worker.

This module never applies or scales Kubernetes resources. It renders a
release-bound activation candidate and projects only allowlisted live fields
from externally collected snapshots.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .dolphinscheduler_worker_activation import (
    ACTIVATION_SCHEMA,
    IMMUTABLE_IMAGE_PATTERN,
    NAMESPACE_PATTERN,
    RESOURCE_UID_PATTERN,
)
from .dolphinscheduler_worker_deployment import (
    CONFIG_NAME,
    DEFAULT_MANIFEST,
    DEFAULT_NETWORK_POLICY,
    DEPLOYMENT_NAME,
    REQUIRED_CONFIG_ENV,
    SECRET_NAME,
)
from .staging_release_evidence import (
    RELEASE_EVIDENCE_SCHEMA,
    release_evidence_fingerprint,
)

MANIFEST_REPORT_SCHEMA = "gda.dolphinscheduler_worker_staging_manifest.v1"
READINESS_SCHEMA = "gda.dolphinscheduler_worker_staging_readiness.v1"
READINESS_STABLE_FIELDS = (
    "schema",
    "status",
    "environment",
    "namespace",
    "cluster_uid",
    "namespace_uid",
    "release_evidence_fingerprint",
    "activation_config_fingerprint",
    "secret_attestation_fingerprint",
    "activation_ready",
    "deployed",
    "live_cluster_verified",
    "live_worker_verified",
    "observation",
    "errors",
    "live_errors",
)
DEFAULT_STAGING_NAMESPACE = "gis-agent-staging"
RELEASE_FINGERPRINT_ANNOTATION = "gisdataagent.io/release-evidence-fingerprint"
SOURCE_REVISION_ANNOTATION = "org.opencontainers.image.revision"
ENVIRONMENT_ANNOTATION = "gisdataagent.io/environment"
DNS_LABEL_PATTERN = NAMESPACE_PATTERN
IMAGE_DIGEST_PATTERN = re.compile(r"sha256:([0-9a-f]{64})")
SOURCE_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class DolphinSchedulerWorkerStagingError(RuntimeError):
    """Staging worker evidence could not be parsed or rendered safely."""


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
        raise DolphinSchedulerWorkerStagingError(
            "JSON evidence is unavailable or invalid"
        ) from exc
    if not isinstance(value, dict):
        raise DolphinSchedulerWorkerStagingError("JSON evidence must be an object")
    return value


def _load_yaml_documents(path: Path) -> list[dict[str, Any]]:
    try:
        values = yaml.safe_load_all(path.read_text(encoding="utf-8"))
        documents = [value for value in values if isinstance(value, dict)]
    except (OSError, yaml.YAMLError) as exc:
        raise DolphinSchedulerWorkerStagingError(
            "Kubernetes source manifest is unavailable or invalid"
        ) from exc
    if not documents:
        raise DolphinSchedulerWorkerStagingError(
            "Kubernetes source manifest has no resources"
        )
    return documents


def _resource(
    documents: list[dict[str, Any]], kind: str, name: str
) -> dict[str, Any] | None:
    return next(
        (
            document
            for document in documents
            if document.get("kind") == kind
            and (document.get("metadata") or {}).get("name") == name
        ),
        None,
    )


def _named(items: Any, name: str) -> dict[str, Any]:
    if not isinstance(items, list):
        return {}
    return next(
        (
            item
            for item in items
            if isinstance(item, dict) and item.get("name") == name
        ),
        {},
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _items(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _image_digest(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = IMAGE_DIGEST_PATTERN.search(value)
    return f"sha256:{match.group(1)}" if match else None


def release_evidence_errors(release: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if release.get("schema") != RELEASE_EVIDENCE_SCHEMA:
        errors.append("release evidence schema is unsupported")
    if release.get("status") != "staging_release_admitted":
        errors.append("release must be admitted for staging")
    for field in (
        "staging_apply_allowed",
        "registry_digest_verified",
        "provenance_attestation_verified",
    ):
        if release.get(field) is not True:
            errors.append(f"release {field} must be true")
    if release.get("errors") != []:
        errors.append("release evidence must not contain errors")
    if release.get("production_promotion_allowed") is not False:
        errors.append("release must not grant production promotion")
    for field in ("source_revision", "verifier_revision"):
        value = release.get(field)
        if not isinstance(value, str) or not SOURCE_REVISION_PATTERN.fullmatch(value):
            errors.append(f"release {field} must be a full lowercase Git SHA-1")
    image = release.get("image")
    if not isinstance(image, str) or not IMMUTABLE_IMAGE_PATTERN.fullmatch(image):
        errors.append("release image must use an immutable sha256 digest")
    if _image_digest(image) != release.get("digest"):
        errors.append("release image and digest do not match")
    if release.get("evidence_fingerprint") != release_evidence_fingerprint(release):
        errors.append("release evidence fingerprint does not match its content")
    return errors


def readiness_evidence_fingerprint(value: Mapping[str, Any]) -> str:
    """Return the canonical fingerprint of stable readiness fields."""
    stable = {field: value.get(field) for field in READINESS_STABLE_FIELDS}
    return _canonical_sha256(stable)


def render_activation_manifest(
    release: Mapping[str, Any],
    *,
    namespace: str,
    image_pull_secret_name: str,
    manifest_path: Path = DEFAULT_MANIFEST,
    network_policy_path: Path = DEFAULT_NETWORK_POLICY,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Render a Secret-free, single-replica candidate without applying it."""
    errors = release_evidence_errors(release)
    if not isinstance(namespace, str) or not NAMESPACE_PATTERN.fullmatch(namespace):
        errors.append("staging namespace must be a valid Kubernetes DNS label")
    if not isinstance(
        image_pull_secret_name, str
    ) or not DNS_LABEL_PATTERN.fullmatch(image_pull_secret_name):
        errors.append("image pull Secret name must be a Kubernetes DNS label")
    if errors:
        raise DolphinSchedulerWorkerStagingError("; ".join(errors))

    worker_documents = _load_yaml_documents(manifest_path)
    network_documents = _load_yaml_documents(network_policy_path)
    deployment = _resource(worker_documents, "Deployment", DEPLOYMENT_NAME)
    service_account = _resource(worker_documents, "ServiceAccount", DEPLOYMENT_NAME)
    postgres_policy = _resource(network_documents, "NetworkPolicy", "postgres-access")
    if deployment is None or service_account is None or postgres_policy is None:
        raise DolphinSchedulerWorkerStagingError(
            "worker Deployment, ServiceAccount, and PostgreSQL NetworkPolicy are required"
        )

    documents = copy.deepcopy([deployment, service_account, postgres_policy])
    rendered_deployment = documents[0]
    release_fingerprint = str(release["evidence_fingerprint"])
    annotations = {
        SOURCE_REVISION_ANNOTATION: str(release["source_revision"]),
        RELEASE_FINGERPRINT_ANNOTATION: release_fingerprint,
        ENVIRONMENT_ANNOTATION: "staging",
    }
    for resource in documents:
        metadata = resource.setdefault("metadata", {})
        metadata["namespace"] = namespace
        metadata.setdefault("annotations", {}).update(annotations)

    deployment_spec = rendered_deployment.setdefault("spec", {})
    deployment_spec["replicas"] = 1
    template = deployment_spec.setdefault("template", {})
    template.setdefault("metadata", {}).setdefault("annotations", {}).update(
        annotations
    )
    pod = template.setdefault("spec", {})
    pod["imagePullSecrets"] = [{"name": image_pull_secret_name}]
    image = str(release["image"])
    for container in [
        *_items(pod.get("containers")),
        *_items(pod.get("initContainers")),
    ]:
        container["image"] = image
        container["imagePullPolicy"] = "Always"

    report = {
        "schema": MANIFEST_REPORT_SCHEMA,
        "status": "rendered",
        "environment": "staging",
        "namespace": namespace,
        "deployment_name": DEPLOYMENT_NAME,
        "requested_replicas": 1,
        "image": image,
        "image_pull_secret_name": image_pull_secret_name,
        "release_evidence_fingerprint": release_fingerprint,
        "automatic_scale_allowed": False,
        "production_promotion_allowed": False,
        "errors": [],
    }
    return documents, report


def _deployment_observation(
    deployment: Mapping[str, Any],
    pods: Mapping[str, Any],
    health: Mapping[str, Any],
    *,
    expected_namespace: str,
    expected_image: str,
) -> tuple[dict[str, Any], list[str], bool, bool]:
    if not deployment:
        return {}, ["worker Deployment is not present"], False, False

    errors: list[str] = []
    metadata = _mapping(deployment.get("metadata"))
    spec = _mapping(deployment.get("spec"))
    status = _mapping(deployment.get("status"))
    pod_template = _mapping(spec.get("template"))
    pod_spec = _mapping(pod_template.get("spec"))
    worker = _named(pod_spec.get("containers"), "worker")
    token_init = _named(pod_spec.get("initContainers"), "prepare-provider-token")
    replicas = spec.get("replicas")
    deployment_uid = metadata.get("uid")

    if metadata.get("name") != DEPLOYMENT_NAME:
        errors.append("live worker Deployment name is invalid")
    if metadata.get("namespace") != expected_namespace:
        errors.append("live worker Deployment namespace does not match staging")
    if not isinstance(deployment_uid, str) or not RESOURCE_UID_PATTERN.fullmatch(
        deployment_uid
    ):
        errors.append("live worker Deployment UID is invalid")
    if replicas not in (0, 1) or isinstance(replicas, bool):
        errors.append("live worker Deployment must have zero or one replica")
    selector = _mapping(spec.get("selector"))
    selector_labels = _mapping(selector.get("matchLabels"))
    if selector_labels.get("app.kubernetes.io/name") != DEPLOYMENT_NAME:
        errors.append("live worker Deployment selector is invalid")
    if pod_spec.get("serviceAccountName") != DEPLOYMENT_NAME:
        errors.append("live worker must use its dedicated ServiceAccount")
    if pod_spec.get("automountServiceAccountToken") is not False:
        errors.append("live worker must disable Kubernetes API token mounting")
    for container_name, container in (
        ("worker", worker),
        ("prepare-provider-token", token_init),
    ):
        if container.get("image") != expected_image:
            errors.append(
                f"live {container_name} image does not match the attested release"
            )

    deployed = replicas == 1 and not isinstance(replicas, bool)
    if not deployed:
        if replicas == 0:
            errors.append("worker Deployment remains intentionally scaled to zero")
        return {
            "deployment_uid": deployment_uid,
            "requested_replicas": replicas,
            "worker_image": worker.get("image"),
            "token_init_image": token_init.get("image"),
            "pod_uids": [],
            "worker_ids": [],
            "health_status": None,
        }, errors, False, False

    if metadata.get("generation") != status.get("observedGeneration"):
        errors.append("worker Deployment generation has not been observed")
    for field in ("replicas", "updatedReplicas", "readyReplicas", "availableReplicas"):
        if status.get(field) != 1:
            errors.append(f"worker Deployment status {field} has not converged")
    if status.get("unavailableReplicas") not in (None, 0):
        errors.append("worker Deployment still has unavailable replicas")

    pod_items = _items(pods.get("items"))
    if len(pod_items) != 1:
        errors.append("worker Deployment must select exactly one Pod")
    pod_uids: list[str] = []
    restart_counts: list[int] = []
    expected_digest = _image_digest(expected_image)
    for pod in pod_items:
        pod_metadata = _mapping(pod.get("metadata"))
        live_spec = _mapping(pod.get("spec"))
        live_status = _mapping(pod.get("status"))
        live_worker = _named(live_spec.get("containers"), "worker")
        container_status = _named(live_status.get("containerStatuses"), "worker")
        pod_uid = pod_metadata.get("uid")
        if not isinstance(pod_uid, str) or not RESOURCE_UID_PATTERN.fullmatch(pod_uid):
            errors.append("worker Pod UID is invalid")
        else:
            pod_uids.append(pod_uid)
        if pod_metadata.get("deletionTimestamp") is not None:
            errors.append("worker Pod is terminating")
        if live_status.get("phase") != "Running" or container_status.get("ready") is not True:
            errors.append("worker Pod is not Running and ready")
        if live_worker.get("image") != expected_image:
            errors.append("worker Pod image does not match the attested release")
        if _image_digest(container_status.get("imageID")) != expected_digest:
            errors.append("worker Pod runtime image ID has not converged")
        restart_count = container_status.get("restartCount")
        if not isinstance(restart_count, int) or isinstance(restart_count, bool):
            errors.append("worker Pod restart count is invalid")
        else:
            restart_counts.append(restart_count)
            if restart_count != 0:
                errors.append("worker Pod must have zero restarts for first activation")

    expected_worker_ids = [f"worker:dolphinscheduler:{uid}" for uid in pod_uids]
    for pod in pod_items:
        labels = _mapping(_mapping(pod.get("metadata")).get("labels"))
        if labels.get("app.kubernetes.io/name") != DEPLOYMENT_NAME:
            errors.append("worker Pod selector label does not match the Deployment")

    environment = {
        str(item.get("name")): item
        for item in _items(worker.get("env"))
        if isinstance(item.get("name"), str)
    }
    for env_name, config_key in REQUIRED_CONFIG_ENV.items():
        reference = _mapping(
            _mapping(environment.get(env_name)).get("valueFrom")
        ).get("configMapKeyRef")
        if _mapping(reference) != {"name": CONFIG_NAME, "key": config_key}:
            errors.append(f"live worker {env_name} must use the dedicated ConfigMap")
    database_reference = _mapping(
        _mapping(environment.get("DATABASE_URL")).get("valueFrom")
    ).get("secretKeyRef")
    if _mapping(database_reference) != {
        "name": SECRET_NAME,
        "key": "database-url",
    }:
        errors.append("live worker DATABASE_URL must use the dedicated Secret")
    if health.get("status") != "healthy":
        errors.append("worker readiness health is not healthy")
    if len(expected_worker_ids) == 1 and health.get("worker_id") != expected_worker_ids[0]:
        errors.append("worker health identity does not match the Pod UID")

    observation = {
        "deployment_uid": deployment_uid,
        "generation": metadata.get("generation"),
        "observed_generation": status.get("observedGeneration"),
        "requested_replicas": replicas,
        "status_replicas": status.get("replicas"),
        "updated_replicas": status.get("updatedReplicas"),
        "ready_replicas": status.get("readyReplicas"),
        "available_replicas": status.get("availableReplicas"),
        "worker_image": worker.get("image"),
        "token_init_image": token_init.get("image"),
        "pod_uids": sorted(pod_uids),
        "worker_ids": sorted(expected_worker_ids),
        "restart_counts": restart_counts,
        "health_status": health.get("status"),
        "health_cycles": health.get("cycles"),
        "failed_commands": health.get("failed_commands"),
    }
    return observation, errors, True, not errors


def build_readiness_report(
    activation: Mapping[str, Any],
    release: Mapping[str, Any],
    deployment: Mapping[str, Any],
    pods: Mapping[str, Any],
    health: Mapping[str, Any],
    *,
    expected_namespace: str,
    expected_cluster_uid: str,
    expected_namespace_uid: str,
    observed_cluster_uid: str,
    observed_namespace_uid: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Bind activation evidence to an allowlisted, read-only live observation."""
    errors = release_evidence_errors(release)
    if activation.get("schema") != ACTIVATION_SCHEMA:
        errors.append("activation evidence schema is unsupported")
    if activation.get("status") != "ready_for_activation":
        errors.append("worker activation preflight is blocked")
    if activation.get("activation_ready") is not True or activation.get("errors") != []:
        errors.append("worker activation evidence is not ready")
    if activation.get("environment") != "staging":
        errors.append("worker activation environment must be staging")
    if activation.get("namespace") != expected_namespace:
        errors.append("worker activation namespace does not match staging")
    if activation.get("requested_replicas") != 1:
        errors.append("worker activation must request exactly one replica")
    if activation.get("image_digest") != release.get("image"):
        errors.append("worker activation image does not match the attested release")
    if activation.get("production_promotion_allowed") is not False:
        errors.append("worker activation must not grant production promotion")
    for field in (
        "config_resource_uid",
        "config_resource_version",
        "config_fingerprint",
        "secret_resource_uid",
        "secret_resource_version",
        "secret_attestation_fingerprint",
    ):
        if not activation.get(field):
            errors.append(f"worker activation {field} is missing")

    for label, value in (
        ("expected cluster UID", expected_cluster_uid),
        ("expected namespace UID", expected_namespace_uid),
        ("observed cluster UID", observed_cluster_uid),
        ("observed namespace UID", observed_namespace_uid),
    ):
        if not isinstance(value, str) or not RESOURCE_UID_PATTERN.fullmatch(value):
            errors.append(f"{label} is invalid")
    if observed_cluster_uid != expected_cluster_uid:
        errors.append("observed cluster UID does not match protected staging")
    if observed_namespace_uid != expected_namespace_uid:
        errors.append("observed namespace UID does not match protected staging")

    observation, live_errors, deployed, live_verified = _deployment_observation(
        deployment,
        pods,
        health,
        expected_namespace=expected_namespace,
        expected_image=str(release.get("image") or ""),
    )
    unsafe_live_state = bool(deployment) and any(
        "image does not match" in error or "zero or one replica" in error
        for error in live_errors
    )
    activation_ready = not errors and not unsafe_live_state
    if not activation_ready:
        status = "blocked"
    elif live_verified:
        status = "live_ready"
    elif deployed:
        status = "waiting_for_readiness"
    else:
        status = "ready_for_activation"

    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        errors.append("readiness observation time must be timezone-aware")
        status = "blocked"
        activation_ready = False
        live_verified = False
    stable = {
        "schema": READINESS_SCHEMA,
        "status": status,
        "environment": "staging",
        "namespace": expected_namespace,
        "cluster_uid": observed_cluster_uid,
        "namespace_uid": observed_namespace_uid,
        "release_evidence_fingerprint": release.get("evidence_fingerprint"),
        "activation_config_fingerprint": activation.get("config_fingerprint"),
        "secret_attestation_fingerprint": activation.get(
            "secret_attestation_fingerprint"
        ),
        "activation_ready": activation_ready,
        "deployed": deployed,
        "live_cluster_verified": not errors,
        "live_worker_verified": live_verified and not errors,
        "observation": observation,
        "errors": errors,
        "live_errors": live_errors,
    }
    return {
        **stable,
        "observed_at": current.isoformat(),
        "automatic_scale_allowed": False,
        "promotion_authority_verified": False,
        "production_promotion_allowed": False,
        "evidence_fingerprint": readiness_evidence_fingerprint(stable),
    }


def _write_json(report: Mapping[str, Any], output: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    render = subparsers.add_parser("render")
    render.add_argument("--release-evidence", type=Path, required=True)
    render.add_argument("--namespace", default=DEFAULT_STAGING_NAMESPACE)
    render.add_argument("--image-pull-secret-name", required=True)
    render.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    render.add_argument("--network-policy", type=Path, default=DEFAULT_NETWORK_POLICY)
    render.add_argument("--output", type=Path, required=True)
    render.add_argument("--report-output", type=Path)

    validate = subparsers.add_parser("validate-readiness")
    validate.add_argument("--activation-evidence", type=Path, required=True)
    validate.add_argument("--release-evidence", type=Path, required=True)
    validate.add_argument("--deployment-snapshot", type=Path, required=True)
    validate.add_argument("--pods-snapshot", type=Path, required=True)
    validate.add_argument("--health-snapshot", type=Path, required=True)
    validate.add_argument("--expected-namespace", default=DEFAULT_STAGING_NAMESPACE)
    validate.add_argument("--expected-cluster-uid", required=True)
    validate.add_argument("--expected-namespace-uid", required=True)
    validate.add_argument("--observed-cluster-uid", required=True)
    validate.add_argument("--observed-namespace-uid", required=True)
    validate.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.command == "render":
            documents, report = render_activation_manifest(
                _load_json_object(args.release_evidence),
                namespace=args.namespace,
                image_pull_secret_name=args.image_pull_secret_name,
                manifest_path=args.manifest,
                network_policy_path=args.network_policy,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                yaml.safe_dump_all(documents, sort_keys=False),
                encoding="utf-8",
            )
            report = {
                **report,
                "manifest_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
            }
            _write_json(report, args.report_output)
            return 0

        report = build_readiness_report(
            _load_json_object(args.activation_evidence),
            _load_json_object(args.release_evidence),
            _load_json_object(args.deployment_snapshot),
            _load_json_object(args.pods_snapshot),
            _load_json_object(args.health_snapshot),
            expected_namespace=args.expected_namespace,
            expected_cluster_uid=args.expected_cluster_uid,
            expected_namespace_uid=args.expected_namespace_uid,
            observed_cluster_uid=args.observed_cluster_uid,
            observed_namespace_uid=args.observed_namespace_uid,
        )
    except DolphinSchedulerWorkerStagingError as exc:
        report = {
            "schema": (
                MANIFEST_REPORT_SCHEMA
                if args.command == "render"
                else READINESS_SCHEMA
            ),
            "status": "blocked",
            "activation_ready": False,
            "deployed": False,
            "live_cluster_verified": False,
            "live_worker_verified": False,
            "automatic_scale_allowed": False,
            "promotion_authority_verified": False,
            "production_promotion_allowed": False,
            "errors": [str(exc)],
        }
        _write_json(
            report,
            args.report_output if args.command == "render" else args.output,
        )
        return 2

    _write_json(report, args.output)
    return 0 if report["status"] in {"ready_for_activation", "live_ready"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
