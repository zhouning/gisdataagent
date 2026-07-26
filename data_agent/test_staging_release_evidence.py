import hashlib
import json
from pathlib import Path

import yaml

from data_agent import (
    staging_provenance_evidence,
    staging_release_evidence,
)
from data_agent import (
    test_staging_deployment_bundle as bundle_fixtures,
)

SOURCE_REPOSITORY = "zhouning/gisdataagent"
SOURCE_REVISION = bundle_fixtures.SOURCE_REVISION
VERIFIER_REVISION = "9" * 40
IMAGE = bundle_fixtures.IMAGE


def _provenance() -> dict:
    policy = {
        "source_repository": SOURCE_REPOSITORY,
        "source_ref": staging_provenance_evidence.PROTECTED_SOURCE_REF,
        "source_digest": SOURCE_REVISION,
        "signer_workflow": (
            f"{SOURCE_REPOSITORY}/"
            f"{staging_provenance_evidence.PUBLISH_WORKFLOW_PATH}"
        ),
        "signer_digest": SOURCE_REVISION,
        "oidc_issuer": staging_provenance_evidence.GITHUB_OIDC_ISSUER,
        "deny_self_hosted_runners": True,
        "predicate_type": staging_provenance_evidence.PREDICATE_TYPE,
    }
    stable = {
        "schema": staging_provenance_evidence.PROVENANCE_EVIDENCE_SCHEMA,
        "source_revision": SOURCE_REVISION,
        "verifier_revision": VERIFIER_REVISION,
        "candidate_evidence_fingerprint": bundle_fixtures._candidate()[
            "evidence_fingerprint"
        ],
        "registry_evidence_fingerprint": "8" * 64,
        "repository": "ghcr.io/zhouning/gisdataagent",
        "digest": "sha256:" + "b" * 64,
        "image": IMAGE,
        "verification_policy": policy,
        "verified_attestation_count": 1,
        "provenance_attestation_verified": True,
        "registry_digest_verified": True,
        "errors": [],
    }
    return {
        **stable,
        "generated_at": "2026-07-26T09:00:00+00:00",
        "status": "provenance_verified",
        "repository_identity_verified": True,
        "signer_workflow_identity_verified": True,
        "source_revision_verified": True,
        "github_oidc_issuer_verified": True,
        "hosted_runner_verified": True,
        "staging_deployed": False,
        "live_cluster_verified": False,
        "production_promotion_allowed": False,
        "required_staging_evidence": list(
            staging_provenance_evidence.REQUIRED_STAGING_EVIDENCE
        ),
        "evidence_fingerprint": (
            staging_provenance_evidence.provenance_evidence_fingerprint(stable)
        ),
    }


def _write_provenance(path: Path, provenance: dict | None = None) -> dict:
    value = provenance or _provenance()
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return value


def _artifact_attestation(path: Path, *, digest: str | None = None) -> str:
    artifact_digest = digest or hashlib.sha256(path.read_bytes()).hexdigest()
    return json.dumps(
        [
            {
                "verificationResult": {
                    "statement": {
                        "predicateType": (
                            staging_provenance_evidence.PREDICATE_TYPE
                        ),
                        "subject": [
                            {
                                "name": path.name,
                                "digest": {"sha256": artifact_digest},
                            }
                        ],
                    }
                }
            }
        ]
    )


def test_verified_release_binds_artifact_identity_and_never_claims_deployment(
    tmp_path: Path,
):
    path = tmp_path / "provenance.json"
    provenance = _write_provenance(path)
    commands: list[list[str]] = []

    def run(command: list[str]) -> str:
        commands.append(command)
        return _artifact_attestation(path)

    documents, report = staging_release_evidence.build_verified_staging_release(
        bundle_fixtures._template(),
        bundle_fixtures._candidate(),
        bundle_fixtures._platform(),
        provenance_path=path,
        source_repository=SOURCE_REPOSITORY,
        source_revision=SOURCE_REVISION,
        verifier_revision=VERIFIER_REVISION,
        run=run,
    )

    assert report["status"] == "verified_for_staging_apply"
    assert report["bundle_ready"] is True
    assert report["provenance_evidence_artifact_verified"] is True
    assert report["provenance_attestation_verified"] is True
    assert report["registry_digest_verified"] is True
    assert report["staging_deployed"] is False
    assert report["live_cluster_verified"] is False
    assert report["production_promotion_allowed"] is False
    assert report["provenance_evidence_fingerprint"] == provenance[
        "evidence_fingerprint"
    ]
    assert report["manifest_fingerprint"]
    assert documents

    command = commands[0]
    assert command[:4] == ["gh", "attestation", "verify", str(path)]
    assert command[command.index("--repo") + 1] == SOURCE_REPOSITORY
    assert command[command.index("--signer-workflow") + 1] == (
        f"{SOURCE_REPOSITORY}/.github/workflows/verify-staging-provenance.yml"
    )
    assert command[command.index("--signer-digest") + 1] == VERIFIER_REVISION
    assert command[command.index("--source-digest") + 1] == VERIFIER_REVISION
    assert command[command.index("--source-ref") + 1] == "refs/heads/main"
    assert "--deny-self-hosted-runners" in command


