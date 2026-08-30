from __future__ import annotations

import json
from pathlib import Path

from scripts.preflight_agentops_temporal_discovery_sandbox import (
    REQUIRED_MIGRATIONS,
    build_report,
)


def test_static_preflight_fails_closed_without_control_schema_report() -> None:
    report = build_report(
        static_only=True,
        schema_report=None,
        namespace="gda-agentops-sandbox",
        control_namespace="gis-agent",
    )
    assert report["passed"] is False
    checks = {item["name"]: item for item in report["checks"]}
    assert checks["manifest.discovery_replicas"]["status"] == "pass"
    assert checks["manifest.image"]["status"] == "pass"
    assert checks["control_database.migrations"]["status"] == "block"


def test_static_preflight_accepts_in_sync_schema_report(tmp_path: Path) -> None:
    from data_agent.migration_runner import catalog_fingerprint, discover_migrations

    report_path = tmp_path / "schema-status.json"
    migrations = discover_migrations()
    report_path.write_text(
        json.dumps(
            {
                "status": "in_sync",
                "catalog_count": len(migrations),
                "catalog_fingerprint": catalog_fingerprint(migrations),
                "pending": [],
                "checksum_mismatches": [],
                "metadata_mismatches": [],
            }
        ),
        encoding="utf-8",
    )
    report = build_report(
        static_only=True,
        schema_report=report_path,
        namespace="gda-agentops-sandbox",
        control_namespace="gis-agent",
    )
    assert report["passed"] is True
    assert REQUIRED_MIGRATIONS
    checks = {item["name"]: item for item in report["checks"]}
    assert checks["manifest.specialist_content_backend"]["status"] == "pass"


def test_in_sync_old_catalog_is_blocked(tmp_path: Path) -> None:
    report_path = tmp_path / "schema-status.json"
    report_path.write_text(
        json.dumps(
            {
                "status": "in_sync",
                "catalog_count": 97,
                "catalog_fingerprint": "old-image-catalog",
                "pending": [],
                "checksum_mismatches": [],
                "metadata_mismatches": [],
            }
        ),
        encoding="utf-8",
    )
    report = build_report(
        static_only=True,
        schema_report=report_path,
        namespace="gda-agentops-sandbox",
        control_namespace="gis-agent",
    )
    checks = {item["name"]: item for item in report["checks"]}
    assert report["passed"] is False
    assert checks["control_database.migrations"]["status"] == "block"


def test_schema_report_with_required_pending_migration_is_blocked(tmp_path: Path) -> None:
    report_path = tmp_path / "schema-status.json"
    report_path.write_text(
        json.dumps(
            {
                "status": "pending",
                "pending": [REQUIRED_MIGRATIONS[-1]],
                "checksum_mismatches": [],
                "metadata_mismatches": [],
            }
        ),
        encoding="utf-8",
    )
    report = build_report(
        static_only=True,
        schema_report=report_path,
        namespace="gda-agentops-sandbox",
        control_namespace="gis-agent",
    )
    checks = {item["name"]: item for item in report["checks"]}
    assert report["passed"] is False
    assert checks["control_database.migrations"]["status"] == "block"


def test_specialist_s3_backend_manifest_requires_versioned_bucket(monkeypatch) -> None:
    from scripts import preflight_agentops_temporal_discovery_sandbox as preflight

    original = preflight._render

    def render(path: Path):
        ok, rendered = original(path)
        if not ok or path != preflight.OVERLAY:
            return ok, rendered
        rendered = rendered.replace(
            "GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_BACKEND: filesystem",
            "GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_BACKEND: s3\n"
            "  GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_BUCKET: evidence\n"
            "  GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_REQUIRE_VERSION_ID: \"true\"",
        ).replace(
            "GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_ROOT: "
            "/var/lib/gda-agentops/reconciler/content",
            "GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_ROOT: /unused",
        )
        return True, rendered

    monkeypatch.setattr(preflight, "_render", render)
    checks = {item.name: item for item in preflight._check_manifest()}
    assert checks["manifest.specialist_content_backend"].status == "pass"


