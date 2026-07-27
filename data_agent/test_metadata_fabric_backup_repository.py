import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import yaml

from data_agent import metadata_fabric_backup_repository as repository
from data_agent import metadata_fabric_recovery_rehearsal as recovery


NOW = datetime(2026, 7, 27, 8, 0, tzinfo=UTC)


def _postgres_marker(seed: str, table_count: int) -> dict:
    return {
        "image_version": recovery.POSTGRESQL_VERSION,
        "server_version": "16.10 (Debian 16.10-1.pgdg12+1)",
        "table_count": table_count,
        "table_name_fingerprint": seed * 64,
        "row_count_fingerprint": chr(ord(seed) + 1) * 64,
        "sequence_state_fingerprint": chr(ord(seed) + 2) * 64,
        "extension_fingerprint": chr(ord(seed) + 3) * 64,
    }


def _recovery_observation() -> dict:
    openmetadata = _postgres_marker("1", 176)
    gravitino = _postgres_marker("5", 39)
    source_search = {
        "version": recovery.OPENSEARCH_VERSION,
        "cluster_uuid": "source-cluster",
        "index_count": 79,
        "total_index_count": 79,
        "index_name_fingerprint": "9" * 64,
        "document_count_fingerprint": "a" * 64,
    }
    artifacts = {
        "openmetadata_postgresql": {
            "format": "postgresql_custom_dump_v1",
            "sha256": "b" * 64,
            "bytes": 8192,
        },
        "gravitino_postgresql": {
            "format": "postgresql_custom_dump_v1",
            "sha256": "c" * 64,
            "bytes": 4096,
        },
        "opensearch": {
            "format": "opensearch_fs_snapshot_tar_gzip_v1",
            "sha256": "d" * 64,
            "bytes": 16384,
        },
    }
    return {
        "schema": recovery.OBSERVATION_SCHEMA,
        "observed_at": NOW.isoformat(),
        "started_at": NOW.isoformat(),
        "duration_seconds": 120.0,
        "contract": {
            "static_contract_verified": True,
            "contract_fingerprint": "e" * 64,
        },
        "cluster": {
            "context": "docker-desktop",
            "uid": "cluster-uid",
            "source_namespace": {
                "name": recovery.SOURCE_NAMESPACE,
                "uid": "source-uid",
            },
            "recovery_namespace": {
                "name": recovery.RECOVERY_NAMESPACE,
                "uid": "recovery-uid",
            },
        },
        "recovery_pvcs": {
            name: {
                "uid": f"uid-{index}",
                "volume_name": f"volume-{index}",
                "capacity": capacity,
                "phase": "Bound",
            }
            for index, (name, capacity) in enumerate(
                recovery.RECOVERY_PVCS.items(), start=1
            )
        },
        "artifacts": artifacts,
        "source_markers": {
            "openmetadata_postgresql": openmetadata,
            "gravitino_postgresql": gravitino,
            "opensearch": source_search,
        },
        "recovered_markers": {
            "openmetadata_postgresql": dict(openmetadata),
            "gravitino_postgresql": dict(gravitino),
            "opensearch": {**source_search, "cluster_uuid": "recovered-cluster"},
        },
        "runtime_checks": {
            "source_quiesced": True,
            "source_snapshot_staging_initially_empty": True,
            "recovery_search_target_cleared": True,
            "source_services_restored": True,
            "source_snapshot_staging_cleaned": True,
            "recovery_namespace_removed": True,
            "local_artifacts_removed": True,
        },
    }


