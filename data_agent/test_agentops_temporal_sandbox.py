"""Offline deployment contracts for the optional Temporal AgentOps sandbox."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "k8s/optional/temporal-agentops-sandbox"
OVERLAY = ROOT / "k8s/overlays/temporal-agentops-sandbox"
DISCOVERY_OVERLAY = ROOT / "k8s/overlays/temporal-agentops-discovery-sandbox"
CONTROL_ACCESS = ROOT / "k8s/optional/temporal-agentops-discovery-control-access"
DISCOVERY_OBSERVABILITY = ROOT / "k8s/optional/temporal-agentops-discovery-observability"


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


def _render(path: Path) -> list[dict]:
    completed = subprocess.run(
        ["kubectl", "kustomize", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    return [document for document in yaml.safe_load_all(completed.stdout) if document]


def test_profile_is_optional_and_defaults_closed() -> None:
    kustomization = yaml.safe_load((PROFILE / "kustomization.yaml").read_text(encoding="utf-8"))
    assert kustomization["namespace"] == "gda-agentops-sandbox"
    assert kustomization["resources"] == [
        "namespace.yaml",
        "postgres.yaml",
        "temporal.yaml",
        "worker.yaml",
        "discovery-worker.yaml",
        "networkpolicy.yaml",
    ]
    assert "temporal-agentops-sandbox" not in (ROOT / "k8s/base/kustomization.yaml").read_text(
        encoding="utf-8"
    )
    assert (
        _resource(PROFILE / "postgres.yaml", "StatefulSet", "gis-agent-temporal-postgres")["spec"][
            "replicas"
        ]
        == 0
    )
    assert (
        _resource(PROFILE / "temporal.yaml", "Deployment", "gis-agent-temporal")["spec"]["replicas"]
        == 0
    )
    assert (
        _resource(PROFILE / "worker.yaml", "Deployment", "gis-agent-agentops-worker")["spec"][
            "replicas"
        ]
        == 0
    )
    assert (
        _resource(PROFILE / "discovery-worker.yaml", "Deployment", "gis-agent-agentops-discovery")[
            "spec"
        ]["replicas"]
        == 0
    )
    discovery = _resource(
        PROFILE / "discovery-worker.yaml", "Deployment", "gis-agent-agentops-discovery"
    )
    assert discovery["spec"]["strategy"] == {
        "type": "RollingUpdate",
        "rollingUpdate": {"maxUnavailable": 0, "maxSurge": 1},
    }


def test_profile_uses_pinned_server_and_external_secret_only() -> None:
    server = _resource(PROFILE / "temporal.yaml", "Deployment", "gis-agent-temporal")
    container = server["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == "temporalio/auto-setup:1.29.7"
    env = {item["name"]: item for item in container["env"]}
    assert env["DB"]["value"] == "postgres12"
    assert env["POSTGRES_SEEDS"]["value"] == "gis-agent-temporal-postgres"
    assert env["DEFAULT_NAMESPACE"]["value"] == "gda-agentops-sandbox"
    assert env["DEFAULT_NAMESPACE_RETENTION"]["value"] == "24h"
    assert env["DYNAMIC_CONFIG_FILE_PATH"]["value"] == ("config/dynamicconfig/docker.yaml")
    assert env["BIND_ON_IP"]["value"] == "0.0.0.0"
    assert env["POSTGRES_PWD"]["valueFrom"]["secretKeyRef"] == {
        "name": "gis-agent-temporal-runtime",
        "key": "database-password",
    }
    rendered_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in PROFILE.iterdir()
        if path.suffix in {".yaml", ".md"}
    )
    assert "kind: Secret" not in rendered_sources
    assert "postgresql://" not in rendered_sources
    assert "POSTGRES_PWD:" not in rendered_sources

    postgres = _resource(PROFILE / "postgres.yaml", "StatefulSet", "gis-agent-temporal-postgres")
    pod_security = postgres["spec"]["template"]["spec"]["securityContext"]
    container_security = postgres["spec"]["template"]["spec"]["containers"][0]["securityContext"]
    assert pod_security["runAsNonRoot"] is True
    assert pod_security["runAsUser"] == 70
    assert pod_security["runAsGroup"] == 70
    assert pod_security["fsGroup"] == 70
    assert container_security["runAsNonRoot"] is True
    assert container_security["runAsUser"] == 70
    assert container_security["runAsGroup"] == 70

    temporal_pod_security = server["spec"]["template"]["spec"]["securityContext"]
    temporal_container_security = container["securityContext"]
    assert temporal_pod_security["runAsNonRoot"] is True
    assert temporal_pod_security["runAsUser"] == 1000
    assert temporal_pod_security["runAsGroup"] == 1000
    assert temporal_container_security["runAsNonRoot"] is True
    assert temporal_container_security["runAsUser"] == 1000
    assert temporal_container_security["runAsGroup"] == 1000

    discovery = _resource(
        PROFILE / "discovery-worker.yaml", "Deployment", "gis-agent-agentops-discovery"
    )
    discovery_container = discovery["spec"]["template"]["spec"]["containers"][0]
    discovery_env = {item["name"]: item for item in discovery_container["env"]}
    assert discovery_env["DATABASE_URL"]["valueFrom"]["secretKeyRef"] == {
        "name": "gis-agent-agentops-discovery-runtime",
        "key": "database-url",
    }
    assert "--discover" in discovery_container["args"][0]
    assert discovery_container["ports"] == [
        {"name": "metrics", "containerPort": 9090, "protocol": "TCP"}
    ]
    assert discovery_env["GDA_AGENTOPS_RECONCILER_STATUS_FILE"]["value"] == (
        "/var/run/gda-status/discovery.json"
    )
    assert {probe for probe in discovery_container if probe.endswith("Probe")} == {
        "startupProbe",
        "readinessProbe",
        "livenessProbe",
    }
    assert discovery["spec"]["template"]["spec"]["automountServiceAccountToken"] is False
    assert discovery_container["securityContext"]["readOnlyRootFilesystem"] is True

    service = _resource(
        PROFILE / "discovery-worker.yaml", "Service", "gis-agent-agentops-discovery"
    )
    assert service["spec"]["ports"] == [
        {"name": "metrics", "port": 9090, "targetPort": "metrics", "protocol": "TCP"}
    ]


def test_discovery_service_monitor_is_an_optional_crd_package() -> None:
    rendered = _render(DISCOVERY_OBSERVABILITY)
    monitor = next(
        document
        for document in rendered
        if document["kind"] == "ServiceMonitor"
        and document["metadata"]["name"] == "gis-agent-agentops-discovery"
    )
    assert monitor["spec"]["namespaceSelector"]["matchNames"] == ["gda-agentops-sandbox"]
    assert monitor["spec"]["endpoints"] == [
        {
            "port": "metrics",
            "path": "/metrics",
            "scheme": "http",
            "interval": "30s",
            "scrapeTimeout": "10s",
        }
    ]


def test_network_policies_are_namespace_local_and_fail_closed() -> None:
    temporal = _resource(
        PROFILE / "networkpolicy.yaml",
        "NetworkPolicy",
        "gis-agent-temporal-server-isolation",
    )["spec"]
    assert temporal["ingress"] == [
        {
            "from": [
                {
                    "podSelector": {
                        "matchLabels": {"app.kubernetes.io/name": "gis-agent-agentops-worker"}
                    }
                },
                {
                    "podSelector": {
                        "matchLabels": {"app.kubernetes.io/name": "gis-agent-agentops-discovery"}
                    }
                },
            ],
            "ports": [
                {"protocol": "TCP", "port": 7233},
                {"protocol": "TCP", "port": 7235},
            ],
        }
    ]
    worker = _resource(
        PROFILE / "networkpolicy.yaml",
        "NetworkPolicy",
        "gis-agent-agentops-worker-isolation",
    )["spec"]
    assert worker["ingress"] == []
    assert {port["port"] for rule in worker["egress"] for port in rule["ports"]} == {
        53,
        7233,
    }
    discovery = _resource(
        PROFILE / "networkpolicy.yaml",
        "NetworkPolicy",
        "gis-agent-agentops-discovery-isolation",
    )["spec"]
    assert discovery["ingress"] == [
        {
            "from": [
                {
                    "namespaceSelector": {
                        "matchLabels": {"kubernetes.io/metadata.name": "monitoring"}
                    }
                }
            ],
            "ports": [{"protocol": "TCP", "port": 9090}],
        }
    ]
    assert {port["port"] for rule in discovery["egress"] for port in rule["ports"]} == {
        53,
        5432,
        7233,
    }


def test_overlay_enables_only_server_and_metadata_database() -> None:
    kustomization = yaml.safe_load((OVERLAY / "kustomization.yaml").read_text(encoding="utf-8"))
    assert kustomization["resources"] == ["../../optional/temporal-agentops-sandbox"]
    assert [patch["path"] for patch in kustomization["patches"]] == [
        "postgres-enable-patch.yaml",
        "temporal-enable-patch.yaml",
    ]
    documents = _render(OVERLAY)
    replicas = {
        (document["kind"], document["metadata"]["name"]): document["spec"]["replicas"]
        for document in documents
        if document["kind"] in {"Deployment", "StatefulSet"}
    }
    assert replicas["StatefulSet", "gis-agent-temporal-postgres"] == 1
    assert replicas["Deployment", "gis-agent-temporal"] == 1
    assert replicas["Deployment", "gis-agent-agentops-worker"] == 0
    assert replicas["Deployment", "gis-agent-agentops-discovery"] == 0
    assert all(
        document["metadata"]["namespace"] == "gda-agentops-sandbox"
        for document in documents
        if document["kind"] != "Namespace"
    )


def test_discovery_control_access_is_separate_gis_agent_namespace_package() -> None:
    kustomization = yaml.safe_load(
        (CONTROL_ACCESS / "kustomization.yaml").read_text(encoding="utf-8")
    )
    assert kustomization["namespace"] == "gis-agent"
    documents = _render(CONTROL_ACCESS)
    policy = next(
        document
        for document in documents
        if document["kind"] == "NetworkPolicy"
        and document["metadata"]["name"] == "gis-agent-postgres-agentops-discovery-access"
    )
    assert policy["metadata"]["namespace"] == "gis-agent"
    source = policy["spec"]["ingress"][0]["from"][0]
    assert source["namespaceSelector"]["matchLabels"] == {
        "kubernetes.io/metadata.name": "gda-agentops-sandbox"
    }
    assert source["podSelector"]["matchLabels"] == {
        "app.kubernetes.io/name": "gis-agent-agentops-discovery"
    }
    readme = (CONTROL_ACCESS / "README.md").read_text(encoding="utf-8")
    assert "gda_control_gateway" in readme
    assert "kind: Secret" not in readme


def test_discovery_overlay_is_explicit_two_replica_opt_in() -> None:
    kustomization = yaml.safe_load(
        (DISCOVERY_OVERLAY / "kustomization.yaml").read_text(encoding="utf-8")
    )
    assert kustomization["resources"] == ["../../optional/temporal-agentops-sandbox"]
    assert [patch["path"] for patch in kustomization["patches"]] == [
        "discovery-enable-patch.yaml",
        "postgres-enable-patch.yaml",
        "temporal-enable-patch.yaml",
    ]
    documents = _render(DISCOVERY_OVERLAY)
    replicas = {
        (document["kind"], document["metadata"]["name"]): document["spec"]["replicas"]
        for document in documents
        if document["kind"] in {"Deployment", "StatefulSet"}
    }
    assert replicas["StatefulSet", "gis-agent-temporal-postgres"] == 1
    assert replicas["Deployment", "gis-agent-temporal"] == 1
    assert replicas["Deployment", "gis-agent-agentops-discovery"] == 2
    pdb = next(
        document
        for document in documents
        if document["kind"] == "PodDisruptionBudget"
        and document["metadata"]["name"] == "gis-agent-agentops-discovery"
    )
    assert pdb["spec"]["minAvailable"] == 1
