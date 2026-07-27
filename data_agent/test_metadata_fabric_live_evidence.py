import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from data_agent import metadata_fabric_live_evidence as live

NOW = datetime(2026, 7, 27, 4, 0, tzinfo=UTC)


def _seal(collection: dict) -> dict:
    collection.pop("collection_fingerprint", None)
    collection["collection_fingerprint"] = live._canonical_sha256(collection)
    return collection


def _collection(*, restarted: bool = False) -> dict:
    workloads = {}
    for index, (name, expected) in enumerate(live.WORKLOADS.items(), start=1):
        pod_suffix = index + (100 if restarted else 0)
        workloads[name] = {
            "kind": "Deployment" if expected["kind"] == "deployment" else "StatefulSet",
            "name": name,
            "uid": f"00000000-0000-4000-8000-{index:012d}",
            "desired_replicas": 1,
            "ready_replicas": 1,
            "service_account_name": name,
            "automount_service_account_token": False,
            "image": expected["image"],
            "image_pull_policy": expected["pull_policy"],
            "pods": [
                {
                    "name": f"{name}-pod",
                    "uid": f"00000000-0000-4000-9000-{pod_suffix:012d}",
                    "phase": "Running",
                    "ready": True,
                    "restart_count": 0,
                    "service_account_name": name,
                    "automount_service_account_token": False,
                    "image": expected["image"],
                    "image_id": "sha256:" + f"{index:x}" * 64,
                }
            ],
        }
    services = {
        name: {
            "name": name,
            "uid": f"00000000-0000-4001-8000-{index:012d}",
            "type": "ClusterIP",
            "ports": [],
            "external_ips": [],
            "node_ports": [],
        }
        for index, name in enumerate(sorted(live.SERVICES), start=1)
    }
    pvcs = {
        name: {
            "name": name,
            "uid": f"00000000-0000-4002-8000-{index:012d}",
            "volume_name": f"pvc-volume-{index}",
            "storage_class": "standard",
            "access_modes": ["ReadWriteOnce"],
            "capacity": capacity,
            "phase": "Bound",
        }
        for index, (name, capacity) in enumerate(live.PVCS.items(), start=1)
    }
    collection = {
        "schema": live.COLLECTION_SCHEMA,
        "observed_at": NOW.isoformat(),
        "source_contract": {
            "schema": "gda.metadata_fabric_sandbox.v1",
            "static_contract_verified": True,
            "fingerprint": "a" * 64,
        },
        "cluster": {
            "context": "docker-desktop",
            "uid": "00000000-0000-4003-8000-000000000001",
            "server_version": "v1.35.5",
            "nodes": [
                {
                    "name": "desktop-control-plane",
                    "architecture": "arm64",
                    "kubelet_version": "v1.35.5",
                },
                {
                    "name": "desktop-worker",
                    "architecture": "arm64",
                    "kubelet_version": "v1.35.5",
                },
            ],
        },
        "namespace": {
            "name": live.NAMESPACE,
            "uid": "00000000-0000-4003-8000-000000000002",
        },
        "workloads": workloads,
        "services": services,
        "pvcs": pvcs,
        "network_policy_names": sorted(live.NETWORK_POLICIES),
        "providers": {
            "openmetadata": {
                "health": "OK",
                "version": live.OPENMETADATA_VERSION,
                "revision": live.OPENMETADATA_SERVER_COMMIT,
            },
            "gravitino": {
                "ready": True,
                "version": live.GRAVITINO_VERSION,
                "revision": live.GRAVITINO_TAG_COMMIT,
            },
        },
        "storage_markers": {
            "openmetadata_postgresql": {
                "table_count": 176,
                "table_name_fingerprint": "b" * 64,
            },
            "gravitino_postgresql": {
                "table_count": 39,
                "table_name_fingerprint": "c" * 64,
            },
            "opensearch": {
                "cluster_uuid": "sandbox-cluster-uuid",
                "version": live.OPENSEARCH_VERSION,
                "index_count": 84,
                "index_name_fingerprint": "d" * 64,
            },
        },
    }
    return _seal(collection)


