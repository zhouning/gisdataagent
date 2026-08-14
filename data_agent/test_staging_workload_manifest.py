import hashlib
import json
from pathlib import Path

import pytest
import yaml

from data_agent import (
    staging_platform_preflight,
    staging_platform_snapshot,
    staging_provenance_evidence,
    staging_registry_evidence,
    staging_release_evidence,
    staging_workload_manifest,
)

SOURCE_REPOSITORY = "zhouning/gisdataagent"
SOURCE_REVISION = "a" * 40
VERIFIER_REVISION = "9" * 40
LOCAL_IMAGE_ID = "sha256:" + "b" * 64
REPOSITORY = f"ghcr.io/{SOURCE_REPOSITORY}"
DIGEST = "sha256:" + "c" * 64
ENVIRONMENT_ACCESS = "1" * 64
CONFIG = "2" * 64
LIVE_CONFIG = "5" * 64
RUNTIME = "3" * 64


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


PLATFORM = _fingerprint(
    {"config": CONFIG, "environment_access": ENVIRONMENT_ACCESS, "runtime": RUNTIME}
)
LIVE_PLATFORM = _fingerprint(
    {
        "config": LIVE_CONFIG,
        "environment_access": ENVIRONMENT_ACCESS,
        "runtime": RUNTIME,
    }
)


def _candidate() -> dict:
    stable = {
        "schema": "gda.staging_candidate_evidence.v1",
        "source_revision": SOURCE_REVISION,
        "image_id": LOCAL_IMAGE_ID,
        "schema_fingerprint": "4" * 64,
        "platform_fingerprint": PLATFORM,
        "config_fingerprint": CONFIG,
        "environment_access_fingerprint": ENVIRONMENT_ACCESS,
        "runtime_fingerprint": RUNTIME,
        "tests": {"tests": 20, "failures": 0, "errors": 0, "skipped": 1},
        "candidate_validated": True,
        "errors": [],
    }
    return {
        **stable,
        "status": "candidate_validated",
        "staging_deployed": False,
        "live_cluster_verified": False,
        "registry_digest_verified": False,
        "production_promotion_allowed": False,
        "evidence_fingerprint": _fingerprint(stable),
    }


def _registry(candidate: dict) -> dict:
    return staging_registry_evidence.build_registry_evidence(
        candidate,
        source_revision=SOURCE_REVISION,
        local_image_id=LOCAL_IMAGE_ID,
        repository=REPOSITORY,
        digest=DIGEST,
        expected_repository=REPOSITORY,
    )


def _attestation() -> str:
    return json.dumps(
        [
            {
                "verificationResult": {
                    "statement": {
                        "predicateType": staging_provenance_evidence.PREDICATE_TYPE,
                        "subject": [
                            {
                                "name": REPOSITORY,
                                "digest": {"sha256": DIGEST.removeprefix("sha256:")},
                            }
                        ],
                    }
                }
            }
        ]
    )


def _evidence() -> tuple[dict, dict, dict, dict, dict]:
    candidate = _candidate()
    registry = _registry(candidate)
    provenance = staging_provenance_evidence.verify_registry_provenance(
        registry,
        source_repository=SOURCE_REPOSITORY,
        source_revision=SOURCE_REVISION,
        verifier_revision=VERIFIER_REVISION,
        run=lambda _: _attestation(),
    )
    release = staging_release_evidence.build_staging_release_evidence(
        candidate,
        registry,
        provenance,
        source_repository=SOURCE_REPOSITORY,
        source_revision=SOURCE_REVISION,
        verifier_revision=VERIFIER_REVISION,
    )
    assert release["staging_apply_allowed"] is True
    platform = {
        "schema": "gda.platform_truth.v1",
        "platform_fingerprint": LIVE_PLATFORM,
        "config": {
            "profile": "staging",
            "strict": True,
            "valid": True,
            "startup_allowed": True,
            "config_fingerprint": LIVE_CONFIG,
        },
        "environment_access": {
            "fingerprint": ENVIRONMENT_ACCESS,
            "matches_baseline": True,
            "parse_errors": [],
        },
        "runtime": {
            "status": "valid",
            "errors": [],
            "matches_primitive_baseline": True,
            "inventory_fingerprint": RUNTIME,
        },
    }
    return candidate, registry, provenance, release, platform


