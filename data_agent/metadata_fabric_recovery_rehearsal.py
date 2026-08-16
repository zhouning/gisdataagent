"""Verify an isolated backup/restore rehearsal for the metadata fabric.

The live runner quiesces only the two metadata provider applications, creates
logical PostgreSQL dumps and an OpenSearch filesystem snapshot, optionally
round-trips those artifacts through an external repository callback, restores
all three stores into an ephemeral namespace with new PVCs, compares allowlisted
content markers, restores source availability, and removes the recovery
namespace and local backup files. It does not prove production RPO/RTO,
cross-cluster disaster recovery, OIDC, or production readiness.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import tarfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from .metadata_fabric_sandbox import (
    NAMESPACE as SOURCE_NAMESPACE,
    OPENSEARCH_VERSION,
    POSTGRESQL_VERSION,
    build_sandbox_report,
)

OBSERVATION_SCHEMA = "gda.metadata_fabric_recovery_observation.v1"
EVIDENCE_SCHEMA = "gda.metadata_fabric_recovery_evidence.v1"
CONTRACT_SCHEMA = "gda.metadata_fabric_recovery_contract.v1"
RECOVERY_NAMESPACE = "gda-metadata-recovery-rehearsal"
POSTGRESQL_IMAGE = f"postgres:{POSTGRESQL_VERSION}"
OPENSEARCH_IMAGE = f"opensearchproject/opensearch:{OPENSEARCH_VERSION}"
SNAPSHOT_REPOSITORY = "gda-recovery-rehearsal"
SNAPSHOT_MOUNT_PATH = "/var/lib/gda-snapshots"
SNAPSHOT_PATH = f"{SNAPSHOT_MOUNT_PATH}/repository"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECOVERY_MANIFEST_DIR = REPO_ROOT / "k8s/metadata-fabric-recovery-rehearsal"
DEFAULT_SOURCE_OPENSEARCH = REPO_ROOT / "k8s/metadata-fabric-sandbox/opensearch.yaml"
DEFAULT_WRAPPER = REPO_ROOT / "scripts/metadata-fabric-recovery-rehearsal.sh"

POSTGRES_TARGETS = {
    "openmetadata_postgresql": {
        "source_pod": "metadata-openmetadata-postgresql-0",
        "recovery_pod": "recovery-openmetadata-postgresql-0",
        "recovery_statefulset": "recovery-openmetadata-postgresql",
        "format": "postgresql_custom_dump_v1",
    },
    "gravitino_postgresql": {
        "source_pod": "metadata-gravitino-postgresql-0",
        "recovery_pod": "recovery-gravitino-postgresql-0",
        "recovery_statefulset": "recovery-gravitino-postgresql",
        "format": "postgresql_custom_dump_v1",
    },
}
RECOVERY_STATEFULSETS = {
    "recovery-openmetadata-postgresql": POSTGRESQL_IMAGE,
    "recovery-gravitino-postgresql": POSTGRESQL_IMAGE,
    "recovery-opensearch": OPENSEARCH_IMAGE,
}
RECOVERY_PVCS = {
    "recovery-openmetadata-data-recovery-openmetadata-postgresql-0": "2Gi",
    "recovery-gravitino-data-recovery-gravitino-postgresql-0": "2Gi",
    "recovery-opensearch-data-recovery-opensearch-0": "8Gi",
}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SENSITIVE_KEY_PATTERN = re.compile(
    r"(^|[-_.])(password|passwd|secret|token|private[-_.]?key|access[-_.]?key)($|[-_.])",
    re.IGNORECASE,
)


class MetadataFabricRecoveryError(RuntimeError):
    """The recovery contract or live rehearsal failed closed."""


ArtifactRoundTrip = Callable[
    [Mapping[str, Path], Mapping[str, Mapping[str, Any]]], Mapping[str, Any]
]


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_documents(path: Path) -> list[dict[str, Any]]:
    return [
        item
        for item in yaml.safe_load_all(path.read_text(encoding="utf-8"))
        if isinstance(item, dict)
    ]


def _resource(
    documents: list[dict[str, Any]], kind: str, name: str
) -> dict[str, Any] | None:
    for document in documents:
        if document.get("kind") != kind:
            continue
        if ((document.get("metadata") or {}).get("name")) == name:
            return document
    return None


def _pod_spec(document: Mapping[str, Any]) -> Mapping[str, Any]:
    spec = document.get("spec") or {}
    return ((spec.get("template") or {}).get("spec") or {})


def _container(document: Mapping[str, Any]) -> Mapping[str, Any]:
    containers = list(_pod_spec(document).get("containers") or [])
    return containers[0] if containers and isinstance(containers[0], dict) else {}


def _sensitive_paths(value: Any, path: tuple[str, ...] = ()) -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key)
            child = (*path, key_text)
            if SENSITIVE_KEY_PATTERN.search(key_text):
                found.append(".".join(child))
            found.extend(_sensitive_paths(nested, child))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.extend(_sensitive_paths(nested, (*path, str(index))))
    return found


def build_recovery_contract_report(
    recovery_manifest_dir: Path | None = None,
    source_opensearch_path: Path | None = None,
    wrapper_path: Path | None = None,
) -> dict[str, Any]:
    """Validate the static rehearsal boundary without claiming a live restore."""
    manifest_dir = (recovery_manifest_dir or DEFAULT_RECOVERY_MANIFEST_DIR).resolve()
    source_path = (source_opensearch_path or DEFAULT_SOURCE_OPENSEARCH).resolve()
    wrapper = (wrapper_path or DEFAULT_WRAPPER).resolve()
    errors: list[str] = []
    documents: list[dict[str, Any]] = []
    resource_paths: list[Path] = []
    kustomization_path = manifest_dir / "kustomization.yaml"

    try:
        kustomization = yaml.safe_load(kustomization_path.read_text(encoding="utf-8"))
        if not isinstance(kustomization, dict):
            raise TypeError("Kustomization is not an object")
        if kustomization.get("namespace") != RECOVERY_NAMESPACE:
            errors.append("recovery Kustomization must target the isolated namespace")
        for relative in kustomization.get("resources") or []:
            path = (manifest_dir / str(relative)).resolve()
            if path.parent != manifest_dir:
                errors.append("recovery resources must stay inside the manifest directory")
                continue
            resource_paths.append(path)
            documents.extend(_load_documents(path))
    except (OSError, TypeError, yaml.YAMLError) as exc:
        errors.append(f"recovery Kustomization is invalid: {type(exc).__name__}")

    namespace = _resource(documents, "Namespace", RECOVERY_NAMESPACE)
    if namespace is None:
        errors.append("recovery rehearsal must define its exact ephemeral Namespace")
    elif ((namespace.get("metadata") or {}).get("labels") or {}).get(
        "gda.openai.com/ephemeral-owner"
    ) != "metadata-recovery-rehearsal":
        errors.append("recovery Namespace must carry the cleanup ownership label")

    quota = _resource(documents, "ResourceQuota", "metadata-recovery-rehearsal") or {}
    quota_hard = ((quota.get("spec") or {}).get("hard") or {})
    if str(quota_hard.get("persistentvolumeclaims")) != "3":
        errors.append("recovery quota must allow exactly three PVCs")
    if str(quota_hard.get("requests.storage")) != "16Gi":
        errors.append("recovery storage quota must remain bounded at 16Gi")

    forbidden_kinds = {"Secret", "Service", "Ingress", "Gateway", "HTTPRoute", "Route"}
    for document in documents:
        kind = str(document.get("kind"))
        name = str((document.get("metadata") or {}).get("name"))
        if kind in forbidden_kinds:
            errors.append(f"{kind}/{name} is forbidden in the recovery manifests")
        if kind != "Namespace" and (document.get("metadata") or {}).get(
            "namespace"
        ) != RECOVERY_NAMESPACE:
            errors.append(f"{kind}/{name} is outside the recovery namespace")

    statefulsets = {
        str((item.get("metadata") or {}).get("name")): item
        for item in documents
        if item.get("kind") == "StatefulSet"
    }
    if set(statefulsets) != set(RECOVERY_STATEFULSETS):
        errors.append("recovery StatefulSet inventory does not match the contract")
    for name, image in RECOVERY_STATEFULSETS.items():
        workload = statefulsets.get(name) or {}
        pod = _pod_spec(workload)
        container = _container(workload)
        if pod.get("serviceAccountName") != name:
            errors.append(f"StatefulSet/{name} must use its dedicated ServiceAccount")
        if pod.get("automountServiceAccountToken") is not False:
            errors.append(f"StatefulSet/{name} must disable API token mounting")
        if container.get("image") != image:
            errors.append(f"StatefulSet/{name} image does not match the source version")
        security = container.get("securityContext") or {}
        if security.get("allowPrivilegeEscalation") is not False:
            errors.append(f"StatefulSet/{name} may not allow privilege escalation")
        if security.get("readOnlyRootFilesystem") is not True:
            errors.append(f"StatefulSet/{name} must use a read-only root filesystem")
        if any("hostPath" in volume for volume in pod.get("volumes") or []):
            errors.append(f"StatefulSet/{name} may not use hostPath")
        templates = (workload.get("spec") or {}).get("volumeClaimTemplates") or []
        if len(templates) != 1:
            errors.append(f"StatefulSet/{name} must define exactly one recovery PVC")
        if name == "recovery-opensearch":
            mounts = {
                item.get("name"): item.get("mountPath")
                for item in container.get("volumeMounts") or []
                if isinstance(item, dict)
            }
            volumes = {
                item.get("name"): item
                for item in pod.get("volumes") or []
                if isinstance(item, dict)
            }
            if mounts.get("logs") != "/usr/share/opensearch/logs":
                errors.append("recovery OpenSearch must mount its writable logs directory")
            if "emptyDir" not in (volumes.get("logs") or {}):
                errors.append("recovery OpenSearch logs must use an ephemeral volume")
            if mounts.get("config") != "/usr/share/opensearch/config":
                errors.append("recovery OpenSearch must mount its writable config directory")
            if "emptyDir" not in (volumes.get("config") or {}):
                errors.append("recovery OpenSearch config must use an ephemeral volume")
            env = {
                item.get("name"): item.get("value")
                for item in container.get("env") or []
                if isinstance(item, dict)
            }
            if env.get("path.repo") != SNAPSHOT_MOUNT_PATH:
                errors.append("recovery OpenSearch must pin the snapshot parent path")
            if mounts.get("snapshot-staging") != SNAPSHOT_MOUNT_PATH:
                errors.append("recovery OpenSearch must mount snapshot staging")
            init_containers = pod.get("initContainers") or []
            prepare = next(
                (
                    item
                    for item in init_containers
                    if isinstance(item, dict) and item.get("name") == "prepare-config"
                ),
                {},
            )
            if prepare.get("image") != OPENSEARCH_IMAGE:
                errors.append("recovery OpenSearch config init image must match the server")
            prepare_command = " ".join(str(item) for item in prepare.get("command") or [])
            if "cp -R /usr/share/opensearch/config/. /mnt/config/" not in prepare_command:
                errors.append("recovery OpenSearch must copy immutable image config")

    observed_pvcs: dict[str, str] = {}
    for name, workload in statefulsets.items():
        templates = (workload.get("spec") or {}).get("volumeClaimTemplates") or []
        for template in templates:
            template_name = (template.get("metadata") or {}).get("name")
            storage = (
                ((template.get("spec") or {}).get("resources") or {})
                .get("requests", {})
                .get("storage")
            )
            observed_pvcs[f"{template_name}-{name}-0"] = str(storage)
    if observed_pvcs != RECOVERY_PVCS:
        errors.append("recovery PVC names or capacities do not match the contract")

    policy = _resource(documents, "NetworkPolicy", "recovery-default-deny") or {}
    policy_spec = policy.get("spec") or {}
    if set(policy_spec.get("policyTypes") or []) != {"Ingress", "Egress"}:
        errors.append("recovery Namespace must default-deny ingress and egress")
    if policy_spec.get("ingress") or policy_spec.get("egress"):
        errors.append("recovery default-deny policy may not add allow rules")

    try:
        source_documents = _load_documents(source_path)
        source = _resource(source_documents, "StatefulSet", "metadata-opensearch") or {}
        source_container = _container(source)
        env = {
            item.get("name"): item.get("value")
            for item in source_container.get("env") or []
            if isinstance(item, dict)
        }
        mounts = {
            item.get("name"): item.get("mountPath")
            for item in source_container.get("volumeMounts") or []
            if isinstance(item, dict)
        }
        volumes = {
            item.get("name"): item
            for item in _pod_spec(source).get("volumes") or []
            if isinstance(item, dict)
        }
        if env.get("path.repo") != SNAPSHOT_MOUNT_PATH:
            errors.append("source OpenSearch must pin the isolated snapshot path")
        if mounts.get("snapshot-staging") != SNAPSHOT_MOUNT_PATH:
            errors.append("source OpenSearch must mount the snapshot staging directory")
        if "emptyDir" not in (volumes.get("snapshot-staging") or {}):
            errors.append("source snapshot staging must be ephemeral and separate from data")
        if mounts.get("logs") != "/usr/share/opensearch/logs":
            errors.append("source OpenSearch must mount its writable logs directory")
        if "emptyDir" not in (volumes.get("logs") or {}):
            errors.append("source OpenSearch logs must use an ephemeral volume")
        if mounts.get("config") != "/usr/share/opensearch/config":
            errors.append("source OpenSearch must mount its writable config directory")
        if "emptyDir" not in (volumes.get("config") or {}):
            errors.append("source OpenSearch config must use an ephemeral volume")
        init_containers = _pod_spec(source).get("initContainers") or []
        prepare = next(
            (
                item
                for item in init_containers
                if isinstance(item, dict) and item.get("name") == "prepare-config"
            ),
            {},
        )
        if prepare.get("image") != OPENSEARCH_IMAGE:
            errors.append("source OpenSearch config init image must match the server")
    except (OSError, yaml.YAMLError) as exc:
        errors.append(f"source OpenSearch manifest is invalid: {type(exc).__name__}")

    try:
        wrapper_text = wrapper.read_text(encoding="utf-8")
        for marker in ("set -euo pipefail", "metadata_fabric_recovery_rehearsal"):
            if marker not in wrapper_text:
                errors.append(f"recovery wrapper is missing safety marker: {marker}")
    except OSError as exc:
        errors.append(f"recovery wrapper is invalid: {type(exc).__name__}")

    files: dict[str, dict[str, str]] = {}
    for path in [
        Path(__file__).resolve(),
        kustomization_path,
        *resource_paths,
        source_path,
        wrapper,
    ]:
        if path.is_file():
            try:
                relative_path = path.relative_to(REPO_ROOT).as_posix()
            except ValueError:
                relative_path = path.name
            files[relative_path] = {
                "path": relative_path,
                "sha256": _file_sha256(path),
            }
    stable = {
        "schema": CONTRACT_SCHEMA,
        "source_namespace": SOURCE_NAMESPACE,
        "recovery_namespace": RECOVERY_NAMESPACE,
        "stores": sorted([*POSTGRES_TARGETS, "opensearch"]),
        "static_contract_verified": not errors,
        "live_recovery_verified": False,
        "files": files,
        "errors": errors,
    }
    return {**stable, "contract_fingerprint": _canonical_sha256(stable)}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _valid_fingerprint(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_PATTERN.fullmatch(value))


def _marker_errors(name: str, source: Mapping[str, Any], recovered: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if name.endswith("postgresql"):
        if not isinstance(source.get("table_count"), int) or source.get("table_count", 0) <= 0:
            errors.append(f"{name} source table inventory is empty")
        if source.get("image_version") != POSTGRESQL_VERSION:
            errors.append(f"{name} source image version does not match the contract")
        if not str(source.get("server_version", "")).startswith("16.10"):
            errors.append(f"{name} source server version does not match the contract")
        for key in (
            "table_name_fingerprint",
            "row_count_fingerprint",
            "sequence_state_fingerprint",
            "extension_fingerprint",
        ):
            if not _valid_fingerprint(source.get(key)):
                errors.append(f"{name} source {key} is invalid")
        if source != recovered:
            errors.append(f"{name} recovered content markers differ from source")
        return errors

    if not isinstance(source.get("index_count"), int) or source.get("index_count", 0) <= 0:
        errors.append("opensearch source index inventory is empty")
    if source.get("version") != OPENSEARCH_VERSION:
        errors.append("opensearch source version does not match the contract")
    for key in ("index_name_fingerprint", "document_count_fingerprint"):
        if not _valid_fingerprint(source.get(key)):
            errors.append(f"opensearch source {key} is invalid")
    comparable_source = {key: value for key, value in source.items() if key != "cluster_uuid"}
    comparable_recovered = {
        key: value for key, value in recovered.items() if key != "cluster_uuid"
    }
    if comparable_source != comparable_recovered:
        errors.append("opensearch recovered content markers differ from source")
    if not source.get("cluster_uuid") or not recovered.get("cluster_uuid"):
        errors.append("opensearch cluster identity is unavailable")
    elif source.get("cluster_uuid") == recovered.get("cluster_uuid"):
        errors.append("opensearch restore target is not an independent cluster")
    return errors


def _observation_errors(
    observation: Mapping[str, Any], *, now: datetime, max_age_seconds: float
) -> list[str]:
    errors: list[str] = []
    if _sensitive_paths(observation):
        errors.append("observation contains forbidden credential-bearing fields")
    if observation.get("schema") != OBSERVATION_SCHEMA:
        errors.append("observation schema does not match")
    try:
        observed_at = datetime.fromisoformat(str(observation.get("observed_at")))
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError
        age = (now - observed_at).total_seconds()
        if age < -30 or age > max_age_seconds:
            errors.append("observation is outside the accepted freshness window")
    except ValueError:
        errors.append("observation timestamp is invalid")

    contract = _mapping(observation.get("contract"))
    if contract.get("static_contract_verified") is not True:
        errors.append("static recovery contract was not verified")
    if not _valid_fingerprint(contract.get("contract_fingerprint")):
        errors.append("static recovery contract fingerprint is invalid")

    cluster = _mapping(observation.get("cluster"))
    source_context = cluster.get("context")
    source_cluster_uid = cluster.get("uid")
    recovery_context = cluster.get("recovery_context", source_context)
    recovery_cluster_uid = cluster.get("recovery_uid", source_cluster_uid)
    if source_context != "docker-desktop" or not source_cluster_uid:
        errors.append("rehearsal did not run on the bounded Docker Desktop cluster")
    if not recovery_context or not recovery_cluster_uid:
        errors.append("recovery cluster identity is unavailable")
    if (source_context == recovery_context) != (
        source_cluster_uid == recovery_cluster_uid
    ):
        errors.append("source and recovery cluster context/identity isolation disagrees")
    source_ns = _mapping(cluster.get("source_namespace"))
    recovery_ns = _mapping(cluster.get("recovery_namespace"))
    if source_ns.get("name") != SOURCE_NAMESPACE or not source_ns.get("uid"):
        errors.append("source Namespace identity does not match")
    if recovery_ns.get("name") != RECOVERY_NAMESPACE or not recovery_ns.get("uid"):
        errors.append("recovery Namespace identity does not match")
    if source_ns.get("uid") == recovery_ns.get("uid"):
        errors.append("source and recovery Namespace identities are not isolated")

    pvcs = _mapping(observation.get("recovery_pvcs"))
    if set(pvcs) != set(RECOVERY_PVCS):
        errors.append("recovery PVC inventory does not match")
    for name, capacity in RECOVERY_PVCS.items():
        pvc = _mapping(pvcs.get(name))
        if pvc.get("capacity") != capacity or pvc.get("phase") != "Bound":
            errors.append(f"recovery PVC {name} was not Bound at {capacity}")
        if not pvc.get("uid") or not pvc.get("volume_name"):
            errors.append(f"recovery PVC {name} has no independent identity")

    artifacts = _mapping(observation.get("artifacts"))
    expected_formats = {
        "openmetadata_postgresql": "postgresql_custom_dump_v1",
        "gravitino_postgresql": "postgresql_custom_dump_v1",
        "opensearch": "opensearch_fs_snapshot_tar_gzip_v1",
    }
    if set(artifacts) != set(expected_formats):
        errors.append("backup artifact inventory does not match")
    for name, expected_format in expected_formats.items():
        artifact = _mapping(artifacts.get(name))
        if artifact.get("format") != expected_format:
            errors.append(f"{name} backup format does not match")
        if not _valid_fingerprint(artifact.get("sha256")):
            errors.append(f"{name} backup artifact fingerprint is invalid")
        if not isinstance(artifact.get("bytes"), int) or artifact.get("bytes", 0) <= 0:
            errors.append(f"{name} backup artifact is empty")

    source_markers = _mapping(observation.get("source_markers"))
    recovered_markers = _mapping(observation.get("recovered_markers"))
    for name in (*POSTGRES_TARGETS, "opensearch"):
        errors.extend(
            _marker_errors(
                name,
                _mapping(source_markers.get(name)),
                _mapping(recovered_markers.get(name)),
            )
        )

    checks = _mapping(observation.get("runtime_checks"))
    required_true = (
        "source_quiesced",
        "source_snapshot_staging_initially_empty",
        "recovery_search_target_cleared",
        "source_services_restored",
        "source_snapshot_staging_cleaned",
        "recovery_namespace_removed",
        "local_artifacts_removed",
    )
    for key in required_true:
        if checks.get(key) is not True:
            errors.append(f"runtime check did not pass: {key}")
    return errors


def build_recovery_evidence(
    observation: Mapping[str, Any],
    *,
    now: datetime | None = None,
    max_age_seconds: float = 3600,
) -> dict[str, Any]:
    """Build fail-closed evidence for a local isolated recovery rehearsal."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise MetadataFabricRecoveryError("verification time must be timezone-aware")
    errors = _observation_errors(
        observation, now=current, max_age_seconds=max_age_seconds
    )
    verified = not errors
    cluster = _mapping(observation.get("cluster"))
    source_context = cluster.get("context")
    source_cluster_uid = cluster.get("uid")
    recovery_context = cluster.get("recovery_context", source_context)
    recovery_cluster_uid = cluster.get("recovery_uid", source_cluster_uid)
    cross_cluster = (
        source_context != recovery_context
        and source_cluster_uid != recovery_cluster_uid
    )
    scope = (
        "local_distinct_kubernetes_clusters_new_namespace_and_pvcs"
        if cross_cluster
        else "local_same_cluster_new_namespace_and_pvcs"
    )
    stable = {
        "schema": EVIDENCE_SCHEMA,
        "environment": (
            "local_cross_cluster_recovery_rehearsal"
            if cross_cluster
            else "local_isolated_recovery_rehearsal"
        ),
        "source_namespace": SOURCE_NAMESPACE,
        "recovery_namespace": RECOVERY_NAMESPACE,
        "observation_fingerprint": _canonical_sha256(observation),
        "checks": {
            "static_contract": "passed" if verified else "blocked",
            "artifact_integrity": "passed" if verified else "blocked",
            "postgresql_restore": "passed" if verified else "blocked",
            "opensearch_restore": "passed" if verified else "blocked",
            "source_availability_restored": "passed" if verified else "blocked",
            "ephemeral_cleanup": "passed" if verified else "blocked",
            "production_boundaries": "passed",
        },
        "errors": errors,
        "backup_restore_scope": scope,
        "backup_restore_verified": verified,
        "local_backup_restore_verified": verified,
        "local_cross_cluster_recovery_verified": verified and cross_cluster,
        "production_backup_restore_verified": False,
        "production_cross_cluster_recovery_verified": False,
        "rpo_slo_verified": False,
        "rto_slo_verified": False,
        "cross_cluster_recovery_verified": False,
        "cross_region_recovery_verified": False,
        "oidc_verified": False,
        "network_policy_enforcement_verified": False,
        "upgrade_verified": False,
        "writes_to_gda_enabled": False,
        "production_ready": False,
        "observation": observation,
    }
    return {
        **stable,
        "generated_at": current.isoformat(),
        "status": (
            "local_cross_cluster_backup_restore_verified"
            if verified and cross_cluster
            else "local_backup_restore_verified"
            if verified
            else "blocked"
        ),
        "evidence_fingerprint": _canonical_sha256(stable),
    }


