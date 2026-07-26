"""Deployment contracts for the exclusive database migration authority."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _compose(filename: str) -> dict:
    return yaml.safe_load((ROOT / filename).read_text(encoding="utf-8"))


def _documents(filename: str) -> list[dict]:
    return [
        document
        for document in yaml.safe_load_all(
            (ROOT / filename).read_text(encoding="utf-8")
        )
        if isinstance(document, dict)
    ]


def _deployment(filename: str, name: str) -> dict:
    return next(
        document
        for document in _documents(filename)
        if document.get("kind") == "Deployment"
        and (document.get("metadata") or {}).get("name") == name
    )


def _container(deployment: dict, name: str) -> dict:
    containers = deployment["spec"]["template"]["spec"]["containers"]
    return next(container for container in containers if container["name"] == name)


def _init_container(deployment: dict, name: str) -> dict:
    containers = deployment["spec"]["template"]["spec"]["initContainers"]
    return next(container for container in containers if container["name"] == name)


@pytest.mark.parametrize(
    ("filename", "app_name", "migration_name"),
    [
        ("docker-compose.yml", "app", "migrate"),
        (
            "docker-compose.staging.yml",
            "app-staging",
            "migrate-staging",
        ),
    ],
)
def test_compose_app_waits_for_migration_authority_without_admin_credentials(
    filename: str,
    app_name: str,
    migration_name: str,
):
    services = _compose(filename)["services"]
    app = services[app_name]
    migration = services[migration_name]

    assert app["depends_on"][migration_name]["condition"] == (
        "service_completed_successfully"
    )
    assert "POSTGRES_ADMIN_USER" not in app["environment"]
    assert "POSTGRES_ADMIN_PASSWORD" not in app["environment"]
    assert migration["restart"] == "no"
    assert migration["entrypoint"] == [
        "python",
        "-m",
        "data_agent.migration_runner",
    ]
    assert migration["command"] == ["migrate"]
    assert migration["environment"]["POSTGRES_USER"] == "postgres"
    assert "POSTGRES_PASSWORD" in migration["environment"]


@pytest.mark.parametrize(
    ("filename", "deployment_name", "container_name"),
    [
        ("k8s/base/app-deployment.yaml", "gis-agent-app", "app"),
        (
            "k8s/base/outbox-worker.yaml",
            "gis-agent-outbox-worker",
            "worker",
        ),
    ],
)
def test_kubernetes_runtime_containers_mask_admin_database_credentials(
    filename: str,
    deployment_name: str,
    container_name: str,
):
    deployment = _deployment(filename, deployment_name)
    container = _container(deployment, container_name)
    environment = {
        item["name"]: item.get("value") for item in container.get("env", [])
    }

    assert environment["POSTGRES_ADMIN_USER"] == ""
    assert environment["POSTGRES_ADMIN_PASSWORD"] == ""


def test_kubernetes_migration_job_retains_admin_database_authority():
    job = next(
        document
        for document in _documents("k8s/base/migrations-job.yaml")
        if document.get("kind") == "Job"
    )
    container = job["spec"]["template"]["spec"]["containers"][0]
    command = "\n".join(container["command"])

    assert {next(iter(source)) for source in container["envFrom"]} == {
        "configMapRef",
        "secretRef",
    }
    assert 'export POSTGRES_USER="${POSTGRES_ADMIN_USER}"' in command
    assert 'export POSTGRES_PASSWORD="${POSTGRES_ADMIN_PASSWORD}"' in command
    assert "python -m data_agent.migration_runner migrate" in command


@pytest.mark.parametrize(
    ("filename", "deployment_name"),
    [
        ("k8s/base/app-deployment.yaml", "gis-agent-app"),
        ("k8s/base/outbox-worker.yaml", "gis-agent-outbox-worker"),
    ],
)
def test_kubernetes_runtime_waits_on_read_only_schema_without_api_token(
    filename: str,
    deployment_name: str,
):
    documents = _documents(filename)
    deployment = next(
        document
        for document in documents
        if document.get("kind") == "Deployment"
        and (document.get("metadata") or {}).get("name") == deployment_name
    )
    pod = deployment["spec"]["template"]["spec"]
    waiter = _init_container(deployment, "wait-for-migrate")
    environment = {
        item["name"]: item.get("value") for item in waiter.get("env", [])
    }

    assert pod["automountServiceAccountToken"] is False
    assert waiter["image"] == "gis-data-agent:latest"
    assert waiter["command"] == [
        "python",
        "-m",
        "data_agent.migration_runner",
        "status",
    ]
    assert {next(iter(source)) for source in waiter["envFrom"]} == {
        "configMapRef",
        "secretRef",
    }
    assert environment == {
        "POSTGRES_ADMIN_USER": "",
        "POSTGRES_ADMIN_PASSWORD": "",
    }
    assert not any(
        document.get("kind") in {"Role", "RoleBinding"}
        for document in documents
    )