def test_renderer_emits_only_immutable_workload_resources():
    candidate, registry, provenance, release, platform = _evidence()
    documents = staging_workload_manifest.build_staging_workload_documents(
        candidate,
        registry,
        provenance,
        release,
        platform,
        source_repository=SOURCE_REPOSITORY,
        source_revision=SOURCE_REVISION,
        verifier_revision=VERIFIER_REVISION,
    )
    assert [(doc["kind"], doc["metadata"]["name"]) for doc in documents] == [
        ("ServiceAccount", "gis-agent-app"),
        ("ServiceAccount", "gis-agent-migrate"),
        (
            "Job",
            "gis-agent-migrate-"
            f"{SOURCE_REVISION[:8]}-{release['evidence_fingerprint'][:8]}",
        ),
        ("Deployment", "gis-agent-app"),
        ("Service", "gis-agent-app"),
    ]
    rendered = staging_workload_manifest.render_staging_workload_manifest(documents)
    parsed = list(yaml.safe_load_all(rendered))
    assert len(parsed) == 5
    assert all(document["kind"] != "Secret" for document in parsed)
    assert all(document["kind"] != "ConfigMap" for document in parsed)
    assert "StatefulSet" not in rendered
    assert "postgres" not in rendered
    assert "minio" not in rendered
    deployment = parsed[3]
    annotations = deployment["spec"]["template"]["metadata"]["annotations"]
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == f"{REPOSITORY}@{DIGEST}"
    assert annotations[staging_workload_manifest.ENVIRONMENT_ANNOTATION] == "staging"
    assert (
        annotations[staging_workload_manifest.PLATFORM_FINGERPRINT_ANNOTATION]
        == LIVE_PLATFORM
    )
    assert deployment["spec"]["template"]["spec"]["automountServiceAccountToken"] is False
    assert deployment["spec"]["template"]["spec"]["imagePullSecrets"] == [
        {"name": "gis-agent-staging-registry"}
    ]
    init = deployment["spec"]["template"]["spec"]["initContainers"][0]
    assert "data_agent.migration_runner status" in init["args"][0]
    assert init["env"] == [
        {"name": "POSTGRES_ADMIN_USER", "value": ""},
        {"name": "POSTGRES_ADMIN_PASSWORD", "value": ""},
    ]
    migration, application = (
        staging_workload_manifest.split_staging_workload_documents(documents)
    )
    assert [document["kind"] for document in migration] == [
        "ServiceAccount",
        "Job",
    ]
    assert [document["kind"] for document in application] == [
        "ServiceAccount",
        "Deployment",
        "Service",
    ]


def test_preflight_uses_release_image_without_api_token_or_schema_authority():
    candidate, registry, provenance, release, _ = _evidence()
    document = staging_platform_preflight.build_staging_platform_preflight(
        candidate,
        registry,
        provenance,
        release,
        source_repository=SOURCE_REPOSITORY,
        source_revision=SOURCE_REVISION,
        verifier_revision=VERIFIER_REVISION,
        observation_id="12345",
    )

    assert document["kind"] == "Job"
    assert document["metadata"]["namespace"] == "gis-agent-staging"
    assert document["spec"]["activeDeadlineSeconds"] == 1200
    pod = document["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["imagePullSecrets"] == [
        {"name": "gis-agent-staging-registry"}
    ]
    container = pod["containers"][0]
    assert container["image"] == f"{REPOSITORY}@{DIGEST}"
    assert container["command"] == ["/app/.venv/bin/python"]
    assert container["args"] == [
        "-m",
        "data_agent.staging_platform_snapshot",
        "--profile",
        "staging",
    ]
    assert container["env"][0] == {
        "name": "PYTHONWARNINGS",
        "value": "ignore::SyntaxWarning",
    }
    rendered = yaml.safe_dump(document)
    assert "migration_runner" not in rendered
    assert "POSTGRES_ADMIN_PASSWORD" in rendered
    assert "gis-agent-staging-secret" in rendered
    assert "value: ''" in rendered


