"""Collect and verify allowlisted metadata fabric sandbox observations.

The collector deliberately reads no Kubernetes Secret. It proves only a local
foundation deployment and, when given before/after observations, continuity
across controlled Pod restarts. It cannot prove backup/restore, disaster
recovery, OIDC, production provider conformance, or production readiness.
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

from .metadata_fabric_sandbox import (
    GRAVITINO_LOCAL_IMAGE,
    GRAVITINO_TAG_COMMIT,
    GRAVITINO_VERSION,
    NAMESPACE,
    OPENMETADATA_SERVER_COMMIT,
    OPENMETADATA_VERSION,
    OPENSEARCH_VERSION,
    POSTGRESQL_VERSION,
    build_sandbox_report,
)

COLLECTION_SCHEMA = "gda.metadata_fabric_live_collection.v1"
EVIDENCE_SCHEMA = "gda.metadata_fabric_live_evidence.v1"
OPENMETADATA_IMAGE = (
    f"docker.getcollate.io/openmetadata/server:{OPENMETADATA_VERSION}"
)
POSTGRESQL_IMAGE = f"postgres:{POSTGRESQL_VERSION}"
OPENSEARCH_IMAGE = f"opensearchproject/opensearch:{OPENSEARCH_VERSION}"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DNS_LABEL_PATTERN = re.compile(
    r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$"
)
SENSITIVE_KEY_PATTERN = re.compile(
    r"(^|[-_.])(password|passwd|secret|token|private[-_.]?key|access[-_.]?key)($|[-_.])",
    re.IGNORECASE,
)
SAFE_SECURITY_FIELDS = {"automount_service_account_token"}

WORKLOADS = {
    "openmetadata": {
        "kind": "deployment",
        "container": "openmetadata",
        "image": OPENMETADATA_IMAGE,
        "pull_policy": "Never",
    },
    "metadata-gravitino": {
        "kind": "statefulset",
        "container": "gravitino",
        "image": GRAVITINO_LOCAL_IMAGE,
        "pull_policy": "Never",
    },
    "metadata-openmetadata-postgresql": {
        "kind": "statefulset",
        "container": "postgresql",
        "image": POSTGRESQL_IMAGE,
        "pull_policy": "IfNotPresent",
    },
    "metadata-gravitino-postgresql": {
        "kind": "statefulset",
        "container": "postgresql",
        "image": POSTGRESQL_IMAGE,
        "pull_policy": "IfNotPresent",
    },
    "metadata-opensearch": {
        "kind": "statefulset",
        "container": "opensearch",
        "image": OPENSEARCH_IMAGE,
        "pull_policy": "IfNotPresent",
    },
}
SERVICES = {
    "openmetadata",
    "metadata-gravitino",
    "metadata-openmetadata-postgresql",
    "metadata-gravitino-postgresql",
    "metadata-opensearch",
}
PVCS = {
    "data-metadata-openmetadata-postgresql-0": "8Gi",
    "gravitino-data-metadata-gravitino-postgresql-0": "8Gi",
    "opensearch-data-metadata-opensearch-0": "16Gi",
}
NETWORK_POLICIES = {
    "metadata-default-deny",
    "metadata-dns-egress",
    "metadata-provider-ingress",
    "metadata-openmetadata-egress",
    "metadata-gravitino-egress",
    "metadata-openmetadata-postgresql-ingress",
    "metadata-gravitino-postgresql-ingress",
    "metadata-opensearch-ingress",
}

CommandRunner = Callable[[list[str]], str]


class MetadataFabricLiveEvidenceError(RuntimeError):
    """A live observation could not be collected or parsed safely."""


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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
        raise MetadataFabricLiveEvidenceError(
            f"command unavailable: {args[0]}"
        ) from exc
    if completed.returncode != 0:
        raise MetadataFabricLiveEvidenceError(
            f"command failed without usable evidence: {args[0]}"
        )
    return completed.stdout


def _parse_json_object(raw: str, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MetadataFabricLiveEvidenceError(
            f"{label} did not return a JSON object"
        ) from exc
    if not isinstance(payload, dict):
        raise MetadataFabricLiveEvidenceError(f"{label} must be a JSON object")
    return payload


def _parse_json_list(raw: str, label: str) -> list[Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MetadataFabricLiveEvidenceError(
            f"{label} did not return a JSON list"
        ) from exc
    if not isinstance(payload, list):
        raise MetadataFabricLiveEvidenceError(f"{label} must be a JSON list")
    return payload


def _kubectl_json(
    kubectl: str,
    args: list[str],
    *,
    label: str,
    run: CommandRunner,
) -> dict[str, Any]:
    return _parse_json_object(run([kubectl, *args]), label)


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


def _selector(resource: Mapping[str, Any]) -> str:
    spec = _mapping(resource.get("spec"))
    labels = _mapping(_mapping(spec.get("selector")).get("matchLabels"))
    if not labels:
        raise MetadataFabricLiveEvidenceError("workload has no matchLabels selector")
    return ",".join(f"{key}={labels[key]}" for key in sorted(labels))


def _project_workload(
    resource: Mapping[str, Any],
    pods: Mapping[str, Any],
    *,
    container_name: str,
) -> dict[str, Any]:
    metadata = _mapping(resource.get("metadata"))
    spec = _mapping(resource.get("spec"))
    status = _mapping(resource.get("status"))
    pod_template = _mapping(spec.get("template"))
    pod_spec = _mapping(pod_template.get("spec"))
    container = _named(pod_spec.get("containers"), container_name)
    pod_reports: list[dict[str, Any]] = []
    for pod in _items(pods.get("items")):
        pod_metadata = _mapping(pod.get("metadata"))
        live_spec = _mapping(pod.get("spec"))
        live_status = _mapping(pod.get("status"))
        live_container = _named(live_spec.get("containers"), container_name)
        container_status = _named(
            live_status.get("containerStatuses"), container_name
        )
        pod_reports.append(
            {
                "name": pod_metadata.get("name"),
                "uid": pod_metadata.get("uid"),
                "phase": live_status.get("phase"),
                "ready": container_status.get("ready"),
                "restart_count": container_status.get("restartCount"),
                "service_account_name": live_spec.get("serviceAccountName"),
                "automount_service_account_token": live_spec.get(
                    "automountServiceAccountToken"
                ),
                "image": live_container.get("image"),
                "image_id": container_status.get("imageID"),
            }
        )
    return {
        "kind": resource.get("kind"),
        "name": metadata.get("name"),
        "uid": metadata.get("uid"),
        "desired_replicas": spec.get("replicas"),
        "ready_replicas": status.get("readyReplicas", 0),
        "service_account_name": pod_spec.get("serviceAccountName"),
        "automount_service_account_token": pod_spec.get(
            "automountServiceAccountToken"
        ),
        "image": container.get("image"),
        "image_pull_policy": container.get("imagePullPolicy"),
        "pods": sorted(pod_reports, key=lambda item: str(item.get("name"))),
    }


def _project_service(resource: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _mapping(resource.get("metadata"))
    spec = _mapping(resource.get("spec"))
    ports = _items(spec.get("ports"))
    return {
        "name": metadata.get("name"),
        "uid": metadata.get("uid"),
        "type": spec.get("type", "ClusterIP"),
        "ports": sorted(
            [
                {
                    "name": item.get("name"),
                    "port": item.get("port"),
                    "protocol": item.get("protocol"),
                }
                for item in ports
            ],
            key=lambda item: str(item.get("name")),
        ),
        "external_ips": list(spec.get("externalIPs") or []),
        "node_ports": sorted(
            item.get("nodePort") for item in ports if item.get("nodePort") is not None
        ),
    }


def _project_pvc(resource: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _mapping(resource.get("metadata"))
    spec = _mapping(resource.get("spec"))
    status = _mapping(resource.get("status"))
    return {
        "name": metadata.get("name"),
        "uid": metadata.get("uid"),
        "volume_name": spec.get("volumeName"),
        "storage_class": spec.get("storageClassName"),
        "access_modes": sorted(status.get("accessModes") or []),
        "capacity": _mapping(status.get("capacity")).get("storage"),
        "phase": status.get("phase"),
    }


def _table_marker(raw: str) -> dict[str, Any]:
    names = sorted(line.strip() for line in raw.splitlines() if line.strip())
    return {
        "table_count": len(names),
        "table_name_fingerprint": hashlib.sha256(
            "\n".join(names).encode("utf-8")
        ).hexdigest(),
    }


def _source_contract() -> dict[str, Any]:
    report = build_sandbox_report()
    files = {
        name: _mapping(value).get("sha256")
        for name, value in sorted(_mapping(report.get("files")).items())
    }
    stable = {
        "schema": report.get("schema"),
        "static_contract_verified": report.get("static_contract_verified"),
        "files": files,
        "providers": report.get("providers"),
    }
    return {
        "schema": stable["schema"],
        "static_contract_verified": stable["static_contract_verified"],
        "fingerprint": _canonical_sha256(stable),
    }


def collect_live_metadata_fabric(
    *,
    namespace: str = NAMESPACE,
    kubectl: str = "kubectl",
    now: datetime | None = None,
    run: CommandRunner = _run_command,
) -> dict[str, Any]:
    """Collect a Secret-free, allowlisted local sandbox observation."""
    if not DNS_LABEL_PATTERN.fullmatch(namespace):
        raise MetadataFabricLiveEvidenceError("invalid Kubernetes namespace")

    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise MetadataFabricLiveEvidenceError("collection time must be timezone-aware")

    context = run([kubectl, "config", "current-context"]).strip()
    version = _kubectl_json(
        kubectl, ["version", "-o", "json"], label="Kubernetes version", run=run
    )
    kube_system = _kubectl_json(
        kubectl,
        ["get", "namespace", "kube-system", "-o", "json"],
        label="kube-system namespace",
        run=run,
    )
    namespace_resource = _kubectl_json(
        kubectl,
        ["get", "namespace", namespace, "-o", "json"],
        label="metadata fabric namespace",
        run=run,
    )
    nodes = _kubectl_json(
        kubectl, ["get", "nodes", "-o", "json"], label="Kubernetes nodes", run=run
    )

    workload_reports: dict[str, Any] = {}
    for name, expected in WORKLOADS.items():
        kind = str(expected["kind"])
        resource = _kubectl_json(
            kubectl,
            ["-n", namespace, "get", kind, name, "-o", "json"],
            label=f"{kind}/{name}",
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
                _selector(resource),
                "-o",
                "json",
            ],
            label=f"Pods for {kind}/{name}",
            run=run,
        )
        workload_reports[name] = _project_workload(
            resource, pods, container_name=str(expected["container"])
        )

    service_reports = {}
    for name in sorted(SERVICES):
        resource = _kubectl_json(
            kubectl,
            ["-n", namespace, "get", "service", name, "-o", "json"],
            label=f"Service/{name}",
            run=run,
        )
        service_reports[name] = _project_service(resource)

    pvc_reports = {}
    for name in sorted(PVCS):
        resource = _kubectl_json(
            kubectl,
            ["-n", namespace, "get", "pvc", name, "-o", "json"],
            label=f"PersistentVolumeClaim/{name}",
            run=run,
        )
        pvc_reports[name] = _project_pvc(resource)

    policies = _kubectl_json(
        kubectl,
        ["-n", namespace, "get", "networkpolicy", "-o", "json"],
        label="NetworkPolicies",
        run=run,
    )
    policy_names = sorted(
        str(_mapping(item.get("metadata")).get("name"))
        for item in _items(policies.get("items"))
    )

    gravitino_version = _parse_json_object(
        run(
            [
                kubectl,
                "-n",
                namespace,
                "exec",
                "statefulset/metadata-gravitino",
                "-c",
                "gravitino",
                "--",
                "curl",
                "-fsS",
                "--max-time",
                "15",
                "http://127.0.0.1:8090/api/version",
            ]
        ),
        "Gravitino version",
    )
    run(
        [
            kubectl,
            "-n",
            namespace,
            "exec",
            "statefulset/metadata-gravitino",
            "-c",
            "gravitino",
            "--",
            "curl",
            "-fsS",
            "--max-time",
            "15",
            "http://127.0.0.1:8090/api/health/ready",
        ]
    )
    openmetadata_version = _parse_json_object(
        run(
            [
                kubectl,
                "-n",
                namespace,
                "exec",
                "deployment/openmetadata",
                "-c",
                "openmetadata",
                "--",
                "wget",
                "-qO-",
                "-T",
                "15",
                "http://127.0.0.1:8585/api/v1/system/version",
            ]
        ),
        "OpenMetadata version",
    )
    openmetadata_health = run(
        [
            kubectl,
            "-n",
            namespace,
            "exec",
            "deployment/openmetadata",
            "-c",
            "openmetadata",
            "--",
            "wget",
            "-qO-",
            "-T",
            "15",
            "http://127.0.0.1:8585/api/v1/system/health",
        ]
    ).strip()

    openmetadata_tables = run(
        [
            kubectl,
            "-n",
            namespace,
            "exec",
            "statefulset/metadata-openmetadata-postgresql",
            "--",
            "psql",
            "-U",
            "openmetadata_user",
            "-d",
            "openmetadata_db",
            "-Atc",
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name;",
        ]
    )
    gravitino_tables = run(
        [
            kubectl,
            "-n",
            namespace,
            "exec",
            "statefulset/metadata-gravitino-postgresql",
            "--",
            "psql",
            "-U",
            "gravitino",
            "-d",
            "gravitino",
            "-Atc",
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name;",
        ]
    )
    opensearch_root = _parse_json_object(
        run(
            [
                kubectl,
                "-n",
                namespace,
                "exec",
                "statefulset/metadata-opensearch",
                "-c",
                "opensearch",
                "--",
                "curl",
                "-fsS",
                "--max-time",
                "15",
                "http://127.0.0.1:9200/",
            ]
        ),
        "OpenSearch root",
    )
    opensearch_indices = _parse_json_list(
        run(
            [
                kubectl,
                "-n",
                namespace,
                "exec",
                "statefulset/metadata-opensearch",
                "-c",
                "opensearch",
                "--",
                "curl",
                "-fsS",
                "--max-time",
                "15",
                "http://127.0.0.1:9200/_cat/indices?format=json&h=index",
            ]
        ),
        "OpenSearch indices",
    )
    index_names = sorted(
        str(_mapping(item).get("index"))
        for item in opensearch_indices
        if isinstance(_mapping(item).get("index"), str)
    )

    server_version = _mapping(version.get("serverVersion"))
    node_reports = []
    for node in _items(nodes.get("items")):
        metadata = _mapping(node.get("metadata"))
        node_info = _mapping(_mapping(node.get("status")).get("nodeInfo"))
        node_reports.append(
            {
                "name": metadata.get("name"),
                "architecture": node_info.get("architecture"),
                "kubelet_version": node_info.get("kubeletVersion"),
            }
        )

    collection = {
        "schema": COLLECTION_SCHEMA,
        "observed_at": current.isoformat(),
        "source_contract": _source_contract(),
        "cluster": {
            "context": context,
            "uid": _mapping(kube_system.get("metadata")).get("uid"),
            "server_version": server_version.get("gitVersion"),
            "nodes": sorted(node_reports, key=lambda item: str(item.get("name"))),
        },
        "namespace": {
            "name": _mapping(namespace_resource.get("metadata")).get("name"),
            "uid": _mapping(namespace_resource.get("metadata")).get("uid"),
        },
        "workloads": workload_reports,
        "services": service_reports,
        "pvcs": pvc_reports,
        "network_policy_names": policy_names,
        "providers": {
            "openmetadata": {
                "health": openmetadata_health,
                "version": openmetadata_version.get("version"),
                "revision": openmetadata_version.get("revision"),
            },
            "gravitino": {
                "ready": True,
                "version": _mapping(gravitino_version.get("version")).get(
                    "version"
                ),
                "revision": _mapping(gravitino_version.get("version")).get(
                    "gitCommit"
                ),
            },
        },
        "storage_markers": {
            "openmetadata_postgresql": _table_marker(openmetadata_tables),
            "gravitino_postgresql": _table_marker(gravitino_tables),
            "opensearch": {
                "cluster_uuid": opensearch_root.get("cluster_uuid"),
                "version": _mapping(opensearch_root.get("version")).get("number"),
                "index_count": len(index_names),
                "index_name_fingerprint": hashlib.sha256(
                    "\n".join(index_names).encode("utf-8")
                ).hexdigest(),
            },
        },
    }
    return {**collection, "collection_fingerprint": _canonical_sha256(collection)}


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _sensitive_paths(value: Any, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key)
            nested_path = f"{path}.{key_text}"
            if (
                key_text not in SAFE_SECURITY_FIELDS
                and SENSITIVE_KEY_PATTERN.search(key_text)
            ):
                found.append(nested_path)
            found.extend(_sensitive_paths(nested, nested_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.extend(_sensitive_paths(nested, f"{path}[{index}]"))
    return found


def _validate_collection(
    collection: Mapping[str, Any],
    *,
    label: str,
    now: datetime,
    max_age_seconds: float,
) -> list[str]:
    errors: list[str] = []
    if collection.get("schema") != COLLECTION_SCHEMA:
        errors.append(f"{label} collection schema is invalid")
    stable = dict(collection)
    fingerprint = stable.pop("collection_fingerprint", None)
    if fingerprint != _canonical_sha256(stable):
        errors.append(f"{label} collection fingerprint does not match")
    sensitive = _sensitive_paths(collection)
    if sensitive:
        errors.append(f"{label} collection contains forbidden sensitive fields")

    observed = _parse_timestamp(collection.get("observed_at"))
    if observed is None:
        errors.append(f"{label} observed_at is invalid")
    elif observed > now or (now - observed).total_seconds() > max_age_seconds:
        errors.append(f"{label} collection is stale or from the future")

    source = _mapping(collection.get("source_contract"))
    if source.get("static_contract_verified") is not True:
        errors.append(f"{label} source contract is not statically verified")
    if not isinstance(source.get("fingerprint"), str) or not SHA256_PATTERN.fullmatch(
        str(source.get("fingerprint"))
    ):
        errors.append(f"{label} source contract fingerprint is invalid")

    cluster = _mapping(collection.get("cluster"))
    if cluster.get("context") != "docker-desktop":
        errors.append(f"{label} cluster context is not docker-desktop")
    if not cluster.get("uid") or not cluster.get("server_version"):
        errors.append(f"{label} cluster identity or version is missing")
    nodes = _items(cluster.get("nodes"))
    if not nodes or {item.get("architecture") for item in nodes} != {"arm64"}:
        errors.append(f"{label} cluster nodes are not all arm64")
    namespace = _mapping(collection.get("namespace"))
    if namespace.get("name") != NAMESPACE:
        errors.append(f"{label} namespace is not {NAMESPACE}")
    if not namespace.get("uid"):
        errors.append(f"{label} namespace identity is missing")

    workloads = _mapping(collection.get("workloads"))
    if set(workloads) != set(WORKLOADS):
        errors.append(f"{label} workload inventory does not match the sandbox")
    for name, expected in WORKLOADS.items():
        workload = _mapping(workloads.get(name))
        expected_kind = (
            "Deployment" if expected["kind"] == "deployment" else "StatefulSet"
        )
        if workload.get("kind") != expected_kind:
            errors.append(f"{label} workload {name} kind does not match")
        if workload.get("desired_replicas") != 1 or workload.get("ready_replicas") != 1:
            errors.append(f"{label} workload {name} is not exactly one Ready replica")
        if workload.get("automount_service_account_token") is not False:
            errors.append(f"{label} workload {name} mounts a Kubernetes API token")
        service_account = workload.get("service_account_name")
        if not isinstance(service_account, str) or service_account == "default":
            errors.append(f"{label} workload {name} has no dedicated ServiceAccount")
        if workload.get("image") != expected["image"]:
            errors.append(f"{label} workload {name} image does not match")
        if workload.get("image_pull_policy") != expected["pull_policy"]:
            errors.append(f"{label} workload {name} pull policy does not match")
        pods = _items(workload.get("pods"))
        if len(pods) != 1:
            errors.append(f"{label} workload {name} does not have exactly one Pod")
            continue
        pod = pods[0]
        if pod.get("phase") != "Running" or pod.get("ready") is not True:
            errors.append(f"{label} workload {name} Pod is not Running and Ready")
        if pod.get("automount_service_account_token") is not False:
            errors.append(f"{label} workload {name} Pod mounts a Kubernetes API token")
        if pod.get("service_account_name") != service_account:
            errors.append(f"{label} workload {name} Pod identity does not match")
        if pod.get("image") != expected["image"]:
            errors.append(f"{label} workload {name} Pod image does not match")
        if not isinstance(pod.get("image_id"), str) or not pod.get("image_id"):
            errors.append(f"{label} workload {name} Pod image ID is missing")

    services = _mapping(collection.get("services"))
    if set(services) != SERVICES:
        errors.append(f"{label} Service inventory does not match the sandbox")
    for name in SERVICES:
        service = _mapping(services.get(name))
        if service.get("name") != name or not service.get("uid"):
            errors.append(f"{label} Service {name} identity is missing")
        if service.get("type") != "ClusterIP":
            errors.append(f"{label} Service {name} is not ClusterIP")
        if service.get("external_ips") or service.get("node_ports"):
            errors.append(f"{label} Service {name} has an external exposure")

    pvcs = _mapping(collection.get("pvcs"))
    if set(pvcs) != set(PVCS):
        errors.append(f"{label} PVC inventory does not match the sandbox")
    for name, capacity in PVCS.items():
        pvc = _mapping(pvcs.get(name))
        if pvc.get("name") != name:
            errors.append(f"{label} PVC {name} identity does not match")
        if pvc.get("phase") != "Bound" or pvc.get("capacity") != capacity:
            errors.append(f"{label} PVC {name} is not Bound at {capacity}")
        if not pvc.get("uid") or not pvc.get("volume_name"):
            errors.append(f"{label} PVC {name} has no persistent identity")

    if set(collection.get("network_policy_names") or []) != NETWORK_POLICIES:
        errors.append(f"{label} NetworkPolicy inventory does not match the sandbox")

    providers = _mapping(collection.get("providers"))
    openmetadata = _mapping(providers.get("openmetadata"))
    if openmetadata != {
        "health": "OK",
        "version": OPENMETADATA_VERSION,
        "revision": OPENMETADATA_SERVER_COMMIT,
    }:
        errors.append(f"{label} OpenMetadata health or version does not match")
    gravitino = _mapping(providers.get("gravitino"))
    if gravitino != {
        "ready": True,
        "version": GRAVITINO_VERSION,
        "revision": GRAVITINO_TAG_COMMIT,
    }:
        errors.append(f"{label} Gravitino health or version does not match")

    storage = _mapping(collection.get("storage_markers"))
    for name in ("openmetadata_postgresql", "gravitino_postgresql"):
        marker = _mapping(storage.get(name))
        if not isinstance(marker.get("table_count"), int) or marker.get("table_count", 0) <= 0:
            errors.append(f"{label} {name} has no schema tables")
        if not isinstance(marker.get("table_name_fingerprint"), str) or not SHA256_PATTERN.fullmatch(
            str(marker.get("table_name_fingerprint"))
        ):
            errors.append(f"{label} {name} table fingerprint is invalid")
    opensearch = _mapping(storage.get("opensearch"))
    if opensearch.get("version") != OPENSEARCH_VERSION:
        errors.append(f"{label} OpenSearch version does not match")
    if not opensearch.get("cluster_uuid") or opensearch.get("index_count", 0) <= 0:
        errors.append(f"{label} OpenSearch persistent marker is missing")
    if not isinstance(opensearch.get("index_name_fingerprint"), str) or not SHA256_PATTERN.fullmatch(
        str(opensearch.get("index_name_fingerprint"))
    ):
        errors.append(f"{label} OpenSearch index fingerprint is invalid")
    return errors


def _restart_errors(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> list[str]:
    errors: list[str] = []
    if _mapping(before.get("source_contract")).get("fingerprint") != _mapping(
        after.get("source_contract")
    ).get("fingerprint"):
        errors.append("source contract changed across the restart")
    if _mapping(before.get("cluster")).get("uid") != _mapping(
        after.get("cluster")
    ).get("uid"):
        errors.append("cluster identity changed across the restart")
    if _mapping(before.get("namespace")).get("uid") != _mapping(
        after.get("namespace")
    ).get("uid"):
        errors.append("namespace identity changed across the restart")

    before_workloads = _mapping(before.get("workloads"))
    after_workloads = _mapping(after.get("workloads"))
    for name in WORKLOADS:
        old = _mapping(before_workloads.get(name))
        new = _mapping(after_workloads.get(name))
        if old.get("uid") != new.get("uid"):
            errors.append(f"workload identity changed across restart: {name}")
        old_pods = _items(old.get("pods"))
        new_pods = _items(new.get("pods"))
        if len(old_pods) != 1 or len(new_pods) != 1:
            errors.append(f"Pod identity is unavailable across restart: {name}")
        elif old_pods[0].get("uid") == new_pods[0].get("uid"):
            errors.append(f"Pod was not replaced during restart: {name}")

    if before.get("pvcs") != after.get("pvcs"):
        errors.append("PVC identity or capacity changed across the restart")
    if before.get("services") != after.get("services"):
        errors.append("Service identity or exposure changed across the restart")
    if before.get("storage_markers") != after.get("storage_markers"):
        errors.append("persistent schema or index markers changed across the restart")
    return errors


def build_live_metadata_fabric_evidence(
    before: Mapping[str, Any],
    after: Mapping[str, Any] | None = None,
    *,
    now: datetime | None = None,
    max_age_seconds: float = 900,
) -> dict[str, Any]:
    """Verify live foundation health and optional controlled-restart continuity."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise MetadataFabricLiveEvidenceError("verification time must be timezone-aware")
    errors = _validate_collection(
        before,
        label="before",
        now=current,
        max_age_seconds=max_age_seconds,
    )
    checks = {"before_collection": "passed" if not errors else "blocked"}
    restart_verified = False
    current_observation = before
    if after is not None:
        after_errors = _validate_collection(
            after,
            label="after",
            now=current,
            max_age_seconds=max_age_seconds,
        )
        errors.extend(after_errors)
        checks["after_collection"] = "passed" if not after_errors else "blocked"
        restart_failures = _restart_errors(before, after)
        errors.extend(restart_failures)
        restart_verified = not after_errors and not restart_failures
        checks["controlled_restart"] = "passed" if restart_verified else "blocked"
        current_observation = after
    else:
        checks["after_collection"] = "not_run"
        checks["controlled_restart"] = "not_run"

    live_verified = not errors
    checks["production_boundaries"] = "passed"
    stable = {
        "schema": EVIDENCE_SCHEMA,
        "environment": "local_foundation_sandbox",
        "namespace": NAMESPACE,
        "source_contract_fingerprint": _mapping(
            current_observation.get("source_contract")
        ).get("fingerprint"),
        "before_collection_fingerprint": before.get("collection_fingerprint"),
        "after_collection_fingerprint": (
            after.get("collection_fingerprint") if after is not None else None
        ),
        "checks": checks,
        "errors": errors,
        "live_foundation_verified": live_verified,
        "local_persistence_restart_verified": restart_verified,
        "production_provider_verified": False,
        "production_table_catalog_provider_verified": False,
        "network_policy_enforcement_verified": False,
        "oidc_verified": False,
        "backup_restore_verified": False,
        "upgrade_verified": False,
        "writes_to_gda_enabled": False,
        "production_ready": False,
        "before": before,
        "after": after,
    }
    return {
        **stable,
        "generated_at": current.isoformat(),
        "status": "live_foundation_verified" if live_verified else "blocked",
        "persistence_configured": live_verified,
        "evidence_fingerprint": _canonical_sha256(stable),
    }


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MetadataFabricLiveEvidenceError("JSON evidence must be an object")
    return payload


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
    collect.add_argument("--kubectl", default="kubectl")
    collect.add_argument("--output", type=Path)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--before", type=Path, required=True)
    verify.add_argument("--after", type=Path)
    verify.add_argument("--max-age-seconds", type=float, default=900)
    verify.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.command == "collect":
            report = collect_live_metadata_fabric(
                namespace=args.namespace, kubectl=args.kubectl
            )
            _write_report(report, args.output)
            return 0
        report = build_live_metadata_fabric_evidence(
            _load_json_object(args.before),
            _load_json_object(args.after) if args.after else None,
            max_age_seconds=args.max_age_seconds,
        )
    except (
        OSError,
        json.JSONDecodeError,
        MetadataFabricLiveEvidenceError,
    ) as exc:
        detail = (
            str(exc)
            if isinstance(exc, MetadataFabricLiveEvidenceError)
            else type(exc).__name__
        )
        report = {
            "schema": EVIDENCE_SCHEMA,
            "status": "error",
            "live_foundation_verified": False,
            "local_persistence_restart_verified": False,
            "production_provider_verified": False,
            "production_ready": False,
            "error": f"live evidence input is invalid: {detail}",
        }
        _write_report(report, args.output)
        return 2

    _write_report(report, args.output)
    return 0 if report["live_foundation_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
