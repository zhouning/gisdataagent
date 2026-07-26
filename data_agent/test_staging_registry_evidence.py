import hashlib
import json
from pathlib import Path

import yaml

from data_agent import staging_registry_evidence

ROOT = Path(__file__).resolve().parents[1]
SOURCE_REVISION = "a" * 40
LOCAL_IMAGE_ID = "sha256:" + "b" * 64
REPOSITORY = "ghcr.io/zhouning/gisdataagent"
DIGEST = "sha256:" + "c" * 64


def _fingerprint(value: object) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def _candidate() -> dict:
    stable = {
        "schema": "gda.staging_candidate_evidence.v1",
        "source_revision": SOURCE_REVISION,
        "image_id": LOCAL_IMAGE_ID,
        "schema_fingerprint": "d" * 64,
        "config_fingerprint": "e" * 64,
        "runtime_fingerprint": "f" * 64,
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


def test_registry_binding_never_self_verifies_provenance_or_deployment():
    report = staging_registry_evidence.build_registry_evidence(
        _candidate(),
        source_revision=SOURCE_REVISION,
        local_image_id=LOCAL_IMAGE_ID,
        repository=REPOSITORY,
        digest=DIGEST,
        expected_repository=REPOSITORY,
    )

    assert report["status"] == "registry_subject_bound"
    assert report["registry_subject_bound"] is True
    assert report["registry_push_observed"] is True
    assert report["image"] == f"{REPOSITORY}@{DIGEST}"
    assert report["provenance_attestation_verified"] is False
    assert report["registry_digest_verified"] is False
    assert report["staging_deployed"] is False
    assert report["live_cluster_verified"] is False
    assert report["production_promotion_allowed"] is False
    assert len(report["required_provenance"]) == 3


def test_registry_binding_blocks_candidate_repository_and_digest_drift():
    candidate = _candidate()
    candidate["source_revision"] = "9" * 40
    report = staging_registry_evidence.build_registry_evidence(
        candidate,
        source_revision=SOURCE_REVISION,
        local_image_id="sha256:" + "1" * 64,
        repository="ghcr.io/other/repository",
        digest="latest",
        expected_repository=REPOSITORY,
    )

    rendered = "\n".join(report["errors"])
    assert report["status"] == "blocked"
    assert report["registry_subject_bound"] is False
    assert "candidate evidence fingerprint does not match" in rendered
    assert "source revision does not match" in rendered
    assert "local image ID does not match" in rendered
    assert "repository does not match" in rendered
    assert "digest must be sha256" in rendered
    assert report["production_promotion_allowed"] is False


def test_registry_evidence_cli_is_machine_readable(tmp_path: Path, capsys):
    candidate = tmp_path / "candidate.json"
    output = tmp_path / "registry.json"
    candidate.write_text(json.dumps(_candidate()), encoding="utf-8")

    result = staging_registry_evidence.main(
        [
            "validate",
            "--candidate-evidence",
            str(candidate),
            "--source-revision",
            SOURCE_REVISION,
            "--local-image-id",
            LOCAL_IMAGE_ID,
            "--repository",
            REPOSITORY,
            "--digest",
            DIGEST,
            "--expected-repository",
            REPOSITORY,
            "--output",
            str(output),
        ]
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert result == 0
    assert report["registry_subject_bound"] is True
    assert json.loads(capsys.readouterr().out) == report


def test_registry_evidence_cli_fails_closed_on_invalid_candidate(
    tmp_path: Path, capsys
):
    candidate = tmp_path / "candidate.json"
    output = tmp_path / "registry.json"
    candidate.write_text("[]", encoding="utf-8")

    result = staging_registry_evidence.main(
        [
            "validate",
            "--candidate-evidence",
            str(candidate),
            "--source-revision",
            SOURCE_REVISION,
            "--local-image-id",
            LOCAL_IMAGE_ID,
            "--repository",
            REPOSITORY,
            "--digest",
            DIGEST,
            "--expected-repository",
            REPOSITORY,
            "--output",
            str(output),
        ]
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert result == 2
    assert report["status"] == "error"
    assert report["registry_subject_bound"] is False
    assert report["production_promotion_allowed"] is False
    assert json.loads(capsys.readouterr().out) == report


def test_staging_workflow_publishes_attested_subject_without_deploying():
    path = ROOT / ".github/workflows/cd-staging.yml"
    text = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    job = workflow["jobs"]["validate-candidate"]
    steps = job["steps"]

    assert workflow["name"] == "Publish - Staging Candidate Image"
    assert workflow["permissions"] == {
        "contents": "read",
        "packages": "write",
        "id-token": "write",
        "attestations": "write",
    }
    assert "environment" not in job
    assert "kubectl" not in text
    assert "helm" not in text
    assert "deploy-staging" not in text

    action_steps = {step.get("uses"): index for index, step in enumerate(steps)}
    run_steps = {
        step.get("name"): index
        for index, step in enumerate(steps)
        if step.get("run")
    }
    candidate_index = run_steps["Generate non-promotion candidate evidence"]
    push_index = run_steps["Push exact candidate image and resolve registry digest"]
    registry_index = run_steps["Bind candidate evidence to registry subject"]
    attest_index = action_steps["actions/attest-build-provenance@v3"]
    assert candidate_index < push_index < registry_index < attest_index
    assert "docker/login-action@v3" in action_steps
    assert "docker/setup-buildx-action@v3" in action_steps

    attest = steps[attest_index]
    assert attest["with"] == {
        "subject-name": "${{ steps.registry.outputs.repository }}",
        "subject-digest": "${{ steps.registry.outputs.digest }}",
        "push-to-registry": True,
    }
    application_build = steps[
        run_steps["Build the application candidate image"]
    ]["run"]
    assert application_build.count("docker build ") == 1
    commands = "\n".join(step.get("run", "") for step in steps)
    assert "docker buildx imagetools inspect" in commands
    assert '--raw > "$MANIFEST_FILE"' in commands
    assert "sha256sum" in commands
    assert "docker push \"$TAGGED_IMAGE\"" in commands
    assert "docker push \"$TAGGED_IMAGE\" |" not in commands
    assert "data_agent.staging_registry_evidence validate" in commands
    assert "org.opencontainers.image.revision" in commands

    registry_upload_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Upload registry binding evidence"
    )
    registry_upload = steps[registry_upload_index]
    assert attest_index < registry_upload_index
    assert registry_upload["uses"] == "actions/upload-artifact@v4"
    assert "if" not in registry_upload
    assert registry_upload["with"]["path"] == (
        "staging-candidate-evidence/registry.json"
    )

    candidate_upload = next(
        step for step in steps if step.get("name") == "Upload candidate evidence"
    )
    assert candidate_upload["if"] == "always()"
