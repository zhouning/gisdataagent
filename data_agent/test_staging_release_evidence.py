import hashlib
import json
from pathlib import Path

from data_agent import (
    staging_provenance_evidence,
    staging_registry_evidence,
    staging_release_evidence,
)

SOURCE_REPOSITORY = "zhouning/gisdataagent"
SOURCE_REVISION = "a" * 40
VERIFIER_REVISION = "9" * 40
LOCAL_IMAGE_ID = "sha256:" + "b" * 64
REPOSITORY = f"ghcr.io/{SOURCE_REPOSITORY}"
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
        "schema": "gda.staging_candidate_evidence.v2",
        "source_revision": SOURCE_REVISION,
        "image_id": LOCAL_IMAGE_ID,
        "schema_fingerprint": "d" * 64,
        "platform_fingerprint": "2" * 64,
        "config_fingerprint": "e" * 64,
        "environment_access_fingerprint": "1" * 64,
        "runtime_fingerprint": "f" * 64,
        "runtime_privilege_fingerprint": "9" * 64,
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
                        "predicateType": (
                            staging_provenance_evidence.PREDICATE_TYPE
                        ),
                        "subject": [
                            {
                                "name": REPOSITORY,
                                "digest": {
                                    "sha256": DIGEST.removeprefix("sha256:")
                                },
                            }
                        ],
                    }
                }
            }
        ]
    )


def _provenance(registry: dict) -> dict:
    return staging_provenance_evidence.verify_registry_provenance(
        registry,
        source_repository=SOURCE_REPOSITORY,
        source_revision=SOURCE_REVISION,
        verifier_revision=VERIFIER_REVISION,
        run=lambda _: _attestation(),
    )


def _release(candidate: dict, registry: dict, provenance: dict) -> dict:
    return staging_release_evidence.build_staging_release_evidence(
        candidate,
        registry,
        provenance,
        source_repository=SOURCE_REPOSITORY,
        source_revision=SOURCE_REVISION,
        verifier_revision=VERIFIER_REVISION,
    )


def test_bound_release_allows_only_staging_apply():
    candidate = _candidate()
    registry = _registry(candidate)
    provenance = _provenance(registry)

    report = _release(candidate, registry, provenance)

    assert report["status"] == "staging_release_admitted"
    assert report["staging_apply_allowed"] is True
    assert report["image"] == f"{REPOSITORY}@{DIGEST}"
    assert report["candidate_evidence_fingerprint"] == candidate[
        "evidence_fingerprint"
    ]
    assert report["registry_evidence_fingerprint"] == registry[
        "evidence_fingerprint"
    ]
    assert report["provenance_evidence_fingerprint"] == provenance[
        "evidence_fingerprint"
    ]
    assert report["staging_deployed"] is False
    assert report["live_cluster_verified"] is False
    assert report["golden_slice_verified"] is False
    assert report["production_promotion_allowed"] is False


def test_candidate_content_drift_blocks_release():
    candidate = _candidate()
    registry = _registry(candidate)
    provenance = _provenance(registry)
    candidate["runtime_fingerprint"] = "8" * 64

    report = _release(candidate, registry, provenance)

    assert report["status"] == "blocked"
    assert report["staging_apply_allowed"] is False
    assert report["production_promotion_allowed"] is False
    assert "candidate evidence fingerprint does not match" in "\n".join(
        report["errors"]
    )


def test_registry_digest_drift_blocks_release():
    candidate = _candidate()
    registry = _registry(candidate)
    provenance = _provenance(registry)
    registry["digest"] = "sha256:" + "8" * 64
    registry["image"] = f"{REPOSITORY}@{registry['digest']}"

    report = _release(candidate, registry, provenance)

    rendered = "\n".join(report["errors"])
    assert report["staging_apply_allowed"] is False
    assert "registry evidence fingerprint does not match" in rendered
    assert "provenance digest does not match registry" in rendered
    assert "provenance image does not match registry" in rendered


def test_runtime_privilege_binding_drift_blocks_release():
    candidate = _candidate()
    registry = _registry(candidate)
    provenance = _provenance(registry)
    registry["runtime_privilege_fingerprint"] = "8" * 64

    report = _release(candidate, registry, provenance)

    rendered = "\n".join(report["errors"])
    assert report["staging_apply_allowed"] is False
    assert "runtime privilege fingerprint" in rendered
    assert report["production_promotion_allowed"] is False


def test_provenance_policy_drift_blocks_even_with_recomputed_fingerprint():
    candidate = _candidate()
    registry = _registry(candidate)
    provenance = _provenance(registry)
    provenance["verification_policy"]["source_ref"] = "refs/heads/feature"
    provenance["evidence_fingerprint"] = (
        staging_provenance_evidence.provenance_evidence_fingerprint(provenance)
    )

    report = _release(candidate, registry, provenance)

    assert report["staging_apply_allowed"] is False
    assert "verification policy does not match" in "\n".join(report["errors"])
    assert report["production_promotion_allowed"] is False


def test_cli_writes_machine_readable_release_bundle(tmp_path: Path, capsys):
    candidate = _candidate()
    registry = _registry(candidate)
    provenance = _provenance(registry)
    inputs = {
        "candidate": candidate,
        "registry": registry,
        "provenance": provenance,
    }
    paths = {}
    for name, value in inputs.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        paths[name] = path
    output = tmp_path / "release.json"

    result = staging_release_evidence.main(
        [
            "build",
            "--candidate-evidence",
            str(paths["candidate"]),
            "--registry-evidence",
            str(paths["registry"]),
            "--provenance-evidence",
            str(paths["provenance"]),
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

    report = json.loads(output.read_text(encoding="utf-8"))
    assert result == 0
    assert report["staging_apply_allowed"] is True
    assert json.loads(capsys.readouterr().out) == report
