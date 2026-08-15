"""Collect and validate fail-closed live staging observations.

The collector reads Kubernetes and application state through ``kubectl`` and
projects only allowlisted, non-secret fields. The verifier can prove that a
live staging observation is internally consistent, but v1 deliberately cannot
authorize production: protected-runner provenance and artifact attestation are
still required.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .staging_candidate_evidence import CANDIDATE_SCHEMA
from .staging_release_evidence import (
    RELEASE_EVIDENCE_SCHEMA,
    release_evidence_fingerprint,
)

COLLECTION_SCHEMA = "gda.staging_live_collection.v1"
LIVE_EVIDENCE_SCHEMA = "gda.staging_live_evidence.v1"
GOLDEN_SLICE_SCHEMA = "gda.staging_live_golden_slice.v1"
ROLLOUT_CONVERGENCE_SCHEMA = "gda.staging_rollout_convergence.v1"
PLATFORM_TRUTH_SCHEMA = "gda.platform_truth.v1"
NAMESPACE = "gis-agent-staging"
DEVELOPMENT_NAMESPACE = "gis-agent"
DEPLOYMENT_NAME = "gis-agent-app"
APP_CONTAINER = "app"
SOURCE_REVISION_ANNOTATION = "org.opencontainers.image.revision"
CANDIDATE_FINGERPRINT_ANNOTATION = (
    "gisdataagent.io/candidate-evidence-fingerprint"
)
ENVIRONMENT_ANNOTATION = "gisdataagent.io/environment"
PLATFORM_FINGERPRINT_ANNOTATION = "gisdataagent.io/platform-fingerprint"
RELEASE_FINGERPRINT_ANNOTATION = "gisdataagent.io/release-evidence-fingerprint"
SCHEMA_FINGERPRINT_ANNOTATION = "gisdataagent.io/schema-fingerprint"
ENVIRONMENT_ACCESS_FINGERPRINT_ANNOTATION = (
    "gisdataagent.io/environment-access-fingerprint"
)
RUNTIME_FINGERPRINT_ANNOTATION = "gisdataagent.io/runtime-fingerprint"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SOURCE_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
LOCAL_IMAGE_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
UID_PATTERN = re.compile(
    r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$"
)
DNS_LABEL_PATTERN = re.compile(
    r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$"
)
IMMUTABLE_IMAGE_PATTERN = re.compile(
    r"^(?:[a-z0-9]+(?:[.-][a-z0-9]+)*(?::[0-9]+)?/)?"
    r"[a-z0-9]+(?:[._-][a-z0-9]+)*"
    r"(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*"
    r"@sha256:[0-9a-f]{64}$"
)
IMAGE_DIGEST_PATTERN = re.compile(r"sha256:([0-9a-f]{64})")
CANDIDATE_STABLE_FIELDS = (
    "schema",
    "source_revision",
    "image_id",
    "schema_fingerprint",
    "platform_fingerprint",
    "config_fingerprint",
    "environment_access_fingerprint",
    "runtime_fingerprint",
    "tests",
    "candidate_validated",
    "errors",
)
COLLECTION_FIELDS = {
    "schema",
    "observed_at",
    "kubernetes",
    "schema_report",
    "platform_snapshot",
    "health",
}
GOLDEN_SLICE_FIELDS = {
    "schema",
    "environment",
    "status",
    "source_revision",
    "deployment_uid",
    "image_digest",
    "schema_fingerprint",
    "config_fingerprint",
    "environment_access_fingerprint",
    "runtime_fingerprint",
    "tenant_id",
    "capability_id",
    "definition_version_id",
    "definition_sha256",
    "input_resource_version_id",
    "output_resource_version_id",
    "run_id",
    "output_artifact_sha256",
    "quality_result_id",
    "quality_evidence_fingerprint",
    "lineage_event_id",
    "run_success_evidence_fingerprint",
    "observed_at",
    "evidence_fingerprint",
}
REQUIRED_PROMOTION_PROVENANCE = (
    "protected staging runner identity",
    "attested evidence artifact bound to this observation fingerprint",
    "production environment approval bound to the same source revision",
)

CommandRunner = Callable[[list[str]], str]


class StagingLiveEvidenceError(RuntimeError):
    """Live staging evidence could not be collected or parsed safely."""


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
        raise StagingLiveEvidenceError("JSON evidence must be an object")
    return payload


def _parse_json_output(raw: str, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StagingLiveEvidenceError(
            f"{label} did not return a JSON object"
        ) from exc
    if not isinstance(payload, dict):
        raise StagingLiveEvidenceError(f"{label} must return a JSON object")
    return payload


def _run_command(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            check=False,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise StagingLiveEvidenceError(
            f"command unavailable: {args[0]}"
        ) from exc
    if completed.returncode != 0:
        operation = " ".join(args[1:])
        raise StagingLiveEvidenceError(
            f"command failed without usable evidence: {args[0]} {operation}"
        )
    return completed.stdout


def _kubectl_json(
    kubectl: str,
    arguments: list[str],
    *,
    label: str,
    run: CommandRunner,
) -> dict[str, Any]:
    return _parse_json_output(run([kubectl, *arguments]), label)


def _metadata(resource: Mapping[str, Any]) -> Mapping[str, Any]:
    value = resource.get("metadata")
    return value if isinstance(value, Mapping) else {}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _items(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _named(items: Any, name: str) -> Mapping[str, Any]:
    for item in _items(items):
        if item.get("name") == name:
            return item
    return {}


def _condition_true(conditions: Any, condition_type: str) -> bool:
    for condition in _items(conditions):
        if condition.get("type") == condition_type:
            return condition.get("status") in (True, "True")
    return False


def _project_schema_report(report: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "format_version",
        "generated_at",
        "status",
        "ledger_present",
        "catalog_fingerprint",
        "database_fingerprint",
        "catalog_count",
        "applied_count",
        "pending",
        "unknown_applied",
        "missing_checksums",
        "checksum_mismatches",
        "metadata_mismatches",
    )
    return {field: report.get(field) for field in fields}


def _project_platform_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    config = _mapping(snapshot.get("config"))
    environment_access = _mapping(snapshot.get("environment_access"))
    runtime = _mapping(snapshot.get("runtime"))
    return {
        "schema": snapshot.get("schema"),
        "generated_at": snapshot.get("generated_at"),
        "platform_fingerprint": snapshot.get("platform_fingerprint"),
        "config": {
            field: config.get(field)
            for field in (
                "schema",
                "generated_at",
                "profile",
                "strict",
                "valid",
                "startup_allowed",
                "config_fingerprint",
            )
        },
        "environment_access": {
            field: environment_access.get(field)
            for field in (
                "fingerprint",
                "matches_baseline",
                "parse_errors",
            )
        },
        "runtime": {
            field: runtime.get(field)
            for field in (
                "schema",
                "status",
                "matches_primitive_baseline",
                "inventory_fingerprint",
            )
        },
    }


def _project_health(payload: Mapping[str, Any]) -> dict[str, Any]:
    checks = _mapping(payload.get("checks"))
    return {
        "status": payload.get("status"),
        "checks": {
            name: {"status": _mapping(value).get("status")}
            for name, value in sorted(checks.items())
        },
    }


def _project_kubernetes(
    *,
    kube_system: Mapping[str, Any],
    namespace: Mapping[str, Any],
    deployment: Mapping[str, Any],
    pods: Mapping[str, Any],
    service_account: Mapping[str, Any],
    endpoint_slices: Mapping[str, Any],
) -> dict[str, Any]:
    deployment_metadata = _metadata(deployment)
    deployment_spec = _mapping(deployment.get("spec"))
    deployment_status = _mapping(deployment.get("status"))
    pod_template = _mapping(deployment_spec.get("template"))
    pod_template_metadata = _metadata(pod_template)
    pod_spec = _mapping(pod_template.get("spec"))
    annotations = _mapping(pod_template_metadata.get("annotations"))
    app = _named(pod_spec.get("containers"), APP_CONTAINER)

    pod_reports: list[dict[str, Any]] = []
    for pod in _items(pods.get("items")):
        metadata = _metadata(pod)
        spec = _mapping(pod.get("spec"))
        status = _mapping(pod.get("status"))
        container = _named(spec.get("containers"), APP_CONTAINER)
        container_status = _named(status.get("containerStatuses"), APP_CONTAINER)
        pod_reports.append(
            {
                "name": metadata.get("name"),
                "uid": metadata.get("uid"),
                "created_at": metadata.get("creationTimestamp"),
                "phase": status.get("phase"),
                "service_account_name": spec.get("serviceAccountName"),
                "image": container.get("image"),
                "image_id": container_status.get("imageID"),
                "ready": container_status.get("ready"),
                "restart_count": container_status.get("restartCount"),
            }
        )

    endpoint_uids: set[str] = set()
    for endpoint_slice in _items(endpoint_slices.get("items")):
        for endpoint in _items(endpoint_slice.get("endpoints")):
            conditions = _mapping(endpoint.get("conditions"))
            target = _mapping(endpoint.get("targetRef"))
            if (
                conditions.get("ready") is True
                and target.get("kind") == "Pod"
                and isinstance(target.get("uid"), str)
            ):
                endpoint_uids.add(target["uid"])

    return {
        "cluster_uid": _metadata(kube_system).get("uid"),
        "namespace": {
            "name": _metadata(namespace).get("name"),
            "uid": _metadata(namespace).get("uid"),
            "resource_version": _metadata(namespace).get("resourceVersion"),
        },
        "deployment": {
            "name": deployment_metadata.get("name"),
            "uid": deployment_metadata.get("uid"),
            "resource_version": deployment_metadata.get("resourceVersion"),
            "generation": deployment_metadata.get("generation"),
            "observed_generation": deployment_status.get("observedGeneration"),
            "replicas": deployment_spec.get("replicas"),
            "status_replicas": deployment_status.get("replicas"),
            "updated_replicas": deployment_status.get("updatedReplicas"),
            "ready_replicas": deployment_status.get("readyReplicas"),
            "available_replicas": deployment_status.get("availableReplicas"),
            "available": _condition_true(
                deployment_status.get("conditions"), "Available"
            ),
            "progressing": _condition_true(
                deployment_status.get("conditions"), "Progressing"
            ),
            "source_revision": annotations.get(SOURCE_REVISION_ANNOTATION),
            "candidate_evidence_fingerprint": annotations.get(
                CANDIDATE_FINGERPRINT_ANNOTATION
            ),
            "environment": annotations.get(ENVIRONMENT_ANNOTATION),
            "platform_fingerprint": annotations.get(
                PLATFORM_FINGERPRINT_ANNOTATION
            ),
            "release_evidence_fingerprint": annotations.get(
                RELEASE_FINGERPRINT_ANNOTATION
            ),
            "schema_fingerprint": annotations.get(
                SCHEMA_FINGERPRINT_ANNOTATION
            ),
            "environment_access_fingerprint": annotations.get(
                ENVIRONMENT_ACCESS_FINGERPRINT_ANNOTATION
            ),
            "runtime_fingerprint": annotations.get(
                RUNTIME_FINGERPRINT_ANNOTATION
            ),
            "image": app.get("image"),
            "service_account_name": pod_spec.get("serviceAccountName"),
            "automount_service_account_token": pod_spec.get(
                "automountServiceAccountToken"
            ),
        },
        "service_account": {
            "name": _metadata(service_account).get("name"),
            "uid": _metadata(service_account).get("uid"),
            "resource_version": _metadata(service_account).get("resourceVersion"),
        },
        "pods": sorted(pod_reports, key=lambda item: str(item.get("name"))),
        "ready_endpoint_pod_uids": sorted(endpoint_uids),
    }


def collect_live_staging(
    *,
    namespace: str = NAMESPACE,
    deployment_name: str = DEPLOYMENT_NAME,
    service_name: str = DEPLOYMENT_NAME,
    kubectl: str = "kubectl",
    now: datetime | None = None,
    run: CommandRunner = _run_command,
) -> dict[str, Any]:
    """Collect an allowlisted observation without reading Kubernetes Secrets."""
    for label, value in (
        ("namespace", namespace),
        ("deployment", deployment_name),
        ("service", service_name),
    ):
        if not DNS_LABEL_PATTERN.fullmatch(value):
            raise StagingLiveEvidenceError(f"invalid Kubernetes {label} name")

    kube_system = _kubectl_json(
        kubectl,
        ["get", "namespace", "kube-system", "-o", "json"],
        label="kube-system namespace",
        run=run,
    )
    namespace_resource = _kubectl_json(
        kubectl,
        ["get", "namespace", namespace, "-o", "json"],
        label="staging namespace",
        run=run,
    )
    deployment = _kubectl_json(
        kubectl,
        ["-n", namespace, "get", "deployment", deployment_name, "-o", "json"],
        label="application Deployment",
        run=run,
    )
    deployment_spec = _mapping(deployment.get("spec"))
    pod_spec = _mapping(_mapping(deployment_spec.get("template")).get("spec"))
    service_account_name = pod_spec.get("serviceAccountName")
    if not isinstance(service_account_name, str) or not DNS_LABEL_PATTERN.fullmatch(
        service_account_name
    ):
        raise StagingLiveEvidenceError(
            "application Deployment has no valid service account"
        )
    pods = _kubectl_json(
        kubectl,
        [
            "-n",
            namespace,
            "get",
            "pods",
            "-l",
            f"app.kubernetes.io/name={deployment_name}",
            "-o",
            "json",
        ],
        label="application Pods",
        run=run,
    )
    service_account = _kubectl_json(
        kubectl,
        [
            "-n",
            namespace,
            "get",
            "serviceaccount",
            service_account_name,
            "-o",
            "json",
        ],
        label="application ServiceAccount",
        run=run,
    )
    endpoint_slices = _kubectl_json(
        kubectl,
        [
            "-n",
            namespace,
            "get",
            "endpointslices",
            "-l",
            f"kubernetes.io/service-name={service_name}",
            "-o",
            "json",
        ],
        label="application EndpointSlices",
        run=run,
    )
    schema = _kubectl_json(
        kubectl,
        [
            "-n",
            namespace,
            "exec",
            f"deployment/{deployment_name}",
            "-c",
            APP_CONTAINER,
            "--",
            "python",
            "-m",
            "data_agent.migration_runner",
            "status",
        ],
        label="live schema report",
        run=run,
    )
    platform = _kubectl_json(
        kubectl,
        [
            "-n",
            namespace,
            "exec",
            f"deployment/{deployment_name}",
            "-c",
            APP_CONTAINER,
            "--",
            "python",
            "-m",
            "data_agent.platform_truth",
            "snapshot",
        ],
        label="live platform snapshot",
        run=run,
    )
    proxy_prefix = (
        f"/api/v1/namespaces/{namespace}/services/"
        f"http:{service_name}:80/proxy"
    )
    health = _parse_json_output(
        run([kubectl, "get", "--raw", f"{proxy_prefix}/health"]),
        "live health endpoint",
    )
    readiness = _parse_json_output(
        run([kubectl, "get", "--raw", f"{proxy_prefix}/ready"]),
        "live readiness endpoint",
    )
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise StagingLiveEvidenceError("collection time must be timezone-aware")
    return {
        "schema": COLLECTION_SCHEMA,
        "observed_at": current.isoformat(),
        "kubernetes": _project_kubernetes(
            kube_system=kube_system,
            namespace=namespace_resource,
            deployment=deployment,
            pods=pods,
            service_account=service_account,
            endpoint_slices=endpoint_slices,
        ),
        "schema_report": _project_schema_report(schema),
        "platform_snapshot": _project_platform_snapshot(platform),
        "health": {
            "liveness": _project_health(health),
            "readiness": _project_health(readiness),
        },
    }


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_PATTERN.fullmatch(value))


def _is_uid(value: Any) -> bool:
    return isinstance(value, str) and bool(UID_PATTERN.fullmatch(value))


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return None
    return timestamp


def _validate_fresh_timestamp(
    value: Any,
    *,
    label: str,
    now: datetime,
    max_age_seconds: float,
    errors: list[str],
) -> None:
    timestamp = _parse_timestamp(value)
    if timestamp is None:
        errors.append(f"{label} must be timezone-aware")
        return
    age = (now - timestamp).total_seconds()
    if age < -300:
        errors.append(f"{label} is in the future")
    elif age > max_age_seconds:
        errors.append(f"{label} is stale")


def _image_digest(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = IMAGE_DIGEST_PATTERN.search(value)
    return f"sha256:{match.group(1)}" if match else None


def build_rollout_convergence_observation(
    deployment: Mapping[str, Any],
    pods: Mapping[str, Any],
    endpoint_slices: Mapping[str, Any],
    *,
    expected_image: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build an allowlisted, fail-closed rollout convergence observation."""
    expected_digest = _image_digest(expected_image)
    if (
        not IMMUTABLE_IMAGE_PATTERN.fullmatch(expected_image)
        or expected_digest is None
    ):
        raise StagingLiveEvidenceError(
            "expected rollout image must use an immutable registry digest"
        )

    errors: list[str] = []
    metadata = _metadata(deployment)
    spec = _mapping(deployment.get("spec"))
    status = _mapping(deployment.get("status"))
    template = _mapping(spec.get("template"))
    template_spec = _mapping(template.get("spec"))
    app = _named(template_spec.get("containers"), APP_CONTAINER)
    replicas = spec.get("replicas")

    if replicas != 1 or isinstance(replicas, bool):
        errors.append("rollout convergence requires exactly one replica")
    if metadata.get("generation") != status.get("observedGeneration"):
        errors.append(
            "Deployment controller has not observed the current generation"
        )
    for field in (
        "replicas",
        "updatedReplicas",
        "readyReplicas",
        "availableReplicas",
    ):
        if status.get(field) != replicas:
            errors.append(f"Deployment status {field} has not converged")
    if status.get("unavailableReplicas") not in (None, 0):
        errors.append("Deployment still has unavailable replicas")
    if app.get("image") != expected_image:
        errors.append(
            "Deployment template image does not match the attested release"
        )

    pod_items = _items(pods.get("items"))
    if replicas != 1 or isinstance(replicas, bool) or len(pod_items) != replicas:
        errors.append(
            "selected Pod count has not converged to the requested replicas"
        )

    ready_pod_uids: set[str] = set()
    pod_uids: list[str] = []
    for pod in pod_items:
        pod_metadata = _metadata(pod)
        pod_spec = _mapping(pod.get("spec"))
        pod_status = _mapping(pod.get("status"))
        pod_container = _named(pod_spec.get("containers"), APP_CONTAINER)
        container_status = _named(
            pod_status.get("containerStatuses"), APP_CONTAINER
        )
        name = str(pod_metadata.get("name") or "<unknown>")
        uid = pod_metadata.get("uid")
        if isinstance(uid, str):
            pod_uids.append(uid)
        else:
            errors.append(f"Pod {name} has no UID")
        if pod_metadata.get("deletionTimestamp") is not None:
            errors.append(f"Pod {name} is still terminating")
        if pod_status.get("phase") != "Running" or container_status.get(
            "ready"
        ) is not True:
            errors.append(f"Pod {name} is not Running and ready")
        elif isinstance(uid, str):
            ready_pod_uids.add(uid)
        if pod_container.get("image") != expected_image:
            errors.append(
                f"Pod {name} image does not match the attested release"
            )
        if _image_digest(container_status.get("imageID")) != expected_digest:
            errors.append(f"Pod {name} runtime image ID has not converged")

    ready_endpoint_uids: set[str] = set()
    invalid_ready_endpoints = 0
    for endpoint_slice in _items(endpoint_slices.get("items")):
        for endpoint in _items(endpoint_slice.get("endpoints")):
            conditions = _mapping(endpoint.get("conditions"))
            if conditions.get("ready") is not True:
                continue
            target = _mapping(endpoint.get("targetRef"))
            uid = target.get("uid")
            if target.get("kind") == "Pod" and isinstance(uid, str):
                ready_endpoint_uids.add(uid)
            else:
                invalid_ready_endpoints += 1
    if invalid_ready_endpoints:
        errors.append("ready EndpointSlice targets must identify Pods")
    if ready_endpoint_uids != ready_pod_uids:
        errors.append("ready EndpointSlice Pod UIDs have not converged")

    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise StagingLiveEvidenceError(
            "rollout convergence time must be timezone-aware"
        )
    return {
        "schema": ROLLOUT_CONVERGENCE_SCHEMA,
        "observed_at": current.isoformat(),
        "status": "converged" if not errors else "waiting",
        "deployment_uid": metadata.get("uid"),
        "generation": metadata.get("generation"),
        "observed_generation": status.get("observedGeneration"),
        "requested_replicas": replicas,
        "status_replicas": status.get("replicas"),
        "updated_replicas": status.get("updatedReplicas"),
        "ready_replicas": status.get("readyReplicas"),
        "available_replicas": status.get("availableReplicas"),
        "expected_image": expected_image,
        "expected_image_digest": expected_digest,
        "pod_uids": sorted(pod_uids),
        "ready_endpoint_pod_uids": sorted(ready_endpoint_uids),
        "errors": errors,
    }


