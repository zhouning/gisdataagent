import hashlib
import json
from pathlib import Path

import yaml

from data_agent import staging_deployment_bundle

ROOT = Path(__file__).resolve().parents[1]
SOURCE_REVISION = "a" * 40
IMAGE = "ghcr.io/zhouning/gisdataagent@sha256:" + "b" * 64
CONFIG_FINGERPRINT = "c" * 64
RUNTIME_FINGERPRINT = "d" * 64


def _fingerprint(value: object) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


PLATFORM_FINGERPRINT = _fingerprint(
    {"config": CONFIG_FINGERPRINT, "runtime": RUNTIME_FINGERPRINT}
)


def _candidate() -> dict:
    stable = {
        "schema": "gda.staging_candidate_evidence.v1",
        "source_revision": SOURCE_REVISION,
        "image_id": "sha256:" + "e" * 64,
        "schema_fingerprint": "f" * 64,
        "config_fingerprint": "1" * 64,
        "runtime_fingerprint": RUNTIME_FINGERPRINT,
        "tests": {"tests": 42, "failures": 0, "errors": 0, "skipped": 1},
        "candidate_validated": True,
        "errors": [],
    }
    return {
        **stable,
        "status": "candidate_validated",
        "evidence_fingerprint": _fingerprint(stable),
    }


def _platform() -> dict:
    return {
        "schema": "gda.platform_truth.v1",
        "platform_fingerprint": PLATFORM_FINGERPRINT,
        "config": {
            "profile": "staging",
            "strict": True,
            "valid": True,
            "startup_allowed": True,
            "config_fingerprint": CONFIG_FINGERPRINT,
        },
        "runtime": {
            "status": "valid",
            "errors": [],
            "matches_primitive_baseline": True,
            "inventory_fingerprint": RUNTIME_FINGERPRINT,
        },
    }


def _pod_resource(kind: str, name: str, containers: list[dict], init: list[dict]):
    return {
        "apiVersion": "batch/v1" if kind == "Job" else "apps/v1",
        "kind": kind,
        "metadata": {"name": name, "namespace": "gis-agent"},
        "spec": {
            **({"replicas": 1} if kind == "Deployment" else {}),
            "template": {
                "metadata": {"annotations": {}},
                "spec": {
                    "automountServiceAccountToken": True,
                    "containers": containers,
                    "initContainers": init,
                },
            },
        },
    }


def _template() -> list[dict]:
    return [
        {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": "gis-agent"},
        },
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "gis-agent-config", "namespace": "gis-agent"},
            "data": {
                "GDA_DEPLOYMENT_PROFILE": "staging",
                "GDA_CONFIG_STRICT": "true",
                "OLLAMA_API_BASE": "https://models.staging.example.com",
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "must-not-leak", "namespace": "gis-agent"},
            "stringData": {"PASSWORD": "unsafe"},
        },
        _pod_resource(
            "Deployment",
            "gis-agent-app",
            [{"name": "app", "image": "gis-data-agent:latest"}],
            [
                {
                    "name": "wait-for-migrate",
                    "image": "gis-data-agent:latest",
                    "command": [
                        "python",
                        "-m",
                        "data_agent.migration_runner",
                        "status",
                    ],
                }
            ],
        ),
        _pod_resource(
            "Deployment",
            "gis-agent-outbox-worker",
            [{"name": "worker", "image": "gis-data-agent:latest"}],
            [
                {
                    "name": "wait-for-migrate",
                    "image": "gis-data-agent:latest",
                    "command": [
                        "python",
                        "-m",
                        "data_agent.migration_runner",
                        "status",
                    ],
                }
            ],
        ),
        _pod_resource(
            "Deployment",
            "gis-agent-dolphinscheduler-command-worker",
            [{"name": "worker", "image": "gis-data-agent:latest"}],
            [
                {
                    "name": "prepare-provider-token",
                    "image": "gis-data-agent:latest",
                }
            ],
        ),
        _pod_resource(
            "Job",
            "gis-agent-migrate",
            [{"name": "migrate", "image": "gis-data-agent:latest"}],
            [],
        ),
        {
            "apiVersion": "autoscaling/v2",
            "kind": "HorizontalPodAutoscaler",
            "metadata": {
                "name": "gis-agent-app-hpa",
                "namespace": "gis-agent",
            },
            "spec": {"minReplicas": 1, "maxReplicas": 1},
        },
    ]


def _resource(documents: list[dict], kind: str, name: str) -> dict:
    return next(
        item
        for item in documents
        if item.get("kind") == kind
        and (item.get("metadata") or {}).get("name") == name
    )


def test_build_staging_bundle_binds_release_and_never_claims_deployment():
    documents, report = staging_deployment_bundle.build_staging_bundle(
        _template(), _candidate(), _platform(), image=IMAGE
    )

    assert report["status"] == "ready_for_staging_apply"
    assert report["bundle_ready"] is True
    assert report["registry_digest_declared"] is True
    assert report["registry_digest_verified"] is False
    assert report["staging_deployed"] is False
    assert report["live_cluster_verified"] is False
    assert report["production_promotion_allowed"] is False
    assert report["removed_secret_names"] == ["must-not-leak"]
    assert not any(item.get("kind") == "Secret" for item in documents)

    for kind, name in staging_deployment_bundle.RELEASE_WORKLOADS:
        workload = _resource(documents, kind, name)
        pod = workload["spec"]["template"]
        assert pod["spec"]["automountServiceAccountToken"] is False
        assert pod["metadata"]["annotations"] == {
            "org.opencontainers.image.revision": SOURCE_REVISION,
            "gisdataagent.io/candidate-evidence-fingerprint": _candidate()[
                "evidence_fingerprint"
            ],
            "gisdataagent.io/environment": "staging",
            "gisdataagent.io/platform-fingerprint": PLATFORM_FINGERPRINT,
        }

    for kind, name, section, container_name in (
        staging_deployment_bundle.IMAGE_CONSUMERS
    ):
        workload = _resource(documents, kind, name)
        containers = workload["spec"]["template"]["spec"][section]
        container = next(item for item in containers if item["name"] == container_name)
        assert container["image"] == IMAGE


