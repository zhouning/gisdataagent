import copy
import json
from datetime import UTC, datetime

import yaml

from data_agent.dolphinscheduler_worker_activation import (
    SECRET_ATTESTATION_SCHEMA,
    build_activation_report,
)
from data_agent.dolphinscheduler_worker_deployment import (
    CONFIG_NAME,
    DEPLOYMENT_NAME,
    SECRET_NAME,
)
from data_agent.dolphinscheduler_worker_staging import (
    build_readiness_report,
    render_activation_manifest,
)
from data_agent.staging_release_evidence import (
    RELEASE_EVIDENCE_SCHEMA,
    release_evidence_fingerprint,
)

NOW = datetime(2026, 8, 15, 4, 0, tzinfo=UTC)
NAMESPACE = "gis-agent-staging"
IMAGE_DIGEST = "sha256:" + "4" * 64
IMAGE = f"ghcr.io/zhouning/gisdataagent@{IMAGE_DIGEST}"
CLUSTER_UID = "00000000-0000-4000-8000-000000000201"
NAMESPACE_UID = "00000000-0000-4000-8000-000000000202"
DEPLOYMENT_UID = "00000000-0000-4000-8000-000000000203"
POD_UID = "00000000-0000-4000-8000-000000000204"


def _release() -> dict:
    release = {
        "schema": RELEASE_EVIDENCE_SCHEMA,
        "source_revision": "5" * 40,
        "verifier_revision": "5" * 40,
        "candidate_evidence_fingerprint": "1" * 64,
        "registry_evidence_fingerprint": "2" * 64,
        "provenance_evidence_fingerprint": "3" * 64,
        "repository": "ghcr.io/zhouning/gisdataagent",
        "digest": IMAGE_DIGEST,
        "image": IMAGE,
        "schema_fingerprint": "6" * 64,
        "platform_fingerprint": "7" * 64,
        "config_fingerprint": "8" * 64,
        "environment_access_fingerprint": "9" * 64,
        "runtime_fingerprint": "a" * 64,
        "staging_apply_allowed": True,
        "errors": [],
        "status": "staging_release_admitted",
        "registry_digest_verified": True,
        "provenance_attestation_verified": True,
        "staging_deployed": False,
        "live_cluster_verified": False,
        "golden_slice_verified": False,
        "promotion_authority_verified": False,
        "production_promotion_allowed": False,
    }
    release["evidence_fingerprint"] = release_evidence_fingerprint(release)
    return release


def _activation(tmp_path, documents: list[dict]) -> dict:
    manifest = tmp_path / "worker-staging.yaml"
    manifest.write_text(
        yaml.safe_dump_all(documents, sort_keys=False),
        encoding="utf-8",
    )
    config = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": CONFIG_NAME,
            "namespace": NAMESPACE,
            "uid": "00000000-0000-4000-8000-000000000205",
            "resourceVersion": "31001",
        },
        "data": {
            "base-url": "https://dolphinscheduler.staging.example.com/dolphinscheduler",
            "project-code": "1001",
            "workload-subject": "workload:dataops-adapter-staging",
            "policy-evaluator-subject": "workload:policy-evaluator-staging",
            "command-tenant-id": "tenant-staging",
            "provider-tenant-code": "default",
            "provider-worker-group": "default",
        },
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    attestation = {
        "schema": SECRET_ATTESTATION_SCHEMA,
        "environment": "staging",
        "namespace": NAMESPACE,
        "secret_name": SECRET_NAME,
        "keys": ["access-token", "database-url"],
        "resource_uid": "00000000-0000-4000-8000-000000000206",
        "resource_version": "31002",
        "observed_at": NOW.isoformat(),
    }
    attestation_path = tmp_path / "secret-attestation.json"
    attestation_path.write_text(json.dumps(attestation), encoding="utf-8")
    return build_activation_report(
        manifest,
        config_path,
        attestation_path,
        environment="staging",
        expected_namespace=NAMESPACE,
        now=NOW,
    )


def test_rendered_activation_manifest_is_release_bound_and_secret_free(tmp_path):
    release = _release()

    documents, report = render_activation_manifest(
        release,
        namespace=NAMESPACE,
        image_pull_secret_name="ghcr-staging-pull",
    )

    assert report["status"] == "rendered"
    assert report["automatic_scale_allowed"] is False
    assert report["production_promotion_allowed"] is False
    assert {document["kind"] for document in documents} == {
        "Deployment",
        "ServiceAccount",
        "NetworkPolicy",
    }
    assert all(document["metadata"]["namespace"] == NAMESPACE for document in documents)
    deployment = next(
        document for document in documents if document["kind"] == "Deployment"
    )
    pod = deployment["spec"]["template"]["spec"]
    assert deployment["spec"]["replicas"] == 1
    assert pod["imagePullSecrets"] == [{"name": "ghcr-staging-pull"}]
    assert {container["image"] for container in [*pod["containers"], *pod["initContainers"]]} == {
        IMAGE
    }
    assert not any(document["kind"] in {"ConfigMap", "Secret"} for document in documents)

    activation = _activation(tmp_path, documents)
    assert activation["activation_ready"] is True
    assert activation["image_digest"] == IMAGE


