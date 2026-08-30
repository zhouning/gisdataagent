"""Deployment-level database connection budget regression tests."""

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_WORKERS = (
    "projection-recovery-worker",
    "ingestion-worker",
    "incident-notification-worker",
    "approval-notification-worker",
    "consumer-binding-notification-worker",
    "metadata-fabric-worker",
    "master-metadata-worker",
)


def _default_int(value: str | int) -> int:
    if isinstance(value, int):
        return value
    if value.isdigit():
        return int(value)
    match = re.fullmatch(r"\$\{[^:}]+:-(\d+)}", value)
    if not match:
        raise AssertionError(f"value has no integer default: {value!r}")
    return int(match.group(1))


def _load_yaml(path: str) -> dict:
    return yaml.safe_load((REPO_ROOT / path).read_text(encoding="utf-8"))


def _load_yaml_documents(path: str) -> list[dict]:
    return list(
        yaml.safe_load_all((REPO_ROOT / path).read_text(encoding="utf-8"))
    )


def test_compose_full_profile_fits_declared_server_budget() -> None:
    compose = _load_yaml("docker-compose.yml")
    services = compose["services"]
    app_env = services["app"]["environment"]
    server_limit = _default_int(app_env["POSTGRES_MAX_CONNECTIONS"])
    reserve = _default_int(app_env["POSTGRES_CONNECTION_RESERVE"])
    app_peak = sum(
        _default_int(app_env[key])
        for key in ("DB_POOL_SIZE", "DB_MAX_OVERFLOW", "ASYNC_POOL_MAX")
    )
    worker_peak = 0
    for service_name in COMPOSE_WORKERS:
        env = services[service_name]["environment"]
        worker_peak += sum(
            _default_int(env[key])
            for key in ("DB_POOL_SIZE", "DB_MAX_OVERFLOW", "ASYNC_POOL_MAX")
        )
    martin_peak = _default_int(
        _load_yaml("deploy/martin/config.yaml")["postgres"]["pool_size"]
    )

    assert app_peak == 50
    assert worker_peak == 42
    assert martin_peak == 10
    assert app_peak + worker_peak + martin_peak <= server_limit - reserve


def test_kubernetes_hpa_peak_leaves_half_capacity_for_other_workloads() -> None:
    config = _load_yaml("k8s/base/configmap.yaml")["data"]
    hpa = _load_yaml("k8s/base/hpa.yaml")["spec"]
    postgres = next(
        document
        for document in _load_yaml_documents(
            "k8s/base/postgres-statefulset.yaml"
        )
        if document["kind"] == "StatefulSet"
    )
    per_pod_peak = sum(
        int(config[key])
        for key in ("DB_POOL_SIZE", "DB_MAX_OVERFLOW", "ASYNC_POOL_MAX")
    )
    api_peak = per_pod_peak * int(hpa["maxReplicas"])
    application_capacity = (
        int(config["POSTGRES_MAX_CONNECTIONS"])
        - int(config["POSTGRES_CONNECTION_RESERVE"])
    )
    postgres_args = postgres["spec"]["template"]["spec"]["containers"][0][
        "args"
    ]

    assert api_peak == 80
    assert api_peak <= application_capacity // 2
    assert "max_connections=$(POSTGRES_MAX_CONNECTIONS)" in postgres_args
