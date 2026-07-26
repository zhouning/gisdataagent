import json
from pathlib import Path

import yaml

from data_agent import (
    staging_provenance_evidence,
    staging_registry_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_REPOSITORY = "zhouning/gisdataagent"
SOURCE_REVISION = "a" * 40
REPOSITORY = f"ghcr.io/{SOURCE_REPOSITORY}"
DIGEST = "sha256:" + "b" * 64
IMAGE = f"{REPOSITORY}@{DIGEST}"


def _registry() -> dict:
    stable = {
        "schema": staging_registry_evidence.REGISTRY_EVIDENCE_SCHEMA,
        "source_revision": SOURCE_REVISION,
        "candidate_evidence_fingerprint": "c" * 64,
        "local_image_id": "sha256:" + "d" * 64,
        "repository": REPOSITORY,
        "digest": DIGEST,
        "image": IMAGE,
        "registry_subject_bound": True,
        "errors": [],
    }
    return {
        **stable,
        "generated_at": "2026-07-26T08:00:00+00:00",
        "status": "registry_subject_bound",
        "registry_push_observed": True,
        "provenance_attestation_verified": False,
        "registry_digest_verified": False,
        "staging_deployed": False,
        "live_cluster_verified": False,
        "production_promotion_allowed": False,
        "required_provenance": list(
            staging_registry_evidence.REQUIRED_PROVENANCE
        ),
        "evidence_fingerprint": (
            staging_registry_evidence.registry_evidence_fingerprint(stable)
        ),
    }


def _attestation(*, repository: str = REPOSITORY, digest: str = DIGEST) -> str:
    return json.dumps(
        [
            {
                "attestation": {"bundle": "not persisted in GDA evidence"},
                "verificationResult": {
                    "statement": {
                        "predicateType": (
                            staging_provenance_evidence.PREDICATE_TYPE
                        ),
                        "subject": [
                            {
                                "name": repository,
                                "digest": {
                                    "sha256": digest.removeprefix("sha256:")
                                },
                            }
                        ],
                    }
                },
            }
        ]
    )


def test_protected_verifier_enforces_exact_identity_and_keeps_promotion_false():
    commands: list[list[str]] = []

    def run(command: list[str]) -> str:
        commands.append(command)
        return _attestation()

    report = staging_provenance_evidence.verify_registry_provenance(
        _registry(),
        source_repository=SOURCE_REPOSITORY,
        source_revision=SOURCE_REVISION,
        run=run,
    )

    assert report["status"] == "provenance_verified"
    assert report["provenance_attestation_verified"] is True
    assert report["registry_digest_verified"] is True
    assert report["repository_identity_verified"] is True
    assert report["signer_workflow_identity_verified"] is True
    assert report["source_revision_verified"] is True
    assert report["github_oidc_issuer_verified"] is True
    assert report["hosted_runner_verified"] is True
    assert report["staging_deployed"] is False
    assert report["live_cluster_verified"] is False
    assert report["production_promotion_allowed"] is False
    assert report["verified_attestation_count"] == 1

    command = commands[0]
    assert command[:4] == ["gh", "attestation", "verify", f"oci://{IMAGE}"]
    assert command[command.index("--repo") + 1] == SOURCE_REPOSITORY
    assert command[command.index("--signer-workflow") + 1] == (
        f"{SOURCE_REPOSITORY}/.github/workflows/cd-staging.yml"
    )
    assert command[command.index("--signer-digest") + 1] == SOURCE_REVISION
    assert command[command.index("--source-ref") + 1] == "refs/heads/main"
    assert command[command.index("--source-digest") + 1] == SOURCE_REVISION
    assert "--deny-self-hosted-runners" in command
    assert command[command.index("--cert-oidc-issuer") + 1] == (
        "https://token.actions.githubusercontent.com"
    )


def test_registry_drift_blocks_before_attestation_command_runs():
    registry = _registry()
    registry["source_revision"] = "9" * 40
    registry["repository"] = "ghcr.io/other/repository"

    def forbidden(_: list[str]) -> str:
        raise AssertionError("attestation command must not run for drifted input")

    report = staging_provenance_evidence.verify_registry_provenance(
        registry,
        source_repository=SOURCE_REPOSITORY,
        source_revision=SOURCE_REVISION,
        run=forbidden,
    )

    rendered = "\n".join(report["errors"])
    assert report["status"] == "blocked"
    assert "source revision does not match" in rendered
    assert "repository does not match" in rendered
    assert "fingerprint does not match" in rendered
    assert report["provenance_attestation_verified"] is False
    assert report["production_promotion_allowed"] is False


def test_empty_or_mismatched_attestation_output_fails_closed():
    empty = staging_provenance_evidence.verify_registry_provenance(
        _registry(),
        source_repository=SOURCE_REPOSITORY,
        source_revision=SOURCE_REVISION,
        run=lambda _: "[]",
    )
    mismatched = staging_provenance_evidence.verify_registry_provenance(
        _registry(),
        source_repository=SOURCE_REPOSITORY,
        source_revision=SOURCE_REVISION,
        run=lambda _: _attestation(repository="ghcr.io/other/repository"),
    )

    assert empty["status"] == "blocked"
    assert "no attestations" in "\n".join(empty["errors"])
    assert mismatched["status"] == "blocked"
    assert "subject does not match" in "\n".join(mismatched["errors"])
    assert empty["registry_digest_verified"] is False
    assert mismatched["registry_digest_verified"] is False


def test_cli_writes_machine_readable_verified_evidence(
    tmp_path: Path, capsys, monkeypatch
):
    registry = tmp_path / "registry.json"
    output = tmp_path / "provenance.json"
    registry.write_text(json.dumps(_registry()), encoding="utf-8")
    monkeypatch.setattr(
        staging_provenance_evidence,
        "_run_command",
        lambda _: _attestation(),
    )

    result = staging_provenance_evidence.main(
        [
            "verify",
            "--registry-evidence",
            str(registry),
            "--source-repository",
            SOURCE_REPOSITORY,
            "--source-revision",
            SOURCE_REVISION,
            "--output",
            str(output),
        ]
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert result == 0
    assert report["provenance_attestation_verified"] is True
    assert json.loads(capsys.readouterr().out) == report


def test_cli_hides_attestation_command_failure(
    tmp_path: Path, capsys, monkeypatch
):
    registry = tmp_path / "registry.json"
    output = tmp_path / "provenance.json"
    registry.write_text(json.dumps(_registry()), encoding="utf-8")

    def fail(_: list[str]) -> str:
        raise staging_provenance_evidence.StagingProvenanceEvidenceError(
            "sensitive registry failure"
        )

    monkeypatch.setattr(staging_provenance_evidence, "_run_command", fail)
    result = staging_provenance_evidence.main(
        [
            "verify",
            "--registry-evidence",
            str(registry),
            "--source-repository",
            SOURCE_REPOSITORY,
            "--source-revision",
            SOURCE_REVISION,
            "--output",
            str(output),
        ]
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    rendered = output.read_text(encoding="utf-8") + capsys.readouterr().out
    assert result == 2
    assert report["status"] == "error"
    assert report["provenance_attestation_verified"] is False
    assert report["production_promotion_allowed"] is False
    assert "sensitive registry failure" not in rendered


def test_protected_workflow_verifies_and_attests_without_deploying():
    path = ROOT / ".github/workflows/verify-staging-provenance.yml"
    text = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    job = workflow["jobs"]["verify-provenance"]
    steps = job["steps"]

    assert workflow["name"] == "Verify - Staging Image Provenance"
    assert workflow["permissions"] == {
        "actions": "read",
        "attestations": "write",
        "contents": "read",
        "id-token": "write",
        "packages": "read",
    }
    assert job["runs-on"] == "ubuntu-latest"
    assert job["environment"] == "staging-provenance"
    assert "workflow_run" in text
    assert 'workflows: ["Publish - Staging Candidate Image"]' in text
    assert "github.event.workflow_run.event == 'push'" in job["if"]
    assert "github.event.workflow_run.head_branch == 'main'" in job["if"]
    assert "head_repository.full_name == github.repository" in job["if"]
    assert "kubectl" not in text
    assert "helm" not in text

    named = {step.get("name"): index for index, step in enumerate(steps)}
    download = steps[named["Download registry binding evidence"]]
    verify = steps[named["Independently verify OCI provenance"]]
    attest = steps[named["Attest protected provenance evidence"]]
    upload = steps[named["Upload protected provenance evidence"]]
    assert download["uses"] == "actions/download-artifact@v4"
    assert download["with"]["run-id"] == (
        "${{ github.event.workflow_run.id }}"
    )
    assert verify["env"]["GH_TOKEN"] == "${{ secrets.GITHUB_TOKEN }}"
    assert "data_agent.staging_provenance_evidence verify" in verify["run"]
    assert attest["uses"] == "actions/attest-build-provenance@v3"
    assert attest["with"]["subject-path"] == (
        "staging-provenance-evidence/provenance.json"
    )
    assert upload["uses"] == "actions/upload-artifact@v4"
    assert named["Independently verify OCI provenance"] < named[
        "Attest protected provenance evidence"
    ] < named["Upload protected provenance evidence"]