def collect_rollout_convergence(
    *,
    expected_image: str,
    namespace: str = NAMESPACE,
    deployment_name: str = DEPLOYMENT_NAME,
    service_name: str = DEPLOYMENT_NAME,
    kubectl: str = "kubectl",
    now: datetime | None = None,
    run: CommandRunner = _run_command,
) -> dict[str, Any]:
    """Observe whether rollout replicas, digests, and endpoints agree."""
    for label, value in (
        ("namespace", namespace),
        ("deployment", deployment_name),
        ("service", service_name),
    ):
        if not DNS_LABEL_PATTERN.fullmatch(value):
            raise StagingLiveEvidenceError(f"invalid Kubernetes {label} name")

    deployment = _kubectl_json(
        kubectl,
        [
            "-n",
            namespace,
            "get",
            "deployment",
            deployment_name,
            "-o",
            "json",
        ],
        label="application Deployment",
        run=run,
    )
    pods = _kubectl_json(
        kubectl,
        [
            "-n",
            namespace,
            "get",
            "pods",
            "-l",
            f"app.kubernetes.io/name={deployment_name}",
            "-o",
            "json",
        ],
        label="application Pods",
        run=run,
    )
    endpoint_slices = _kubectl_json(
        kubectl,
        [
            "-n",
            namespace,
            "get",
            "endpointslices",
            "-l",
            f"kubernetes.io/service-name={service_name}",
            "-o",
            "json",
        ],
        label="application EndpointSlices",
        run=run,
    )
    return build_rollout_convergence_observation(
        deployment,
        pods,
        endpoint_slices,
        expected_image=expected_image,
        now=now,
    )


