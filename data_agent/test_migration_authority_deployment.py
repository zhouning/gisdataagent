"""Deployment contracts for the exclusive database migration authority."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _yaml(filename: str):
    return yaml.safe_load((ROOT / filename).read_text(encoding="utf-8"))


def _documents(filename: str) -> list[dict]:
    return [
        document
        for document in yaml.safe_load_all(
            (ROOT / filename).read_text(encoding="utf-8")
        )
        if isinstance(document, dict)
    ]


def test_compose_app_waits_for_one_shot_migration_authority():
    for filename in ("docker-compose.yml", "docker-compose.gemma4-demo.yml"):
        services = _yaml(filename)["services"]
        app = services["app"]
        migration = services["migrate"]

        assert app["depends_on"]["migrate"]["condition"] == (
            "service_completed_successfully"
        )
        assert "POSTGRES_ADMIN_USER" not in app["environment"]
        assert "POSTGRES_ADMIN_PASSWORD" not in app["environment"]
        assert migration["restart"] == "no"
        assert migration["entrypoint"] == ["/bin/sh", "-c"]
        command = "\n".join(migration["command"])
        assert "python -m data_agent.migration_runner migrate" in command
        assert "bash /app/scripts/grant-platform-gateway-role.sh" in command
        assert migration["environment"]["POSTGRES_USER"] == "postgres"
        assert migration["environment"]["MIGRATION_RUNTIME_DB_ROLE"] == "agent_user"


def test_kubernetes_job_uses_strict_runner_with_admin_role():
    job = next(
        document
        for document in _documents("k8s/base/migrations-job.yaml")
        if document.get("kind") == "Job"
    )
    container = job["spec"]["template"]["spec"]["containers"][0]
    command = "\n".join(container["command"])

    assert 'export POSTGRES_USER="${POSTGRES_ADMIN_USER}"' in command
    assert 'export POSTGRES_PASSWORD="${POSTGRES_ADMIN_PASSWORD}"' in command
    assert 'export MIGRATION_RUNTIME_DB_ROLE="${POSTGRES_USER}"' in command
    assert "python -m data_agent.migration_runner migrate" in command
    assert "bash /app/scripts/grant-platform-gateway-role.sh" in command
    assert "run_pending_migrations" not in command


def test_kubernetes_runtime_containers_mask_admin_credentials():
    cases = (
        ("k8s/base/app-deployment.yaml", "gis-agent-app", "app"),
        ("k8s/base/outbox-worker.yaml", "gis-agent-outbox-worker", "worker"),
    )
    for filename, deployment_name, container_name in cases:
        deployment = next(
            document
            for document in _documents(filename)
            if document.get("kind") == "Deployment"
            and document["metadata"]["name"] == deployment_name
        )
        container = next(
            item
            for item in deployment["spec"]["template"]["spec"]["containers"]
            if item["name"] == container_name
        )
        environment = {
            item["name"]: item.get("value") for item in container.get("env", [])
        }

        assert environment["POSTGRES_ADMIN_USER"] == ""
        assert environment["POSTGRES_ADMIN_PASSWORD"] == ""


def test_shell_entrypoint_delegates_to_python_runner_and_fails_closed():
    script = (ROOT / "scripts/migrate.sh").read_text(encoding="utf-8")

    assert "set -euo pipefail" in script
    assert "python -m data_agent.migration_runner migrate" in script
    assert 'grant-platform-gateway-role.sh"' in script
    assert "ON_ERROR_STOP=0" not in script
    assert "|| true" not in script


def test_gateway_role_grant_validates_identifier_and_fails_closed():
    script = (ROOT / "scripts/grant-platform-gateway-role.sh").read_text(
        encoding="utf-8"
    )

    assert "set -euo pipefail" in script
    assert "MIGRATION_RUNTIME_DB_ROLE" in script
    assert "^[A-Za-z_][A-Za-z0-9_$]*$" in script
    assert "python -m data_agent.platform_gateway_role" in script
    assert "|| true" not in script
