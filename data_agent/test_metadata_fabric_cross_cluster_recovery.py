import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import yaml

from data_agent import metadata_fabric_cross_cluster_recovery as cross_cluster
from data_agent import metadata_fabric_recovery_rehearsal as recovery


NOW = datetime(2026, 7, 27, 9, 0, tzinfo=UTC)


class _Denied(Exception):
    response = {"Error": {"Code": "AccessDenied"}}


class _Body:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload


class _FakeS3:
    def __init__(self, role: str, objects: dict) -> None:
        self.role = role
        self.objects = objects

    def put_object(self, **kwargs):
        if self.role == "reader":
            raise _Denied
        key = str(kwargs["Key"])
        body = bytes(kwargs["Body"])
        version = f"version-{len(self.objects) + 1}"
        self.objects[(key, version)] = body
        return {"VersionId": version}

    def head_object(self, **kwargs):
        body = self.objects[(str(kwargs["Key"]), str(kwargs["VersionId"]))]
        return {
            "Metadata": {"gda-sha256": hashlib.sha256(body).hexdigest()},
            "ObjectLockMode": cross_cluster.RETENTION_MODE,
            "ObjectLockRetainUntilDate": NOW,
            "ContentLength": len(body),
        }

    def delete_object(self, **kwargs):
        raise _Denied

    def get_object(self, **kwargs):
        body = self.objects[(str(kwargs["Key"]), str(kwargs["VersionId"]))]
        return {"Body": _Body(body)}


def _cross_cluster_observation() -> dict:
    evidence_path = (
        Path(__file__).resolve().parent.parent
        / "docs/evidence/metadata-fabric-recovery-rehearsal-2026-07-27.json"
    )
    committed = json.loads(evidence_path.read_text(encoding="utf-8"))
    recovered = deepcopy(committed["observation"])
    recovered["observed_at"] = NOW.isoformat()
    recovered["started_at"] = NOW.isoformat()
    recovered["duration_seconds"] = 120.0
    recovered["cluster"]["recovery_context"] = cross_cluster.RECOVERY_CONTEXT
    recovered["cluster"]["recovery_uid"] = "recovery-cluster-uid"
    objects = {
        name: {
            "object_path": f"metadata-fabric/rp-test/{name}.backup",
            "version_id": f"version-{index}",
            "format": artifact["format"],
            "sha256": artifact["sha256"],
            "bytes": artifact["bytes"],
            "retention_mode": cross_cluster.RETENTION_MODE,
            "retained_until": "2026-07-28T09:00:00+00:00",
            "writer_delete_denied": True,
            "compliance_delete_blocked": True,
        }
        for index, (name, artifact) in enumerate(
            recovered["artifacts"].items(), start=1
        )
    }
    recovered["repository_round_trip"] = {
        "provider": "minio_s3_compatible",
        "repository_runtime": "docker_host_container",
        "failure_domain": cross_cluster.FAILURE_DOMAIN,
        "bucket": cross_cluster.BUCKET,
        "versioning_status": "Enabled",
        "object_lock_enabled": True,
        "default_retention_mode": cross_cluster.RETENTION_MODE,
        "default_retention_days": cross_cluster.RETENTION_DAYS,
        "artifact_objects": objects,
        "identity_controls": {
            "separate_writer_reader": True,
            "writer_delete_denied": True,
            "reader_write_denied": True,
        },
        "local_artifacts_removed_before_download": True,
        "round_trip_verified": True,
        "transport_tls_verified": False,
        "kms_encryption_verified": False,
        "production_durability_verified": False,
    }
    recovery_evidence = recovery.build_recovery_evidence(recovered, now=NOW)
    return {
        "schema": cross_cluster.OBSERVATION_SCHEMA,
        "observed_at": NOW.isoformat(),
        "started_at": NOW.isoformat(),
        "duration_seconds": 150.0,
        "contract": {
            "local_static_contract_verified": True,
            "contract_fingerprint": "f" * 64,
        },
        "repository": {
            "runtime": "docker_host_container",
            "failure_domain": cross_cluster.FAILURE_DOMAIN,
            "minio_image": cross_cluster.MINIO_IMAGE,
            "mc_image": cross_cluster.MC_IMAGE,
        },
        "recovery_evidence": recovery_evidence,
        "runtime_checks": {
            "external_repository_container_removed": True,
            "external_repository_volume_removed": True,
            "runtime_credentials_removed": True,
            "recovery_cluster_preserved": True,
        },
    }


def test_static_cross_cluster_contract_is_valid_and_portable():
    report = cross_cluster.build_cross_cluster_contract_report()

    assert report["local_static_contract_verified"] is True
    assert report["errors"] == []
    assert report["source_context"] != report["recovery_context"]
    assert report["production_cross_cluster_recovery_verified"] is False
    assert all(not Path(item["path"]).is_absolute() for item in report["files"].values())


def test_static_contract_rejects_shared_context_and_production_overclaim(tmp_path):
    profile = yaml.safe_load(
        cross_cluster.DEFAULT_PROFILE_PATH.read_text(encoding="utf-8")
    )
    profile["recovery_cluster"]["context"] = cross_cluster.SOURCE_CONTEXT
    profile["claims"]["production_ready"] = True
    target = tmp_path / "profile.yaml"
    target.write_text(yaml.safe_dump(profile), encoding="utf-8")

    report = cross_cluster.build_cross_cluster_contract_report(profile_path=target)

    assert report["local_static_contract_verified"] is False
    rendered = "\n".join(report["errors"])
    assert "recovery cluster context" in rendered
    assert "contexts must differ" in rendered
    assert "production_ready" in rendered


