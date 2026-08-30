from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "k8s/overlays/projection-recovery-sandbox"


def _documents(path: Path) -> list[dict]:
    return [
        document
        for document in yaml.safe_load_all(path.read_text(encoding="utf-8"))
        if document is not None
    ]


def test_overlay_is_opt_in_and_only_patches_recovery_worker() -> None:
    kustomization = yaml.safe_load(
        (OVERLAY / "kustomization.yaml").read_text(encoding="utf-8")
    )
    assert kustomization["resources"] == [
        "../../optional/projection-recovery-worker"
    ]
    assert kustomization["patches"][0]["path"] == "worker-enable-patch.yaml"
    patch = yaml.safe_load(
        (OVERLAY / "worker-enable-patch.yaml").read_text(encoding="utf-8")
    )
    assert patch["spec"]["replicas"] == 1
    assert patch["spec"]["template"]["metadata"]["annotations"] == {
        "gda.gisdataagent.io/enable-reason":
        "environment-approved-projection-recovery-sandbox"
    }


def test_overlay_has_no_secret_or_provider_credential_material() -> None:
    rendered_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in OVERLAY.iterdir()
        if path.suffix == ".yaml"
    )
    assert "kind: Secret" not in rendered_sources
    assert "AWS_SECRET_ACCESS_KEY" not in rendered_sources
    assert "POSTGRES_PASSWORD:" not in rendered_sources
    assert "replicas: 0" not in rendered_sources


def test_overlay_renders_worker_enabled_without_changing_profile_security() -> None:
    completed = subprocess.run(
        ["kubectl", "kustomize", str(OVERLAY)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    documents = [
        document
        for document in yaml.safe_load_all(completed.stdout)
        if document is not None
    ]
    deployment = next(
        document
        for document in documents
        if document["kind"] == "Deployment"
        and document["metadata"]["name"]
        == "gis-agent-projection-recovery-worker"
    )
    pod = deployment["spec"]["template"]["spec"]
    container = pod["containers"][0]
    assert deployment["spec"]["replicas"] == 1
    assert pod["automountServiceAccountToken"] is False
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["runAsUser"] == 10001
    assert "gis-agent-projection-recovery-admission" in completed.stdout
    assert "gis-agent-projection-recovery-runtime" in completed.stdout
