import json
from pathlib import Path

import yaml

from data_agent import staging_candidate_evidence

SHA = "a" * 40
IMAGE_ID = "sha256:" + "b" * 64
FINGERPRINT = "c" * 64
ROOT = Path(__file__).resolve().parents[1]


def _schema_report() -> dict:
    return {
        "status": "in_sync",
        "catalog_count": 97,
        "applied_count": 97,
        "catalog_fingerprint": FINGERPRINT,
        "database_fingerprint": FINGERPRINT,
        "pending": [],
        "unknown_applied": [],
        "missing_checksums": [],
        "checksum_mismatches": [],
        "metadata_mismatches": [],
    }


def _platform_snapshot(secret: str = "must-not-appear") -> dict:
    return {
        "schema": "gda.platform_truth.v1",
        "config": {
            "profile": "staging",
            "strict": True,
            "valid": True,
            "startup_allowed": True,
            "config_fingerprint": FINGERPRINT,
            "entries": {"DATABASE_URL": {"value": secret}},
        },
        "runtime": {
            "status": "valid",
            "errors": [],
            "matches_primitive_baseline": True,
            "inventory_fingerprint": FINGERPRINT,
            "production_ready": False,
            "production_blockers": ["legacy-runtime"],
        },
    }


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps(_schema_report()), encoding="utf-8")
    platform = tmp_path / "platform.json"
    platform.write_text(json.dumps(_platform_snapshot()), encoding="utf-8")
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<testsuites><testsuite tests="12" failures="0" errors="0" '
        'skipped="1" /></testsuites>',
        encoding="utf-8",
    )
    return schema, platform, junit


def test_valid_candidate_evidence_never_claims_live_staging_or_promotion():
    report = staging_candidate_evidence.build_candidate_evidence(
        _schema_report(),
        _platform_snapshot(),
        {"tests": 12, "failures": 0, "errors": 0, "skipped": 1},
        source_revision=SHA,
        image_id=IMAGE_ID,
    )

    assert report["status"] == "candidate_validated"
    assert report["candidate_validated"] is True
    assert report["staging_deployed"] is False
    assert report["live_cluster_verified"] is False
    assert report["registry_digest_verified"] is False
    assert report["production_promotion_allowed"] is False
    assert len(report["required_live_evidence"]) == 5
    assert len(report["evidence_fingerprint"]) == 64
    assert "must-not-appear" not in json.dumps(report)


def test_candidate_gate_collects_schema_config_runtime_test_and_image_errors():
    schema = _schema_report()
    schema["status"] = "pending"
    schema["applied_count"] = 96
    schema["pending"] = ["097_example"]
    platform = _platform_snapshot()
    platform["config"]["profile"] = "test"
    platform["config"]["valid"] = False
    platform["runtime"]["status"] = "invalid"
    platform["runtime"]["matches_primitive_baseline"] = False

    report = staging_candidate_evidence.build_candidate_evidence(
        schema,
        platform,
        {"tests": 12, "failures": 1, "errors": 2, "skipped": 0},
        source_revision="short",
        image_id="gis-data-agent:latest",
    )

    assert report["status"] == "blocked"
    assert report["candidate_validated"] is False
    assert report["production_promotion_allowed"] is False
    assert len(report["errors"]) >= 10


def test_junit_loader_aggregates_suites_without_copying_testcase_content(tmp_path):
    junit = tmp_path / "junit.xml"
    junit.write_text(
        """<testsuites>
        <testsuite tests="3" failures="0" errors="0" skipped="1">
          <testcase name="secret-test-name" />
        </testsuite>
        <testsuite tests="2" failures="0" errors="0" skipped="0" />
        </testsuites>""",
        encoding="utf-8",
    )

    assert staging_candidate_evidence.load_junit_summary(junit) == {
        "tests": 5,
        "failures": 0,
        "errors": 0,
        "skipped": 1,
    }


def test_candidate_cli_writes_machine_readable_non_promotion_evidence(
    tmp_path, capsys
):
    schema, platform, junit = _write_inputs(tmp_path)
    output = tmp_path / "candidate.json"

    assert staging_candidate_evidence.main(
        [
            "validate",
            "--schema-report",
            str(schema),
            "--platform-snapshot",
            str(platform),
            "--junit",
            str(junit),
            "--source-revision",
            SHA,
            "--image-id",
            IMAGE_ID,
            "--output",
            str(output),
        ]
    ) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["candidate_validated"] is True
    assert report["production_promotion_allowed"] is False
    assert json.loads(capsys.readouterr().out) == report


def test_staging_workflow_is_candidate_validation_not_fake_deployment():
    path = ROOT / ".github/workflows/cd-staging.yml"
    text = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    jobs = workflow["jobs"]

    assert workflow["name"] == "Validate - Staging Candidate"
    assert set(jobs) == {"validate-candidate", "candidate-summary"}
    assert "deploy-staging" not in text
    assert "Ready for production" not in text
    assert "environment: staging" not in text

    validation_commands = "\n".join(
        step.get("run", "") for step in jobs["validate-candidate"]["steps"]
    )
    assert "data_agent.migration_runner migrate" in validation_commands
    assert "data_agent.migration_runner status" in validation_commands
    assert "data_agent.platform_truth snapshot" in validation_commands
    assert "data_agent.staging_candidate_evidence validate" in validation_commands
    assert "docker build" in validation_commands
    assert "docker image inspect" in validation_commands

    upload = next(
        step
        for step in jobs["validate-candidate"]["steps"]
        if step.get("uses") == "actions/upload-artifact@v4"
    )
    uploaded_paths = set(upload["with"]["path"].splitlines())
    assert uploaded_paths == {
        "staging-candidate-evidence/candidate.json",
        "staging-candidate-evidence/platform.json",
        "staging-candidate-evidence/schema-admin.json",
        "staging-candidate-evidence/schema-app.json",
    }
    assert "junit.xml" not in upload["with"]["path"]

    summary = jobs["candidate-summary"]
    assert summary["needs"] == "validate-candidate"
    summary_commands = "\n".join(
        step.get("run", "") for step in summary["steps"]
    )
    assert "No staging deployment was performed" in summary_commands
    assert "Production promotion remains blocked" in summary_commands


def test_production_workflow_fails_closed_until_attested_promotion_gate_exists():
    path = ROOT / ".github/workflows/cd-production.yml"
    text = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)

    assert workflow["name"] == "CD - Production (Blocked)"
    assert set(workflow["jobs"]) == {"promotion-gate"}
    commands = "\n".join(
        step.get("run", "")
        for step in workflow["jobs"]["promotion-gate"]["steps"]
    )
    assert "protected staging provenance" in commands
    assert "live observation JSON alone cannot authorize production" in commands
    assert "exit 1" in commands
    assert "docker build" not in commands
    assert "Canary deployment" not in commands