def _validate_candidate(candidate: Mapping[str, Any], errors: list[str]) -> None:
    if candidate.get("schema") != CANDIDATE_SCHEMA:
        errors.append("candidate evidence schema is unsupported")
    if candidate.get("candidate_validated") is not True:
        errors.append("candidate evidence was not validated")
    if candidate.get("status") != "candidate_validated":
        errors.append("candidate status must be candidate_validated")
    if not SOURCE_REVISION_PATTERN.fullmatch(
        str(candidate.get("source_revision") or "")
    ):
        errors.append("candidate source revision must be a full lowercase Git SHA-1")
    if not LOCAL_IMAGE_ID_PATTERN.fullmatch(str(candidate.get("image_id") or "")):
        errors.append("candidate image ID must be an immutable local sha256 ID")
    for field in (
        "schema_fingerprint",
        "platform_fingerprint",
        "config_fingerprint",
        "environment_access_fingerprint",
        "runtime_fingerprint",
        "evidence_fingerprint",
    ):
        if not _is_sha256(candidate.get(field)):
            errors.append(f"candidate {field} must be sha256")
    if candidate.get("errors") != []:
        errors.append("candidate evidence contains errors")
    tests = _mapping(candidate.get("tests"))
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


def _validate_release(
    release: Mapping[str, Any],
    candidate: Mapping[str, Any],
    errors: list[str],
) -> tuple[str | None, str | None]:
    if release.get("schema") != RELEASE_EVIDENCE_SCHEMA:
        errors.append("release evidence schema is unsupported")
    if release.get("status") != "staging_release_admitted":
        errors.append("release status must be staging_release_admitted")
    if release.get("staging_apply_allowed") is not True:
        errors.append("release does not allow staging apply")
    if release.get("errors") != []:
        errors.append("release evidence contains errors")
    for field in (
        "staging_deployed",
        "live_cluster_verified",
        "golden_slice_verified",
        "promotion_authority_verified",
        "production_promotion_allowed",
    ):
        if release.get(field) is not False:
            errors.append(f"release {field} must remain false")
    if release.get("source_revision") != candidate.get("source_revision"):
        errors.append("release source revision does not match the candidate")
    if release.get("candidate_evidence_fingerprint") != candidate.get(
        "evidence_fingerprint"
    ):
        errors.append("release candidate fingerprint does not match the candidate")
    for field in (
        "schema_fingerprint",
        "environment_access_fingerprint",
        "runtime_fingerprint",
    ):
        if release.get(field) != candidate.get(field):
            errors.append(f"release {field} does not match the candidate")
    release_fingerprint = release.get("evidence_fingerprint")
    if not _is_sha256(release_fingerprint):
        errors.append("release evidence fingerprint must be sha256")
        release_fingerprint = None
    elif release_fingerprint != release_evidence_fingerprint(release):
        errors.append("release evidence fingerprint does not match its content")
        release_fingerprint = None
    repository = release.get("repository")
    digest = release.get("digest")
    image = release.get("image")
    if not isinstance(digest, str) or not LOCAL_IMAGE_ID_PATTERN.fullmatch(digest):
        errors.append("release digest must be sha256")
        digest = None
    if (
        not isinstance(repository, str)
        or not isinstance(image, str)
        or not IMMUTABLE_IMAGE_PATTERN.fullmatch(image)
        or image != f"{repository}@{digest}"
    ):
        errors.append("release image does not match its immutable repository digest")
        image = None
    return release_fingerprint, image


