import json
import shutil
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from data_agent import metadata_fabric_recovery_rehearsal as recovery

NOW = datetime(2026, 7, 27, 6, 0, tzinfo=UTC)


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


def _observation() -> dict:
    openmetadata = _postgres_marker("1", 176)
    gravitino = _postgres_marker("5", 39)
    opensearch_source = {
        "version": recovery.OPENSEARCH_VERSION,
        "cluster_uuid": "source-cluster-uuid",
        "index_count": 78,
        "total_index_count": 78,
        "index_name_fingerprint": "9" * 64,
        "document_count_fingerprint": "a" * 64,
    }
    opensearch_recovered = {
        **opensearch_source,
        "cluster_uuid": "recovered-cluster-uuid",
    }
    pvcs = {
        name: {
            "uid": f"00000000-0000-4000-8000-{index:012d}",
            "volume_name": f"pvc-{index}",
            "capacity": capacity,
            "phase": "Bound",
        }
        for index, (name, capacity) in enumerate(
            recovery.RECOVERY_PVCS.items(), start=1
        )
    }
    return {
        "schema": recovery.OBSERVATION_SCHEMA,
        "observed_at": NOW.isoformat(),
        "started_at": datetime(2026, 7, 27, 5, 50, tzinfo=UTC).isoformat(),
        "duration_seconds": 600.0,
        "contract": {
            "static_contract_verified": True,
            "contract_fingerprint": "b" * 64,
        },
        "cluster": {
            "context": "docker-desktop",
            "uid": "00000000-0000-4000-8000-000000000001",
            "source_namespace": {
                "name": recovery.SOURCE_NAMESPACE,
                "uid": "00000000-0000-4000-8000-000000000002",
            },
            "recovery_namespace": {
                "name": recovery.RECOVERY_NAMESPACE,
                "uid": "00000000-0000-4000-8000-000000000003",
            },
        },
        "recovery_pvcs": pvcs,
        "artifacts": {
            "openmetadata_postgresql": {
                "format": "postgresql_custom_dump_v1",
                "sha256": "c" * 64,
                "bytes": 8192,
            },
            "gravitino_postgresql": {
                "format": "postgresql_custom_dump_v1",
                "sha256": "d" * 64,
                "bytes": 4096,
            },
            "opensearch": {
                "format": "opensearch_fs_snapshot_tar_gzip_v1",
                "sha256": "e" * 64,
                "bytes": 16384,
            },
        },
        "source_markers": {
            "openmetadata_postgresql": openmetadata,
            "gravitino_postgresql": gravitino,
            "opensearch": opensearch_source,
        },
        "recovered_markers": {
            "openmetadata_postgresql": deepcopy(openmetadata),
            "gravitino_postgresql": deepcopy(gravitino),
            "opensearch": opensearch_recovered,
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


def test_static_recovery_contract_is_valid_and_portable():
    report = recovery.build_recovery_contract_report()

    assert report["static_contract_verified"] is True
    assert report["errors"] == []
    assert len(report["files"]) == 9
    assert all(not Path(item["path"]).is_absolute() for item in report["files"].values())
    assert report["contract_fingerprint"] == recovery._canonical_sha256(
        {
            key: value
            for key, value in report.items()
            if key != "contract_fingerprint"
        }
    )


def test_command_runner_binds_every_kubectl_call_to_its_context():
    runner = recovery._CommandRunner("/usr/local/bin/kubectl", "kind-recovery")

    assert runner.kubectl_args(["get", "nodes"]) == [
        "/usr/local/bin/kubectl",
        "--context",
        "kind-recovery",
        "get",
        "nodes",
    ]


def test_static_contract_rejects_api_token_mount(tmp_path):
    target = tmp_path / "recovery"
    shutil.copytree(recovery.DEFAULT_RECOVERY_MANIFEST_DIR, target)
    postgresql = target / "postgresql.yaml"
    postgresql.write_text(
        postgresql.read_text(encoding="utf-8").replace(
            "automountServiceAccountToken: false",
            "automountServiceAccountToken: true",
            1,
        ),
        encoding="utf-8",
    )

    report = recovery.build_recovery_contract_report(recovery_manifest_dir=target)

    assert report["static_contract_verified"] is False
    assert any("disable API token mounting" in error for error in report["errors"])


def test_valid_observation_proves_only_local_recovery():
    report = recovery.build_recovery_evidence(_observation(), now=NOW)

    assert report["status"] == "local_backup_restore_verified"
    assert report["backup_restore_verified"] is True
    assert report["local_backup_restore_verified"] is True
    assert report["production_backup_restore_verified"] is False
    assert report["rpo_slo_verified"] is False
    assert report["rto_slo_verified"] is False
    assert report["cross_cluster_recovery_verified"] is False
    assert report["writes_to_gda_enabled"] is False
    assert report["production_ready"] is False
    assert recovery.verify_evidence_integrity(report) == []


def test_distinct_cluster_observation_proves_only_local_cross_cluster_recovery():
    observation = _observation()
    observation["cluster"]["recovery_context"] = "kind-gda-metadata-recovery"
    observation["cluster"]["recovery_uid"] = (
        "00000000-0000-4000-8000-000000000004"
    )

    report = recovery.build_recovery_evidence(observation, now=NOW)

    assert report["status"] == "local_cross_cluster_backup_restore_verified"
    assert report["backup_restore_scope"] == (
        "local_distinct_kubernetes_clusters_new_namespace_and_pvcs"
    )
    assert report["local_cross_cluster_recovery_verified"] is True
    assert report["cross_cluster_recovery_verified"] is False
    assert report["production_cross_cluster_recovery_verified"] is False
    assert report["production_ready"] is False
    assert recovery.verify_evidence_integrity(report) == []


def test_recovery_verifier_blocks_context_uid_isolation_disagreement():
    observation = _observation()
    observation["cluster"]["recovery_context"] = "kind-gda-metadata-recovery"
    observation["cluster"]["recovery_uid"] = observation["cluster"]["uid"]

    report = recovery.build_recovery_evidence(observation, now=NOW)

    assert report["status"] == "blocked"
    assert any("context/identity isolation disagrees" in item for item in report["errors"])


def test_recovery_verifier_blocks_database_drift_and_shared_search_identity():
    observation = _observation()
    observation["recovered_markers"]["openmetadata_postgresql"][
        "row_count_fingerprint"
    ] = "f" * 64
    observation["recovered_markers"]["opensearch"]["cluster_uuid"] = (
        observation["source_markers"]["opensearch"]["cluster_uuid"]
    )

    report = recovery.build_recovery_evidence(observation, now=NOW)

    assert report["status"] == "blocked"
    assert report["backup_restore_verified"] is False
    rendered = "\n".join(report["errors"])
    assert "recovered content markers differ" in rendered
    assert "not an independent cluster" in rendered


def test_recovery_verifier_blocks_incomplete_cleanup():
    observation = _observation()
    observation["runtime_checks"]["recovery_namespace_removed"] = False

    report = recovery.build_recovery_evidence(observation, now=NOW)

    assert report["status"] == "blocked"
    assert "runtime check did not pass: recovery_namespace_removed" in report["errors"]


def test_recovery_verifier_rejects_credential_bearing_fields_without_echoing_values():
    observation = _observation()
    observation["database_password"] = "must-not-appear"

    report = recovery.build_recovery_evidence(observation, now=NOW)

    assert report["status"] == "blocked"
    rendered = "\n".join(report["errors"])
    assert "forbidden credential-bearing fields" in rendered
    assert "must-not-appear" not in rendered


def test_committed_recovery_evidence_is_integral():
    evidence_path = (
        Path(__file__).resolve().parent.parent
        / "docs/evidence/metadata-fabric-recovery-rehearsal-2026-07-27.json"
    )
    assert evidence_path.exists()
    report = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert recovery.verify_evidence_integrity(report) == []
    assert report["observation"]["contract"]["contract_fingerprint"] == (
        recovery.build_recovery_contract_report()["contract_fingerprint"]
    )
    assert report["local_backup_restore_verified"] is True
    assert report["production_backup_restore_verified"] is False
    assert report["production_ready"] is False