def test_readiness_reports_ready_without_scaling_when_worker_is_absent(tmp_path):
    release = _release()
    documents, _ = render_activation_manifest(
        release,
        namespace=NAMESPACE,
        image_pull_secret_name="ghcr-staging-pull",
    )
    activation = _activation(tmp_path, documents)

    report = build_readiness_report(
        activation,
        release,
        {},
        {"items": []},
        {},
        expected_namespace=NAMESPACE,
        expected_cluster_uid=CLUSTER_UID,
        expected_namespace_uid=NAMESPACE_UID,
        observed_cluster_uid=CLUSTER_UID,
        observed_namespace_uid=NAMESPACE_UID,
        now=NOW,
    )

    assert report["status"] == "ready_for_activation"
    assert report["activation_ready"] is True
    assert report["deployed"] is False
    assert report["live_cluster_verified"] is True
    assert report["live_worker_verified"] is False
    assert report["automatic_scale_allowed"] is False
    assert report["production_promotion_allowed"] is False
    assert report["live_errors"] == ["worker Deployment is not present"]


def test_readiness_verifies_one_release_bound_healthy_worker(tmp_path):
    release = _release()
    documents, _ = render_activation_manifest(
        release,
        namespace=NAMESPACE,
        image_pull_secret_name="ghcr-staging-pull",
    )
    activation = _activation(tmp_path, documents)
    deployment = copy.deepcopy(
        next(document for document in documents if document["kind"] == "Deployment")
    )
    deployment["metadata"].update({"uid": DEPLOYMENT_UID, "generation": 4})
    deployment["status"] = {
        "observedGeneration": 4,
        "replicas": 1,
        "updatedReplicas": 1,
        "readyReplicas": 1,
        "availableReplicas": 1,
    }
    pods = {
        "items": [
            {
                "metadata": {
                    "uid": POD_UID,
                    "namespace": NAMESPACE,
                    "labels": {
                        "app.kubernetes.io/name": DEPLOYMENT_NAME,
                    },
                },
                "spec": {"containers": [{"name": "worker", "image": IMAGE}]},
                "status": {
                    "phase": "Running",
                    "containerStatuses": [
                        {
                            "name": "worker",
                            "ready": True,
                            "restartCount": 0,
                            "imageID": f"docker-pullable://{IMAGE}",
                        }
                    ],
                },
            }
        ]
    }
    health = {
        "status": "healthy",
        "worker_id": f"worker:dolphinscheduler:{POD_UID}",
        "cycles": 3,
        "failed_commands": 0,
    }

    report = build_readiness_report(
        activation,
        release,
        deployment,
        pods,
        health,
        expected_namespace=NAMESPACE,
        expected_cluster_uid=CLUSTER_UID,
        expected_namespace_uid=NAMESPACE_UID,
        observed_cluster_uid=CLUSTER_UID,
        observed_namespace_uid=NAMESPACE_UID,
        now=NOW,
    )

    assert report["status"] == "live_ready"
    assert report["deployed"] is True
    assert report["live_worker_verified"] is True
    assert report["observation"]["worker_ids"] == [
        f"worker:dolphinscheduler:{POD_UID}"
    ]
    assert report["observation"]["restart_counts"] == [0]
    assert report["errors"] == []
    assert report["live_errors"] == []


def test_readiness_blocks_unsafe_live_replica_count(tmp_path):
    release = _release()
    documents, _ = render_activation_manifest(
        release,
        namespace=NAMESPACE,
        image_pull_secret_name="ghcr-staging-pull",
    )
    activation = _activation(tmp_path, documents)
    deployment = copy.deepcopy(
        next(document for document in documents if document["kind"] == "Deployment")
    )
    deployment["metadata"]["uid"] = DEPLOYMENT_UID
    deployment["spec"]["replicas"] = 2

    report = build_readiness_report(
        activation,
        release,
        deployment,
        {"items": []},
        {},
        expected_namespace=NAMESPACE,
        expected_cluster_uid=CLUSTER_UID,
        expected_namespace_uid=NAMESPACE_UID,
        observed_cluster_uid=CLUSTER_UID,
        observed_namespace_uid=NAMESPACE_UID,
        now=NOW,
    )

    assert report["status"] == "blocked"
    assert report["activation_ready"] is False
    assert "live worker Deployment must have zero or one replica" in report["live_errors"]
    assert report["production_promotion_allowed"] is False
