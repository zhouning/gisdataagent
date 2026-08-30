"""Offline deployment contracts for the optional DuckDB Blueprint worker."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from data_agent.duckdb_blueprint_command_worker import (
    DuckDBBlueprintCommandWorkerConfig,
)

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "k8s/optional/duckdb-blueprint-worker"
WORKER_FILE = PROFILE / "worker.yaml"
NETWORK_FILE = PROFILE / "networkpolicy.yaml"
BASE_NETWORK_FILE = ROOT / "k8s/base/networkpolicy.yaml"
COMPOSE_FILE = ROOT / "docker-compose.yml"


def _documents(path: Path) -> list[dict]:
    return [
        document
        for document in yaml.safe_load_all(path.read_text(encoding="utf-8"))
        if document is not None
    ]


def _resource(path: Path, kind: str, name: str) -> dict:
    return next(
        document
        for document in _documents(path)
        if document["kind"] == kind and document["metadata"]["name"] == name
    )


def _named(items: list[dict], name: str) -> dict:
    return next(item for item in items if item["name"] == name)


def test_optional_profile_is_not_part_of_the_default_base() -> None:
    kustomization = yaml.safe_load(
        (PROFILE / "kustomization.yaml").read_text(encoding="utf-8")
    )

    assert kustomization["resources"] == ["worker.yaml", "networkpolicy.yaml"]
    assert "duckdb-blueprint-worker" not in (
        ROOT / "k8s/base/kustomization.yaml"
    ).read_text(encoding="utf-8")


def test_configmap_obeys_the_worker_runtime_budget(tmp_path: Path) -> None:
    configmap = _resource(
        WORKER_FILE,
        "ConfigMap",
        "gis-agent-duckdb-blueprint-worker",
    )["data"]
    config = DuckDBBlueprintCommandWorkerConfig(
        tenant_id="deployment-contract",
        worker_id="worker:blueprint-duckdb:deployment-contract",
        output_root=tmp_path / "workspace",
        result_backend=configmap["GDA_BLUEPRINT_DUCKDB_RESULT_BACKEND"],
        output_s3_bucket=configmap["GDA_BLUEPRINT_DUCKDB_OUTPUT_S3_BUCKET"],
        output_s3_prefix=configmap["GDA_BLUEPRINT_DUCKDB_OUTPUT_S3_PREFIX"],
        input_s3_prefixes=tuple(
            configmap["GDA_BLUEPRINT_DUCKDB_INPUT_S3_PREFIXES"].split(",")
        ),
        batch_size=int(configmap["GDA_BLUEPRINT_DUCKDB_BATCH_SIZE"]),
        lease_seconds=int(configmap["GDA_BLUEPRINT_DUCKDB_LEASE_SECONDS"]),
        provider_timeout_ceiling_seconds=int(
            configmap["GDA_BLUEPRINT_DUCKDB_TIMEOUT_CEILING_SECONDS"]
        ),
        provider_io_budget_seconds=int(
            configmap["GDA_BLUEPRINT_DUCKDB_IO_BUDGET_SECONDS"]
        ),
        object_store_connect_timeout_seconds=float(
            configmap["GDA_BLUEPRINT_DUCKDB_S3_CONNECT_TIMEOUT_SECONDS"]
        ),
        object_store_read_timeout_seconds=float(
            configmap["GDA_BLUEPRINT_DUCKDB_S3_READ_TIMEOUT_SECONDS"]
        ),
        retry_delay_seconds=int(configmap["GDA_BLUEPRINT_DUCKDB_RETRY_SECONDS"]),
        poll_interval_seconds=float(configmap["GDA_BLUEPRINT_DUCKDB_POLL_SECONDS"]),
        status_file=tmp_path / "status" / "worker.json",
        health_max_age_seconds=float(
            configmap["GDA_BLUEPRINT_DUCKDB_HEALTH_MAX_AGE_SECONDS"]
        ),
    )

    assert config.result_backend == "s3"
    assert config.lease_seconds == 900
    assert config.safe_summary()["input_s3_prefixes"] == [
        "s3://gis-agent-lakehouse/products",
        "s3://gis-agent-uploads/admitted",
    ]
    assert configmap["GDA_BLUEPRINT_DUCKDB_SPATIAL_EXTENSION_PATH"] == (
        "/app/duckdb-extensions/spatial.duckdb_extension"
    )


def test_deployment_uses_worker_only_secrets_and_private_ephemeral_storage() -> None:
    deployment = _resource(
        WORKER_FILE,
        "Deployment",
        "gis-agent-duckdb-blueprint-worker",
    )
    assert deployment["spec"]["replicas"] == 1
    assert deployment["spec"]["strategy"] == {"type": "Recreate"}
    pod = deployment["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["enableServiceLinks"] is False
    assert pod["terminationGracePeriodSeconds"] == 660
    assert pod["securityContext"] == {
        "runAsNonRoot": True,
        "runAsUser": 999,
        "runAsGroup": 999,
        "fsGroup": 999,
        "fsGroupChangePolicy": "OnRootMismatch",
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    service_account = _resource(
        WORKER_FILE,
        "ServiceAccount",
        "gis-agent-duckdb-blueprint-worker",
    )
    assert service_account["automountServiceAccountToken"] is False

    worker = _named(pod["containers"], "worker")
    assert "exec python -m data_agent.duckdb_blueprint_command_worker run" in worker[
        "args"
    ][0]
    assert worker["securityContext"] == {
        "runAsNonRoot": True,
        "runAsUser": 999,
        "runAsGroup": 999,
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "capabilities": {"drop": ["ALL"]},
    }
    environment = {item["name"]: item for item in worker["env"]}
    assert environment["POSTGRES_PASSWORD"]["valueFrom"]["secretKeyRef"] == {
        "name": "gis-agent-secret",
        "key": "POSTGRES_PASSWORD",
    }
    assert environment["GDA_BLUEPRINT_DUCKDB_TENANT_ID"]["valueFrom"][
        "secretKeyRef"
    ] == {
        "name": "gis-agent-duckdb-blueprint-runtime",
        "key": "tenant-id",
    }
    assert environment["AWS_ACCESS_KEY_ID"]["valueFrom"]["secretKeyRef"] == {
        "name": "gis-agent-duckdb-blueprint-runtime",
        "key": "s3-access-key-id",
    }
    assert environment["AWS_SECRET_ACCESS_KEY"]["valueFrom"]["secretKeyRef"] == {
        "name": "gis-agent-duckdb-blueprint-runtime",
        "key": "s3-secret-access-key",
    }
    assert environment["POSTGRES_ADMIN_USER"]["value"] == ""
    assert environment["POSTGRES_ADMIN_PASSWORD"]["value"] == ""
    assert environment["GDA_SKIP_RUNTIME_ENV_FILE"]["value"] == "1"
    assert all(
        "secret" not in document["kind"].lower()
        for document in _documents(WORKER_FILE)
    )

    mounts = {mount["name"]: mount["mountPath"] for mount in worker["volumeMounts"]}
    assert mounts == {
        "worker-workspace": "/var/run/gda-workspace",
        "worker-status": "/var/run/gda-status",
        "worker-tmp": "/tmp",
    }
    volumes = {volume["name"]: volume for volume in pod["volumes"]}
    assert volumes["worker-workspace"]["emptyDir"]["sizeLimit"] == "3Gi"
    assert volumes["worker-status"]["emptyDir"] == {
        "medium": "Memory",
        "sizeLimit": "1Mi",
    }
    assert volumes["worker-tmp"]["emptyDir"] == {
        "medium": "Memory",
        "sizeLimit": "128Mi",
    }


def test_probes_are_local_and_fail_closed() -> None:
    worker = _resource(
        WORKER_FILE,
        "Deployment",
        "gis-agent-duckdb-blueprint-worker",
    )["spec"]["template"]["spec"]["containers"][0]

    for probe_name, expected_command in (
        ("startupProbe", "liveness"),
        ("readinessProbe", "health"),
        ("livenessProbe", "liveness"),
    ):
        command = worker[probe_name]["exec"]["command"]
        assert command[3] == expected_command
        assert command[5] == "/var/run/gda-status/worker.json"
        assert command[-1] == "1200"


def test_network_policy_denies_ingress_and_limits_egress() -> None:
    isolation = _resource(
        NETWORK_FILE,
        "NetworkPolicy",
        "gis-agent-duckdb-blueprint-worker-isolation",
    )["spec"]
    assert isolation["policyTypes"] == ["Ingress", "Egress"]
    assert isolation["ingress"] == []
    ports = {
        (port["protocol"], port["port"])
        for rule in isolation["egress"]
        for port in rule["ports"]
    }
    assert ports == {
        ("UDP", 53),
        ("TCP", 53),
        ("TCP", 5432),
        ("TCP", 9000),
    }

    for name, target in (
        ("postgres-from-duckdb-blueprint-worker", "postgres"),
        ("minio-from-duckdb-blueprint-worker", "minio"),
    ):
        policy = _resource(NETWORK_FILE, "NetworkPolicy", name)["spec"]
        assert policy["policyTypes"] == ["Ingress"]
        assert policy["podSelector"]["matchLabels"] == {
            "app.kubernetes.io/name": target
        }
        assert policy["ingress"][0]["from"] == [
            {
                "podSelector": {
                    "matchLabels": {
                        "app.kubernetes.io/name": (
                            "gis-agent-duckdb-blueprint-worker"
                        )
                    }
                }
            }
        ]

    base_minio = _resource(BASE_NETWORK_FILE, "NetworkPolicy", "minio-access")[
        "spec"
    ]
    assert all(
        peer.get("podSelector") != {}
        for rule in base_minio["ingress"]
        for peer in rule["from"]
    )


def test_profile_renders_with_kustomize() -> None:
    completed = subprocess.run(
        ["kubectl", "kustomize", str(PROFILE)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "name: gis-agent-duckdb-blueprint-worker" in completed.stdout


def test_compose_profile_preserves_api_worker_credential_boundary() -> None:
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    services = compose["services"]
    app_environment = services["app"]["environment"]
    worker = services["duckdb-blueprint-worker"]
    worker_environment = worker["environment"]

    assert app_environment["GDA_BLUEPRINT_DUCKDB_RESULT_BACKEND"] == (
        "${GDA_BLUEPRINT_DUCKDB_RESULT_BACKEND:-s3}"
    )
    assert "GDA_BLUEPRINT_DUCKDB_ACCESS_KEY_ID" not in app_environment
    assert "GDA_BLUEPRINT_DUCKDB_SECRET_ACCESS_KEY" not in app_environment
    assert worker["profiles"] == ["blueprint"]
    assert worker_environment["GDA_BLUEPRINT_DUCKDB_RESULT_BACKEND"] == "s3"
    assert worker_environment["GDA_BLUEPRINT_DUCKDB_SPATIAL_EXTENSION_PATH"] == (
        "/app/duckdb-extensions/spatial.duckdb_extension"
    )
    assert worker_environment["AWS_ACCESS_KEY_ID"] == (
        "${GDA_BLUEPRINT_DUCKDB_ACCESS_KEY_ID:-gda_blueprint_worker}"
    )
    assert worker["read_only"] is True
    assert worker["cap_drop"] == ["ALL"]
    assert worker["security_opt"] == ["no-new-privileges:true"]
    assert worker["init"] is True
    assert {item.split(":", 1)[0] for item in worker["volumes"]} == {
        "blueprint-worker-workspace",
        "blueprint-worker-status",
    }


def test_compose_minio_bootstrap_requires_lock_and_scoped_policy() -> None:
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    services = compose["services"]
    bootstrap = services["minio-bucket-init"]["command"][0]
    initializer = services["blueprint-worker-volume-init"]

    assert "mc mb --with-lock" in bootstrap
    assert "mc retention set --default GOVERNANCE 1d" in bootstrap
    assert '"s3:GetObjectVersion"' in bootstrap
    assert '"s3:PutObject"' in bootstrap
    assert "s3:DeleteObject" not in bootstrap
    assert "s3:BypassGovernanceRetention" not in bootstrap
    assert initializer["profiles"] == ["blueprint"]
    assert initializer["network_mode"] == "none"


def test_worker_image_pins_and_preinstalls_duckdb_spatial_extension() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "duckdb==1.5.5" in (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "GDA_BLUEPRINT_DUCKDB_SPATIAL_EXTENSION_PATH" in dockerfile
    assert "INSTALL spatial" in dockerfile
    assert "spatial.duckdb_extension" in dockerfile
    assert "rm -rf /root/.duckdb" in dockerfile
