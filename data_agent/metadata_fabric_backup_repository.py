"""Verify a versioned, retention-locked metadata backup repository boundary.

The local runner deploys an isolated S3-compatible repository, uploads the
three real metadata backup artifacts produced by the recovery rehearsal,
removes their local copies, downloads the retained versions, and restores from
those downloads. The local repository is deleted after the rehearsal, so this
module never claims production durability, KMS, RPO/RTO, or cross-cluster DR.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from . import metadata_fabric_recovery_rehearsal as recovery


CONTRACT_SCHEMA = "gda.metadata_fabric_backup_repository_contract.v1"
OBSERVATION_SCHEMA = "gda.metadata_fabric_backup_repository_observation.v1"
EVIDENCE_SCHEMA = "gda.metadata_fabric_backup_repository_evidence.v1"
POLICY_SCHEMA = "gda.metadata_fabric_backup_policy.v1"
REPOSITORY_NAMESPACE = "gda-metadata-backup-repository"
REPOSITORY_STATEFULSET = "metadata-backup-minio"
REPOSITORY_SERVICE = "metadata-backup-minio"
REPOSITORY_SECRET = "metadata-backup-minio-root"
REPOSITORY_PVC = "repository-data-metadata-backup-minio-0"
REPOSITORY_CAPACITY = "8Gi"
REPOSITORY_BUCKET = "gda-metadata-fabric-backups"
MINIO_IMAGE = "minio/minio:RELEASE.2025-04-22T22-12-26Z"
LOCAL_RETENTION_MODE = "GOVERNANCE"
LOCAL_RETENTION_DAYS = 1
PRODUCTION_RETENTION_MODE = "COMPLIANCE"
PRODUCTION_MINIMUM_RETENTION_DAYS = 30

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST_DIR = REPO_ROOT / "k8s/metadata-fabric-backup-repository"
DEFAULT_POLICY_PATH = REPO_ROOT / "config/metadata-fabric-backup-policy.production.yaml"
DEFAULT_WRAPPER = REPO_ROOT / "scripts/metadata-fabric-backup-repository.sh"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_ARTIFACTS = {
    "openmetadata_postgresql": "postgresql_custom_dump_v1",
    "gravitino_postgresql": "postgresql_custom_dump_v1",
    "opensearch": "opensearch_fs_snapshot_tar_gzip_v1",
}


class MetadataFabricBackupRepositoryError(RuntimeError):
    """The backup repository contract or rehearsal failed closed."""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _valid_fingerprint(value: Any) -> bool:
    return isinstance(value, str) and SHA256_PATTERN.fullmatch(value) is not None


def _load_yaml_object(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("YAML document is not an object")
    return payload


def _production_policy_errors(policy: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    repository = _mapping(policy.get("repository"))
    lock = _mapping(repository.get("object_lock"))
    transport = _mapping(repository.get("transport"))
    encryption = _mapping(repository.get("encryption"))
    integrity = _mapping(repository.get("integrity"))
    access = _mapping(repository.get("access"))
    claims = _mapping(policy.get("claims"))

    if policy.get("schema") != POLICY_SCHEMA or policy.get("environment") != "production":
        errors.append("production backup policy schema or environment does not match")
    if repository.get("provider") != "s3":
        errors.append("production backup repository must use the S3 contract")
    if not repository.get("endpoint_reference") or repository.get("endpoint_url"):
        errors.append("production endpoint must be an external reference, not a literal URL")
    if repository.get("failure_domain") != "external_to_source_cluster":
        errors.append("production backup repository must be outside the source cluster")
    if repository.get("ownership") != "dedicated_backup_account_or_project":
        errors.append("production backup repository must have independent ownership")
    if repository.get("credential_mode") != "workload_identity":
        errors.append("production backup repository must use workload identity")
    if repository.get("versioning") != "Enabled":
        errors.append("production backup bucket versioning must be enabled")
    if lock.get("enabled") is not True or lock.get("mode") != PRODUCTION_RETENTION_MODE:
        errors.append("production backup object lock must use COMPLIANCE mode")
    retention_days = lock.get("minimum_retention_days")
    if not isinstance(retention_days, int) or retention_days < PRODUCTION_MINIMUM_RETENTION_DAYS:
        errors.append("production backup retention must be at least 30 days")
    if transport.get("tls_required") is not True:
        errors.append("production backup transport must require TLS")
    if encryption.get("mode") != "SSE-KMS" or not encryption.get("key_reference"):
        errors.append("production backup objects must use a referenced KMS key")
    if integrity.get("algorithm") != "SHA256":
        errors.append("production backup integrity must use SHA256")
    if integrity.get("independent_read_after_write_required") is not True:
        errors.append("production backup requires independent read-after-write verification")
    if access.get("public_access_blocked") is not True:
        errors.append("production backup bucket must block public access")
    if access.get("source_writer_delete_denied") is not True:
        errors.append("production source writer must not delete retained backups")
    if access.get("recovery_reader_write_denied") is not True:
        errors.append("production recovery reader must not write backups")
    for claim in (
        "production_backup_target_verified",
        "production_retention_verified",
        "production_kms_verified",
        "cross_cluster_recovery_verified",
        "rpo_slo_verified",
        "rto_slo_verified",
        "production_ready",
    ):
        if claims.get(claim) is not False:
            errors.append(f"unverified production claim must remain false: {claim}")
    return errors


def build_backup_repository_contract_report(
    manifest_dir: Path | None = None,
    policy_path: Path | None = None,
    wrapper_path: Path | None = None,
) -> dict[str, Any]:
    """Validate the local repository profile and production policy boundary."""
    manifests = (manifest_dir or DEFAULT_MANIFEST_DIR).resolve()
    policy_file = (policy_path or DEFAULT_POLICY_PATH).resolve()
    wrapper = (wrapper_path or DEFAULT_WRAPPER).resolve()
    errors: list[str] = []
    documents: list[dict[str, Any]] = []
    resource_paths: list[Path] = []
    kustomization_path = manifests / "kustomization.yaml"

    try:
        kustomization = _load_yaml_object(kustomization_path)
        if kustomization.get("namespace") != REPOSITORY_NAMESPACE:
            errors.append("backup repository Kustomization must target its isolated namespace")
        for relative in kustomization.get("resources") or []:
            path = (manifests / str(relative)).resolve()
            if path.parent != manifests:
                errors.append("backup repository resources must stay inside the manifest directory")
                continue
            resource_paths.append(path)
            documents.extend(recovery._load_documents(path))
    except (OSError, TypeError, yaml.YAMLError) as exc:
        errors.append(f"backup repository Kustomization is invalid: {type(exc).__name__}")

    namespace = recovery._resource(documents, "Namespace", REPOSITORY_NAMESPACE)
    labels = ((namespace or {}).get("metadata") or {}).get("labels") or {}
    if namespace is None or labels.get("gda.openai.com/ephemeral-owner") != (
        "metadata-backup-repository-rehearsal"
    ):
        errors.append("backup repository Namespace must have exact cleanup ownership")

    quota = recovery._resource(documents, "ResourceQuota", "metadata-backup-repository") or {}
    hard = ((quota.get("spec") or {}).get("hard") or {})
    if str(hard.get("persistentvolumeclaims")) != "1":
        errors.append("backup repository quota must allow exactly one PVC")
    if str(hard.get("requests.storage")) != REPOSITORY_CAPACITY:
        errors.append("backup repository quota must remain bounded at 8Gi")

    forbidden_kinds = {
        "Secret",
        "Ingress",
        "Gateway",
        "HTTPRoute",
        "Route",
        "Role",
        "RoleBinding",
        "ClusterRole",
        "ClusterRoleBinding",
    }
    for document in documents:
        kind = str(document.get("kind"))
        name = str((document.get("metadata") or {}).get("name"))
        if kind in forbidden_kinds:
            errors.append(f"{kind}/{name} is forbidden in backup repository manifests")
        if kind != "Namespace" and (document.get("metadata") or {}).get(
            "namespace"
        ) != REPOSITORY_NAMESPACE:
            errors.append(f"{kind}/{name} is outside the backup repository namespace")

    workload = recovery._resource(documents, "StatefulSet", REPOSITORY_STATEFULSET) or {}
    pod = recovery._pod_spec(workload)
    container = recovery._container(workload)
    if pod.get("serviceAccountName") != REPOSITORY_STATEFULSET:
        errors.append("backup repository must use its dedicated ServiceAccount")
    if pod.get("automountServiceAccountToken") is not False:
        errors.append("backup repository must disable API token mounting")
    if container.get("image") != MINIO_IMAGE:
        errors.append("backup repository image must be pinned")
    security = container.get("securityContext") or {}
    if security.get("runAsNonRoot") is not True:
        errors.append("backup repository must run as non-root")
    if security.get("allowPrivilegeEscalation") is not False:
        errors.append("backup repository may not allow privilege escalation")
    if security.get("readOnlyRootFilesystem") is not True:
        errors.append("backup repository must use a read-only root filesystem")
    if any("hostPath" in volume for volume in pod.get("volumes") or []):
        errors.append("backup repository may not use hostPath")
    env_from = container.get("envFrom") or []
    secret_names = {
        ((_mapping(item).get("secretRef") or {}).get("name"))
        for item in env_from
        if isinstance(item, Mapping)
    }
    if secret_names != {REPOSITORY_SECRET}:
        errors.append("backup repository must use only the runtime root credential Secret")
    templates = (workload.get("spec") or {}).get("volumeClaimTemplates") or []
    if len(templates) != 1:
        errors.append("backup repository must define exactly one PVC")
    else:
        template = templates[0]
        name = (template.get("metadata") or {}).get("name")
        capacity = (
            ((template.get("spec") or {}).get("resources") or {})
            .get("requests", {})
            .get("storage")
        )
        if name != "repository-data" or str(capacity) != REPOSITORY_CAPACITY:
            errors.append("backup repository PVC identity or capacity does not match")

    service = recovery._resource(documents, "Service", REPOSITORY_SERVICE) or {}
    service_spec = service.get("spec") or {}
    if service_spec.get("type", "ClusterIP") != "ClusterIP":
        errors.append("backup repository Service must remain ClusterIP-only")
    ports = service_spec.get("ports") or []
    if len(ports) != 1 or ports[0].get("port") != 9000:
        errors.append("backup repository Service must expose only the S3 API")

    service_account = recovery._resource(
        documents, "ServiceAccount", REPOSITORY_STATEFULSET
    ) or {}
    if service_account.get("automountServiceAccountToken") is not False:
        errors.append("backup repository ServiceAccount must disable token mounting")

    default_deny = recovery._resource(
        documents, "NetworkPolicy", "metadata-backup-default-deny"
    ) or {}
    deny_spec = default_deny.get("spec") or {}
    if set(deny_spec.get("policyTypes") or []) != {"Ingress", "Egress"}:
        errors.append("backup repository must default-deny ingress and egress")
    if deny_spec.get("ingress") or deny_spec.get("egress"):
        errors.append("backup repository default-deny policy may not add allow rules")
    api_policy = recovery._resource(
        documents, "NetworkPolicy", "metadata-backup-api-access"
    ) or {}
    rendered_api_policy = json.dumps(api_policy, sort_keys=True)
    if "gda.openai.com/backup-client" not in rendered_api_policy or "9000" not in rendered_api_policy:
        errors.append("backup repository API policy must allow only labeled backup clients")

    try:
        policy = _load_yaml_object(policy_file)
        errors.extend(_production_policy_errors(policy))
    except (OSError, TypeError, yaml.YAMLError) as exc:
        errors.append(f"production backup policy is invalid: {type(exc).__name__}")

    try:
        wrapper_text = wrapper.read_text(encoding="utf-8")
        for marker in ("set -euo pipefail", "metadata_fabric_backup_repository"):
            if marker not in wrapper_text:
                errors.append(f"backup repository wrapper is missing safety marker: {marker}")
    except OSError as exc:
        errors.append(f"backup repository wrapper is invalid: {type(exc).__name__}")

    files: dict[str, dict[str, str]] = {}
    for path in [
        Path(__file__).resolve(),
        Path(recovery.__file__).resolve(),
        kustomization_path,
        *resource_paths,
        policy_file,
        wrapper,
    ]:
        if path.is_file():
            try:
                relative = path.relative_to(REPO_ROOT).as_posix()
            except ValueError:
                relative = path.name
            files[relative] = {
                "path": relative,
                "sha256": recovery._file_sha256(path),
            }

    stable = {
        "schema": CONTRACT_SCHEMA,
        "source_namespace": recovery.SOURCE_NAMESPACE,
        "repository_namespace": REPOSITORY_NAMESPACE,
        "repository_bucket": REPOSITORY_BUCKET,
        "artifact_inventory": EXPECTED_ARTIFACTS,
        "local_static_contract_verified": not errors,
        "local_repository_round_trip_verified": False,
        "production_backup_target_verified": False,
        "production_retention_verified": False,
        "files": files,
        "errors": errors,
    }
    return {**stable, "contract_fingerprint": recovery._canonical_sha256(stable)}


def _repository_observation_errors(observation: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    repository = _mapping(observation.get("repository_round_trip"))
    artifacts = _mapping(repository.get("artifact_objects"))
    recovery_evidence = _mapping(observation.get("recovery_evidence"))
    recovery_observation = _mapping(recovery_evidence.get("observation"))
    source_artifacts = _mapping(recovery_observation.get("artifacts"))

    if repository.get("provider") != "minio_s3_compatible":
        errors.append("local repository provider does not match")
    if repository.get("bucket") != REPOSITORY_BUCKET:
        errors.append("local repository bucket does not match")
    if repository.get("versioning_status") != "Enabled":
        errors.append("local repository versioning was not enabled")
    if repository.get("object_lock_enabled") is not True:
        errors.append("local repository object lock was not enabled")
    if repository.get("default_retention_mode") != LOCAL_RETENTION_MODE:
        errors.append("local repository retention mode does not match")
    if repository.get("default_retention_days") != LOCAL_RETENTION_DAYS:
        errors.append("local repository retention duration does not match")
    if repository.get("local_artifacts_removed_before_download") is not True:
        errors.append("local artifacts were not removed before repository download")
    if repository.get("round_trip_verified") is not True:
        errors.append("repository round-trip was not verified")
    if set(artifacts) != set(EXPECTED_ARTIFACTS):
        errors.append("repository artifact inventory does not match")
    for name, expected_format in EXPECTED_ARTIFACTS.items():
        item = _mapping(artifacts.get(name))
        source = _mapping(source_artifacts.get(name))
        if item.get("format") != expected_format:
            errors.append(f"repository object format does not match: {name}")
        if item.get("sha256") != source.get("sha256") or item.get("bytes") != source.get("bytes"):
            errors.append(f"repository object content does not match recovery artifact: {name}")
        if not _valid_fingerprint(item.get("sha256")):
            errors.append(f"repository object fingerprint is invalid: {name}")
        if not item.get("version_id"):
            errors.append(f"repository object has no version identity: {name}")
        if item.get("retention_mode") != LOCAL_RETENTION_MODE:
            errors.append(f"repository object is not retention locked: {name}")
        if item.get("retained_version_delete_blocked") is not True:
            errors.append(f"repository retained version deletion was not blocked: {name}")
        object_path = str(item.get("object_path") or "")
        if not object_path.startswith("metadata-fabric/") or ".." in object_path:
            errors.append(f"repository object path is invalid: {name}")
    return errors


def _observation_errors(
    observation: Mapping[str, Any], *, now: datetime, max_age_seconds: float
) -> list[str]:
    errors: list[str] = []
    if recovery._sensitive_paths(observation):
        errors.append("repository observation contains forbidden credential-bearing fields")
    if observation.get("schema") != OBSERVATION_SCHEMA:
        errors.append("repository observation schema does not match")
    try:
        observed_at = datetime.fromisoformat(str(observation.get("observed_at")))
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError
        age = (now - observed_at).total_seconds()
        if age < -30 or age > max_age_seconds:
            errors.append("repository observation is outside the accepted freshness window")
    except ValueError:
        errors.append("repository observation timestamp is invalid")

    contract = _mapping(observation.get("contract"))
    if contract.get("local_static_contract_verified") is not True:
        errors.append("repository static contract was not verified")
    if not _valid_fingerprint(contract.get("contract_fingerprint")):
        errors.append("repository contract fingerprint is invalid")

    cluster = _mapping(observation.get("cluster"))
    source_ns = _mapping(cluster.get("source_namespace"))
    repository_ns = _mapping(cluster.get("repository_namespace"))
    if cluster.get("context") != "docker-desktop" or not cluster.get("uid"):
        errors.append("repository rehearsal did not run on bounded Docker Desktop")
    if source_ns.get("name") != recovery.SOURCE_NAMESPACE or not source_ns.get("uid"):
        errors.append("repository source Namespace identity does not match")
    if repository_ns.get("name") != REPOSITORY_NAMESPACE or not repository_ns.get("uid"):
        errors.append("repository Namespace identity does not match")
    if source_ns.get("uid") == repository_ns.get("uid"):
        errors.append("source and repository Namespace identities are not isolated")

    pvc = _mapping(observation.get("repository_pvc"))
    if pvc.get("name") != REPOSITORY_PVC or pvc.get("capacity") != REPOSITORY_CAPACITY:
        errors.append("repository PVC identity or capacity does not match")
    if pvc.get("phase") != "Bound" or not pvc.get("uid") or not pvc.get("volume_name"):
        errors.append("repository PVC was not independently Bound")

    recovery_evidence = _mapping(observation.get("recovery_evidence"))
    errors.extend(
        f"nested recovery evidence: {error}"
        for error in recovery.verify_evidence_integrity(recovery_evidence)
    )
    if recovery_evidence.get("backup_restore_verified") is not True:
        errors.append("repository artifacts did not complete a verified restore")
    if recovery_evidence.get("production_backup_restore_verified") is not False:
        errors.append("nested recovery evidence overclaims production backup/restore")
    errors.extend(_repository_observation_errors(observation))

    runtime = _mapping(observation.get("runtime_checks"))
    for key in (
        "repository_namespace_removed",
        "runtime_credentials_removed",
        "port_forward_stopped",
    ):
        if runtime.get(key) is not True:
            errors.append(f"repository runtime check did not pass: {key}")
    return errors


def build_backup_repository_evidence(
    observation: Mapping[str, Any],
    *,
    now: datetime | None = None,
    max_age_seconds: float = 3600,
) -> dict[str, Any]:
    """Build fail-closed evidence for the local locked repository round-trip."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise MetadataFabricBackupRepositoryError(
            "verification time must be timezone-aware"
        )
    errors = _observation_errors(
        observation, now=current, max_age_seconds=max_age_seconds
    )
    verified = not errors
    stable = {
        "schema": EVIDENCE_SCHEMA,
        "environment": "local_isolated_s3_backup_repository_rehearsal",
        "source_namespace": recovery.SOURCE_NAMESPACE,
        "repository_namespace": REPOSITORY_NAMESPACE,
        "observation_fingerprint": recovery._canonical_sha256(observation),
        "checks": {
            "static_contract": "passed" if verified else "blocked",
            "repository_isolation": "passed" if verified else "blocked",
            "versioning": "passed" if verified else "blocked",
            "object_lock_retention": "passed" if verified else "blocked",
            "artifact_round_trip": "passed" if verified else "blocked",
            "repository_backed_restore": "passed" if verified else "blocked",
            "ephemeral_cleanup": "passed" if verified else "blocked",
            "production_boundaries": "passed",
        },
        "errors": errors,
        "backup_repository_scope": "local_same_cluster_isolated_s3_compatible_repository",
        "backup_repository_verified": verified,
        "local_repository_round_trip_verified": verified,
        "repository_backed_restore_verified": verified,
        "production_backup_target_verified": False,
        "production_retention_verified": False,
        "production_kms_verified": False,
        "production_tls_verified": False,
        "cross_cluster_recovery_verified": False,
        "cross_region_recovery_verified": False,
        "rpo_slo_verified": False,
        "rto_slo_verified": False,
        "oidc_verified": False,
        "network_policy_enforcement_verified": False,
        "writes_to_gda_enabled": False,
        "production_ready": False,
        "observation": observation,
    }
    return {
        **stable,
        "generated_at": current.isoformat(),
        "status": "local_backup_repository_verified" if verified else "blocked",
        "evidence_fingerprint": recovery._canonical_sha256(stable),
    }