def test_provenance_or_candidate_drift_blocks_before_artifact_verification(
    tmp_path: Path,
):
    path = tmp_path / "provenance.json"
    provenance = _provenance()
    provenance["candidate_evidence_fingerprint"] = "7" * 64
    _write_provenance(path, provenance)

    def forbidden(_: list[str]) -> str:
        raise AssertionError("artifact verifier must not run for drifted evidence")

    documents, report = staging_release_evidence.build_verified_staging_release(
        bundle_fixtures._template(),
        bundle_fixtures._candidate(),
        bundle_fixtures._platform(),
        provenance_path=path,
        source_repository=SOURCE_REPOSITORY,
        source_revision=SOURCE_REVISION,
        verifier_revision=VERIFIER_REVISION,
        run=forbidden,
    )

    rendered = "\n".join(report["errors"])
    assert documents == []
    assert report["status"] == "blocked"
    assert report["bundle_ready"] is False
    assert report["provenance_evidence_artifact_verified"] is False
    assert "does not bind the candidate" in rendered
    assert "fingerprint does not match" in rendered


def test_mismatched_artifact_subject_digest_blocks_manifest(
    tmp_path: Path,
):
    path = tmp_path / "provenance.json"
    _write_provenance(path)

    documents, report = staging_release_evidence.build_verified_staging_release(
        bundle_fixtures._template(),
        bundle_fixtures._candidate(),
        bundle_fixtures._platform(),
        provenance_path=path,
        source_repository=SOURCE_REPOSITORY,
        source_revision=SOURCE_REVISION,
        verifier_revision=VERIFIER_REVISION,
        run=lambda _: _artifact_attestation(path, digest="0" * 64),
    )

    assert documents == []
    assert report["status"] == "blocked"
    assert report["registry_digest_verified"] is False
    assert "subject digest does not match" in "\n".join(report["errors"])


def test_provenance_file_change_during_verification_blocks_manifest(
    tmp_path: Path,
):
    path = tmp_path / "provenance.json"
    _write_provenance(path)
    original_digest = hashlib.sha256(path.read_bytes()).hexdigest()

    def mutate(_: list[str]) -> str:
        path.write_text("{}", encoding="utf-8")
        return _artifact_attestation(path, digest=original_digest)

    documents, report = staging_release_evidence.build_verified_staging_release(
        bundle_fixtures._template(),
        bundle_fixtures._candidate(),
        bundle_fixtures._platform(),
        provenance_path=path,
        source_repository=SOURCE_REPOSITORY,
        source_revision=SOURCE_REVISION,
        verifier_revision=VERIFIER_REVISION,
        run=mutate,
    )

    assert documents == []
    assert report["status"] == "blocked"
    assert "changed during verification" in "\n".join(report["errors"])


def test_cli_writes_manifest_only_after_artifact_verification(
    tmp_path: Path, capsys, monkeypatch
):
    template = tmp_path / "template.yaml"
    candidate = tmp_path / "candidate.json"
    platform = tmp_path / "platform.json"
    provenance = tmp_path / "provenance.json"
    manifest = tmp_path / "release.yaml"
    report_path = tmp_path / "release.json"
    template.write_text(
        yaml.safe_dump_all(bundle_fixtures._template(), sort_keys=False),
        encoding="utf-8",
    )
    candidate.write_text(
        json.dumps(bundle_fixtures._candidate()), encoding="utf-8"
    )
    platform.write_text(json.dumps(bundle_fixtures._platform()), encoding="utf-8")
    _write_provenance(provenance)
    monkeypatch.setattr(
        staging_release_evidence,
        "_run_command",
        lambda _: _artifact_attestation(provenance),
    )

    result = staging_release_evidence.main(
        [
            "build",
            "--template-manifest",
            str(template),
            "--candidate-evidence",
            str(candidate),
            "--platform-snapshot",
            str(platform),
            "--provenance-evidence",
            str(provenance),
            "--source-repository",
            SOURCE_REPOSITORY,
            "--source-revision",
            SOURCE_REVISION,
            "--verifier-revision",
            VERIFIER_REVISION,
            "--manifest-output",
            str(manifest),
            "--report-output",
            str(report_path),
        ]
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert result == 0
    assert manifest.exists()
    assert report["status"] == "verified_for_staging_apply"
    assert json.loads(capsys.readouterr().out) == report


def test_cli_hides_artifact_verifier_failure(tmp_path: Path, capsys, monkeypatch):
    template = tmp_path / "template.yaml"
    candidate = tmp_path / "candidate.json"
    platform = tmp_path / "platform.json"
    provenance = tmp_path / "provenance.json"
    manifest = tmp_path / "release.yaml"
    report_path = tmp_path / "release.json"
    template.write_text(
        yaml.safe_dump_all(bundle_fixtures._template(), sort_keys=False),
        encoding="utf-8",
    )
    candidate.write_text(
        json.dumps(bundle_fixtures._candidate()), encoding="utf-8"
    )
    platform.write_text(json.dumps(bundle_fixtures._platform()), encoding="utf-8")
    _write_provenance(provenance)

    def fail(_: list[str]) -> str:
        raise staging_release_evidence.StagingReleaseEvidenceError(
            "sensitive verifier output"
        )

    monkeypatch.setattr(staging_release_evidence, "_run_command", fail)
    result = staging_release_evidence.main(
        [
            "build",
            "--template-manifest",
            str(template),
            "--candidate-evidence",
            str(candidate),
            "--platform-snapshot",
            str(platform),
            "--provenance-evidence",
            str(provenance),
            "--source-repository",
            SOURCE_REPOSITORY,
            "--source-revision",
            SOURCE_REVISION,
            "--verifier-revision",
            VERIFIER_REVISION,
            "--manifest-output",
            str(manifest),
            "--report-output",
            str(report_path),
        ]
    )

    rendered = report_path.read_text(encoding="utf-8") + capsys.readouterr().out
    assert result == 2
    assert not manifest.exists()
    assert "sensitive verifier output" not in rendered