def _validate_kubernetes(
    kubernetes: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    expected_release_fingerprint: str | None,
    expected_image: str | None,
    expected_namespace_name: str,
    expected_cluster_uid: str,
    expected_namespace_uid: str,
    errors: list[str],
) -> tuple[str | None, str | None, str | None]:
    if not _is_uid(expected_cluster_uid) or not _is_uid(expected_namespace_uid):
        errors.append("protected expected cluster and namespace UIDs are invalid")
    if kubernetes.get("cluster_uid") != expected_cluster_uid:
        errors.append("observed cluster UID does not match the protected target")
    namespace = _mapping(kubernetes.get("namespace"))
    if not DNS_LABEL_PATTERN.fullmatch(expected_namespace_name):
        errors.append("protected expected namespace name is invalid")
    if expected_namespace_name == DEVELOPMENT_NAMESPACE:
        errors.append("protected staging cannot target the development namespace")
    if namespace.get("name") != expected_namespace_name:
        errors.append(
            "observed namespace name does not match the protected target"
        )
    if namespace.get("uid") != expected_namespace_uid:
        errors.append("observed namespace UID does not match the protected target")

    deployment = _mapping(kubernetes.get("deployment"))
    if deployment.get("name") != DEPLOYMENT_NAME:
        errors.append(f"live Deployment must be {DEPLOYMENT_NAME}")
    deployment_uid = deployment.get("uid")
    if not _is_uid(deployment_uid):
        errors.append("live Deployment UID is invalid")
        deployment_uid = None
    replicas = deployment.get("replicas")
    if replicas != 1 or isinstance(replicas, bool):
        errors.append("live observation v1 requires exactly one staging replica")
    for field in (
        "status_replicas",
        "updated_replicas",
        "ready_replicas",
        "available_replicas",
    ):
        if deployment.get(field) != replicas:
            errors.append(f"live Deployment {field} must match requested replicas")
    if deployment.get("generation") != deployment.get("observed_generation"):
        errors.append("live Deployment controller has not observed the current generation")
    if deployment.get("available") is not True:
        errors.append("live Deployment Available condition is not true")
    if deployment.get("progressing") is not True:
        errors.append("live Deployment Progressing condition is not true")
    if deployment.get("environment") != "staging":
        errors.append("live Deployment environment annotation must be staging")
    if deployment.get("source_revision") != candidate.get("source_revision"):
        errors.append("live Deployment source revision does not match the candidate")
    if deployment.get("candidate_evidence_fingerprint") != candidate.get(
        "evidence_fingerprint"
    ):
        errors.append("live Deployment is not bound to the candidate fingerprint")
    if deployment.get("release_evidence_fingerprint") != (
        expected_release_fingerprint
    ):
        errors.append("live Deployment is not bound to the release fingerprint")
    for field in (
        "schema_fingerprint",
        "environment_access_fingerprint",
        "runtime_fingerprint",
    ):
        if deployment.get(field) != candidate.get(field):
            errors.append(f"live Deployment {field} annotation drifted")
    expected_platform_fingerprint = deployment.get("platform_fingerprint")
    if not _is_sha256(expected_platform_fingerprint):
        errors.append("live Deployment platform fingerprint annotation is invalid")
        expected_platform_fingerprint = None

    image = deployment.get("image")
    image_digest = _image_digest(image)
    if not isinstance(image, str) or not IMMUTABLE_IMAGE_PATTERN.fullmatch(image):
        errors.append("live Deployment image must use an immutable registry digest")
        image_digest = None
    elif image != expected_image:
        errors.append("live Deployment image does not match the attested release")
        image_digest = None
    if deployment.get("service_account_name") != "gis-agent-app":
        errors.append("live Deployment must use the gis-agent-app service account")
    if deployment.get("automount_service_account_token") is not False:
        errors.append("live application Pod must disable service account token mounting")

    service_account = _mapping(kubernetes.get("service_account"))
    if service_account.get("name") != deployment.get("service_account_name"):
        errors.append("live ServiceAccount does not match the Deployment")
    if not _is_uid(service_account.get("uid")):
        errors.append("live ServiceAccount UID is invalid")

    pods = _items(kubernetes.get("pods"))
    if replicas != 1 or isinstance(replicas, bool) or len(pods) != replicas:
        errors.append("live Pod count must match requested replicas")
    ready_pod_uids: set[str] = set()
    for pod in pods:
        name = str(pod.get("name") or "<unknown>")
        uid = pod.get("uid")
        if not _is_uid(uid):
            errors.append(f"Pod {name} UID is invalid")
        if pod.get("phase") != "Running" or pod.get("ready") is not True:
            errors.append(f"Pod {name} is not Running and ready")
        elif isinstance(uid, str):
            ready_pod_uids.add(uid)
        if pod.get("service_account_name") != deployment.get(
            "service_account_name"
        ):
            errors.append(f"Pod {name} service account drifted")
        if _image_digest(pod.get("image")) != image_digest:
            errors.append(f"Pod {name} image does not match the Deployment digest")
        if _image_digest(pod.get("image_id")) != image_digest:
            errors.append(f"Pod {name} runtime image ID does not match the registry digest")
        restart_count = pod.get("restart_count")
        if (
            not isinstance(restart_count, int)
            or isinstance(restart_count, bool)
            or restart_count < 0
        ):
            errors.append(f"Pod {name} restart count is invalid")
    endpoint_uids = kubernetes.get("ready_endpoint_pod_uids")
    if (
        not isinstance(endpoint_uids, list)
        or any(not isinstance(uid, str) for uid in endpoint_uids)
        or set(endpoint_uids) != ready_pod_uids
    ):
        errors.append("ready EndpointSlice Pod UIDs do not match the ready rollout")
    return deployment_uid, image_digest, expected_platform_fingerprint