def test_live_foundation_without_restart_does_not_claim_persistence_proof():
    report = live.build_live_metadata_fabric_evidence(
        _collection(), now=NOW
    )

    assert report["status"] == "live_foundation_verified"
    assert report["live_foundation_verified"] is True
    assert report["persistence_configured"] is True
    assert report["local_persistence_restart_verified"] is False
    assert report["checks"]["controlled_restart"] == "not_run"
    assert report["production_provider_verified"] is False
    assert report["production_table_catalog_provider_verified"] is False
    assert report["network_policy_enforcement_verified"] is False
    assert report["oidc_verified"] is False
    assert report["backup_restore_verified"] is False
    assert report["upgrade_verified"] is False
    assert report["writes_to_gda_enabled"] is False
    assert report["production_ready"] is False


def test_controlled_restart_preserves_pvcs_and_storage_markers():
    report = live.build_live_metadata_fabric_evidence(
        _collection(), _collection(restarted=True), now=NOW
    )

    assert report["status"] == "live_foundation_verified"
    assert report["local_persistence_restart_verified"] is True
    assert report["checks"] == {
        "before_collection": "passed",
        "after_collection": "passed",
        "controlled_restart": "passed",
        "production_boundaries": "passed",
    }
    assert report["errors"] == []


def test_live_verifier_blocks_exposure_identity_and_persistence_drift():
    before = _collection()
    after = deepcopy(_collection(restarted=True))
    after["workloads"]["openmetadata"][
        "automount_service_account_token"
    ] = True
    after["services"]["openmetadata"]["type"] = "LoadBalancer"
    after["services"]["openmetadata"]["uid"] = (
        "00000000-0000-4001-8000-999999999999"
    )
    after["pvcs"]["data-metadata-openmetadata-postgresql-0"]["uid"] = (
        "00000000-0000-4002-8000-999999999999"
    )
    after["providers"]["gravitino"]["revision"] = "9" * 40
    after["storage_markers"]["gravitino_postgresql"]["table_count"] = 38
    _seal(after)

    report = live.build_live_metadata_fabric_evidence(before, after, now=NOW)

    assert report["status"] == "blocked"
    assert report["live_foundation_verified"] is False
    assert report["local_persistence_restart_verified"] is False
    rendered = "\n".join(report["errors"])
    assert "mounts a Kubernetes API token" in rendered
    assert "Service openmetadata is not ClusterIP" in rendered
    assert "Gravitino health or version does not match" in rendered
    assert "Service identity or exposure changed" in rendered
    assert "PVC identity or capacity changed" in rendered
    assert "persistent schema or index markers changed" in rendered


def test_live_verifier_blocks_source_contract_drift_across_restart():
    before = _collection()
    after = _collection(restarted=True)
    after["source_contract"]["fingerprint"] = "e" * 64
    _seal(after)

    report = live.build_live_metadata_fabric_evidence(before, after, now=NOW)

    assert report["status"] == "blocked"
    assert "source contract changed across the restart" in report["errors"]


def test_live_verifier_rejects_sensitive_fields_even_with_valid_fingerprint():
    collection = _collection()
    collection["database_password"] = "must-not-appear"
    _seal(collection)

    report = live.build_live_metadata_fabric_evidence(collection, now=NOW)

    assert report["status"] == "blocked"
    assert "before collection contains forbidden sensitive fields" in report["errors"]
    assert "must-not-appear" not in "\n".join(report["errors"])


def test_committed_local_evidence_is_integral_and_keeps_production_flags_false():
    evidence_path = (
        Path(__file__).resolve().parent.parent
        / "docs/evidence/metadata-fabric-foundation-sandbox-2026-07-27.json"
    )
    report = json.loads(evidence_path.read_text(encoding="utf-8"))
    stable = {
        key: value
        for key, value in report.items()
        if key
        not in {
            "generated_at",
            "status",
            "persistence_configured",
            "evidence_fingerprint",
        }
    }

    assert report["evidence_fingerprint"] == live._canonical_sha256(stable)
    assert live._sensitive_paths(report) == []
    assert report["status"] == "live_foundation_verified"
    assert report["live_foundation_verified"] is True
    assert report["local_persistence_restart_verified"] is True
    for flag in (
        "production_provider_verified",
        "production_table_catalog_provider_verified",
        "network_policy_enforcement_verified",
        "oidc_verified",
        "backup_restore_verified",
        "upgrade_verified",
        "writes_to_gda_enabled",
        "production_ready",
    ):
        assert report[flag] is False
