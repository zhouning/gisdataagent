"""Verify Metadata Fabric recovery across two local Kubernetes clusters.

The source remains Docker Desktop Kubernetes. Recovery runs in a distinct kind
cluster, while a locked MinIO repository runs directly on the Docker host with
separate writer and reader identities. The clusters still share one Docker
Desktop host, so this module never claims production durability, source-host
loss recovery, KMS, TLS, RPO/RTO, or production readiness.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from . import metadata_fabric_backup_repository as repository
from . import metadata_fabric_recovery_rehearsal as recovery


CONTRACT_SCHEMA = "gda.metadata_fabric_cross_cluster_recovery_contract.v1"
OBSERVATION_SCHEMA = "gda.metadata_fabric_cross_cluster_recovery_observation.v1"
EVIDENCE_SCHEMA = "gda.metadata_fabric_cross_cluster_recovery_evidence.v1"
PROFILE_SCHEMA = "gda.metadata_fabric_cross_cluster_recovery_profile.v1"
SOURCE_CONTEXT = "docker-desktop"
RECOVERY_CONTEXT = "kind-gda-metadata-recovery"
KIND_NODE_IMAGE = "kindest/node:v1.35.5"
MINIO_IMAGE = repository.MINIO_IMAGE
MC_IMAGE = "minio/mc:RELEASE.2025-04-16T18-13-26Z"
BUCKET = "gda-metadata-fabric-cross-cluster-backups"
RETENTION_MODE = "COMPLIANCE"
RETENTION_DAYS = 1
FAILURE_DOMAIN = "outside_source_and_recovery_kubernetes_clusters"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = (
    REPO_ROOT / "config/metadata-fabric-cross-cluster-recovery.local.yaml"
)
DEFAULT_WRAPPER = REPO_ROOT / "scripts/metadata-fabric-cross-cluster-recovery.sh"


class MetadataFabricCrossClusterRecoveryError(RuntimeError):
    """The cross-cluster recovery contract or rehearsal failed closed."""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _profile_errors(profile: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    source = _mapping(profile.get("source_cluster"))
    target = _mapping(profile.get("recovery_cluster"))
    backup = _mapping(profile.get("repository"))
    lock = _mapping(backup.get("object_lock"))
    identities = _mapping(backup.get("identities"))
    claims = _mapping(profile.get("claims"))
    if (
        profile.get("schema") != PROFILE_SCHEMA
        or profile.get("environment") != "local_docker_desktop"
    ):
        errors.append("cross-cluster profile schema or environment does not match")
    if source.get("context") != SOURCE_CONTEXT:
        errors.append("source cluster context must remain docker-desktop")
    if target.get("context") != RECOVERY_CONTEXT:
        errors.append("recovery cluster context does not match")
    if source.get("context") == target.get("context"):
        errors.append("source and recovery contexts must differ")
    if target.get("node_image") != KIND_NODE_IMAGE:
        errors.append("recovery kind node image must remain pinned")
    if backup.get("runtime") != "docker_host_container":
        errors.append("repository must run outside both Kubernetes clusters")
    if backup.get("failure_domain") != FAILURE_DOMAIN:
        errors.append("repository failure-domain declaration does not match")
    if backup.get("minio_image") != MINIO_IMAGE or backup.get("mc_image") != MC_IMAGE:
        errors.append("repository runtime images must remain pinned")
    if backup.get("bucket") != BUCKET or backup.get("versioning") != "Enabled":
        errors.append("repository bucket identity or versioning does not match")
    if (
        lock.get("enabled") is not True
        or lock.get("mode") != RETENTION_MODE
        or lock.get("retention_days") != RETENTION_DAYS
    ):
        errors.append("local cross-cluster repository must use COMPLIANCE/1 day")
    if identities.get("writer_delete_denied") is not True:
        errors.append("repository writer must be denied delete access")
    if identities.get("reader_write_denied") is not True:
        errors.append("repository reader must be denied write access")
    for claim in (
        "local_cross_cluster_recovery_verified",
        "production_backup_target_verified",
        "production_retention_verified",
        "production_kms_verified",
        "production_tls_verified",
        "production_cross_cluster_recovery_verified",
        "source_cluster_loss_verified",
        "rpo_slo_verified",
        "rto_slo_verified",
        "oidc_verified",
        "network_policy_enforcement_verified",
        "writes_to_gda_enabled",
        "production_ready",
    ):
        if claims.get(claim) is not False:
            errors.append(f"unverified profile claim must remain false: {claim}")
    return errors


def build_cross_cluster_contract_report(
    profile_path: Path | None = None,
    wrapper_path: Path | None = None,
) -> dict[str, Any]:
    """Validate the local dual-cluster profile and production claim boundary."""
    profile_file = (profile_path or DEFAULT_PROFILE_PATH).resolve()
    wrapper = (wrapper_path or DEFAULT_WRAPPER).resolve()
    errors: list[str] = []
    try:
        profile = repository._load_yaml_object(profile_file)
        errors.extend(_profile_errors(profile))
    except (OSError, TypeError) as exc:
        errors.append(f"cross-cluster profile is invalid: {type(exc).__name__}")

    recovery_contract = recovery.build_recovery_contract_report()
    if recovery_contract.get("static_contract_verified") is not True:
        errors.append("metadata recovery contract is invalid")
    try:
        production_policy = repository._load_yaml_object(
            repository.DEFAULT_POLICY_PATH
        )
        errors.extend(repository._production_policy_errors(production_policy))
    except (OSError, TypeError) as exc:
        errors.append(f"production backup policy is invalid: {type(exc).__name__}")
    try:
        wrapper_text = wrapper.read_text(encoding="utf-8")
        for marker in (
            "set -euo pipefail",
            "metadata_fabric_cross_cluster_recovery",
        ):
            if marker not in wrapper_text:
                errors.append(f"cross-cluster wrapper is missing safety marker: {marker}")
    except OSError as exc:
        errors.append(f"cross-cluster wrapper is invalid: {type(exc).__name__}")

    files: dict[str, dict[str, str]] = {}
    for path in (
        Path(__file__).resolve(),
        Path(recovery.__file__).resolve(),
        Path(repository.__file__).resolve(),
        profile_file,
        repository.DEFAULT_POLICY_PATH.resolve(),
        wrapper,
    ):
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
        "source_context": SOURCE_CONTEXT,
        "recovery_context": RECOVERY_CONTEXT,
        "kind_node_image": KIND_NODE_IMAGE,
        "repository_failure_domain": FAILURE_DOMAIN,
        "repository_bucket": BUCKET,
        "artifact_inventory": repository.EXPECTED_ARTIFACTS,
        "local_static_contract_verified": not errors,
        "local_cross_cluster_recovery_verified": False,
        "production_cross_cluster_recovery_verified": False,
        "files": files,
        "errors": errors,
    }
    return {**stable, "contract_fingerprint": recovery._canonical_sha256(stable)}


class _DockerRuntime:
    def __init__(self, docker: str = "docker") -> None:
        self.docker = docker

    def run(
        self,
        args: list[str],
        *,
        timeout: int = 180,
        label: str,
    ) -> bytes:
        try:
            completed = subprocess.run(
                [self.docker, *args],
                capture_output=True,
                check=False,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise MetadataFabricCrossClusterRecoveryError(
                f"{label} was unavailable"
            ) from exc
        if completed.returncode != 0:
            raise MetadataFabricCrossClusterRecoveryError(f"{label} failed")
        return completed.stdout

    def exists(self, kind: str, name: str) -> bool:
        try:
            completed = subprocess.run(
                [self.docker, kind, "inspect", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise MetadataFabricCrossClusterRecoveryError(
                f"Docker {kind} inspection failed"
            ) from exc
        return completed.returncode == 0


def _write_json_private(path: Path, payload: Mapping[str, Any]) -> None:
    recovery._write_private(
        path,
        (json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )


def _access_denied(action: Callable[[], Any]) -> bool:
    try:
        action()
    except Exception as exc:
        response = _mapping(getattr(exc, "response", None))
        error = _mapping(response.get("Error"))
        return error.get("Code") in {
            "AccessDenied",
            "InvalidRequest",
            "MethodNotAllowed",
        }
    return False


class _ExternalRepositoryRuntime:
    def __init__(self, temp_root: Path, docker: str = "docker") -> None:
        suffix = secrets.token_hex(8)
        self.temp_root = temp_root
        self.runtime = _DockerRuntime(docker)
        self.container_name = f"gda-metadata-cross-cluster-minio-{suffix}"
        self.volume_name = f"gda-metadata-cross-cluster-backup-{suffix}"
        self.port = repository._free_local_port()
        self.root_user = "gdaroot" + secrets.token_hex(8)
        self.root_password = secrets.token_urlsafe(36)
        self.writer_user = "gdawriter" + secrets.token_hex(8)
        self.writer_password = secrets.token_urlsafe(36)
        self.reader_user = "gdareader" + secrets.token_hex(8)
        self.reader_password = secrets.token_urlsafe(36)
        self.container_started = False
        self.volume_created = False

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _wait_for_repository(self, client: Any) -> None:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                client.list_buckets()
                return
            except Exception:
                time.sleep(0.5)
        raise MetadataFabricCrossClusterRecoveryError(
            "external backup repository did not become ready"
        )

    def _initialize(self, client: Any) -> dict[str, Any]:
        try:
            client.create_bucket(Bucket=BUCKET, ObjectLockEnabledForBucket=True)
            client.put_bucket_versioning(
                Bucket=BUCKET,
                VersioningConfiguration={"Status": "Enabled"},
            )
            client.put_object_lock_configuration(
                Bucket=BUCKET,
                ObjectLockConfiguration={
                    "ObjectLockEnabled": "Enabled",
                    "Rule": {
                        "DefaultRetention": {
                            "Mode": RETENTION_MODE,
                            "Days": RETENTION_DAYS,
                        }
                    },
                },
            )
            versioning = client.get_bucket_versioning(Bucket=BUCKET)
            lock = client.get_object_lock_configuration(Bucket=BUCKET)
        except Exception as exc:
            raise MetadataFabricCrossClusterRecoveryError(
                "external backup repository initialization failed"
            ) from exc
        lock_config = _mapping(lock.get("ObjectLockConfiguration"))
        retention = _mapping(_mapping(lock_config.get("Rule")).get("DefaultRetention"))
        controls = {
            "versioning_status": versioning.get("Status"),
            "object_lock_enabled": lock_config.get("ObjectLockEnabled") == "Enabled",
            "default_retention_mode": retention.get("Mode"),
            "default_retention_days": retention.get("Days"),
        }
        if controls != {
            "versioning_status": "Enabled",
            "object_lock_enabled": True,
            "default_retention_mode": RETENTION_MODE,
            "default_retention_days": RETENTION_DAYS,
        }:
            raise MetadataFabricCrossClusterRecoveryError(
                "external repository controls do not match"
            )
        return controls

    def _provision_identities(self) -> None:
        policies = self.temp_root / "policies"
        policies.mkdir(mode=0o700)
        bucket_arn = f"arn:aws:s3:::{BUCKET}"
        common_bucket = {
            "Effect": "Allow",
            "Action": ["s3:GetBucketLocation", "s3:ListBucket"],
            "Resource": [bucket_arn],
        }
        writer_policy = {
            "Version": "2012-10-17",
            "Statement": [
                common_bucket,
                {
                    "Effect": "Allow",
                    "Action": [
                        "s3:GetObject",
                        "s3:GetObjectRetention",
                        "s3:GetObjectVersion",
                        "s3:PutObject",
                    ],
                    "Resource": [f"{bucket_arn}/metadata-fabric/*"],
                },
            ],
        }
        reader_policy = {
            "Version": "2012-10-17",
            "Statement": [
                common_bucket,
                {
                    "Effect": "Allow",
                    "Action": [
                        "s3:GetObject",
                        "s3:GetObjectRetention",
                        "s3:GetObjectVersion",
                    ],
                    "Resource": [f"{bucket_arn}/metadata-fabric/*"],
                },
            ],
        }
        _write_json_private(policies / "writer.json", writer_policy)
        _write_json_private(policies / "reader.json", reader_policy)
        env_path = self.temp_root / "mc-runtime.env"
        recovery._write_private(
            env_path,
            (
                f"MC_HOST_admin=http://{self.root_user}:{self.root_password}@127.0.0.1:9000\n"
                f"GDA_WRITER_USER={self.writer_user}\n"
                f"GDA_WRITER_PASSWORD={self.writer_password}\n"
                f"GDA_READER_USER={self.reader_user}\n"
                f"GDA_READER_PASSWORD={self.reader_password}\n"
            ).encode("ascii"),
        )
        script = "\n".join(
            (
                "mc admin policy create admin gda-metadata-writer /policies/writer.json",
                "mc admin policy create admin gda-metadata-reader /policies/reader.json",
                'mc admin user add admin "$GDA_WRITER_USER" "$GDA_WRITER_PASSWORD"',
                'mc admin user add admin "$GDA_READER_USER" "$GDA_READER_PASSWORD"',
                'mc admin policy attach admin gda-metadata-writer --user "$GDA_WRITER_USER"',
                'mc admin policy attach admin gda-metadata-reader --user "$GDA_READER_USER"',
            )
        )
        self.runtime.run(
            [
                "run",
                "--rm",
                "--network",
                f"container:{self.container_name}",
                "--env-file",
                str(env_path),
                "--mount",
                f"type=bind,src={policies},dst=/policies,readonly",
                "--entrypoint",
                "/bin/sh",
                MC_IMAGE,
                "-ceu",
                script,
            ],
            timeout=120,
            label="provision external repository identities",
        )
        env_path.unlink()

    def start(self) -> tuple[Any, Any, Any, dict[str, Any]]:
        self.runtime.run(
            [
                "volume",
                "create",
                "--label",
                "gda.openai.com/ephemeral-owner=metadata-cross-cluster-rehearsal",
                self.volume_name,
            ],
            label="create external repository volume",
        )
        self.volume_created = True
        self.runtime.run(
            [
                "run",
                "--rm",
                "--mount",
                f"type=volume,src={self.volume_name},dst=/data",
                "busybox:1.36",
                "chown",
                "1000:1000",
                "/data",
            ],
            label="prepare external repository volume ownership",
        )
        env_path = self.temp_root / "minio-runtime.env"
        recovery._write_private(
            env_path,
            (
                f"MINIO_ROOT_USER={self.root_user}\n"
                f"MINIO_ROOT_PASSWORD={self.root_password}\n"
                "MINIO_BROWSER=off\n"
                "HOME=/home/minio\n"
            ).encode("ascii"),
        )
        self.runtime.run(
            [
                "run",
                "--rm",
                "--detach",
                "--name",
                self.container_name,
                "--label",
                "gda.openai.com/ephemeral-owner=metadata-cross-cluster-rehearsal",
                "--publish",
                f"127.0.0.1:{self.port}:9000",
                "--env-file",
                str(env_path),
                "--user",
                "1000:1000",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,nodev,size=1g",
                "--tmpfs",
                "/home/minio:rw,noexec,nosuid,nodev,size=128m",
                "--mount",
                f"type=volume,src={self.volume_name},dst=/data",
                MINIO_IMAGE,
                "server",
                "/data",
                "--address",
                ":9000",
            ],
            label="start external backup repository",
        )
        self.container_started = True
        env_path.unlink()
        admin = repository._build_s3_client(
            self.endpoint, self.root_user, self.root_password
        )
        self._wait_for_repository(admin)
        controls = self._initialize(admin)
        self._provision_identities()
        writer = repository._build_s3_client(
            self.endpoint, self.writer_user, self.writer_password
        )
        reader = repository._build_s3_client(
            self.endpoint, self.reader_user, self.reader_password
        )
        return admin, writer, reader, controls

    def cleanup(self) -> dict[str, bool]:
        if self.runtime.exists("container", self.container_name):
            self.runtime.run(
                ["rm", "--force", self.container_name],
                label="remove external repository container",
            )
        container_removed = not self.runtime.exists("container", self.container_name)
        if self.runtime.exists("volume", self.volume_name):
            self.runtime.run(
                ["volume", "rm", self.volume_name],
                label="remove external repository volume",
            )
        volume_removed = not self.runtime.exists("volume", self.volume_name)
        return {
            "external_repository_container_removed": container_removed,
            "external_repository_volume_removed": volume_removed,
        }


class _ExternalRepositoryRoundTrip:
    def __init__(
        self,
        admin: Any,
        writer: Any,
        reader: Any,
        controls: Mapping[str, Any],
        recovery_point: str,
    ) -> None:
        self.admin = admin
        self.writer = writer
        self.reader = reader
        self.controls = dict(controls)
        self.recovery_point = recovery_point

    def __call__(
        self,
        artifact_paths: Mapping[str, Path],
        artifacts: Mapping[str, Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        uploaded: dict[str, dict[str, Any]] = {}
        try:
            for name in sorted(repository.EXPECTED_ARTIFACTS):
                path = artifact_paths[name]
                body = path.read_bytes()
                sha256 = hashlib.sha256(body).hexdigest()
                suffix = "tar.gz" if name == "opensearch" else "dump"
                object_path = (
                    f"metadata-fabric/{self.recovery_point}/{name}.{suffix}"
                )
                response = self.writer.put_object(
                    Bucket=BUCKET,
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
                    raise MetadataFabricCrossClusterRecoveryError(
                        f"external repository did not version {name}"
                    )
                head = self.reader.head_object(
                    Bucket=BUCKET,
                    Key=object_path,
                    VersionId=version_id,
                )
                metadata = _mapping(head.get("Metadata"))
                if metadata.get("gda-sha256") != sha256:
                    raise MetadataFabricCrossClusterRecoveryError(
                        f"external repository checksum differs for {name}"
                    )
                writer_delete_denied = _access_denied(
                    lambda: self.writer.delete_object(
                        Bucket=BUCKET,
                        Key=object_path,
                        VersionId=version_id,
                    )
                )
                compliance_delete_blocked = _access_denied(
                    lambda: self.admin.delete_object(
                        Bucket=BUCKET,
                        Key=object_path,
                        VersionId=version_id,
                    )
                )
                if not writer_delete_denied or not compliance_delete_blocked:
                    raise MetadataFabricCrossClusterRecoveryError(
                        f"external repository deletion controls failed for {name}"
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
                    "writer_delete_denied": writer_delete_denied,
                    "compliance_delete_blocked": compliance_delete_blocked,
                }

            reader_write_denied = _access_denied(
                lambda: self.reader.put_object(
                    Bucket=BUCKET,
                    Key=f"metadata-fabric/{self.recovery_point}/reader-write-probe",
                    Body=b"denied",
                    ContentLength=6,
                )
            )
            if not reader_write_denied:
                raise MetadataFabricCrossClusterRecoveryError(
                    "external recovery reader was allowed to write"
                )
            for path in artifact_paths.values():
                path.unlink()
            removed_before_download = all(
                not path.exists() for path in artifact_paths.values()
            )
            if not removed_before_download:
                raise MetadataFabricCrossClusterRecoveryError(
                    "local artifacts remained before external repository download"
                )
            for name, item in uploaded.items():
                response = self.reader.get_object(
                    Bucket=BUCKET,
                    Key=item["object_path"],
                    VersionId=item["version_id"],
                )
                body = response["Body"].read()
                if hashlib.sha256(body).hexdigest() != item["sha256"]:
                    raise MetadataFabricCrossClusterRecoveryError(
                        f"external repository download differs for {name}"
                    )
                recovery._write_private(artifact_paths[name], body)
        except MetadataFabricCrossClusterRecoveryError:
            raise
        except Exception as exc:
            raise MetadataFabricCrossClusterRecoveryError(
                "external repository artifact round-trip failed"
            ) from exc

        return {
            "provider": "minio_s3_compatible",
            "repository_runtime": "docker_host_container",
            "failure_domain": FAILURE_DOMAIN,
            "bucket": BUCKET,
            **self.controls,
            "artifact_objects": uploaded,
            "identity_controls": {
                "separate_writer_reader": True,
                "writer_delete_denied": True,
                "reader_write_denied": reader_write_denied,
            },
            "local_artifacts_removed_before_download": removed_before_download,
            "round_trip_verified": True,
            "transport_tls_verified": False,
            "kms_encryption_verified": False,
            "production_durability_verified": False,
        }


def _repository_errors(
    round_trip: Mapping[str, Any], *, verification_time: datetime
) -> list[str]:
    errors: list[str] = []
    artifacts = _mapping(round_trip.get("artifact_objects"))
    identities = _mapping(round_trip.get("identity_controls"))
    if round_trip.get("provider") != "minio_s3_compatible":
        errors.append("external repository provider does not match")
    if round_trip.get("repository_runtime") != "docker_host_container":
        errors.append("repository did not run outside Kubernetes")
    if round_trip.get("failure_domain") != FAILURE_DOMAIN:
        errors.append("repository failure domain does not match")
    if round_trip.get("bucket") != BUCKET:
        errors.append("cross-cluster repository bucket does not match")
    if round_trip.get("versioning_status") != "Enabled":
        errors.append("cross-cluster repository versioning was not enabled")
    if round_trip.get("object_lock_enabled") is not True:
        errors.append("cross-cluster repository Object Lock was not enabled")
    if (
        round_trip.get("default_retention_mode") != RETENTION_MODE
        or round_trip.get("default_retention_days") != RETENTION_DAYS
    ):
        errors.append("cross-cluster repository retention does not match")
    if round_trip.get("local_artifacts_removed_before_download") is not True:
        errors.append("local artifacts were not removed before external download")
    if round_trip.get("round_trip_verified") is not True:
        errors.append("external repository round-trip was not verified")
    if identities.get("separate_writer_reader") is not True:
        errors.append("external repository writer and reader were not separated")
    if identities.get("writer_delete_denied") is not True:
        errors.append("external repository writer delete was not denied")
    if identities.get("reader_write_denied") is not True:
        errors.append("external repository reader write was not denied")
    for claim in (
        "transport_tls_verified",
        "kms_encryption_verified",
        "production_durability_verified",
    ):
        if round_trip.get(claim) is not False:
            errors.append(f"external repository may not claim {claim}")
    if set(artifacts) != set(repository.EXPECTED_ARTIFACTS):
        errors.append("external repository artifact inventory does not match")
    version_ids: set[str] = set()
    for name, expected_format in repository.EXPECTED_ARTIFACTS.items():
        item = _mapping(artifacts.get(name))
        if item.get("format") != expected_format:
            errors.append(f"external repository artifact format differs: {name}")
        if not repository._valid_fingerprint(item.get("sha256")):
            errors.append(f"external repository artifact checksum is invalid: {name}")
        if not isinstance(item.get("bytes"), int) or item.get("bytes", 0) <= 0:
            errors.append(f"external repository artifact is empty: {name}")
        object_path = str(item.get("object_path") or "")
        if not object_path.startswith("metadata-fabric/") or ".." in object_path:
            errors.append(f"external repository artifact path is invalid: {name}")
        if not item.get("version_id"):
            errors.append(f"external repository artifact has no version: {name}")
        elif str(item.get("version_id")) in version_ids:
            errors.append(f"external repository artifact version is not unique: {name}")
        else:
            version_ids.add(str(item.get("version_id")))
        if item.get("retention_mode") != RETENTION_MODE:
            errors.append(f"external repository artifact is not COMPLIANCE locked: {name}")
        try:
            retained_until = datetime.fromisoformat(str(item.get("retained_until")))
            if (
                retained_until.tzinfo is None
                or retained_until.utcoffset() is None
                or retained_until <= verification_time
            ):
                raise ValueError
        except ValueError:
            errors.append(
                f"external repository artifact retention is not in the future: {name}"
            )
        if item.get("writer_delete_denied") is not True:
            errors.append(f"external repository writer delete control failed: {name}")
        if item.get("compliance_delete_blocked") is not True:
            errors.append(f"external repository COMPLIANCE delete was not blocked: {name}")
    return errors


def _observation_errors(
    observation: Mapping[str, Any], *, now: datetime, max_age_seconds: float
) -> list[str]:
    errors: list[str] = []
    if recovery._sensitive_paths(observation):
        errors.append("cross-cluster observation contains credential-bearing fields")
    if observation.get("schema") != OBSERVATION_SCHEMA:
        errors.append("cross-cluster observation schema does not match")
    try:
        observed_at = datetime.fromisoformat(str(observation.get("observed_at")))
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError
        age = (now - observed_at).total_seconds()
        if age < -30 or age > max_age_seconds:
            errors.append("cross-cluster observation is outside the freshness window")
    except ValueError:
        errors.append("cross-cluster observation timestamp is invalid")
    contract = _mapping(observation.get("contract"))
    if contract.get("local_static_contract_verified") is not True:
        errors.append("cross-cluster static contract was not verified")
    if not repository._valid_fingerprint(contract.get("contract_fingerprint")):
        errors.append("cross-cluster contract fingerprint is invalid")

    repository_runtime = _mapping(observation.get("repository"))
    if repository_runtime.get("runtime") != "docker_host_container":
        errors.append("outer repository runtime does not match")
    if repository_runtime.get("failure_domain") != FAILURE_DOMAIN:
        errors.append("outer repository failure domain does not match")
    if repository_runtime.get("minio_image") != MINIO_IMAGE:
        errors.append("outer repository MinIO image does not match")
    if repository_runtime.get("mc_image") != MC_IMAGE:
        errors.append("outer repository client image does not match")

    recovery_evidence = _mapping(observation.get("recovery_evidence"))
    nested_errors = recovery.verify_evidence_integrity(recovery_evidence)
    errors.extend(f"nested recovery evidence: {item}" for item in nested_errors)
    if recovery_evidence.get("local_cross_cluster_recovery_verified") is not True:
        errors.append("nested recovery did not verify distinct local clusters")
    if recovery_evidence.get("production_cross_cluster_recovery_verified") is not False:
        errors.append("nested recovery overclaims production cross-cluster recovery")
    nested_observation = _mapping(recovery_evidence.get("observation"))
    cluster = _mapping(nested_observation.get("cluster"))
    if cluster.get("context") != SOURCE_CONTEXT:
        errors.append("cross-cluster source context does not match")
    if cluster.get("recovery_context") != RECOVERY_CONTEXT:
        errors.append("cross-cluster recovery context does not match")
    if not cluster.get("uid") or not cluster.get("recovery_uid"):
        errors.append("cross-cluster identities are unavailable")
    elif cluster.get("uid") == cluster.get("recovery_uid"):
        errors.append("source and recovery cluster identities are not isolated")

    round_trip = _mapping(nested_observation.get("repository_round_trip"))
    errors.extend(_repository_errors(round_trip, verification_time=now))
    source_artifacts = _mapping(nested_observation.get("artifacts"))
    repository_artifacts = _mapping(round_trip.get("artifact_objects"))
    for name in repository.EXPECTED_ARTIFACTS:
        source = _mapping(source_artifacts.get(name))
        stored = _mapping(repository_artifacts.get(name))
        if stored.get("sha256") != source.get("sha256") or stored.get(
            "bytes"
        ) != source.get("bytes"):
            errors.append(f"external repository content differs from recovery: {name}")

    runtime = _mapping(observation.get("runtime_checks"))
    for key in (
        "external_repository_container_removed",
        "external_repository_volume_removed",
        "runtime_credentials_removed",
        "recovery_cluster_preserved",
    ):
        if runtime.get(key) is not True:
            errors.append(f"cross-cluster runtime check did not pass: {key}")
    return errors


def build_cross_cluster_evidence(
    observation: Mapping[str, Any],
    *,
    now: datetime | None = None,
    max_age_seconds: float = 3600,
) -> dict[str, Any]:
    """Build fail-closed evidence for the host-bounded dual-cluster recovery."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise MetadataFabricCrossClusterRecoveryError(
            "verification time must be timezone-aware"
        )
    errors = _observation_errors(
        observation, now=current, max_age_seconds=max_age_seconds
    )
    verified = not errors
    stable = {
        "schema": EVIDENCE_SCHEMA,
        "environment": "local_same_host_distinct_kubernetes_clusters",
        "source_context": SOURCE_CONTEXT,
        "recovery_context": RECOVERY_CONTEXT,
        "observation_fingerprint": recovery._canonical_sha256(observation),
        "checks": {
            "static_contract": "passed" if verified else "blocked",
            "cluster_identity_isolation": "passed" if verified else "blocked",
            "repository_failure_domain": "passed" if verified else "blocked",
            "writer_reader_separation": "passed" if verified else "blocked",
            "compliance_retention": "passed" if verified else "blocked",
            "artifact_round_trip": "passed" if verified else "blocked",
            "cross_cluster_restore": "passed" if verified else "blocked",
            "ephemeral_cleanup": "passed" if verified else "blocked",
            "production_boundaries": "passed",
        },
        "errors": errors,
        "cross_cluster_recovery_scope": (
            "local_same_host_distinct_kubernetes_clusters_external_s3_repository"
        ),
        "local_cross_cluster_recovery_verified": verified,
        "local_external_repository_verified": verified,
        "local_writer_reader_identity_separation_verified": verified,
        "cross_cluster_recovery_verified": False,
        "production_cross_cluster_recovery_verified": False,
        "production_backup_target_verified": False,
        "production_retention_verified": False,
        "production_kms_verified": False,
        "production_tls_verified": False,
        "source_cluster_loss_verified": False,
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
        "status": "local_cross_cluster_recovery_verified" if verified else "blocked",
        "evidence_fingerprint": recovery._canonical_sha256(stable),
    }