def test_valid_observation_proves_only_host_bounded_cross_cluster_recovery():
    report = cross_cluster.build_cross_cluster_evidence(
        _cross_cluster_observation(), now=NOW
    )

    assert report["status"] == "local_cross_cluster_recovery_verified"
    assert report["local_cross_cluster_recovery_verified"] is True
    assert report["local_external_repository_verified"] is True
    assert report["local_writer_reader_identity_separation_verified"] is True
    assert report["cross_cluster_recovery_verified"] is False
    assert report["production_cross_cluster_recovery_verified"] is False
    assert report["source_cluster_loss_verified"] is False
    assert report["production_ready"] is False
    assert cross_cluster.verify_evidence_integrity(report) == []


def test_cross_cluster_verifier_blocks_shared_cluster_and_identity_drift():
    observation = _cross_cluster_observation()
    nested = observation["recovery_evidence"]
    nested_observation = nested["observation"]
    nested_observation["cluster"]["recovery_uid"] = nested_observation["cluster"]["uid"]
    nested_observation["repository_round_trip"]["identity_controls"][
        "reader_write_denied"
    ] = False
    observation["recovery_evidence"] = recovery.build_recovery_evidence(
        nested_observation, now=NOW
    )

    report = cross_cluster.build_cross_cluster_evidence(observation, now=NOW)

    assert report["status"] == "blocked"
    rendered = "\n".join(report["errors"])
    assert "distinct local clusters" in rendered
    assert "reader write was not denied" in rendered


def test_cross_cluster_verifier_blocks_repository_provenance_and_retention_drift():
    observation = _cross_cluster_observation()
    observation["repository"]["minio_image"] = "minio/minio:latest"
    round_trip = observation["recovery_evidence"]["observation"][
        "repository_round_trip"
    ]
    round_trip["transport_tls_verified"] = True
    round_trip["artifact_objects"]["openmetadata_postgresql"][
        "retained_until"
    ] = "2026-07-27T08:59:59+00:00"
    nested_observation = observation["recovery_evidence"]["observation"]
    observation["recovery_evidence"] = recovery.build_recovery_evidence(
        nested_observation, now=NOW
    )

    report = cross_cluster.build_cross_cluster_evidence(observation, now=NOW)

    assert report["status"] == "blocked"
    rendered = "\n".join(report["errors"])
    assert "MinIO image does not match" in rendered
    assert "may not claim transport_tls_verified" in rendered
    assert "retention is not in the future" in rendered


def test_external_round_trip_uses_writer_and_reader_and_removes_local_files(tmp_path):
    objects: dict = {}
    admin = _FakeS3("admin", objects)
    writer = _FakeS3("writer", objects)
    reader = _FakeS3("reader", objects)
    paths: dict[str, Path] = {}
    artifacts: dict[str, dict] = {}
    for index, (name, format_name) in enumerate(
        cross_cluster.repository.EXPECTED_ARTIFACTS.items(), start=1
    ):
        path = tmp_path / f"{name}.backup"
        payload = f"artifact-{index}".encode("ascii")
        path.write_bytes(payload)
        paths[name] = path
        artifacts[name] = {
            "format": format_name,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
        }

    round_trip = cross_cluster._ExternalRepositoryRoundTrip(
        admin,
        writer,
        reader,
        {
            "versioning_status": "Enabled",
            "object_lock_enabled": True,
            "default_retention_mode": cross_cluster.RETENTION_MODE,
            "default_retention_days": cross_cluster.RETENTION_DAYS,
        },
        "rp-test",
    )
    report = round_trip(paths, artifacts)

    assert report["local_artifacts_removed_before_download"] is True
    assert report["identity_controls"] == {
        "separate_writer_reader": True,
        "writer_delete_denied": True,
        "reader_write_denied": True,
    }
    assert all(path.is_file() for path in paths.values())
    assert all(
        hashlib.sha256(paths[name].read_bytes()).hexdigest()
        == artifacts[name]["sha256"]
        for name in paths
    )


def test_committed_cross_cluster_evidence_is_integral_and_current():
    evidence_path = (
        Path(__file__).resolve().parent.parent
        / "docs/evidence/metadata-fabric-cross-cluster-recovery-2026-07-27.json"
    )
    report = json.loads(evidence_path.read_text(encoding="utf-8"))
    nested = report["observation"]["recovery_evidence"]

    assert cross_cluster.verify_evidence_integrity(report) == []
    assert report["observation"]["contract"]["contract_fingerprint"] == (
        cross_cluster.build_cross_cluster_contract_report()["contract_fingerprint"]
    )
    assert recovery.verify_evidence_integrity(nested) == []
    assert nested["observation"]["contract"]["contract_fingerprint"] == (
        recovery.build_recovery_contract_report()["contract_fingerprint"]
    )
    assert report["local_cross_cluster_recovery_verified"] is True
    assert report["production_cross_cluster_recovery_verified"] is False
    assert report["source_cluster_loss_verified"] is False
    assert report["production_ready"] is False