def _validate_schema(
    schema: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    now: datetime,
    max_age_seconds: float,
    errors: list[str],
) -> None:
    _validate_fresh_timestamp(
        schema.get("generated_at"),
        label="live schema observation",
        now=now,
        max_age_seconds=max_age_seconds,
        errors=errors,
    )
    if schema.get("format_version") != 1:
        errors.append("live schema report format is unsupported")
    if schema.get("status") != "in_sync" or schema.get("ledger_present") is not True:
        errors.append("live schema ledger must be present and in_sync")
    if not _positive_int(schema.get("catalog_count")):
        errors.append("live schema catalog count must be positive")
    if schema.get("applied_count") != schema.get("catalog_count"):
        errors.append("live applied migration count must match the catalog")
    if schema.get("catalog_fingerprint") != candidate.get("schema_fingerprint"):
        errors.append("live migration catalog does not match the candidate")
    if schema.get("database_fingerprint") != candidate.get("schema_fingerprint"):
        errors.append("live database schema does not match the candidate")
    for field in (
        "pending",
        "unknown_applied",
        "missing_checksums",
        "checksum_mismatches",
        "metadata_mismatches",
    ):
        if schema.get(field) != []:
            errors.append(f"live schema report contains {field}")


def _validate_platform(
    platform: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    expected_platform_fingerprint: str | None,
    now: datetime,
    max_age_seconds: float,
    errors: list[str],
) -> tuple[str | None, str | None, str | None]:
    _validate_fresh_timestamp(
        platform.get("generated_at"),
        label="live platform observation",
        now=now,
        max_age_seconds=max_age_seconds,
        errors=errors,
    )
    if platform.get("schema") != PLATFORM_TRUTH_SCHEMA:
        errors.append("live platform snapshot schema is unsupported")
    config = _mapping(platform.get("config"))
    environment_access = _mapping(platform.get("environment_access"))
    runtime = _mapping(platform.get("runtime"))
    if config.get("profile") != "staging" or config.get("strict") is not True:
        errors.append("live platform config must be strict staging")
    if config.get("valid") is not True or config.get("startup_allowed") is not True:
        errors.append("live platform config must be valid and startable")
    config_fingerprint = config.get("config_fingerprint")
    if not _is_sha256(config_fingerprint):
        errors.append("live config fingerprint must be sha256")
        config_fingerprint = None
    if environment_access.get("matches_baseline") is not True:
        errors.append(
            "live environment accesses drifted from the reviewed baseline"
        )
    if environment_access.get("parse_errors") != []:
        errors.append("live environment access scan contains parse errors")
    environment_access_fingerprint = environment_access.get("fingerprint")
    if environment_access_fingerprint != candidate.get(
        "environment_access_fingerprint"
    ):
        errors.append(
            "live environment access fingerprint does not match the candidate"
        )
    if not _is_sha256(environment_access_fingerprint):
        errors.append("live environment access fingerprint must be sha256")
        environment_access_fingerprint = None
    if runtime.get("status") != "valid":
        errors.append("live runtime inventory is invalid")
    if runtime.get("matches_primitive_baseline") is not True:
        errors.append("live runtime primitives drifted from the reviewed baseline")
    runtime_fingerprint = runtime.get("inventory_fingerprint")
    if runtime_fingerprint != candidate.get("runtime_fingerprint"):
        errors.append("live runtime fingerprint does not match the candidate")
    if not _is_sha256(runtime_fingerprint):
        errors.append("live runtime fingerprint must be sha256")
        runtime_fingerprint = None
    computed_platform_fingerprint = (
        _canonical_sha256(
            {
                "config": config_fingerprint,
                "environment_access": environment_access_fingerprint,
                "runtime": runtime_fingerprint,
            }
        )
        if (
            config_fingerprint
            and environment_access_fingerprint
            and runtime_fingerprint
        )
        else None
    )
    if platform.get("platform_fingerprint") != computed_platform_fingerprint:
        errors.append("live platform fingerprint does not match config and runtime")
    if expected_platform_fingerprint != computed_platform_fingerprint:
        errors.append("live platform fingerprint does not match the Deployment")
    return (
        config_fingerprint,
        environment_access_fingerprint,
        runtime_fingerprint,
    )