def verify_evidence_integrity(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if recovery._sensitive_paths(report):
        errors.append("cross-cluster evidence contains credential-bearing fields")
    if report.get("schema") != EVIDENCE_SCHEMA:
        errors.append("cross-cluster evidence schema does not match")
    stable = {
        key: value
        for key, value in report.items()
        if key not in {"generated_at", "status", "evidence_fingerprint"}
    }
    if report.get("evidence_fingerprint") != recovery._canonical_sha256(stable):
        errors.append("cross-cluster evidence fingerprint does not match")
    for claim in (
        "cross_cluster_recovery_verified",
        "production_cross_cluster_recovery_verified",
        "production_backup_target_verified",
        "production_retention_verified",
        "production_kms_verified",
        "production_tls_verified",
        "source_cluster_loss_verified",
        "cross_region_recovery_verified",
        "rpo_slo_verified",
        "rto_slo_verified",
        "oidc_verified",
        "network_policy_enforcement_verified",
        "writes_to_gda_enabled",
        "production_ready",
    ):
        if report.get(claim) is not False:
            errors.append(f"cross-cluster evidence may not claim {claim}")
    return errors


def run_live_cross_cluster_recovery(
    *,
    kubectl: str = "kubectl",
    docker: str = "docker",
    source_context: str = SOURCE_CONTEXT,
    recovery_context: str = RECOVERY_CONTEXT,
) -> dict[str, Any]:
    """Run the locked repository round-trip into a distinct local cluster."""
    if source_context != SOURCE_CONTEXT or recovery_context != RECOVERY_CONTEXT:
        raise MetadataFabricCrossClusterRecoveryError(
            "live contexts do not match the bounded local profile"
        )
    started = datetime.now(UTC)
    contract = build_cross_cluster_contract_report()
    if contract["local_static_contract_verified"] is not True:
        raise MetadataFabricCrossClusterRecoveryError(
            "cross-cluster static contract is invalid"
        )
    source_runner = recovery._CommandRunner(kubectl, source_context)
    target_runner = recovery._CommandRunner(kubectl, recovery_context)
    source_uid = recovery._cluster_uid(source_runner)
    recovery_uid = recovery._cluster_uid(target_runner)
    if not source_uid or not recovery_uid or source_uid == recovery_uid:
        raise MetadataFabricCrossClusterRecoveryError(
            "source and recovery clusters are not independently identified"
        )

    temp_root = Path(tempfile.mkdtemp(prefix="gda-metadata-cross-cluster-"))
    os.chmod(temp_root, 0o700)
    external = _ExternalRepositoryRuntime(temp_root, docker)
    recovery_observation: dict[str, Any] = {}
    cleanup = {
        "external_repository_container_removed": False,
        "external_repository_volume_removed": False,
    }
    failure: Exception | None = None
    try:
        admin, writer, reader, controls = external.start()
        recovery_point = "rp-" + started.strftime("%Y%m%d%H%M%SZ").lower()
        recovery_observation = recovery.run_live_recovery_rehearsal(
            kubectl=kubectl,
            source_context=source_context,
            recovery_context=recovery_context,
            artifact_round_trip=_ExternalRepositoryRoundTrip(
                admin,
                writer,
                reader,
                controls,
                recovery_point,
            ),
        )
    except Exception as exc:
        failure = exc
    finally:
        try:
            cleanup = external.cleanup()
        except Exception as exc:
            failure = failure or exc
        shutil.rmtree(temp_root, ignore_errors=True)
        runtime_credentials_removed = not temp_root.exists()

    if failure is not None:
        if isinstance(failure, MetadataFabricCrossClusterRecoveryError):
            raise failure
        if isinstance(failure, recovery.MetadataFabricRecoveryError):
            raise MetadataFabricCrossClusterRecoveryError(
                "cross-cluster metadata recovery failed"
            ) from failure
        raise MetadataFabricCrossClusterRecoveryError(
            "live cross-cluster rehearsal failed"
        ) from failure

    completed = datetime.now(UTC)
    recovery_evidence = recovery.build_recovery_evidence(
        recovery_observation, now=completed
    )
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
        "repository": {
            "runtime": "docker_host_container",
            "failure_domain": FAILURE_DOMAIN,
            "minio_image": MINIO_IMAGE,
            "mc_image": MC_IMAGE,
        },
        "recovery_evidence": recovery_evidence,
        "runtime_checks": {
            **cleanup,
            "runtime_credentials_removed": runtime_credentials_removed,
            "recovery_cluster_preserved": (
                recovery._cluster_uid(target_runner) == recovery_uid
            ),
        },
    }
    return build_cross_cluster_evidence(observation, now=completed)


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MetadataFabricCrossClusterRecoveryError("JSON input must be an object")
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
    run_parser.add_argument("--docker", default="docker")
    run_parser.add_argument("--source-context", default=SOURCE_CONTEXT)
    run_parser.add_argument("--recovery-context", default=RECOVERY_CONTEXT)
    run_parser.add_argument("--output", type=Path)
    run_parser.add_argument("--recovery-output", type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "validate":
            report = build_cross_cluster_contract_report()
            _write_report(report, None)
            return 0 if report["local_static_contract_verified"] else 1
        if args.command == "run":
            report = run_live_cross_cluster_recovery(
                kubectl=args.kubectl,
                docker=args.docker,
                source_context=args.source_context,
                recovery_context=args.recovery_context,
            )
            _write_report(report, args.output)
            if args.recovery_output is not None:
                nested = _mapping(_mapping(report.get("observation")).get("recovery_evidence"))
                _write_report(nested, args.recovery_output)
            return 0 if report["local_cross_cluster_recovery_verified"] else 1
        report = _load_json_object(args.input)
        errors = verify_evidence_integrity(report)
        _write_report({"verified": not errors, "errors": errors}, None)
        return 0 if not errors else 1
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        MetadataFabricCrossClusterRecoveryError,
        KeyboardInterrupt,
    ) as exc:
        print(f"metadata cross-cluster recovery: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
