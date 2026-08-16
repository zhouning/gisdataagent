import copy
import hashlib
import json
from datetime import UTC, datetime

import yaml

from data_agent.dolphinscheduler_worker_activation import (
    SECRET_ATTESTATION_SCHEMA,
    build_activation_report,
)
from data_agent.dolphinscheduler_worker_activation_admission import (
    build_activation_admission,
    build_readiness_artifact_report,
    build_readiness_run_report,
)
from data_agent.dolphinscheduler_worker_deployment import (
    CONFIG_NAME,
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

NOW = datetime(2026, 8, 15, 8, 0, tzinfo=UTC)
RUN_ID = 31880000000
SOURCE_REPOSITORY = "zhouning/gisdataagent"
SOURCE_REVISION = "b" * 40
NAMESPACE = "gis-agent-staging"
CLUSTER_UID = "00000000-0000-4000-8000-000000000301"
NAMESPACE_UID = "00000000-0000-4000-8000-000000000302"
IMAGE_DIGEST = "sha256:" + "c" * 64
IMAGE = f"ghcr.io/zhouning/gisdataagent@{IMAGE_DIGEST}"


def _release() -> dict:
    release = {
        "schema": RELEASE_EVIDENCE_SCHEMA,
        "source_revision": "a" * 40,
        "verifier_revision": "a" * 40,
        "candidate_evidence_fingerprint": "1" * 64,
        "registry_evidence_fingerprint": "2" * 64,
        "provenance_evidence_fingerprint": "3" * 64,
        "repository": "ghcr.io/zhouning/gisdataagent",
        "digest": IMAGE_DIGEST,
        "image": IMAGE,
        "schema_fingerprint": "4" * 64,
        "platform_fingerprint": "5" * 64,
        "config_fingerprint": "6" * 64,
        "environment_access_fingerprint": "7" * 64,
        "runtime_fingerprint": "8" * 64,
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


def _run() -> dict:
    return {
        "id": RUN_ID,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "head_branch": "main",
        "head_sha": SOURCE_REVISION,
        "path": ".github/workflows/verify-staging-dolphinscheduler-worker.yml",
        "repository": {"full_name": SOURCE_REPOSITORY},
        "head_repository": {"full_name": SOURCE_REPOSITORY},
    }


def _artifact_payload() -> dict:
    return {
        "total_count": 1,
        "artifacts": [
            {
                "id": 9200000000,
                "name": f"staging-dolphinscheduler-worker-readiness-{RUN_ID}",
                "size_in_bytes": 4096,
                "expired": False,
                "digest": "sha256:" + "d" * 64,
                "workflow_run": {
                    "id": RUN_ID,
                    "head_branch": "main",
                    "head_sha": SOURCE_REVISION,
                },
            }
        ],
    }


def _write_evidence(tmp_path):
    release = _release()
    documents, manifest_report = render_activation_manifest(
        release,
        namespace=NAMESPACE,
        image_pull_secret_name="ghcr-staging-pull",
    )
    manifest = tmp_path / "activation-manifest.yaml"
    manifest.write_text(
        yaml.safe_dump_all(documents, sort_keys=False),
        encoding="utf-8",
    )
    manifest_report["manifest_sha256"] = hashlib.sha256(
        manifest.read_bytes()
    ).hexdigest()

    config = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": CONFIG_NAME,
            "namespace": NAMESPACE,
            "uid": "00000000-0000-4000-8000-000000000303",
            "resourceVersion": "41001",
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
        "resource_uid": "00000000-0000-4000-8000-000000000304",
        "resource_version": "41002",
        "observed_at": NOW.isoformat(),
    }
    attestation_path = tmp_path / "secret-attestation.json"
    attestation_path.write_text(json.dumps(attestation), encoding="utf-8")
    activation = build_activation_report(
        manifest,
        config_path,
        attestation_path,
        environment="staging",
        expected_namespace=NAMESPACE,
        now=NOW,
    )
    readiness = build_readiness_report(
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
    return release, activation, readiness, manifest_report, manifest


def _admit(tmp_path, *, evidence=None, **overrides):
    release, activation, readiness, manifest_report, manifest = (
        evidence or _write_evidence(tmp_path)
    )
    values = {
        "run": _run(),
        "artifact": _artifact_payload()["artifacts"][0],
        "activation": activation,
        "readiness": readiness,
        "release": release,
        "manifest_report": manifest_report,
        "manifest_path": manifest,
        "expected_run_id": RUN_ID,
        "source_repository": SOURCE_REPOSITORY,
        "expected_namespace": NAMESPACE,
        "expected_cluster_uid": CLUSTER_UID,
        "expected_namespace_uid": NAMESPACE_UID,
    }
    values.update(overrides)
    return build_activation_admission(**values)


def test_run_and_artifact_reports_bind_protected_successful_readiness_run():
    run_report = build_readiness_run_report(
        _run(),
        expected_run_id=RUN_ID,
        source_repository=SOURCE_REPOSITORY,
    )
    artifact_report = build_readiness_artifact_report(
        _artifact_payload(),
        run_report=run_report,
    )

    assert run_report["status"] == "valid"
    assert run_report["source_revision"] == SOURCE_REVISION
    assert artifact_report["status"] == "valid"
    assert artifact_report["artifact_id"] == 9200000000
    assert artifact_report["artifact_digest"] == "sha256:" + "d" * 64


def test_run_report_rejects_wrong_workflow_or_unsuccessful_run():
    run = _run()
    run["path"] = ".github/workflows/ci.yml"
    run["conclusion"] = "failure"

    report = build_readiness_run_report(
        run,
        expected_run_id=RUN_ID,
        source_repository=SOURCE_REPOSITORY,
    )

    assert report["status"] == "invalid"
    assert "readiness run workflow path is not protected" in report["errors"]
    assert "readiness run conclusion must be success" in report["errors"]


def test_artifact_report_rejects_digest_or_run_identity_drift():
    payload = _artifact_payload()
    artifact = payload["artifacts"][0]
    artifact["digest"] = "sha512:not-allowed"
    artifact["workflow_run"]["head_sha"] = "e" * 40

    report = build_readiness_artifact_report(
        payload,
        run_report=build_readiness_run_report(
            _run(),
            expected_run_id=RUN_ID,
            source_repository=SOURCE_REPOSITORY,
        ),
    )

    assert report["status"] == "invalid"
    assert "readiness artifact digest is invalid" in report["errors"]
    assert "readiness artifact source revision does not match the run" in report[
        "errors"
    ]


def test_activation_admission_allows_only_exact_single_replica_artifact(tmp_path):
    report = _admit(tmp_path)

    assert report["status"] == "authorized_for_single_replica_apply"
    assert report["single_replica_apply_allowed"] is True
    assert report["requested_replicas"] == 1
    assert report["deployed"] is False
    assert report["automatic_scale_allowed"] is False
    assert report["production_promotion_allowed"] is False
    assert report["errors"] == []
    assert len(report["evidence_fingerprint"]) == 64


def test_activation_admission_rejects_manifest_content_drift(tmp_path):
    release, activation, readiness, manifest_report, manifest = _write_evidence(
        tmp_path
    )
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    report = _admit(
        tmp_path,
        evidence=(release, activation, readiness, manifest_report, manifest),
    )

    assert report["single_replica_apply_allowed"] is False
    assert "activation manifest digest does not match its report" in report["errors"]


def test_activation_admission_rejects_secret_and_second_replica(tmp_path):
    release, activation, readiness, manifest_report, manifest = _write_evidence(
        tmp_path
    )
    documents = list(yaml.safe_load_all(manifest.read_text(encoding="utf-8")))
    deployment = next(
        value for value in documents if value.get("kind") == "Deployment"
    )
    deployment["spec"]["replicas"] = 2
    documents.append(
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": SECRET_NAME, "namespace": NAMESPACE},
        }
    )
    manifest.write_text(
        yaml.safe_dump_all(documents, sort_keys=False),
        encoding="utf-8",
    )
    manifest_report["manifest_sha256"] = hashlib.sha256(
        manifest.read_bytes()
    ).hexdigest()

    report = _admit(
        tmp_path,
        evidence=(release, activation, readiness, manifest_report, manifest),
    )

    assert report["single_replica_apply_allowed"] is False
    assert "activation manifest resources are not exactly allowlisted" in report[
        "errors"
    ]
    assert any("exactly 1 replica" in error for error in report["errors"])


def test_activation_admission_rejects_mutable_or_wrong_release_image(tmp_path):
    release, activation, readiness, manifest_report, manifest = _write_evidence(
        tmp_path
    )
    documents = list(yaml.safe_load_all(manifest.read_text(encoding="utf-8")))
    deployment = next(
        value for value in documents if value.get("kind") == "Deployment"
    )
    deployment["spec"]["template"]["spec"]["containers"][0]["image"] = (
        "ghcr.io/zhouning/gisdataagent:latest"
    )
    manifest.write_text(
        yaml.safe_dump_all(documents, sort_keys=False),
        encoding="utf-8",
    )
    manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()
    manifest_report["manifest_sha256"] = manifest_sha256
    activation["files"]["manifest"]["sha256"] = manifest_sha256

    report = _admit(
        tmp_path,
        evidence=(release, activation, readiness, manifest_report, manifest),
    )

    assert report["single_replica_apply_allowed"] is False
    assert "activation manifest images must use immutable sha256 digests" in report[
        "errors"
    ]
    assert "activation manifest images do not match the admitted release" in report[
        "errors"
    ]


def test_activation_admission_rejects_already_deployed_readiness(tmp_path):
    release, activation, readiness, manifest_report, manifest = _write_evidence(
        tmp_path
    )
    readiness = copy.deepcopy(readiness)
    readiness["status"] = "live_ready"
    readiness["deployed"] = True

    report = _admit(
        tmp_path,
        evidence=(release, activation, readiness, manifest_report, manifest),
    )

    assert report["single_replica_apply_allowed"] is False
    assert "readiness status must be ready_for_activation" in report["errors"]
    assert "readiness must prove the worker is not deployed" in report["errors"]


def test_activation_admission_rejects_different_protected_cluster(tmp_path):
    report = _admit(
        tmp_path,
        expected_cluster_uid="00000000-0000-4000-8000-000000000399",
        expected_namespace_uid="00000000-0000-4000-8000-000000000398",
    )

    assert report["single_replica_apply_allowed"] is False
    assert "readiness cluster UID does not match protected staging" in report["errors"]
    assert "readiness namespace UID does not match protected staging" in report[
        "errors"
    ]