def verify_evidence_integrity(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if recovery._sensitive_paths(report):
        errors.append("backup repository evidence contains credential-bearing fields")
    if report.get("schema") != EVIDENCE_SCHEMA:
        errors.append("backup repository evidence schema does not match")
    stable = {
        key: value
        for key, value in report.items()
        if key not in {"generated_at", "status", "evidence_fingerprint"}
    }
    if report.get("evidence_fingerprint") != recovery._canonical_sha256(stable):
        errors.append("backup repository evidence fingerprint does not match")
    for claim in (
        "production_backup_target_verified",
        "production_retention_verified",
        "production_kms_verified",
        "production_tls_verified",
        "cross_cluster_recovery_verified",
        "production_ready",
    ):
        if report.get(claim) is not False:
            errors.append(f"backup repository evidence may not claim {claim}")
    return errors


def _create_runtime_secret(
    runner: recovery._CommandRunner,
    temp_root: Path,
) -> tuple[str, str]:
    username = "gda" + secrets.token_hex(12)
    password = secrets.token_urlsafe(36)
    credential_file = temp_root / "repository-runtime.env"
    recovery._write_private(
        credential_file,
        f"MINIO_ROOT_USER={username}\nMINIO_ROOT_PASSWORD={password}\n".encode("ascii"),
    )
    rendered = runner.kubectl_run(
        [
            "-n",
            REPOSITORY_NAMESPACE,
            "create",
            "secret",
            "generic",
            REPOSITORY_SECRET,
            f"--from-env-file={credential_file}",
            "--dry-run=client",
            "-o",
            "yaml",
        ],
        label="render backup repository runtime credential",
    )
    runner.kubectl_run(
        ["apply", "-f", "-"],
        input_bytes=rendered,
        label="apply backup repository runtime credential",
    )
    credential_file.unlink()
    return username, password


def _repository_pvc_identity(runner: recovery._CommandRunner) -> dict[str, Any]:
    payload = runner.kubectl_json(
        ["-n", REPOSITORY_NAMESPACE, "get", "pvc", REPOSITORY_PVC, "-o", "json"],
        label="read backup repository PVC",
    )
    metadata = _mapping(payload.get("metadata"))
    spec = _mapping(payload.get("spec"))
    status = _mapping(payload.get("status"))
    return {
        "name": metadata.get("name"),
        "uid": metadata.get("uid"),
        "volume_name": spec.get("volumeName"),
        "capacity": _mapping(status.get("capacity")).get("storage"),
        "phase": status.get("phase"),
    }


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _start_port_forward(kubectl: str, port: int) -> subprocess.Popen[bytes]:
    try:
        process = subprocess.Popen(
            [
                kubectl,
                "-n",
                REPOSITORY_NAMESPACE,
                "port-forward",
                f"service/{REPOSITORY_SERVICE}",
                f"{port}:9000",
                "--address=127.0.0.1",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise MetadataFabricBackupRepositoryError(
            "backup repository port-forward was unavailable"
        ) from exc
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise MetadataFabricBackupRepositoryError(
                "backup repository port-forward stopped before readiness"
            )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return process
        except OSError:
            time.sleep(0.25)
    process.terminate()
    raise MetadataFabricBackupRepositoryError(
        "backup repository port-forward did not become ready"
    )


def _stop_port_forward(process: subprocess.Popen[bytes] | None) -> bool:
    if process is None:
        return True
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    return process.poll() is not None


def _build_s3_client(endpoint: str, username: str, password: str):
    try:
        import boto3
        from botocore.config import Config as BotoConfig
    except Exception as exc:
        raise MetadataFabricBackupRepositoryError(
            "boto3 is required for the backup repository rehearsal"
        ) from exc
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=username,
        aws_secret_access_key=password,
        region_name="us-east-1",
        config=BotoConfig(
            s3={"addressing_style": "path"},
            retries={"max_attempts": 5, "mode": "standard"},
        ),
    )


def _initialize_repository(client: Any) -> dict[str, Any]:
    try:
        client.create_bucket(
            Bucket=REPOSITORY_BUCKET,
            ObjectLockEnabledForBucket=True,
        )
        client.put_bucket_versioning(
            Bucket=REPOSITORY_BUCKET,
            VersioningConfiguration={"Status": "Enabled"},
        )
        client.put_object_lock_configuration(
            Bucket=REPOSITORY_BUCKET,
            ObjectLockConfiguration={
                "ObjectLockEnabled": "Enabled",
                "Rule": {
                    "DefaultRetention": {
                        "Mode": LOCAL_RETENTION_MODE,
                        "Days": LOCAL_RETENTION_DAYS,
                    }
                },
            },
        )
        versioning = client.get_bucket_versioning(Bucket=REPOSITORY_BUCKET)
        lock = client.get_object_lock_configuration(Bucket=REPOSITORY_BUCKET)
    except Exception as exc:
        raise MetadataFabricBackupRepositoryError(
            "backup repository initialization failed"
        ) from exc
    lock_config = _mapping(lock.get("ObjectLockConfiguration"))
    default_retention = _mapping(_mapping(lock_config.get("Rule")).get("DefaultRetention"))
    observed = {
        "versioning_status": versioning.get("Status"),
        "object_lock_enabled": lock_config.get("ObjectLockEnabled") == "Enabled",
        "default_retention_mode": default_retention.get("Mode"),
        "default_retention_days": default_retention.get("Days"),
    }
    if observed != {
        "versioning_status": "Enabled",
        "object_lock_enabled": True,
        "default_retention_mode": LOCAL_RETENTION_MODE,
        "default_retention_days": LOCAL_RETENTION_DAYS,
    }:
        raise MetadataFabricBackupRepositoryError(
            "backup repository controls did not match the local contract"
        )
    return observed


class _RepositoryRoundTrip:
    def __init__(self, client: Any, controls: Mapping[str, Any], recovery_point: str) -> None:
        self.client = client
        self.controls = dict(controls)
        self.recovery_point = recovery_point

    def __call__(
        self,
        artifact_paths: Mapping[str, Path],
        artifacts: Mapping[str, Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        uploaded: dict[str, dict[str, Any]] = {}
        try:
            for name in sorted(EXPECTED_ARTIFACTS):
                path = artifact_paths[name]
                body = path.read_bytes()
                sha256 = hashlib.sha256(body).hexdigest()
                suffix = "tar.gz" if name == "opensearch" else "dump"
                object_path = (
                    f"metadata-fabric/{self.recovery_point}/{name}.{suffix}"
                )
                response = self.client.put_object(
                    Bucket=REPOSITORY_BUCKET,
                    Key=object_path,
                    Body=body,
                    ContentLength=len(body),
                    ContentMD5=base64.b64encode(
                        hashlib.md5(body, usedforsecurity=False).digest()
                    ).decode("ascii"),
                    Metadata={
                        "gda-sha256": sha256,
                        "gda-format": str(artifacts[name]["format"]),
                    },
                )
                version_id = response.get("VersionId")
                if not version_id:
                    raise MetadataFabricBackupRepositoryError(
                        f"backup repository did not version {name}"
                    )
                head = self.client.head_object(
                    Bucket=REPOSITORY_BUCKET,
                    Key=object_path,
                    VersionId=version_id,
                )
                metadata = _mapping(head.get("Metadata"))
                if metadata.get("gda-sha256") != sha256:
                    raise MetadataFabricBackupRepositoryError(
                        f"backup repository metadata checksum differs for {name}"
                    )
                delete_blocked = False
                try:
                    self.client.delete_object(
                        Bucket=REPOSITORY_BUCKET,
                        Key=object_path,
                        VersionId=version_id,
                    )
                except Exception as exc:
                    response_payload = _mapping(getattr(exc, "response", None))
                    error_payload = _mapping(response_payload.get("Error"))
                    if error_payload.get("Code") in {
                        "AccessDenied",
                        "InvalidRequest",
                        "MethodNotAllowed",
                    }:
                        delete_blocked = True
                    else:
                        raise MetadataFabricBackupRepositoryError(
                            f"retained object deletion check failed for {name}"
                        ) from exc
                if not delete_blocked:
                    raise MetadataFabricBackupRepositoryError(
                        f"retained repository version was deletable for {name}"
                    )
                retained_until = head.get("ObjectLockRetainUntilDate")
                uploaded[name] = {
                    "object_path": object_path,
                    "version_id": version_id,
                    "format": artifacts[name]["format"],
                    "sha256": sha256,
                    "bytes": len(body),
                    "retention_mode": head.get("ObjectLockMode"),
                    "retained_until": (
                        retained_until.isoformat()
                        if hasattr(retained_until, "isoformat")
                        else str(retained_until or "")
                    ),
                    "retained_version_delete_blocked": delete_blocked,
                }

            for path in artifact_paths.values():
                path.unlink()
            removed_before_download = all(
                not path.exists() for path in artifact_paths.values()
            )
            if not removed_before_download:
                raise MetadataFabricBackupRepositoryError(
                    "local backup artifacts remained before repository download"
                )

            for name, item in uploaded.items():
                response = self.client.get_object(
                    Bucket=REPOSITORY_BUCKET,
                    Key=item["object_path"],
                    VersionId=item["version_id"],
                )
                body = response["Body"].read()
                if hashlib.sha256(body).hexdigest() != item["sha256"]:
                    raise MetadataFabricBackupRepositoryError(
                        f"downloaded repository checksum differs for {name}"
                    )
                recovery._write_private(artifact_paths[name], body)
        except MetadataFabricBackupRepositoryError:
            raise
        except Exception as exc:
            raise MetadataFabricBackupRepositoryError(
                "backup repository artifact round-trip failed"
            ) from exc

        return {
            "provider": "minio_s3_compatible",
            "bucket": REPOSITORY_BUCKET,
            **self.controls,
            "artifact_objects": uploaded,
            "local_artifacts_removed_before_download": removed_before_download,
            "round_trip_verified": True,
            "transport_tls_verified": False,
            "kms_encryption_verified": False,
            "production_durability_verified": False,
        }


def run_live_backup_repository_rehearsal(*, kubectl: str = "kubectl") -> dict[str, Any]:
    """Run a repository-backed restore and return verified local evidence."""
    runner = recovery._CommandRunner(kubectl)
    started = datetime.now(UTC)
    contract = build_backup_repository_contract_report()
    if contract["local_static_contract_verified"] is not True:
        raise MetadataFabricBackupRepositoryError(
            "backup repository static contract is invalid"
        )
    context = recovery._decode(
        runner.kubectl_run(["config", "current-context"], label="read cluster context"),
        "cluster context",
    ).strip()
    if context != "docker-desktop":
        raise MetadataFabricBackupRepositoryError(
            "backup repository rehearsal requires docker-desktop"
        )
    if runner.namespace_exists(REPOSITORY_NAMESPACE):
        raise MetadataFabricBackupRepositoryError(
            "backup repository Namespace already exists; refusing cleanup ambiguity"
        )

    temp_root = Path(tempfile.mkdtemp(prefix="gda-metadata-backup-repository-"))
    os.chmod(temp_root, 0o700)
    process: subprocess.Popen[bytes] | None = None
    repository_created = False
    repository_namespace_removed = False
    runtime_credentials_removed = False
    port_forward_stopped = False
    repository_identity: dict[str, Any] = {}
    repository_pvc: dict[str, Any] = {}
    repository_round_trip: dict[str, Any] = {}
    recovery_evidence: dict[str, Any] = {}
    failure: Exception | None = None
    source_identity = recovery._namespace_identity(runner, recovery.SOURCE_NAMESPACE)
    cluster_uid = recovery._cluster_uid(runner)

    try:
        runner.kubectl_run(
            ["apply", "-f", str(DEFAULT_MANIFEST_DIR / "namespace.yaml")],
            label="create backup repository Namespace",
        )
        repository_created = True
        username, password = _create_runtime_secret(runner, temp_root)
        runtime_credentials_removed = not any(temp_root.iterdir())
        runner.kubectl_run(
            ["apply", "--dry-run=server", "-k", str(DEFAULT_MANIFEST_DIR)],
            timeout=180,
            label="server validate backup repository workloads",
        )
        runner.kubectl_run(
            ["apply", "-k", str(DEFAULT_MANIFEST_DIR)],
            timeout=180,
            label="apply backup repository workloads",
        )
        runner.kubectl_run(
            [
                "-n",
                REPOSITORY_NAMESPACE,
                "rollout",
                "status",
                f"statefulset/{REPOSITORY_STATEFULSET}",
                "--timeout=10m",
            ],
            timeout=630,
            label="wait for backup repository",
        )
        repository_identity = recovery._namespace_identity(
            runner, REPOSITORY_NAMESPACE
        )
        repository_pvc = _repository_pvc_identity(runner)
        local_port = _free_local_port()
        process = _start_port_forward(kubectl, local_port)
        client = _build_s3_client(
            f"http://127.0.0.1:{local_port}", username, password
        )
        controls = _initialize_repository(client)
        recovery_point = "rp-" + started.strftime("%Y%m%d%H%M%SZ").lower()
        recovery_observation = recovery.run_live_recovery_rehearsal(
            kubectl=kubectl,
            artifact_round_trip=_RepositoryRoundTrip(
                client, controls, recovery_point
            ),
        )
        repository_round_trip = dict(
            _mapping(recovery_observation.get("repository_round_trip"))
        )
        recovery_evidence = recovery.build_recovery_evidence(recovery_observation)
        if recovery_evidence.get("backup_restore_verified") is not True:
            raise MetadataFabricBackupRepositoryError(
                "repository artifacts did not complete the recovery rehearsal"
            )
    except Exception as exc:
        failure = exc
    finally:
        port_forward_stopped = _stop_port_forward(process)
        try:
            if repository_created:
                runner.kubectl_run(
                    [
                        "delete",
                        "namespace",
                        REPOSITORY_NAMESPACE,
                        "--wait=true",
                        "--timeout=10m",
                    ],
                    timeout=630,
                    label="remove backup repository Namespace",
                )
                repository_namespace_removed = not runner.namespace_exists(
                    REPOSITORY_NAMESPACE
                )
        except Exception as exc:
            failure = failure or exc
        shutil.rmtree(temp_root, ignore_errors=True)
        runtime_credentials_removed = runtime_credentials_removed and not temp_root.exists()

    if failure is not None:
        if isinstance(failure, MetadataFabricBackupRepositoryError):
            raise failure
        if isinstance(failure, recovery.MetadataFabricRecoveryError):
            raise MetadataFabricBackupRepositoryError(
                "repository-backed recovery rehearsal failed"
            ) from failure
        raise MetadataFabricBackupRepositoryError(
            "live backup repository rehearsal failed"
        ) from failure

    completed = datetime.now(UTC)
    observation = {
        "schema": OBSERVATION_SCHEMA,
        "observed_at": completed.isoformat(),
        "started_at": started.isoformat(),
        "duration_seconds": round((completed - started).total_seconds(), 3),
        "contract": {
            "local_static_contract_verified": contract[
                "local_static_contract_verified"
            ],
            "contract_fingerprint": contract["contract_fingerprint"],
        },
        "cluster": {
            "context": context,
            "uid": cluster_uid,
            "source_namespace": source_identity,
            "repository_namespace": repository_identity,
        },
        "repository_pvc": repository_pvc,
        "repository_round_trip": repository_round_trip,
        "recovery_evidence": recovery_evidence,
        "runtime_checks": {
            "repository_namespace_removed": repository_namespace_removed,
            "runtime_credentials_removed": runtime_credentials_removed,
            "port_forward_stopped": port_forward_stopped,
        },
    }
    return build_backup_repository_evidence(observation, now=completed)


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MetadataFabricBackupRepositoryError("JSON input must be an object")
    return payload


def _write_report(report: Mapping[str, Any], output: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(rendered, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--kubectl", default="kubectl")
    run_parser.add_argument("--output", type=Path)
    run_parser.add_argument("--recovery-output", type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "validate":
            report = build_backup_repository_contract_report()
            _write_report(report, None)
            return 0 if report["local_static_contract_verified"] else 1
        if args.command == "run":
            report = run_live_backup_repository_rehearsal(kubectl=args.kubectl)
            _write_report(report, args.output)
            if args.recovery_output is not None:
                recovery_report = _mapping(
                    _mapping(report.get("observation")).get("recovery_evidence")
                )
                _write_report(recovery_report, args.recovery_output)
            return 0 if report["backup_repository_verified"] else 1
        report = _load_json_object(args.input)
        errors = verify_evidence_integrity(report)
        _write_report({"verified": not errors, "errors": errors}, None)
        return 0 if not errors else 1
    except MetadataFabricBackupRepositoryError as exc:
        print(f"metadata backup repository: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