def test_preflight_rejects_development_namespace():
    candidate, registry, provenance, release, _ = _evidence()
    with pytest.raises(
        staging_workload_manifest.StagingWorkloadManifestError,
        match="development namespace",
    ):
        staging_platform_preflight.build_staging_platform_preflight(
            candidate,
            registry,
            provenance,
            release,
            source_repository=SOURCE_REPOSITORY,
            source_revision=SOURCE_REVISION,
            verifier_revision=VERIFIER_REVISION,
            observation_id="12345",
            namespace="gis-agent",
        )


def test_compact_platform_snapshot_omits_inventory_and_config_entries():
    platform = _evidence()[-1]
    platform["config"]["entries"] = {"DATABASE_URL": "must-never-appear"}
    platform["environment_access"]["accesses"] = {
        "DATABASE_URL": ["must-never-appear.py"]
    }
    platform["runtime"]["inventory"] = ["must-never-appear"]
    platform["runtime"]["errors"] = []
    compact = staging_platform_snapshot.project_staging_platform_snapshot(
        platform
    )

    assert staging_platform_snapshot.staging_platform_snapshot_valid(compact)
    rendered = json.dumps(compact)
    assert "entries" not in rendered
    assert "accesses" not in rendered
    assert '"inventory":' not in rendered
    assert "must-never-appear" not in rendered


def test_renderer_rejects_development_namespace():
    evidence = _evidence()
    with pytest.raises(
        staging_workload_manifest.StagingWorkloadManifestError,
        match="development namespace",
    ):
        staging_workload_manifest.build_staging_workload_documents(
            *evidence,
            source_repository=SOURCE_REPOSITORY,
            source_revision=SOURCE_REVISION,
            verifier_revision=VERIFIER_REVISION,
            namespace="gis-agent",
        )


def test_renderer_rejects_live_platform_drift_before_manifest_output():
    candidate, registry, provenance, release, platform = _evidence()
    platform["config"]["config_fingerprint"] = "8" * 64
    with pytest.raises(staging_workload_manifest.StagingWorkloadManifestError) as exc:
        staging_workload_manifest.build_staging_workload_documents(
            candidate,
            registry,
            provenance,
            release,
            platform,
            source_repository=SOURCE_REPOSITORY,
            source_revision=SOURCE_REVISION,
            verifier_revision=VERIFIER_REVISION,
        )
    assert "platform fingerprint does not match" in str(exc.value)


def test_renderer_rejects_release_digest_drift_before_manifest_output():
    candidate, registry, provenance, release, platform = _evidence()
    release["image"] = f"{REPOSITORY}@sha256:{'8' * 64}"
    with pytest.raises(staging_workload_manifest.StagingWorkloadManifestError):
        staging_workload_manifest.build_staging_workload_documents(
            candidate,
            registry,
            provenance,
            release,
            platform,
            source_repository=SOURCE_REPOSITORY,
            source_revision=SOURCE_REVISION,
            verifier_revision=VERIFIER_REVISION,
        )


def test_cli_blocks_without_writing_manifest(tmp_path: Path, capsys):
    candidate, registry, provenance, release, platform = _evidence()
    inputs = {
        "candidate": candidate,
        "registry": registry,
        "provenance": provenance,
        "release": release,
        "platform": platform,
    }
    paths = {}
    for name, value in inputs.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        paths[name] = path
    output = tmp_path / "manifest.yaml"
    release["staging_apply_allowed"] = False
    paths["release"].write_text(json.dumps(release), encoding="utf-8")
    result = staging_workload_manifest.main(
        [
            "--candidate-evidence",
            str(paths["candidate"]),
            "--registry-evidence",
            str(paths["registry"]),
            "--provenance-evidence",
            str(paths["provenance"]),
            "--release-evidence",
            str(paths["release"]),
            "--platform-snapshot",
            str(paths["platform"]),
            "--source-repository",
            SOURCE_REPOSITORY,
            "--source-revision",
            SOURCE_REVISION,
            "--verifier-revision",
            VERIFIER_REVISION,
            "--output",
            str(output),
        ]
    )
    assert result == 1
    assert not output.exists()
    assert json.loads(capsys.readouterr().out)["manifest_rendered"] is False