def _validate_health(health: Mapping[str, Any], errors: list[str]) -> None:
    liveness = _mapping(health.get("liveness"))
    readiness = _mapping(health.get("readiness"))
    if liveness.get("status") != "ok":
        errors.append("live liveness endpoint is not healthy")
    if readiness.get("status") != "ok":
        errors.append("live readiness endpoint is not healthy")
    database = _mapping(_mapping(readiness.get("checks")).get("database"))
    if database.get("status") != "ok":
        errors.append("live readiness database check is not healthy")


def golden_slice_fingerprint(golden_slice: Mapping[str, Any]) -> str:
    stable = {
        field: golden_slice.get(field)
        for field in sorted(GOLDEN_SLICE_FIELDS - {"evidence_fingerprint"})
    }
    return _canonical_sha256(stable)


def _validate_golden_slice(
    golden_slice: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    deployment_uid: str | None,
    image_digest: str | None,
    schema_fingerprint: str | None,
    config_fingerprint: str | None,
    environment_access_fingerprint: str | None,
    runtime_fingerprint: str | None,
    expected_tenant_id: str | None,
    expected_capability_id: str | None,
    expected_definition_version_id: str | None,
    expected_input_resource_version_id: str | None,
    now: datetime,
    max_age_seconds: float,
    errors: list[str],
) -> None:
    if set(golden_slice) != GOLDEN_SLICE_FIELDS:
        errors.append("golden-slice evidence fields do not match the v1 allowlist")
    if golden_slice.get("schema") != GOLDEN_SLICE_SCHEMA:
        errors.append("golden-slice evidence schema is unsupported")
    if golden_slice.get("environment") != "staging":
        errors.append("golden-slice evidence environment must be staging")
    if golden_slice.get("status") != "passed":
        errors.append("golden-slice verdict must be passed")
    _validate_fresh_timestamp(
        golden_slice.get("observed_at"),
        label="golden-slice observation",
        now=now,
        max_age_seconds=max_age_seconds,
        errors=errors,
    )
    bindings = {
        "source_revision": candidate.get("source_revision"),
        "deployment_uid": deployment_uid,
        "image_digest": image_digest,
        "schema_fingerprint": schema_fingerprint,
        "config_fingerprint": config_fingerprint,
        "environment_access_fingerprint": environment_access_fingerprint,
        "runtime_fingerprint": runtime_fingerprint,
    }
    for field, expected in bindings.items():
        if golden_slice.get(field) != expected:
            errors.append(f"golden-slice {field} does not match live staging")
    protected_identities = {
        "tenant_id": expected_tenant_id,
        "capability_id": expected_capability_id,
        "definition_version_id": expected_definition_version_id,
        "input_resource_version_id": expected_input_resource_version_id,
    }
    for field, expected in protected_identities.items():
        if expected is None:
            errors.append(f"protected golden {field} is missing")
        elif golden_slice.get(field) != expected:
            errors.append(
                f"golden-slice {field} does not match the protected identity"
            )
    for field in (
        "definition_version_id",
        "input_resource_version_id",
        "output_resource_version_id",
        "run_id",
        "quality_result_id",
        "lineage_event_id",
    ):
        if not _is_uid(golden_slice.get(field)):
            errors.append(f"golden-slice {field} is invalid")
    tenant_id = golden_slice.get("tenant_id")
    if not isinstance(tenant_id, str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9._-]{0,63}", tenant_id
    ):
        errors.append("golden-slice tenant_id is invalid")
    capability_id = golden_slice.get("capability_id")
    if not isinstance(capability_id, str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9._-]{2,127}", capability_id
    ):
        errors.append("golden-slice capability_id is invalid")
    for field in (
        "definition_sha256",
        "output_artifact_sha256",
        "quality_evidence_fingerprint",
        "run_success_evidence_fingerprint",
        "evidence_fingerprint",
    ):
        if not _is_sha256(golden_slice.get(field)):
            errors.append(f"golden-slice {field} must be sha256")
    if golden_slice.get("evidence_fingerprint") != golden_slice_fingerprint(
        golden_slice
    ):
        errors.append("golden-slice evidence fingerprint does not match its content")


