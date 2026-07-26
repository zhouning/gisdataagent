from pathlib import Path

import yaml

from data_agent.dolphinscheduler_worker_deployment import (
    DEFAULT_KUSTOMIZATION,
    DEFAULT_MANIFEST,
    DEFAULT_NETWORK_POLICY,
    DEPLOYMENT_NAME,
    build_deployment_report,
)


def _documents(path: Path) -> list[dict]:
    return [
        item
        for item in yaml.safe_load_all(path.read_text(encoding="utf-8"))
        if isinstance(item, dict)
    ]


def _deployment(documents: list[dict]) -> dict:
    return next(
        item
        for item in documents
        if item.get("kind") == "Deployment"
        and (item.get("metadata") or {}).get("name") == DEPLOYMENT_NAME
    )


def _worker(deployment: dict) -> dict:
    containers = deployment["spec"]["template"]["spec"]["containers"]
    return next(item for item in containers if item.get("name") == "worker")


def test_worker_kubernetes_contract_is_valid_and_inert():
    report = build_deployment_report()

    assert report["status"] == "valid"
    assert report["errors"] == []
    assert report["default_replicas"] == 0
    assert report["resource_count"] == 2
    assert set(report["files"]) == {
        "manifest",
        "kustomization",
        "network_policy",
    }


def test_validator_rejects_active_unsafe_or_secret_leaking_worker(
    tmp_path,
):
    documents = _documents(DEFAULT_MANIFEST)
    deployment = _deployment(documents)
    deployment["spec"]["replicas"] = 1
    worker = _worker(deployment)
    worker["args"] = [
        "exec python -m data_agent.dolphinscheduler_command_worker run"
    ]
    worker["env"].append(
        {"name": "DOLPHINSCHEDULER_ACCESS_TOKEN", "value": "unsafe-inline"}
    )
    worker.pop("livenessProbe")
    unsafe_manifest = tmp_path / "worker.yaml"
    unsafe_manifest.write_text(
        yaml.safe_dump_all(documents, sort_keys=False),
        encoding="utf-8",
    )

    report = build_deployment_report(unsafe_manifest)

    assert report["status"] == "invalid"
    assert "base worker Deployment must default to zero replicas" in report["errors"]
    assert any("WORKER_ID" in error for error in report["errors"])
    assert "provider token must not be injected as an environment value" in report[
        "errors"
    ]
    assert "livenessProbe must execute the worker liveness command" in report[
        "errors"
    ]


def test_validator_requires_kustomize_and_postgres_network_registration(
    tmp_path,
):
    kustomization = yaml.safe_load(DEFAULT_KUSTOMIZATION.read_text(encoding="utf-8"))
    kustomization["resources"].remove("dolphinscheduler-command-worker.yaml")
    unsafe_kustomization = tmp_path / "kustomization.yaml"
    unsafe_kustomization.write_text(
        yaml.safe_dump(kustomization, sort_keys=False),
        encoding="utf-8",
    )

    network_documents = _documents(DEFAULT_NETWORK_POLICY)
    postgres = next(
        item
        for item in network_documents
        if item.get("kind") == "NetworkPolicy"
        and (item.get("metadata") or {}).get("name") == "postgres-access"
    )
    sources = postgres["spec"]["ingress"][0]["from"]
    postgres["spec"]["ingress"][0]["from"] = [
        source
        for source in sources
        if ((source.get("podSelector") or {}).get("matchLabels") or {}).get(
            "app.kubernetes.io/name"
        )
        != DEPLOYMENT_NAME
    ]
    unsafe_network = tmp_path / "networkpolicy.yaml"
    unsafe_network.write_text(
        yaml.safe_dump_all(network_documents, sort_keys=False),
        encoding="utf-8",
    )

    report = build_deployment_report(
        kustomization_path=unsafe_kustomization,
        network_policy_path=unsafe_network,
    )

    assert report["status"] == "invalid"
    assert "base Kustomization must register the worker manifest" in report["errors"]
    assert "PostgreSQL NetworkPolicy must allow the worker Pod label" in report[
        "errors"
    ]