def test_bundle_blocks_mutated_candidate_tagged_image_and_unsafe_template():
    candidate = _candidate()
    candidate["source_revision"] = "9" * 40
    template = _template()
    app = _resource(template, "Deployment", "gis-agent-app")
    app["spec"]["replicas"] = 2
    app["metadata"]["namespace"] = "wrong-namespace"
    app["spec"]["template"]["spec"]["containers"].append(
        {"name": "unsafe-sidecar", "image": "busybox:latest"}
    )
    app["spec"]["template"]["spec"]["initContainers"][0]["command"] = [
        "kubectl",
        "wait",
    ]
    app["spec"]["template"]["spec"]["volumes"] = [
        {"name": "unsafe", "hostPath": {"path": "/tmp"}}
    ]
    config = _resource(template, "ConfigMap", "gis-agent-config")
    config["data"]["GDA_CONFIG_STRICT"] = "false"
    config["data"]["DATABASE_URL"] = "postgresql://unsafe:inline@postgres/db"
    config["data"]["OLLAMA_API_BASE"] = "http://ollama:11434"

    _, report = staging_deployment_bundle.build_staging_bundle(
        template,
        candidate,
        _platform(),
        image="ghcr.io/zhouning/gisdataagent:latest",
    )

    rendered = "\n".join(report["errors"])
    assert report["status"] == "blocked"
    assert report["bundle_ready"] is False
    assert "candidate evidence fingerprint does not match" in rendered
    assert "immutable registry digest" in rendered
    assert "strict mode must be true" in rendered
    assert "sensitive keys: DATABASE_URL" in rendered
    assert "non-local HTTPS model endpoint" in rendered
    assert "exactly one replica" in rendered
    assert "must be in the gis-agent namespace" in rendered
    assert "must read schema readiness from the ledger" in rendered
    assert "container unsafe-sidecar must use an immutable image digest" in rendered
    assert "must not use hostPath" in rendered


def test_bundle_cli_writes_manifest_only_when_ready(tmp_path: Path, capsys):
    template_path = tmp_path / "template.yaml"
    candidate_path = tmp_path / "candidate.json"
    platform_path = tmp_path / "platform.json"
    manifest_path = tmp_path / "bundle.yaml"
    report_path = tmp_path / "report.json"
    template_path.write_text(
        yaml.safe_dump_all(_template(), sort_keys=False), encoding="utf-8"
    )
    candidate_path.write_text(json.dumps(_candidate()), encoding="utf-8")
    platform_path.write_text(json.dumps(_platform()), encoding="utf-8")

    result = staging_deployment_bundle.main(
        [
            "build",
            "--template-manifest",
            str(template_path),
            "--candidate-evidence",
            str(candidate_path),
            "--platform-snapshot",
            str(platform_path),
            "--image",
            IMAGE,
            "--manifest-output",
            str(manifest_path),
            "--report-output",
            str(report_path),
        ]
    )

    assert result == 0
    assert manifest_path.exists()
    assert json.loads(report_path.read_text())["bundle_ready"] is True
    assert json.loads(capsys.readouterr().out)["staging_deployed"] is False

    blocked_manifest = tmp_path / "blocked.yaml"
    result = staging_deployment_bundle.main(
        [
            "build",
            "--template-manifest",
            str(template_path),
            "--candidate-evidence",
            str(candidate_path),
            "--platform-snapshot",
            str(platform_path),
            "--image",
            "gis-data-agent:latest",
            "--manifest-output",
            str(blocked_manifest),
        ]
    )
    assert result == 1
    assert not blocked_manifest.exists()


def test_public_staging_overlay_is_secret_free_and_single_replica():
    overlay = yaml.safe_load(
        (ROOT / "k8s/overlays/staging/kustomization.yaml").read_text(
            encoding="utf-8"
        )
    )
    targets = {
        (patch["target"]["kind"], patch["target"]["name"]): patch["patch"]
        for patch in overlay["patches"]
    }

    assert overlay["resources"] == ["../../base"]
    assert "$patch: delete" in targets[("Secret", "gis-agent-secret")]
    assert "$patch: delete" in targets[("Secret", "minio-root")]
    assert "$patch: delete" in targets[("Ingress", "gis-agent-ingress")]
    assert "$patch: delete" in targets[("Service", "ollama")]
    config_patch = yaml.safe_load(targets[("ConfigMap", "gis-agent-config")])
    assert config_patch["data"] == {
        "GDA_DEPLOYMENT_PROFILE": "staging",
        "GDA_CONFIG_STRICT": "true",
    }
    hpa_patch = yaml.safe_load(
        targets[("HorizontalPodAutoscaler", "gis-agent-app-hpa")]
    )
    assert {operation["value"] for operation in hpa_patch} == {1}