def build_live_staging_evidence(
    candidate: Mapping[str, Any],
    release: Mapping[str, Any],
    collection: Mapping[str, Any],
    golden_slice: Mapping[str, Any] | None,
    *,
    expected_namespace_name: str = NAMESPACE,
    expected_cluster_uid: str,
    expected_namespace_uid: str,
    expected_golden_tenant_id: str | None = None,
    expected_golden_capability_id: str | None = None,
    expected_golden_definition_version_id: str | None = None,
    expected_golden_input_resource_version_id: str | None = None,
    max_age_seconds: float = 900,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate live observations without granting production authority."""
    current = now or datetime.now(UTC)
    timing_errors: list[str] = []
    if (
        current.tzinfo is None
        or current.utcoffset() is None
        or not math.isfinite(max_age_seconds)
        or max_age_seconds <= 0
    ):
        timing_errors.append("live evidence validation time window is invalid")

    section_errors: dict[str, list[str]] = {
        "candidate": [],
        "release": [],
        "collection": list(timing_errors),
        "kubernetes": [],
        "schema": [],
        "platform": [],
        "health": [],
        "golden_slice": [],
    }
    _validate_candidate(candidate, section_errors["candidate"])
    release_fingerprint, expected_image = _validate_release(
        release,
        candidate,
        section_errors["release"],
    )
    if collection.get("schema") != COLLECTION_SCHEMA:
        section_errors["collection"].append(
            "live collection schema is unsupported"
        )
    if set(collection) != COLLECTION_FIELDS:
        section_errors["collection"].append(
            "live collection fields do not match the v1 allowlist"
        )
    if not timing_errors:
        _validate_fresh_timestamp(
            collection.get("observed_at"),
            label="live collection",
            now=current,
            max_age_seconds=max_age_seconds,
            errors=section_errors["collection"],
        )
    kubernetes = _mapping(collection.get("kubernetes"))
    (
        deployment_uid,
        image_digest,
        expected_platform_fingerprint,
    ) = _validate_kubernetes(
        kubernetes,
        candidate,
        expected_release_fingerprint=release_fingerprint,
        expected_image=expected_image,
        expected_namespace_name=expected_namespace_name,
        expected_cluster_uid=expected_cluster_uid,
        expected_namespace_uid=expected_namespace_uid,
        errors=section_errors["kubernetes"],
    )
    live_config_fingerprint: str | None = None
    live_environment_access_fingerprint: str | None = None
    live_runtime_fingerprint: str | None = None
    if timing_errors:
        for section in ("schema", "platform"):
            section_errors[section].append(
                "live evidence validation time window is invalid"
            )
    else:
        _validate_schema(
            _mapping(collection.get("schema_report")),
            candidate,
            now=current,
            max_age_seconds=max_age_seconds,
            errors=section_errors["schema"],
        )
        (
            live_config_fingerprint,
            live_environment_access_fingerprint,
            live_runtime_fingerprint,
        ) = _validate_platform(
            _mapping(collection.get("platform_snapshot")),
            candidate,
            expected_platform_fingerprint=expected_platform_fingerprint,
            now=current,
            max_age_seconds=max_age_seconds,
            errors=section_errors["platform"],
        )
    _validate_health(
        _mapping(collection.get("health")), section_errors["health"]
    )
    if golden_slice is None:
        section_errors["golden_slice"].append(
            "live golden-slice evidence is missing"
        )
    elif timing_errors:
        section_errors["golden_slice"].append(
            "live evidence validation time window is invalid"
        )
    else:
        _validate_golden_slice(
            golden_slice,
            candidate,
            deployment_uid=deployment_uid,
            image_digest=image_digest,
            schema_fingerprint=candidate.get("schema_fingerprint"),
            config_fingerprint=live_config_fingerprint,
            environment_access_fingerprint=(
                live_environment_access_fingerprint
            ),
            runtime_fingerprint=live_runtime_fingerprint,
            expected_tenant_id=expected_golden_tenant_id,
            expected_capability_id=expected_golden_capability_id,
            expected_definition_version_id=(
                expected_golden_definition_version_id
            ),
            expected_input_resource_version_id=(
                expected_golden_input_resource_version_id
            ),
            now=current,
            max_age_seconds=max_age_seconds,
            errors=section_errors["golden_slice"],
        )

    checks = {
        section: "passed" if not errors else "blocked"
        for section, errors in section_errors.items()
    }
    errors = [
        f"{section}: {error}"
        for section, section_values in section_errors.items()
        for error in section_values
    ]
    live_verified = not errors
    deployment_verified = all(
        checks[section] == "passed"
        for section in ("candidate", "release", "collection", "kubernetes")
    )
    golden_verified = all(
        checks[section] == "passed"
        for section in (
            "candidate",
            "release",
            "collection",
            "kubernetes",
            "schema",
            "platform",
            "golden_slice",
        )
    )
    stable = {
        "schema": LIVE_EVIDENCE_SCHEMA,
        "source_revision": candidate.get("source_revision"),
        "candidate_evidence_fingerprint": candidate.get("evidence_fingerprint"),
        "release_evidence_fingerprint": release_fingerprint,
        "cluster_uid": kubernetes.get("cluster_uid"),
        "namespace_uid": _mapping(kubernetes.get("namespace")).get("uid"),
        "deployment_uid": deployment_uid,
        "image_digest": image_digest,
        "schema_fingerprint": candidate.get("schema_fingerprint"),
        "candidate_config_fingerprint": candidate.get("config_fingerprint"),
        "config_fingerprint": live_config_fingerprint,
        "environment_access_fingerprint": (
            live_environment_access_fingerprint
        ),
        "runtime_fingerprint": live_runtime_fingerprint,
        "golden_slice_evidence_fingerprint": (
            golden_slice.get("evidence_fingerprint")
            if isinstance(golden_slice, Mapping)
            else None
        ),
        "checks": checks,
        "errors": errors,
        "live_staging_verified": live_verified,
    }
    return {
        **stable,
        "generated_at": current.isoformat(),
        "status": "live_staging_verified" if live_verified else "blocked",
        "environment": "staging",
        "staging_deployed": deployment_verified,
        "live_cluster_verified": live_verified,
        "registry_digest_verified": (
            deployment_verified and image_digest is not None
        ),
        "golden_slice_verified": golden_verified,
        "promotion_authority_verified": False,
        "production_promotion_allowed": False,
        "required_promotion_provenance": list(REQUIRED_PROMOTION_PROVENANCE),
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
    collect = subparsers.add_parser("collect")
    collect.add_argument("--namespace", default=NAMESPACE)
    collect.add_argument("--deployment", default=DEPLOYMENT_NAME)
    collect.add_argument("--service", default=DEPLOYMENT_NAME)
    collect.add_argument("--kubectl", default="kubectl")
    collect.add_argument("--output", type=Path)

    convergence = subparsers.add_parser("check-rollout")
    convergence.add_argument("--release-evidence", type=Path, required=True)
    convergence.add_argument("--namespace", default=NAMESPACE)
    convergence.add_argument("--deployment", default=DEPLOYMENT_NAME)
    convergence.add_argument("--service", default=DEPLOYMENT_NAME)
    convergence.add_argument("--kubectl", default="kubectl")
    convergence.add_argument("--output", type=Path)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--candidate-evidence", type=Path, required=True)
    validate.add_argument("--release-evidence", type=Path, required=True)
    validate.add_argument("--live-collection", type=Path, required=True)
    validate.add_argument("--golden-slice", type=Path)
    validate.add_argument("--expected-namespace-name", default=NAMESPACE)
    validate.add_argument("--expected-cluster-uid", required=True)
    validate.add_argument("--expected-namespace-uid", required=True)
    validate.add_argument("--expected-golden-tenant-id")
    validate.add_argument("--expected-golden-capability-id")
    validate.add_argument("--expected-golden-definition-version-id")
    validate.add_argument("--expected-golden-input-resource-version-id")
    validate.add_argument("--max-age-seconds", type=float, default=900)
    validate.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.command == "collect":
            report = collect_live_staging(
                namespace=args.namespace,
                deployment_name=args.deployment,
                service_name=args.service,
                kubectl=args.kubectl,
            )
            _write_report(report, args.output)
            return 0

        if args.command == "check-rollout":
            release = _load_json_object(args.release_evidence)
            report = collect_rollout_convergence(
                expected_image=str(release.get("image") or ""),
                namespace=args.namespace,
                deployment_name=args.deployment,
                service_name=args.service,
                kubectl=args.kubectl,
            )
            _write_report(report, args.output)
            return 0 if report["status"] == "converged" else 1

        golden_slice = (
            _load_json_object(args.golden_slice) if args.golden_slice else None
        )
        report = build_live_staging_evidence(
            _load_json_object(args.candidate_evidence),
            _load_json_object(args.release_evidence),
            _load_json_object(args.live_collection),
            golden_slice,
            expected_namespace_name=args.expected_namespace_name,
            expected_cluster_uid=args.expected_cluster_uid,
            expected_namespace_uid=args.expected_namespace_uid,
            expected_golden_tenant_id=args.expected_golden_tenant_id,
            expected_golden_capability_id=args.expected_golden_capability_id,
            expected_golden_definition_version_id=(
                args.expected_golden_definition_version_id
            ),
            expected_golden_input_resource_version_id=(
                args.expected_golden_input_resource_version_id
            ),
            max_age_seconds=args.max_age_seconds,
        )
    except (OSError, json.JSONDecodeError, StagingLiveEvidenceError) as exc:
        detail = (
            str(exc)
            if isinstance(exc, StagingLiveEvidenceError)
            else type(exc).__name__
        )
        report = {
            "schema": (
                ROLLOUT_CONVERGENCE_SCHEMA
                if args.command == "check-rollout"
                else LIVE_EVIDENCE_SCHEMA
            ),
            "status": "error",
            "live_staging_verified": False,
            "promotion_authority_verified": False,
            "production_promotion_allowed": False,
            "error": f"live evidence input is invalid: {detail}",
        }
        _write_report(report, args.output)
        return 2

    _write_report(report, args.output)
    return 0 if report["live_staging_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