def _repository_observation() -> dict:
    recovery_evidence = recovery.build_recovery_evidence(
        _recovery_observation(), now=NOW
    )
    source_artifacts = recovery_evidence["observation"]["artifacts"]
    artifact_objects = {
        name: {
            "object_path": f"metadata-fabric/rp-20260727/{name}.backup",
            "version_id": f"version-{index}",
            "format": artifact["format"],
            "sha256": artifact["sha256"],
            "bytes": artifact["bytes"],
            "retention_mode": repository.LOCAL_RETENTION_MODE,
            "retained_until": "2026-07-28T08:00:00+00:00",
            "retained_version_delete_blocked": True,
        }
        for index, (name, artifact) in enumerate(source_artifacts.items(), start=1)
    }
    return {
        "schema": repository.OBSERVATION_SCHEMA,
        "observed_at": NOW.isoformat(),
        "started_at": NOW.isoformat(),
        "duration_seconds": 180.0,
        "contract": {
            "local_static_contract_verified": True,
            "contract_fingerprint": "f" * 64,
        },
        "cluster": {
            "context": "docker-desktop",
            "uid": "cluster-uid",
            "source_namespace": {
                "name": recovery.SOURCE_NAMESPACE,
                "uid": "source-uid",
            },
            "repository_namespace": {
                "name": repository.REPOSITORY_NAMESPACE,
                "uid": "repository-uid",
            },
        },
        "repository_pvc": {
            "name": repository.REPOSITORY_PVC,
            "uid": "repository-pvc-uid",
            "volume_name": "repository-volume",
            "capacity": repository.REPOSITORY_CAPACITY,
            "phase": "Bound",
        },
        "repository_round_trip": {
            "provider": "minio_s3_compatible",
            "bucket": repository.REPOSITORY_BUCKET,
            "versioning_status": "Enabled",
            "object_lock_enabled": True,
            "default_retention_mode": repository.LOCAL_RETENTION_MODE,
            "default_retention_days": repository.LOCAL_RETENTION_DAYS,
            "artifact_objects": artifact_objects,
            "local_artifacts_removed_before_download": True,
            "round_trip_verified": True,
            "transport_tls_verified": False,
            "kms_encryption_verified": False,
            "production_durability_verified": False,
        },
        "recovery_evidence": recovery_evidence,
        "runtime_checks": {
            "repository_namespace_removed": True,
            "runtime_credentials_removed": True,
            "port_forward_stopped": True,
        },
    }


def test_static_backup_repository_contract_is_valid_and_portable():
    report = repository.build_backup_repository_contract_report()

    assert report["local_static_contract_verified"] is True
    assert report["errors"] == []
    assert report["production_backup_target_verified"] is False
    assert report["production_retention_verified"] is False
    assert all(not Path(item["path"]).is_absolute() for item in report["files"].values())


def test_static_contract_rejects_api_token_mount(tmp_path):
    target = tmp_path / "repository"
    shutil.copytree(repository.DEFAULT_MANIFEST_DIR, target)
    minio = target / "minio.yaml"
    minio.write_text(
        minio.read_text(encoding="utf-8").replace(
            "automountServiceAccountToken: false",
            "automountServiceAccountToken: true",
            1,
        ),
        encoding="utf-8",
    )

    report = repository.build_backup_repository_contract_report(manifest_dir=target)

    assert report["local_static_contract_verified"] is False
    assert any("disable API token mounting" in error for error in report["errors"])


