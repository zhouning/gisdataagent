"""Offline deployment contracts for the optional metric-query worker profile."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import yaml

from data_agent.metric_query_command_worker import MetricQueryCommandWorkerConfig

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "k8s/optional/metric-query-worker"
WORKER_FILE = PROFILE / "worker.yaml"
NETWORK_FILE = PROFILE / "networkpolicy.yaml"
MATERIALIZER = ROOT / "scripts/materialize_metric_query_provider_secret.sh"


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


def test_secret_materializer_creates_owner_only_redacted_copy(tmp_path: Path) -> None:
    secret = "postgresql://metric_reader:private-fixture@postgres/metrics"
    source = tmp_path / "projected" / "database-url"
    source.parent.mkdir()
    source.write_text(secret + "\n", encoding="utf-8")
    source.chmod(0o444)
    destination = tmp_path / "owned" / "postgis.url"

    completed = subprocess.run(
        ["/bin/sh", str(MATERIALIZER), str(source), str(destination)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert destination.read_text(encoding="utf-8") == secret + "\n"
    assert stat.S_IMODE(destination.stat().st_mode) == 0o400
    assert destination.stat().st_uid == os.getuid()
    assert secret not in completed.stdout
    assert secret not in completed.stderr


def test_secret_materializer_rejects_symlink_destination(tmp_path: Path) -> None:
    source = tmp_path / "database-url"
    source.write_text("postgresql://reader:secret@db/metrics\n", encoding="utf-8")
    target = tmp_path / "target"
    target.write_text("must-remain", encoding="utf-8")
    destination = tmp_path / "postgis.url"
    destination.symlink_to(target)

    completed = subprocess.run(
        ["/bin/sh", str(MATERIALIZER), str(source), str(destination)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert target.read_text(encoding="utf-8") == "must-remain"
    assert "postgresql://" not in completed.stderr


def test_optional_profile_does_not_embed_or_generate_a_secret() -> None:
    rendered = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (WORKER_FILE, NETWORK_FILE, PROFILE / "kustomization.yaml")
    )
    assert all(document["kind"] != "Secret" for document in _documents(WORKER_FILE))
    assert "stringData:" not in rendered
    assert "postgresql://" not in rendered
    assert "gis-agent-metric-query-postgis-runtime" in rendered


def test_worker_configmap_obeys_runtime_budget_contract(tmp_path: Path) -> None:
    configmap = _resource(
        WORKER_FILE,
        "ConfigMap",
        "gis-agent-metric-query-worker",
    )["data"]
    provider_url_file = tmp_path / "postgis.url"
    provider_url_file.write_text(
        "postgresql://gda_metric_query_reader:secret@postgres/gis_agent\n",
        encoding="utf-8",
    )
    provider_url_file.chmod(0o600)

    config = MetricQueryCommandWorkerConfig(
        tenant_id="deployment-contract",
        worker_id="worker:metric-query-postgis:deployment-contract",
        provider_database_url_file=provider_url_file,
        provider_database_role=configmap[
            "GDA_METRIC_QUERY_POSTGIS_DATABASE_ROLE"
        ],
        result_backend=configmap["GDA_METRIC_QUERY_RESULT_BACKEND"],
        result_s3_bucket=configmap["GDA_METRIC_QUERY_RESULT_S3_BUCKET"],
        result_s3_prefix=configmap["GDA_METRIC_QUERY_RESULT_S3_PREFIX"],
        result_store_timeout_seconds=int(
            configmap["GDA_METRIC_QUERY_RESULT_STORE_TIMEOUT_SECONDS"]
        ),
        relation_authority=configmap[
            "GDA_METRIC_QUERY_POSTGIS_RELATION_AUTHORITY"
        ],
        provider_connect_timeout_seconds=int(
            configmap["GDA_METRIC_QUERY_POSTGIS_CONNECT_TIMEOUT_SECONDS"]
        ),
        statement_timeout_ms=int(
            configmap["GDA_METRIC_QUERY_POSTGIS_STATEMENT_TIMEOUT_MS"]
        ),
        max_result_rows=int(configmap["GDA_METRIC_QUERY_MAX_RESULT_ROWS"]),
        batch_size=int(configmap["GDA_METRIC_QUERY_BATCH_SIZE"]),
        lease_seconds=int(configmap["GDA_METRIC_QUERY_LEASE_SECONDS"]),
        poll_interval_seconds=float(
            configmap["GDA_METRIC_QUERY_POLL_INTERVAL_SECONDS"]
        ),
        status_file=tmp_path / "status.json",
        health_max_age_seconds=float(
            configmap["GDA_METRIC_QUERY_HEALTH_MAX_AGE_SECONDS"]
        ),
    )

    assert config.provider_database_url().startswith(
        "postgresql://gda_metric_query_reader:"
    )


def test_deployment_materializes_secret_outside_main_container() -> None:
    deployment = _resource(
        WORKER_FILE,
        "Deployment",
        "gis-agent-metric-query-worker",
    )
    assert deployment["spec"]["replicas"] == 1
    assert deployment["spec"]["strategy"] == {"type": "Recreate"}
    pod = deployment["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["enableServiceLinks"] is False
    assert pod["terminationGracePeriodSeconds"] == 120
    service_account = _resource(
        WORKER_FILE,
        "ServiceAccount",
        "gis-agent-metric-query-worker",
    )
    assert service_account["automountServiceAccountToken"] is False
    assert pod["securityContext"] == {
        "runAsNonRoot": True,
        "runAsUser": 10001,
        "runAsGroup": 10001,
        "fsGroup": 10001,
        "fsGroupChangePolicy": "OnRootMismatch",
        "seccompProfile": {"type": "RuntimeDefault"},
    }

    init = _named(pod["initContainers"], "materialize-provider-secret")
    assert init["command"][-2:] == [
        "/var/run/gda-secret-input/database-url",
        "/var/run/gda-secret-owned/postgis.url",
    ]
    assert init["securityContext"]["runAsUser"] == 10001
    assert init["securityContext"]["allowPrivilegeEscalation"] is False
    assert init["securityContext"]["readOnlyRootFilesystem"] is True
    assert init["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert {mount["name"] for mount in init["volumeMounts"]} == {
        "provider-secret-input",
        "provider-secret-owned",
    }
    assert "env" not in init
    assert "envFrom" not in init

    worker = _named(pod["containers"], "worker")
    worker_mounts = {mount["name"] for mount in worker["volumeMounts"]}
    assert "provider-secret-input" not in worker_mounts
    assert "provider-secret-owned" in worker_mounts
    assert worker["securityContext"]["runAsUser"] == 10001
    assert worker["securityContext"]["allowPrivilegeEscalation"] is False
    assert worker["securityContext"]["readOnlyRootFilesystem"] is True
    assert worker["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert "exec python -m data_agent.metric_query_command_worker run" in worker[
        "args"
    ][0]

    volumes = {volume["name"]: volume for volume in pod["volumes"]}
    source = volumes["provider-secret-input"]["secret"]
    assert source["secretName"] == "gis-agent-metric-query-postgis-runtime"
    assert source["defaultMode"] == 0o444
    assert volumes["provider-secret-owned"]["emptyDir"]["medium"] == "Memory"
    assert "query-results" not in volumes


def test_deployment_uses_secret_refs_and_fail_closed_exec_probes() -> None:
    deployment = _resource(
        WORKER_FILE,
        "Deployment",
        "gis-agent-metric-query-worker",
    )
    worker = deployment["spec"]["template"]["spec"]["containers"][0]
    environment = {item["name"]: item for item in worker["env"]}
    assert environment["POSTGRES_PASSWORD"]["valueFrom"]["secretKeyRef"] == {
        "name": "gis-agent-secret",
        "key": "POSTGRES_PASSWORD",
    }
    assert environment["GDA_METRIC_QUERY_TENANT_ID"]["valueFrom"][
        "secretKeyRef"
    ] == {
        "name": "gis-agent-metric-query-postgis-runtime",
        "key": "tenant-id",
    }
    assert environment["GDA_METRIC_QUERY_POSTGIS_DATABASE_URL_FILE"]["value"] == (
        "/var/run/gda-secret-owned/postgis.url"
    )
    assert environment["POSTGRES_ADMIN_USER"]["value"] == ""
    assert environment["POSTGRES_ADMIN_PASSWORD"]["value"] == ""
    assert environment["AWS_ACCESS_KEY_ID"]["valueFrom"]["secretKeyRef"] == {
        "name": "gis-agent-metric-query-postgis-runtime",
        "key": "s3-access-key-id",
    }
    assert environment["AWS_SECRET_ACCESS_KEY"]["valueFrom"]["secretKeyRef"] == {
        "name": "gis-agent-metric-query-postgis-runtime",
        "key": "s3-secret-access-key",
    }
    assert all(
        item.get("valueFrom", {}).get("secretKeyRef", {}).get("key")
        != "database-url"
        for item in worker["env"]
    )

    assert worker["startupProbe"]["exec"]["command"][3] == "liveness"
    assert worker["readinessProbe"]["exec"]["command"][3] == "health"
    assert worker["livenessProbe"]["exec"]["command"][3] == "liveness"
    for probe_name in ("startupProbe", "readinessProbe", "livenessProbe"):
        command = worker[probe_name]["exec"]["command"]
        assert "/var/run/gda-status/worker.json" in command
        assert command[-1] == "180"


def test_network_policy_denies_ingress_and_limits_egress_to_dns_and_postgres() -> None:
    isolation = _resource(
        NETWORK_FILE,
        "NetworkPolicy",
        "gis-agent-metric-query-worker-isolation",
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
    assert isolation["egress"][0]["to"] == [
        {
            "namespaceSelector": {
                "matchLabels": {"kubernetes.io/metadata.name": "kube-system"}
            },
            "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
        }
    ]
    assert isolation["egress"][1]["to"] == [
        {
            "podSelector": {
                "matchLabels": {"app.kubernetes.io/name": "postgres"}
            }
        }
    ]
    assert isolation["egress"][2]["to"] == [
        {
            "podSelector": {
                "matchLabels": {"app.kubernetes.io/name": "minio"}
            }
        }
    ]

    postgres_ingress = _resource(
        NETWORK_FILE,
        "NetworkPolicy",
        "postgres-from-metric-query-worker",
    )["spec"]
    assert postgres_ingress["policyTypes"] == ["Ingress"]
    assert postgres_ingress["ingress"][0]["from"] == [
        {
            "podSelector": {
                "matchLabels": {
                    "app.kubernetes.io/name": "gis-agent-metric-query-worker"
                }
            }
        }
    ]
    assert postgres_ingress["ingress"][0]["ports"] == [
        {"protocol": "TCP", "port": 5432}
    ]


def test_profile_is_explicitly_optional_and_uses_shared_object_results() -> None:
    kustomization = yaml.safe_load(
        (PROFILE / "kustomization.yaml").read_text(encoding="utf-8")
    )
    assert kustomization["resources"] == ["worker.yaml", "networkpolicy.yaml"]
    assert "metric-query-worker" not in (
        ROOT / "k8s/base/kustomization.yaml"
    ).read_text(encoding="utf-8")
    assert all(
        document["kind"] != "PersistentVolumeClaim"
        for document in _documents(WORKER_FILE)
    )
    configmap = _resource(
        WORKER_FILE,
        "ConfigMap",
        "gis-agent-metric-query-worker",
    )["data"]
    assert configmap["GDA_METRIC_QUERY_RESULT_BACKEND"] == "s3"
    assert configmap["GDA_METRIC_QUERY_RESULT_S3_BUCKET"] == (
        "gis-agent-metric-query-results"
    )
    assert configmap["GDA_METRIC_QUERY_RESULT_S3_PREFIX"] == (
        "metric-query-results/v1"
    )
