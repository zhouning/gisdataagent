"""Offline deployment contracts for the optional projection recovery worker."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "k8s/optional/projection-recovery-worker"
WORKER_FILE = PROFILE / "worker.yaml"
NETWORK_FILE = PROFILE / "networkpolicy.yaml"


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


def test_profile_is_optional_and_defaults_to_zero_replicas() -> None:
    kustomization = yaml.safe_load(
        (PROFILE / "kustomization.yaml").read_text(encoding="utf-8")
    )
    assert kustomization["resources"] == ["worker.yaml", "networkpolicy.yaml"]
    assert "projection-recovery-worker" not in (
        ROOT / "k8s/base/kustomization.yaml"
    ).read_text(encoding="utf-8")
    deployment = _resource(
        WORKER_FILE,
        "Deployment",
        "gis-agent-projection-recovery-worker",
    )
    assert deployment["spec"]["replicas"] == 0
    assert deployment["spec"]["strategy"] == {"type": "Recreate"}


def test_worker_uses_dedicated_identity_and_read_only_evidence() -> None:
    service_account = _resource(
        WORKER_FILE,
        "ServiceAccount",
        "gis-agent-projection-recovery-worker",
    )
    assert service_account["automountServiceAccountToken"] is False
    deployment = _resource(
        WORKER_FILE,
        "Deployment",
        "gis-agent-projection-recovery-worker",
    )
    pod = deployment["spec"]["template"]["spec"]
    container = pod["containers"][0]
    assert pod["serviceAccountName"] == "gis-agent-projection-recovery-worker"
    assert pod["automountServiceAccountToken"] is False
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["runAsUser"] == 10001
    mounts = {item["name"]: item for item in container["volumeMounts"]}
    assert mounts["controller-admission"]["readOnly"] is True
    assert mounts["runtime-identity"]["readOnly"] is True
    assert mounts["recovery-rows"]["readOnly"] is True
    volumes = {item["name"]: item for item in pod["volumes"]}
    assert volumes["controller-admission"]["secret"]["secretName"] == (
        "gis-agent-projection-recovery-admission"
    )
    assert volumes["runtime-identity"]["secret"]["secretName"] == (
        "gis-agent-projection-recovery-runtime"
    )


def test_worker_requires_controller_admission_bundle_and_never_embeds_provider_secret() -> None:
    config = _resource(
        WORKER_FILE,
        "ConfigMap",
        "gis-agent-projection-recovery-worker",
    )["data"]
    assert config["GDA_PROJECTION_RECOVERY_CONTROLLER_ADMISSION_FILE"] == (
        "/var/run/gda-controller/admissions.json"
    )
    rendered = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (WORKER_FILE, NETWORK_FILE, PROFILE / "kustomization.yaml")
    )
    assert "kind: Secret" not in rendered
    assert "postgresql://" not in rendered
    assert "AWS_SECRET_ACCESS_KEY" not in rendered
    assert "gis-agent-projection-recovery-admission" in rendered


def test_network_policy_limits_worker_to_dns_postgres_and_minio() -> None:
    isolation = _resource(
        NETWORK_FILE,
        "NetworkPolicy",
        "gis-agent-projection-recovery-worker-isolation",
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
    postgres = _resource(
        NETWORK_FILE,
        "NetworkPolicy",
        "postgres-from-projection-recovery-worker",
    )["spec"]
    assert postgres["ingress"][0]["from"] == [
        {
            "podSelector": {
                "matchLabels": {
                    "app.kubernetes.io/name": "gis-agent-projection-recovery-worker"
                }
            }
        }
    ]


def test_profile_renders_with_kustomize() -> None:
    completed = subprocess.run(
        ["kubectl", "kustomize", str(PROFILE)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "name: gis-agent-projection-recovery-worker" in completed.stdout