def test_specialist_s3_backend_requires_bucket(monkeypatch) -> None:
    from scripts import preflight_agentops_temporal_discovery_sandbox as preflight

    original = preflight._render

    def render(path: Path):
        ok, rendered = original(path)
        if not ok or path != preflight.OVERLAY:
            return ok, rendered
        rendered = rendered.replace(
            "GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_BACKEND: filesystem",
            "GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_BACKEND: s3",
        )
        return True, rendered

    monkeypatch.setattr(preflight, "_render", render)
    checks = {item.name: item for item in preflight._check_manifest()}
    assert checks["manifest.specialist_content_backend"].status == "block"


def test_specialist_s3_backend_requires_version_id(monkeypatch) -> None:
    from scripts import preflight_agentops_temporal_discovery_sandbox as preflight

    original = preflight._render

    def render(path: Path):
        ok, rendered = original(path)
        if not ok or path != preflight.OVERLAY:
            return ok, rendered
        rendered = rendered.replace(
            "GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_BACKEND: filesystem",
            "GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_BACKEND: s3\n"
            "  GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_BUCKET: evidence\n"
            "  GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_REQUIRE_VERSION_ID: \"false\"",
        )
        return True, rendered

    monkeypatch.setattr(preflight, "_render", render)
    checks = {item.name: item for item in preflight._check_manifest()}
    assert checks["manifest.specialist_content_backend"].status == "block"


def test_manifest_requires_immutable_discovery_image(monkeypatch) -> None:
    from scripts import preflight_agentops_temporal_discovery_sandbox as preflight

    original = preflight._render

    def render(path: Path):
        ok, rendered = original(path)
        if not ok or path != preflight.OVERLAY:
            return ok, rendered
        return True, rendered.replace(
            "gis-data-agent@sha256:0d09d950ee02bbe5e55058bbd8c116cf8dc00b1fad4fcb6172ee89d57221c3cb",
            "gis-data-agent:latest",
        )

    monkeypatch.setattr(preflight, "_render", render)
    checks = {item.name: item for item in preflight._check_manifest()}
    assert checks["manifest.image"].status == "block"


def test_cluster_preflight_requires_ready_rollout_and_live_specialist_config(monkeypatch) -> None:
    from scripts import preflight_agentops_temporal_discovery_sandbox as preflight

    image = "gis-data-agent@sha256:" + "a" * 64
    deployment = {
        "metadata": {"generation": 4},
        "spec": {
            "replicas": 2,
            "template": {
                "spec": {"containers": [{"name": "discovery", "image": image}]}
            },
        },
        "status": {
            "observedGeneration": 4,
            "readyReplicas": 2,
            "availableReplicas": 2,
            "updatedReplicas": 2,
        },
    }
    config = {
        "data": {
            "GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_BACKEND": "filesystem",
            "GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_ROOT": "/content",
            "GDA_AGENTOPS_RECONCILER_SPECIALIST_MATERIALIZATION_ROOT": "/materialized",
        }
    }

    def kubectl(*args: str):
        if args[:3] == ("get", "namespace", "gda-agentops-sandbox"):
            return True, "namespace/gda-agentops-sandbox"
        if args[:3] == ("get", "secret", "gis-agent-agentops-discovery-runtime"):
            return True, '{"data":{"database-url":"x","tenant-id":"y"}}'
        if args[:3] == ("get", "networkpolicy", "gis-agent-postgres-agentops-discovery-access"):
            return True, "networkpolicy/gis-agent-postgres-agentops-discovery-access"
        if args[:3] == ("get", "deployment", "gis-agent-agentops-discovery"):
            return True, json.dumps(deployment)
        if args[:3] == ("get", "configmap", "gis-agent-agentops-discovery"):
            return True, json.dumps(config)
        raise AssertionError(args)

    monkeypatch.setattr(preflight, "_kubectl", kubectl)
    checks = {
        item.name: item
        for item in preflight._check_cluster(
            "gda-agentops-sandbox",
            "gis-agent",
            expect_deployed=True,
            expected_image=image,
            expected_specialist_config=preflight._specialist_config_projection(
                config["data"]
            ),
        )
    }
    assert checks["cluster.discovery_readiness"].status == "pass"
    assert checks["cluster.discovery_image"].status == "pass"
    assert checks["cluster.specialist_content_config"].status == "pass"
    assert checks["cluster.specialist_content_config_binding"].status == "pass"