def verify_evidence_integrity(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if _sensitive_paths(report):
        errors.append("evidence contains forbidden credential-bearing fields")
    if report.get("schema") != EVIDENCE_SCHEMA:
        errors.append("evidence schema does not match")
    stable = {
        key: value
        for key, value in report.items()
        if key not in {"generated_at", "status", "evidence_fingerprint"}
    }
    if report.get("evidence_fingerprint") != _canonical_sha256(stable):
        errors.append("evidence fingerprint does not match its stable content")
    if report.get("production_backup_restore_verified") is not False:
        errors.append("evidence may not claim production backup/restore")
    if report.get("production_cross_cluster_recovery_verified") is not False:
        errors.append("evidence may not claim production cross-cluster recovery")
    if report.get("production_ready") is not False:
        errors.append("evidence may not claim production readiness")
    return errors


class _CommandRunner:
    def __init__(self, kubectl: str = "kubectl", context: str | None = None) -> None:
        self.kubectl = kubectl
        self.context = context

    def kubectl_args(self, args: list[str]) -> list[str]:
        command = [self.kubectl]
        if self.context is not None:
            command.extend(["--context", self.context])
        return [*command, *args]

    def run(
        self,
        args: list[str],
        *,
        input_bytes: bytes | None = None,
        timeout: int = 120,
        label: str | None = None,
    ) -> bytes:
        try:
            completed = subprocess.run(
                args,
                input=input_bytes,
                capture_output=True,
                check=False,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise MetadataFabricRecoveryError(
                f"{label or args[0]} was unavailable"
            ) from exc
        if completed.returncode != 0:
            raise MetadataFabricRecoveryError(f"{label or args[0]} failed")
        return completed.stdout

    def kubectl_run(
        self,
        args: list[str],
        *,
        input_bytes: bytes | None = None,
        timeout: int = 120,
        label: str,
    ) -> bytes:
        return self.run(
            self.kubectl_args(args),
            input_bytes=input_bytes,
            timeout=timeout,
            label=label,
        )

    def kubectl_json(self, args: list[str], *, label: str) -> dict[str, Any]:
        try:
            payload = json.loads(self.kubectl_run(args, label=label))
        except json.JSONDecodeError as exc:
            raise MetadataFabricRecoveryError(f"{label} returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise MetadataFabricRecoveryError(f"{label} did not return an object")
        return payload

    def namespace_exists(self, namespace: str) -> bool:
        try:
            completed = subprocess.run(
                self.kubectl_args(
                    ["get", "namespace", namespace, "-o", "name"]
                ),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise MetadataFabricRecoveryError("kubectl namespace check failed") from exc
        return completed.returncode == 0


def _decode(value: bytes, label: str) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MetadataFabricRecoveryError(f"{label} returned non-text output") from exc


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("utf-8")


def _json_output(value: bytes, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise MetadataFabricRecoveryError(f"{label} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise MetadataFabricRecoveryError(f"{label} did not return an object")
    return payload


def _write_private(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def _artifact(path: Path, format_name: str) -> dict[str, Any]:
    return {
        "format": format_name,
        "sha256": _file_sha256(path),
        "bytes": path.stat().st_size,
    }


def _validate_snapshot_archive(payload: bytes) -> None:
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            members = archive.getmembers()
    except tarfile.TarError as exc:
        raise MetadataFabricRecoveryError("OpenSearch snapshot artifact is invalid") from exc
    if not members:
        raise MetadataFabricRecoveryError("OpenSearch snapshot artifact is empty")
    for member in members:
        path = Path(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise MetadataFabricRecoveryError("OpenSearch snapshot artifact path is unsafe")
        if not path.parts or path.parts[0] != "repository":
            raise MetadataFabricRecoveryError("OpenSearch snapshot artifact root does not match")
        if member.issym() or member.islnk() or member.isdev():
            raise MetadataFabricRecoveryError("OpenSearch snapshot artifact type is unsafe")


def _fingerprint_lines(raw: str) -> tuple[int, str]:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    canonical = "\n".join(lines).encode("utf-8")
    return len(lines), hashlib.sha256(canonical).hexdigest()


def _postgres_query(
    runner: _CommandRunner, namespace: str, pod: str, sql: str, *, label: str
) -> str:
    command = (
        'PGPASSWORD="$POSTGRES_PASSWORD" '
        'psql -X -qAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" '
        '-d "$POSTGRES_DB"'
    )
    output = runner.kubectl_run(
        ["-n", namespace, "exec", "-i", f"pod/{pod}", "--", "sh", "-ceu", command],
        input_bytes=sql.encode("utf-8"),
        timeout=300,
        label=label,
    )
    return _decode(output, label)


def _postgres_marker(
    runner: _CommandRunner, namespace: str, pod: str, *, label: str
) -> dict[str, Any]:
    table_names = _postgres_query(
        runner,
        namespace,
        pod,
        """
SELECT schemaname || '.' || tablename
FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY schemaname, tablename;
""",
        label=f"{label} table inventory",
    )
    row_counts = _postgres_query(
        runner,
        namespace,
        pod,
        r"""
SELECT format(
  'SELECT %L || ''='' || count(*)::text FROM %I.%I;',
  schemaname || '.' || tablename,
  schemaname,
  tablename
)
FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY schemaname, tablename;
\gexec
        """,
        label=f"{label} row counts",
    )
    sequences = _postgres_query(
        runner,
        namespace,
        pod,
        r"""
SELECT format(
  'SELECT %L || ''='' || last_value::text || '':'' || is_called::text FROM %I.%I;',
  n.nspname || '.' || c.relname,
  n.nspname,
  c.relname
)
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'S'
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY n.nspname, c.relname;
\gexec
""",
        label=f"{label} sequence states",
    )
    extensions = _postgres_query(
        runner,
        namespace,
        pod,
        "SELECT extname || '=' || extversion FROM pg_extension ORDER BY extname;\n",
        label=f"{label} extensions",
    )
    server_version = _postgres_query(
        runner,
        namespace,
        pod,
        "SHOW server_version;\n",
        label=f"{label} server version",
    ).strip()
    table_count, table_fingerprint = _fingerprint_lines(table_names)
    _, row_fingerprint = _fingerprint_lines(row_counts)
    _, sequence_fingerprint = _fingerprint_lines(sequences)
    _, extension_fingerprint = _fingerprint_lines(extensions)
    return {
        "image_version": POSTGRESQL_VERSION,
        "server_version": server_version,
        "table_count": table_count,
        "table_name_fingerprint": table_fingerprint,
        "row_count_fingerprint": row_fingerprint,
        "sequence_state_fingerprint": sequence_fingerprint,
        "extension_fingerprint": extension_fingerprint,
    }


def _postgres_dump(
    runner: _CommandRunner, namespace: str, pod: str, *, label: str
) -> bytes:
    command = (
        'PGPASSWORD="$POSTGRES_PASSWORD" '
        'pg_dump -Fc --no-owner --no-privileges '
        '-U "$POSTGRES_USER" -d "$POSTGRES_DB"'
    )
    return runner.kubectl_run(
        ["-n", namespace, "exec", f"pod/{pod}", "--", "sh", "-ceu", command],
        timeout=600,
        label=label,
    )


def _postgres_restore(
    runner: _CommandRunner,
    namespace: str,
    pod: str,
    payload: bytes,
    *,
    label: str,
) -> None:
    command = (
        'PGPASSWORD="$POSTGRES_PASSWORD" '
        'pg_restore --exit-on-error --no-owner --no-privileges '
        '-U "$POSTGRES_USER" -d "$POSTGRES_DB"'
    )
    runner.kubectl_run(
        ["-n", namespace, "exec", "-i", f"pod/{pod}", "--", "sh", "-ceu", command],
        input_bytes=payload,
        timeout=900,
        label=label,
    )


def _opensearch_request(
    runner: _CommandRunner,
    namespace: str,
    pod: str,
    method: str,
    path: str,
    *,
    body: object | None = None,
    timeout: int = 180,
    label: str,
) -> dict[str, Any]:
    args = [
        "-n",
        namespace,
        "exec",
    ]
    if body is not None:
        args.append("-i")
    args.extend(
        [
            f"pod/{pod}",
            "-c",
            "opensearch",
            "--",
            "curl",
            "-fsS",
            "--max-time",
            str(timeout),
            "-X",
            method,
            "-H",
            "Content-Type: application/json",
            f"http://127.0.0.1:9200{path}",
        ]
    )
    input_bytes = None
    if body is not None:
        args.extend(["--data-binary", "@-"])
        input_bytes = _json_bytes(body)
    return _json_output(
        runner.kubectl_run(
            args,
            input_bytes=input_bytes,
            timeout=timeout + 30,
            label=label,
        ),
        label,
    )


def _opensearch_marker(
    runner: _CommandRunner,
    namespace: str,
    pod: str,
    *,
    expected_names: list[str] | None = None,
    label: str,
) -> tuple[dict[str, Any], list[str]]:
    root = _opensearch_request(
        runner, namespace, pod, "GET", "/", label=f"{label} identity"
    )
    raw = runner.kubectl_run(
        [
            "-n",
            namespace,
            "exec",
            f"pod/{pod}",
            "-c",
            "opensearch",
            "--",
            "curl",
            "-fsS",
            "--max-time",
            "30",
            "http://127.0.0.1:9200/_cat/indices?format=json&h=index,docs.count&expand_wildcards=all",
        ],
        label=f"{label} index inventory",
    )
    try:
        indices = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MetadataFabricRecoveryError(f"{label} index inventory is invalid") from exc
    if not isinstance(indices, list):
        raise MetadataFabricRecoveryError(f"{label} index inventory is not a list")
    by_name = {
        str(item.get("index")): str(item.get("docs.count"))
        for item in indices
        if isinstance(item, dict) and item.get("index")
    }
    names = sorted(expected_names if expected_names is not None else by_name)
    if any(name not in by_name for name in names):
        raise MetadataFabricRecoveryError(f"{label} is missing restored indexes")
    name_count, name_fingerprint = _fingerprint_lines("\n".join(names))
    _, document_fingerprint = _fingerprint_lines(
        "\n".join(f"{name}={by_name[name]}" for name in names)
    )
    version = ((_mapping(root.get("version"))).get("number"))
    return (
        {
            "version": version,
            "cluster_uuid": root.get("cluster_uuid"),
            "index_count": name_count,
            "total_index_count": len(by_name),
            "index_name_fingerprint": name_fingerprint,
            "document_count_fingerprint": document_fingerprint,
        },
        names,
    )


def _create_runtime_credential(
    runner: _CommandRunner, namespace: str, name: str, temp_dir: Path
) -> None:
    credential_file = temp_dir / f"{name}.credential"
    _write_private(credential_file, (secrets.token_hex(32) + "\n").encode("ascii"))
    rendered = runner.kubectl_run(
        [
            "-n",
            namespace,
            "create",
            "secret",
            "generic",
            name,
            f"--from-file=password={credential_file}",
            "--dry-run=client",
            "-o",
            "yaml",
        ],
        label=f"render runtime credential for {name}",
    )
    runner.kubectl_run(
        ["apply", "-f", "-"],
        input_bytes=rendered,
        label=f"apply runtime credential for {name}",
    )
    credential_file.unlink()


def _wait_for_no_pods(
    runner: _CommandRunner, namespace: str, selector: str, *, label: str
) -> None:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        payload = runner.kubectl_json(
            ["-n", namespace, "get", "pods", "-l", selector, "-o", "json"],
            label=label,
        )
        if not payload.get("items"):
            return
        time.sleep(2)
    raise MetadataFabricRecoveryError(f"{label} timed out")


def _namespace_identity(runner: _CommandRunner, namespace: str) -> dict[str, Any]:
    payload = runner.kubectl_json(
        ["get", "namespace", namespace, "-o", "json"],
        label=f"collect {namespace} identity",
    )
    metadata = payload.get("metadata") or {}
    return {"name": metadata.get("name"), "uid": metadata.get("uid")}


def _cluster_uid(runner: _CommandRunner) -> str | None:
    payload = runner.kubectl_json(
        ["get", "namespace", "kube-system", "-o", "json"],
        label="collect cluster identity",
    )
    return (payload.get("metadata") or {}).get("uid")


def _pvc_identities(runner: _CommandRunner) -> dict[str, Any]:
    payload = runner.kubectl_json(
        ["-n", RECOVERY_NAMESPACE, "get", "pvc", "-o", "json"],
        label="collect recovery PVC identities",
    )
    result: dict[str, Any] = {}
    for item in payload.get("items") or []:
        metadata = item.get("metadata") or {}
        spec = item.get("spec") or {}
        status = item.get("status") or {}
        name = metadata.get("name")
        if name:
            result[str(name)] = {
                "uid": metadata.get("uid"),
                "volume_name": spec.get("volumeName"),
                "capacity": (status.get("capacity") or {}).get("storage"),
                "phase": status.get("phase"),
            }
    return result


def _restore_source_services(
    runner: _CommandRunner, replicas: Mapping[str, int]
) -> bool:
    if "openmetadata" in replicas:
        runner.kubectl_run(
            [
                "-n",
                SOURCE_NAMESPACE,
                "scale",
                "deployment/openmetadata",
                f"--replicas={replicas['openmetadata']}",
            ],
            label="restore OpenMetadata replicas",
        )
    if "metadata-gravitino" in replicas:
        runner.kubectl_run(
            [
                "-n",
                SOURCE_NAMESPACE,
                "scale",
                "statefulset/metadata-gravitino",
                f"--replicas={replicas['metadata-gravitino']}",
            ],
            label="restore Gravitino replicas",
        )
    if replicas.get("metadata-gravitino", 0) > 0:
        runner.kubectl_run(
            [
                "-n",
                SOURCE_NAMESPACE,
                "rollout",
                "status",
                "statefulset/metadata-gravitino",
                "--timeout=15m",
            ],
            timeout=930,
            label="wait for restored Gravitino",
        )
    if replicas.get("openmetadata", 0) > 0:
        runner.kubectl_run(
            [
                "-n",
                SOURCE_NAMESPACE,
                "rollout",
                "status",
                "deployment/openmetadata",
                "--timeout=20m",
            ],
            timeout=1230,
            label="wait for restored OpenMetadata",
        )
    return True


def run_live_recovery_rehearsal(
    *,
    kubectl: str = "kubectl",
    source_context: str = "docker-desktop",
    recovery_context: str | None = None,
    artifact_round_trip: ArtifactRoundTrip | None = None,
) -> dict[str, Any]:
    """Execute the bounded local rehearsal and return an allowlisted observation."""
    target_context = recovery_context or source_context
    source_runner = _CommandRunner(kubectl, source_context)
    recovery_runner = (
        source_runner
        if target_context == source_context
        else _CommandRunner(kubectl, target_context)
    )
    started = datetime.now(UTC)
    contract = build_recovery_contract_report()
    if contract["static_contract_verified"] is not True:
        raise MetadataFabricRecoveryError("static recovery contract is invalid")
    sandbox = build_sandbox_report()
    if sandbox["static_contract_verified"] is not True:
        raise MetadataFabricRecoveryError("source sandbox contract is invalid")
    if source_context != "docker-desktop":
        raise MetadataFabricRecoveryError("recovery rehearsal requires docker-desktop")
    if recovery_runner.namespace_exists(RECOVERY_NAMESPACE):
        raise MetadataFabricRecoveryError("recovery Namespace already exists; refusing cleanup ambiguity")

    temp_root = Path(tempfile.mkdtemp(prefix="gda-metadata-recovery-"))
    os.chmod(temp_root, 0o700)
    artifacts: dict[str, dict[str, Any]] = {}
    source_markers: dict[str, dict[str, Any]] = {}
    recovered_markers: dict[str, dict[str, Any]] = {}
    recovery_pvcs: dict[str, Any] = {}
    recovery_identity: dict[str, Any] = {}
    source_identity = _namespace_identity(source_runner, SOURCE_NAMESPACE)
    source_cluster_uid = _cluster_uid(source_runner)
    recovery_cluster_uid = _cluster_uid(recovery_runner)
    if not source_cluster_uid or not recovery_cluster_uid:
        raise MetadataFabricRecoveryError("source or recovery cluster identity is unavailable")
    if (source_context == target_context) != (
        source_cluster_uid == recovery_cluster_uid
    ):
        raise MetadataFabricRecoveryError("cluster context and identity isolation disagree")
    original_replicas: dict[str, int] = {}
    source_quiesced = False
    source_snapshot_staging_initially_empty = False
    recovery_search_target_cleared = False
    source_services_restored = False
    source_snapshot_staging_cleaned = False
    recovery_created = False
    recovery_namespace_removed = False
    local_artifacts_removed = False
    failure: Exception | None = None
    source_repository_created = False
    snapshot_name: str | None = None
    repository_round_trip: dict[str, Any] | None = None

    try:
        source_runner.kubectl_run(
            ["apply", "--dry-run=server", "-k", str(REPO_ROOT / "k8s/metadata-fabric-sandbox")],
            timeout=180,
            label="server validate source snapshot configuration",
        )
        source_runner.kubectl_run(
            ["apply", "-k", str(REPO_ROOT / "k8s/metadata-fabric-sandbox")],
            timeout=180,
            label="apply source snapshot configuration",
        )
        source_runner.kubectl_run(
            [
                "-n",
                SOURCE_NAMESPACE,
                "rollout",
                "status",
                "statefulset/metadata-opensearch",
                "--timeout=15m",
            ],
            timeout=930,
            label="wait for source OpenSearch snapshot configuration",
        )

        for name, kind in (
            ("openmetadata", "deployment"),
            ("metadata-gravitino", "statefulset"),
        ):
            value = _decode(
                source_runner.kubectl_run(
                    [
                        "-n",
                        SOURCE_NAMESPACE,
                        "get",
                        f"{kind}/{name}",
                        "-o",
                        "jsonpath={.spec.replicas}",
                    ],
                    label=f"read {name} replicas",
                ),
                f"{name} replicas",
            )
            original_replicas[name] = int(value)
            if original_replicas[name] != 1:
                raise MetadataFabricRecoveryError(f"{name} must have exactly one source replica")

        source_runner.kubectl_run(
            ["-n", SOURCE_NAMESPACE, "scale", "deployment/openmetadata", "--replicas=0"],
            label="quiesce OpenMetadata",
        )
        source_runner.kubectl_run(
            [
                "-n",
                SOURCE_NAMESPACE,
                "scale",
                "statefulset/metadata-gravitino",
                "--replicas=0",
            ],
            label="quiesce Gravitino",
        )
        _wait_for_no_pods(
            source_runner,
            SOURCE_NAMESPACE,
            "app.kubernetes.io/name=openmetadata",
            label="wait for OpenMetadata quiescence",
        )
        _wait_for_no_pods(
            source_runner,
            SOURCE_NAMESPACE,
            "app.kubernetes.io/name=metadata-gravitino",
            label="wait for Gravitino quiescence",
        )
        source_quiesced = True

        for name, target in POSTGRES_TARGETS.items():
            source_pod = str(target["source_pod"])
            source_markers[name] = _postgres_marker(
                source_runner, SOURCE_NAMESPACE, source_pod, label=f"source {name}"
            )
            backup_path = temp_root / f"{name}.dump"
            _write_private(
                backup_path,
                _postgres_dump(
                    source_runner,
                    SOURCE_NAMESPACE,
                    source_pod,
                    label=f"backup {name}",
                ),
            )
            artifacts[name] = _artifact(backup_path, str(target["format"]))

        source_os_marker, source_index_names = _opensearch_marker(
            source_runner,
            SOURCE_NAMESPACE,
            "metadata-opensearch-0",
            label="source opensearch",
        )
        source_markers["opensearch"] = source_os_marker
        initial_staging = source_runner.kubectl_run(
            [
                "-n",
                SOURCE_NAMESPACE,
                "exec",
                "pod/metadata-opensearch-0",
                "-c",
                "opensearch",
                "--",
                "ls",
                "-A",
                SNAPSHOT_MOUNT_PATH,
            ],
            label="verify empty source snapshot staging",
        )
        source_snapshot_staging_initially_empty = not initial_staging.strip()
        if not source_snapshot_staging_initially_empty:
            raise MetadataFabricRecoveryError("source snapshot staging is not empty")
        snapshot_name = "gda-" + started.strftime("%Y%m%d%H%M%SZ").lower()
        repository = _opensearch_request(
            source_runner,
            SOURCE_NAMESPACE,
            "metadata-opensearch-0",
            "PUT",
            f"/_snapshot/{SNAPSHOT_REPOSITORY}",
            body={"type": "fs", "settings": {"location": SNAPSHOT_PATH, "compress": True}},
            label="register source snapshot repository",
        )
        if repository.get("acknowledged") is not True:
            raise MetadataFabricRecoveryError("source snapshot repository was not acknowledged")
        source_repository_created = True
        snapshot = _opensearch_request(
            source_runner,
            SOURCE_NAMESPACE,
            "metadata-opensearch-0",
            "PUT",
            f"/_snapshot/{SNAPSHOT_REPOSITORY}/{snapshot_name}?wait_for_completion=true",
            body={
                "indices": ",".join(source_index_names),
                "ignore_unavailable": False,
                "include_global_state": False,
            },
            timeout=900,
            label="create OpenSearch snapshot",
        )
        snapshot_result = _mapping(snapshot.get("snapshot"))
        if snapshot_result.get("state") != "SUCCESS" or _mapping(
            snapshot_result.get("shards")
        ).get("failed") != 0:
            raise MetadataFabricRecoveryError("OpenSearch snapshot did not complete successfully")
        os_backup_path = temp_root / "opensearch-snapshot.tar.gz"
        _write_private(
            os_backup_path,
            source_runner.kubectl_run(
                [
                    "-n",
                    SOURCE_NAMESPACE,
                    "exec",
                    "pod/metadata-opensearch-0",
                    "-c",
                    "opensearch",
                    "--",
                    "tar",
                    "-C",
                    SNAPSHOT_MOUNT_PATH,
                    "-czf",
                    "-",
                    "repository",
                ],
                timeout=600,
                label="export OpenSearch snapshot artifact",
            ),
        )
        artifacts["opensearch"] = _artifact(
            os_backup_path, "opensearch_fs_snapshot_tar_gzip_v1"
        )
        _validate_snapshot_archive(os_backup_path.read_bytes())

        if artifact_round_trip is not None:
            artifact_paths = {
                "openmetadata_postgresql": temp_root / "openmetadata_postgresql.dump",
                "gravitino_postgresql": temp_root / "gravitino_postgresql.dump",
                "opensearch": os_backup_path,
            }
            repository_round_trip = dict(
                artifact_round_trip(artifact_paths, artifacts)
            )
            for name, path in artifact_paths.items():
                if not path.is_file():
                    raise MetadataFabricRecoveryError(
                        f"repository round-trip did not restore {name} locally"
                    )
                restored_artifact = _artifact(path, str(artifacts[name]["format"]))
                if restored_artifact != artifacts[name]:
                    raise MetadataFabricRecoveryError(
                        f"repository round-trip changed {name} content"
                    )

        recovery_runner.kubectl_run(
            ["apply", "-f", str(DEFAULT_RECOVERY_MANIFEST_DIR / "namespace.yaml")],
            label="create recovery Namespace",
        )
        recovery_created = True
        _create_runtime_credential(
            recovery_runner,
            RECOVERY_NAMESPACE,
            "recovery-openmetadata-postgresql",
            temp_root,
        )
        _create_runtime_credential(
            recovery_runner,
            RECOVERY_NAMESPACE,
            "recovery-gravitino-postgresql",
            temp_root,
        )
        recovery_runner.kubectl_run(
            ["apply", "--dry-run=server", "-k", str(DEFAULT_RECOVERY_MANIFEST_DIR)],
            timeout=180,
            label="server validate recovery workloads",
        )
        recovery_runner.kubectl_run(
            ["apply", "-k", str(DEFAULT_RECOVERY_MANIFEST_DIR)],
            timeout=180,
            label="apply recovery workloads",
        )
        for statefulset in RECOVERY_STATEFULSETS:
            recovery_runner.kubectl_run(
                [
                    "-n",
                    RECOVERY_NAMESPACE,
                    "rollout",
                    "status",
                    f"statefulset/{statefulset}",
                    "--timeout=15m",
                ],
                timeout=930,
                label=f"wait for {statefulset}",
            )
        recovery_identity = _namespace_identity(recovery_runner, RECOVERY_NAMESPACE)
        recovery_pvcs = _pvc_identities(recovery_runner)

        for name, target in POSTGRES_TARGETS.items():
            backup_path = temp_root / f"{name}.dump"
            _postgres_restore(
                recovery_runner,
                RECOVERY_NAMESPACE,
                str(target["recovery_pod"]),
                backup_path.read_bytes(),
                label=f"restore {name}",
            )
            recovered_markers[name] = _postgres_marker(
                recovery_runner,
                RECOVERY_NAMESPACE,
                str(target["recovery_pod"]),
                label=f"recovered {name}",
            )

        recovery_runner.kubectl_run(
            [
                "-n",
                RECOVERY_NAMESPACE,
                "exec",
                "-i",
                "pod/recovery-opensearch-0",
                "-c",
                "opensearch",
                "--",
                "tar",
                "--no-overwrite-dir",
                "--no-same-owner",
                "--no-same-permissions",
                "-C",
                SNAPSHOT_MOUNT_PATH,
                "-xzf",
                "-",
            ],
            input_bytes=os_backup_path.read_bytes(),
            timeout=600,
            label="import OpenSearch snapshot artifact",
        )
        recovery_repository = _opensearch_request(
            recovery_runner,
            RECOVERY_NAMESPACE,
            "recovery-opensearch-0",
            "PUT",
            f"/_snapshot/{SNAPSHOT_REPOSITORY}",
            body={"type": "fs", "settings": {"location": SNAPSHOT_PATH, "readonly": True}},
            label="register recovery snapshot repository",
        )
        if recovery_repository.get("acknowledged") is not True:
            raise MetadataFabricRecoveryError("recovery snapshot repository was not acknowledged")
        _, recovery_initial_names = _opensearch_marker(
            recovery_runner,
            RECOVERY_NAMESPACE,
            "recovery-opensearch-0",
            label="initial recovery opensearch",
        )
        if recovery_initial_names:
            encoded_indices = quote(",".join(recovery_initial_names), safe=",.-_")
            cleared = _opensearch_request(
                recovery_runner,
                RECOVERY_NAMESPACE,
                "recovery-opensearch-0",
                "DELETE",
                f"/{encoded_indices}?expand_wildcards=all&ignore_unavailable=true",
                label="clear explicit recovery indexes",
            )
            if cleared.get("acknowledged") is not True:
                raise MetadataFabricRecoveryError(
                    "recovery search target cleanup was not acknowledged"
                )
        _, remaining_initial_names = _opensearch_marker(
            recovery_runner,
            RECOVERY_NAMESPACE,
            "recovery-opensearch-0",
            label="cleared recovery opensearch",
        )
        recovery_search_target_cleared = not remaining_initial_names
        if not recovery_search_target_cleared:
            raise MetadataFabricRecoveryError("recovery search target is not empty")
        restored = _opensearch_request(
            recovery_runner,
            RECOVERY_NAMESPACE,
            "recovery-opensearch-0",
            "POST",
            f"/_snapshot/{SNAPSHOT_REPOSITORY}/{snapshot_name}/_restore?wait_for_completion=true",
            body={"indices": ",".join(source_index_names), "include_global_state": False},
            timeout=900,
            label="restore OpenSearch snapshot",
        )
        restored_result = _mapping(restored.get("snapshot"))
        if _mapping(restored_result.get("shards")).get("failed") != 0:
            raise MetadataFabricRecoveryError("OpenSearch restore reported failed shards")
        _opensearch_request(
            recovery_runner,
            RECOVERY_NAMESPACE,
            "recovery-opensearch-0",
            "GET",
            "/_cluster/health?wait_for_status=yellow&timeout=300s",
            timeout=330,
            label="wait for recovered OpenSearch health",
        )
        recovered_os_marker, _ = _opensearch_marker(
            recovery_runner,
            RECOVERY_NAMESPACE,
            "recovery-opensearch-0",
            expected_names=source_index_names,
            label="recovered opensearch",
        )
        recovered_markers["opensearch"] = recovered_os_marker
    except Exception as exc:  # cleanup must run for every fail-closed path
        failure = exc
    finally:
        try:
            if source_repository_created:
                if snapshot_name is not None:
                    _opensearch_request(
                        source_runner,
                        SOURCE_NAMESPACE,
                        "metadata-opensearch-0",
                        "DELETE",
                        f"/_snapshot/{SNAPSHOT_REPOSITORY}/{snapshot_name}",
                        label="remove source rehearsal snapshot",
                    )
                deleted_repository = _opensearch_request(
                    source_runner,
                    SOURCE_NAMESPACE,
                    "metadata-opensearch-0",
                    "DELETE",
                    f"/_snapshot/{SNAPSHOT_REPOSITORY}",
                    label="remove source snapshot repository",
                )
                if deleted_repository.get("acknowledged") is not True:
                    raise MetadataFabricRecoveryError(
                        "source snapshot repository cleanup was not acknowledged"
                    )
                source_runner.kubectl_run(
                    [
                        "-n",
                        SOURCE_NAMESPACE,
                        "exec",
                        "pod/metadata-opensearch-0",
                        "-c",
                        "opensearch",
                        "--",
                        "sh",
                        "-ceu",
                        'rm -rf -- "$1"; test -z "$(ls -A "$2")"',
                        "sh",
                        SNAPSHOT_PATH,
                        SNAPSHOT_MOUNT_PATH,
                    ],
                    label="clear and verify source snapshot staging files",
                )
                source_snapshot_staging_cleaned = True
        except Exception as exc:
            failure = failure or exc
        try:
            if original_replicas:
                source_services_restored = _restore_source_services(
                    source_runner, original_replicas
                )
        except Exception as exc:
            failure = failure or exc
        try:
            if recovery_created:
                recovery_runner.kubectl_run(
                    [
                        "delete",
                        "namespace",
                        RECOVERY_NAMESPACE,
                        "--wait=true",
                        "--timeout=10m",
                    ],
                    timeout=630,
                    label="remove recovery Namespace",
                )
                recovery_namespace_removed = not recovery_runner.namespace_exists(
                    RECOVERY_NAMESPACE
                )
        except Exception as exc:
            failure = failure or exc
        shutil.rmtree(temp_root, ignore_errors=True)
        local_artifacts_removed = not temp_root.exists()

    if failure is not None:
        if isinstance(failure, MetadataFabricRecoveryError):
            raise failure
        raise MetadataFabricRecoveryError("live recovery rehearsal failed") from failure

    completed = datetime.now(UTC)
    observation = {
        "schema": OBSERVATION_SCHEMA,
        "observed_at": completed.isoformat(),
        "started_at": started.isoformat(),
        "duration_seconds": round((completed - started).total_seconds(), 3),
        "contract": {
            "static_contract_verified": contract["static_contract_verified"],
            "contract_fingerprint": contract["contract_fingerprint"],
        },
        "cluster": {
            "context": source_context,
            "uid": source_cluster_uid,
            "source_namespace": source_identity,
            "recovery_context": target_context,
            "recovery_uid": recovery_cluster_uid,
            "recovery_namespace": recovery_identity,
        },
        "recovery_pvcs": recovery_pvcs,
        "artifacts": artifacts,
        "source_markers": source_markers,
        "recovered_markers": recovered_markers,
        "runtime_checks": {
            "source_quiesced": source_quiesced,
            "source_snapshot_staging_initially_empty": source_snapshot_staging_initially_empty,
            "recovery_search_target_cleared": recovery_search_target_cleared,
            "source_services_restored": source_services_restored,
            "source_snapshot_staging_cleaned": source_snapshot_staging_cleaned,
            "recovery_namespace_removed": recovery_namespace_removed,
            "local_artifacts_removed": local_artifacts_removed,
        },
    }
    if repository_round_trip is not None:
        observation["repository_round_trip"] = repository_round_trip
    if _sensitive_paths(observation):
        raise MetadataFabricRecoveryError("allowlisted observation rejected a field")
    return observation


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MetadataFabricRecoveryError("JSON input must be an object")
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
    subparsers.add_parser("validate")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--kubectl", default="kubectl")
    run_parser.add_argument("--source-context", default="docker-desktop")
    run_parser.add_argument("--recovery-context")
    run_parser.add_argument("--output", type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "validate":
            report = build_recovery_contract_report()
            _write_report(report, None)
            return 0 if report["static_contract_verified"] else 1
        if args.command == "run":
            observation = run_live_recovery_rehearsal(
                kubectl=args.kubectl,
                source_context=args.source_context,
                recovery_context=args.recovery_context,
            )
            report = build_recovery_evidence(observation)
            _write_report(report, args.output)
            return 0 if report["local_backup_restore_verified"] else 1
        report = _load_json_object(args.input)
        errors = verify_evidence_integrity(report)
        print(
            json.dumps(
                {
                    "schema": EVIDENCE_SCHEMA,
                    "status": "valid" if not errors else "invalid",
                    "evidence_fingerprint": report.get("evidence_fingerprint"),
                    "errors": errors,
                },
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if not errors else 1
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        MetadataFabricRecoveryError,
        KeyboardInterrupt,
    ) as exc:
        detail = str(exc) if isinstance(exc, MetadataFabricRecoveryError) else type(exc).__name__
        _write_report(
            {
                "schema": EVIDENCE_SCHEMA,
                "status": "error",
                "backup_restore_verified": False,
                "local_backup_restore_verified": False,
                "production_backup_restore_verified": False,
                "production_ready": False,
                "error": f"recovery rehearsal failed closed: {detail}",
            },
            getattr(args, "output", None),
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
