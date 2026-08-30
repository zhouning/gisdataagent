"""Deployment contracts for writable non-root ingestion lake staging."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_compose_initializes_ingestion_lake_for_non_root_worker():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    initializer = services["ingestion-lake-init"]
    worker = services["ingestion-worker"]

    assert initializer["restart"] == "no"
    assert initializer["user"] == "0:0"
    assert initializer["network_mode"] == "none"
    assert "chown 999:999 /lake /lake/raw" in "\n".join(initializer["command"])
    assert initializer["volumes"] == ["ingestion-lake:/lake"]
    assert worker["depends_on"]["ingestion-lake-init"]["condition"] == (
        "service_completed_successfully"
    )


def test_kubernetes_ingestion_worker_assigns_staging_volume_to_agent_group():
    documents = yaml.safe_load_all(
        (ROOT / "k8s/base/ingestion-worker.yaml").read_text(encoding="utf-8")
    )
    deployment = next(document for document in documents if document["kind"] == "Deployment")
    pod_spec = deployment["spec"]["template"]["spec"]

    assert pod_spec["securityContext"] == {
        "runAsNonRoot": True,
        "runAsUser": 999,
        "runAsGroup": 999,
        "fsGroup": 999,
        "fsGroupChangePolicy": "OnRootMismatch",
    }


def test_image_precreates_agent_owned_ingestion_lake_path():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "mkdir -p /app/data_agent/uploads /app/data_agent/data_lake/raw" in dockerfile
    assert "chown agent:agent /app /app/data_agent" in dockerfile
    assert "chown -R agent:agent /app" not in dockerfile
