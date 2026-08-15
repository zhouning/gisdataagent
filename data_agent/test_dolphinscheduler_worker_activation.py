import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from data_agent.dolphinscheduler_worker_activation import (
    SECRET_ATTESTATION_SCHEMA,
    build_activation_report,
    main,
)
from data_agent.dolphinscheduler_worker_deployment import (
    CONFIG_NAME,
    DEFAULT_MANIFEST,
    DEFAULT_NETWORK_POLICY,
    DEPLOYMENT_NAME,
    SECRET_NAME,
)

NOW = datetime(2026, 7, 25, 16, 0, tzinfo=UTC)
IMAGE = "registry.example.com/gis-data-agent@sha256:" + "a" * 64


def _documents(path: Path) -> list[dict]:
    return [
        item
        for item in yaml.safe_load_all(path.read_text(encoding="utf-8"))
        if isinstance(item, dict)
    ]


def _resource(documents: list[dict], kind: str, name: str) -> dict:
    return next(
        item
        for item in documents
        if item.get("kind") == kind
        and (item.get("metadata") or {}).get("name") == name
    )


def _write_activation_inputs(
    tmp_path,
    *,
    observed_at=NOW,
    namespace="gis-agent",
):
    documents = _documents(DEFAULT_MANIFEST)
    documents.extend(_documents(DEFAULT_NETWORK_POLICY))
    deployment = _resource(documents, "Deployment", DEPLOYMENT_NAME)
    deployment["spec"]["replicas"] = 1
    pod = deployment["spec"]["template"]["spec"]
    for container in [*pod["containers"], *pod["initContainers"]]:
        container["image"] = IMAGE
    for document in documents:
        metadata = document.get("metadata") or {}
        if "namespace" in metadata:
            metadata["namespace"] = namespace
    manifest = tmp_path / "rendered-staging.yaml"
    manifest.write_text(
        yaml.safe_dump_all(documents, sort_keys=False),
        encoding="utf-8",
    )

    config_map = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": CONFIG_NAME,
            "namespace": namespace,
            "uid": "00000000-0000-4000-8000-000000000101",
            "resourceVersion": "18421",
        },
        "data": {
            "base-url": "https://dolphinscheduler.staging.example.com/dolphinscheduler",
            "project-code": "1001",
            "workload-subject": "workload:dataops-adapter-staging",
            "policy-evaluator-subject": "workload:policy-evaluator-staging",
            "command-tenant-id": "tenant-staging",
            "provider-tenant-code": "default",
            "provider-worker-group": "default",
        },
    }
    config_snapshot = tmp_path / "worker-configmap.yaml"
    config_snapshot.write_text(
        yaml.safe_dump(config_map, sort_keys=False),
        encoding="utf-8",
    )

    attestation = {
        "schema": SECRET_ATTESTATION_SCHEMA,
        "environment": "staging",
        "namespace": namespace,
        "secret_name": SECRET_NAME,
        "keys": ["access-token", "database-url"],
        "resource_uid": "00000000-0000-4000-8000-000000000102",
        "resource_version": "18422",
        "observed_at": observed_at.isoformat(),
    }
    attestation_path = tmp_path / "worker-secret-attestation.json"
    attestation_path.write_text(
        json.dumps(attestation, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest, config_snapshot, attestation_path


def test_staging_activation_preflight_is_redacted_and_does_not_claim_deployment(
    tmp_path,
):
    manifest, config_snapshot, attestation = _write_activation_inputs(tmp_path)

    report = build_activation_report(
        manifest,
        config_snapshot,
        attestation,
        environment="staging",
        now=NOW,
    )

    assert report["status"] == "ready_for_activation"
    assert report["activation_ready"] is True
    assert report["deployed"] is False
    assert report["live_cluster_verified"] is False
    assert report["promotion_authority_verified"] is False
    assert report["production_promotion_allowed"] is False
    assert report["requested_replicas"] == 1
    assert report["image_digest"] == IMAGE
    assert len(report["config_fingerprint"]) == 64
    assert report["config_resource_version"] == "18421"
    assert report["secret_resource_uid"].endswith("0102")
    assert report["secret_resource_version"] == "18422"
    assert report["errors"] == []
    rendered = json.dumps(report)
    assert "dolphinscheduler.staging.example.com" not in rendered
    assert "dataops-adapter-staging" not in rendered


def test_activation_preflight_blocks_unsafe_manifest_config_and_attestation(
    tmp_path,
):
    manifest, config_snapshot, attestation_path = _write_activation_inputs(
        tmp_path,
        observed_at=NOW - timedelta(seconds=901),
    )
    documents = _documents(manifest)
    deployment = _resource(documents, "Deployment", DEPLOYMENT_NAME)
    deployment["spec"]["replicas"] = 2
    pod = deployment["spec"]["template"]["spec"]
    pod["containers"][0]["image"] = "gis-data-agent:latest"
    postgres_policy = _resource(documents, "NetworkPolicy", "postgres-access")
    sources = postgres_policy["spec"]["ingress"][0]["from"]
    postgres_policy["spec"]["ingress"][0]["from"] = [
        source
        for source in sources
        if ((source.get("podSelector") or {}).get("matchLabels") or {}).get(
            "app.kubernetes.io/name"
        )
        != DEPLOYMENT_NAME
    ]
    documents.append(
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": SECRET_NAME, "namespace": "gis-agent"},
            "stringData": {"access-token": "must-never-appear"},
        }
    )
    manifest.write_text(
        yaml.safe_dump_all(documents, sort_keys=False),
        encoding="utf-8",
    )

    config_map = _resource(_documents(config_snapshot), "ConfigMap", CONFIG_NAME)
    config_map["apiVersion"] = "v2"
    config_map["data"]["base-url"] = "http://localhost:12345/dolphinscheduler"
    config_map["data"]["project-code"] = "0"
    config_map["data"]["command-tenant-id"] = "INVALID TENANT"
    config_map["data"]["policy-evaluator-subject"] = config_map["data"][
        "workload-subject"
    ]
    config_snapshot.write_text(
        yaml.safe_dump(config_map, sort_keys=False),
        encoding="utf-8",
    )

    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    attestation["data"] = {"access-token": "attested-secret-value"}
    attestation_path.write_text(json.dumps(attestation), encoding="utf-8")

    report = build_activation_report(
        manifest,
        config_snapshot,
        attestation_path,
        environment="staging",
        now=NOW,
    )

    assert report["status"] == "blocked"
    assert report["activation_ready"] is False
    assert any("exactly 1 replica" in error for error in report["errors"])
    assert "worker image must use an immutable sha256 digest" in report["errors"]
    assert "worker and token init containers must use the same image digest" in report[
        "errors"
    ]
    assert "activation manifest must not embed the dedicated worker Secret" in report[
        "errors"
    ]
    assert "PostgreSQL NetworkPolicy must allow the worker Pod label" in report[
        "errors"
    ]
    assert (
        "staging DolphinScheduler base-url must be credential-free HTTPS"
        in report["errors"]
    )
    assert "staging ConfigMap snapshot must use apiVersion v1" in report["errors"]
    assert "staging DolphinScheduler project-code must be positive" in report["errors"]
    assert "worker and policy evaluator subjects must be distinct" in report["errors"]
    assert "staging ConfigMap command-tenant-id is invalid" in report["errors"]
    assert "secret attestation is stale" in report["errors"]
    assert any("must not contain secret values" in error for error in report["errors"])
    rendered = json.dumps(report)
    assert "must-never-appear" not in rendered
    assert "attested-secret-value" not in rendered


def test_activation_cli_emits_machine_readable_ready_report(tmp_path, capsys):
    manifest, config_snapshot, attestation = _write_activation_inputs(
        tmp_path,
        observed_at=datetime.now(UTC),
    )

    assert (
        main(
            [
                "validate",
                "--manifest",
                str(manifest),
                "--config-map",
                str(config_snapshot),
                "--secret-attestation",
                str(attestation),
                "--environment",
                "staging",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ready_for_activation"
    assert report["deployed"] is False


@pytest.mark.parametrize("replicas", [True, 2])
def test_activation_requires_integer_single_replica(tmp_path, replicas):
    manifest, config_snapshot, attestation = _write_activation_inputs(tmp_path)
    documents = _documents(manifest)
    deployment = _resource(documents, "Deployment", DEPLOYMENT_NAME)
    deployment["spec"]["replicas"] = replicas
    manifest.write_text(
        yaml.safe_dump_all(documents, sort_keys=False),
        encoding="utf-8",
    )

    report = build_activation_report(
        manifest,
        config_snapshot,
        attestation,
        environment="staging",
        now=NOW,
    )

    assert report["activation_ready"] is False
    assert any("exactly 1 replica" in error for error in report["errors"])


def test_activation_binds_real_staging_namespace_and_exact_config_keys(tmp_path):
    namespace = "gis-agent-staging"
    manifest, config_snapshot, attestation = _write_activation_inputs(
        tmp_path,
        namespace=namespace,
    )

    report = build_activation_report(
        manifest,
        config_snapshot,
        attestation,
        environment="staging",
        expected_namespace=namespace,
        now=NOW,
    )

    assert report["activation_ready"] is True
    assert report["namespace"] == namespace

    config_map = _resource(_documents(config_snapshot), "ConfigMap", CONFIG_NAME)
    config_map["data"]["unexpected-token-hint"] = "not-a-secret"
    config_snapshot.write_text(
        yaml.safe_dump(config_map, sort_keys=False),
        encoding="utf-8",
    )
    blocked = build_activation_report(
        manifest,
        config_snapshot,
        attestation,
        environment="staging",
        expected_namespace=namespace,
        now=NOW,
    )

    assert blocked["activation_ready"] is False
    assert (
        "staging ConfigMap must contain exactly the required non-secret keys"
        in blocked["errors"]
    )


def test_activation_rejects_cross_namespace_external_attestation(tmp_path):
    manifest, config_snapshot, attestation_path = _write_activation_inputs(
        tmp_path,
        namespace="gis-agent-staging",
    )
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    attestation["namespace"] = "gis-agent"
    attestation_path.write_text(json.dumps(attestation), encoding="utf-8")

    report = build_activation_report(
        manifest,
        config_snapshot,
        attestation_path,
        environment="staging",
        expected_namespace="gis-agent-staging",
        now=NOW,
    )

    assert report["activation_ready"] is False
    assert (
        "secret attestation namespace must be gis-agent-staging"
        in report["errors"]
    )