def test_production_policy_rejects_static_credentials_and_short_governance_retention(
    tmp_path,
):
    policy = yaml.safe_load(repository.DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
    policy["repository"]["credential_mode"] = "static"
    policy["repository"]["object_lock"]["mode"] = "GOVERNANCE"
    policy["repository"]["object_lock"]["minimum_retention_days"] = 1
    target = tmp_path / "policy.yaml"
    target.write_text(yaml.safe_dump(policy), encoding="utf-8")

    report = repository.build_backup_repository_contract_report(policy_path=target)

    assert report["local_static_contract_verified"] is False
    rendered = "\n".join(report["errors"])
    assert "workload identity" in rendered
    assert "COMPLIANCE" in rendered
    assert "at least 30 days" in rendered


def test_valid_repository_observation_proves_only_local_round_trip():
    report = repository.build_backup_repository_evidence(
        _repository_observation(), now=NOW
    )

    assert report["status"] == "local_backup_repository_verified"
    assert report["backup_repository_verified"] is True
    assert report["repository_backed_restore_verified"] is True
    assert report["production_backup_target_verified"] is False
    assert report["production_retention_verified"] is False
    assert report["production_kms_verified"] is False
    assert report["cross_cluster_recovery_verified"] is False
    assert report["production_ready"] is False
    assert repository.verify_evidence_integrity(report) == []


def test_repository_verifier_blocks_versioning_and_artifact_drift():
    observation = _repository_observation()
    observation["repository_round_trip"]["versioning_status"] = "Suspended"
    observation["repository_round_trip"]["artifact_objects"][
        "openmetadata_postgresql"
    ]["sha256"] = "0" * 64

    report = repository.build_backup_repository_evidence(observation, now=NOW)

    assert report["backup_repository_verified"] is False
    rendered = "\n".join(report["errors"])
    assert "versioning was not enabled" in rendered
    assert "content does not match" in rendered


def test_repository_verifier_blocks_local_shortcut_and_credential_fields():
    observation = _repository_observation()
    observation["repository_round_trip"][
        "local_artifacts_removed_before_download"
    ] = False
    observation["root_password"] = "must-not-appear"

    report = repository.build_backup_repository_evidence(observation, now=NOW)

    assert report["backup_repository_verified"] is False
    rendered = "\n".join(report["errors"])
    assert "forbidden credential-bearing fields" in rendered
    assert "local artifacts were not removed" in rendered
    assert "must-not-appear" not in rendered


class _RetainedDeleteError(Exception):
    response = {"Error": {"Code": "AccessDenied"}}


class _FakeBody:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, **kwargs):
        key = str(kwargs["Key"])
        body = bytes(kwargs["Body"])
        self.objects[(key, "v1")] = body
        return {"VersionId": "v1"}

    def head_object(self, **kwargs):
        body = self.objects[(str(kwargs["Key"]), str(kwargs["VersionId"]))]
        return {
            "Metadata": {"gda-sha256": hashlib.sha256(body).hexdigest()},
            "ObjectLockMode": repository.LOCAL_RETENTION_MODE,
            "ObjectLockRetainUntilDate": NOW,
            "ContentLength": len(body),
        }

    def delete_object(self, **kwargs):
        raise _RetainedDeleteError

    def get_object(self, **kwargs):
        body = self.objects[(str(kwargs["Key"]), str(kwargs["VersionId"]))]
        return {"Body": _FakeBody(body)}


def test_repository_round_trip_removes_and_redownloads_artifacts(tmp_path):
    paths: dict[str, Path] = {}
    artifacts: dict[str, dict] = {}
    client = _FakeS3Client()
    for index, (name, format_name) in enumerate(repository.EXPECTED_ARTIFACTS.items()):
        path = tmp_path / f"{name}.backup"
        payload = f"artifact-{index}".encode("ascii")
        path.write_bytes(payload)
        sha256 = hashlib.sha256(payload).hexdigest()
        paths[name] = path
        artifacts[name] = {"format": format_name, "sha256": sha256, "bytes": len(payload)}

    round_trip = repository._RepositoryRoundTrip(
        client,
        {
            "versioning_status": "Enabled",
            "object_lock_enabled": True,
            "default_retention_mode": repository.LOCAL_RETENTION_MODE,
            "default_retention_days": repository.LOCAL_RETENTION_DAYS,
        },
        "rp-test",
    )

    report = round_trip(paths, artifacts)

    assert report["local_artifacts_removed_before_download"] is True
    assert report["round_trip_verified"] is True
    assert all(path.exists() for path in paths.values())
    assert all(
        hashlib.sha256(paths[name].read_bytes()).hexdigest() == artifacts[name]["sha256"]
        for name in paths
    )


def test_committed_backup_repository_evidence_is_integral_and_current():
    evidence_root = Path(__file__).resolve().parent.parent / "docs/evidence"
    report = json.loads(
        (evidence_root / "metadata-fabric-backup-repository-2026-07-27.json").read_text(
            encoding="utf-8"
        )
    )
    recovery_report = json.loads(
        (evidence_root / "metadata-fabric-recovery-rehearsal-2026-07-27.json").read_text(
            encoding="utf-8"
        )
    )

    assert repository.verify_evidence_integrity(report) == []
    assert report["observation"]["contract"]["contract_fingerprint"] == (
        repository.build_backup_repository_contract_report()["contract_fingerprint"]
    )
    assert report["observation"]["recovery_evidence"] == recovery_report
    assert report["backup_repository_verified"] is True
    assert report["production_backup_target_verified"] is False
    assert report["production_retention_verified"] is False
    assert report["production_ready"] is False