def test_cluster_preflight_blocks_configmap_drift(monkeypatch) -> None:
    from scripts import preflight_agentops_temporal_discovery_sandbox as preflight

    def kubectl(*args: str):
        if args[:3] == ("get", "namespace", "gda-agentops-sandbox"):
            return True, "namespace/gda-agentops-sandbox"
        if args[:3] == ("get", "secret", "gis-agent-agentops-discovery-runtime"):
            return True, '{"data":{"database-url":"x","tenant-id":"y"}}'
        if args[:3] == ("get", "networkpolicy", "gis-agent-postgres-agentops-discovery-access"):
            return True, "networkpolicy/gis-agent-postgres-agentops-discovery-access"
        if args[:3] == ("get", "deployment", "gis-agent-agentops-discovery"):
            return True, json.dumps({"spec": {"replicas": 2}, "status": {}})
        if args[:3] == ("get", "configmap", "gis-agent-agentops-discovery"):
            return True, json.dumps(
                {
                    "data": {
                        "GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_BACKEND": "s3"
                    }
                }
            )
        raise AssertionError(args)

    monkeypatch.setattr(preflight, "_kubectl", kubectl)
    checks = {
        item.name: item
        for item in preflight._check_cluster(
            "gda-agentops-sandbox", "gis-agent", expect_deployed=False
        )
    }
    assert checks["cluster.specialist_content_config"].status == "block"


def test_cluster_preflight_allows_missing_configmap_before_apply(monkeypatch) -> None:
    from scripts import preflight_agentops_temporal_discovery_sandbox as preflight

    def kubectl(*args: str):
        if args[:3] == ("get", "namespace", "gda-agentops-sandbox"):
            return True, "namespace/gda-agentops-sandbox"
        if args[:3] == ("get", "secret", "gis-agent-agentops-discovery-runtime"):
            return True, '{"data":{"database-url":"x","tenant-id":"y"}}'
        if args[:3] == ("get", "networkpolicy", "gis-agent-postgres-agentops-discovery-access"):
            return True, "networkpolicy/gis-agent-postgres-agentops-discovery-access"
        if args[:3] == ("get", "deployment", "gis-agent-agentops-discovery"):
            return False, "deployment not found"
        if args[:3] == ("get", "configmap", "gis-agent-agentops-discovery"):
            return False, "ConfigMap not found"
        raise AssertionError(args)

    monkeypatch.setattr(preflight, "_kubectl", kubectl)
    checks = {
        item.name: item
        for item in preflight._check_cluster(
            "gda-agentops-sandbox", "gis-agent", expect_deployed=False
        )
    }
    assert checks["cluster.discovery_deployment"].status == "pass"
    assert checks["cluster.specialist_content_config"].status == "pass"


def test_cluster_preflight_requires_configmap_after_apply(monkeypatch) -> None:
    from scripts import preflight_agentops_temporal_discovery_sandbox as preflight

    def kubectl(*args: str):
        if args[:3] == ("get", "namespace", "gda-agentops-sandbox"):
            return True, "namespace/gda-agentops-sandbox"
        if args[:3] == ("get", "secret", "gis-agent-agentops-discovery-runtime"):
            return True, '{"data":{"database-url":"x","tenant-id":"y"}}'
        if args[:3] == ("get", "networkpolicy", "gis-agent-postgres-agentops-discovery-access"):
            return True, "networkpolicy/gis-agent-postgres-agentops-discovery-access"
        if args[:3] == ("get", "deployment", "gis-agent-agentops-discovery"):
            return True, '{"spec":{"replicas":2},"status":{}}'
        if args[:3] == ("get", "configmap", "gis-agent-agentops-discovery"):
            return False, "ConfigMap not found"
        raise AssertionError(args)

    monkeypatch.setattr(preflight, "_kubectl", kubectl)
    checks = {
        item.name: item
        for item in preflight._check_cluster(
            "gda-agentops-sandbox", "gis-agent", expect_deployed=True
        )
    }
    assert checks["cluster.specialist_content_config"].status == "block"
