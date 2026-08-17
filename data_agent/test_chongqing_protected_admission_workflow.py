from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_protected_admission_workflow_is_read_only_and_fail_closed():
    path = ROOT / ".github/workflows/verify-chongqing-admission.yml"
    rendered = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(rendered)
    job = workflow["jobs"]["verify-chongqing-admission"]
    steps = job["steps"]
    named = {step.get("name"): index for index, step in enumerate(steps)}

    assert workflow["name"] == "Verify - Chongqing Protected Admission"
    assert "workflow_dispatch" in rendered
    assert workflow["permissions"] == {
        "actions": "read",
        "attestations": "write",
        "contents": "read",
        "id-token": "write",
    }
    assert job["if"] == "github.ref == 'refs/heads/main'"
    assert job["runs-on"] == ["self-hosted", "linux", "gda-admission"]
    assert job["environment"] == "chongqing-admission"
    assert job["timeout-minutes"] == 20
    assert workflow["concurrency"] == {
        "group": "chongqing-protected-admission",
        "cancel-in-progress": False,
    }

    assert (
        named["Check out the exact protected verifier revision"]
        < named["Require protected metadata-only attestation input"]
        < named["Evaluate the protected admission contract"]
        < named["Verify the report and preserve the no-authority boundary"]
        < named["Attest the protected admission evidence"]
        < named["Upload the protected admission evidence"]
    )
    checkout = steps[named["Check out the exact protected verifier revision"]]
    assert checkout["with"] == {
        "ref": "${{ github.sha }}",
        "path": "protected-source",
        "persist-credentials": False,
    }
    assert job["env"]["PYTHONPATH"] == "${{ github.workspace }}/protected-source"
    assert job["env"]["GDA_CHONGQING_READINESS_SHA256"] == (
        "2f5ae24ab904af0eed18ee7c517ab5c4638cbdf0923c9345b0041af185d25591"
    )
    assert job["env"]["GDA_CHONGQING_READINESS_FILE_SHA256"] == (
        "c595065e152988529ff12e2301d59caebb31d2889658a676c9d1f8239e6f8372"
    )

    require_input = steps[named["Require protected metadata-only attestation input"]]
    assert require_input["env"]["GDA_CHONGQING_ADMISSION_PROTECTED"] == (
        "${{ vars.GDA_CHONGQING_ADMISSION_PROTECTED }}"
    )
    assert require_input["env"]["GDA_CHONGQING_ATTESTATION_BUNDLE_B64"] == (
        "${{ secrets.GDA_CHONGQING_ATTESTATION_BUNDLE_B64 }}"
    )
    assert "umask 077" in require_input["run"]
    assert "base64 --decode" in require_input["run"]
    assert "python -m json.tool" in require_input["run"]

    evaluate = steps[named["Evaluate the protected admission contract"]]["run"]
    assert "data_agent.chongqing_protected_admission evaluate" in evaluate
    assert "chongqing-admission-readiness-2026-08-17.json" in evaluate
    assert '--attestation "$GDA_CHONGQING_ATTESTATION_PATH"' in evaluate
    assert "--output chongqing-protected-admission/report.json" in evaluate

    verify = steps[
        named["Verify the report and preserve the no-authority boundary"]
    ]["run"]
    assert "data_agent.chongqing_protected_admission verify" in verify
    assert 'report["attestation_valid"] is True' in verify
    assert 'report["admission_eligible"] is True' in verify
    for claim in (
        "content_admission_authorized",
        "source_content_admitted",
        "landing_authority_created",
        "resource_version_created",
        "platform_run_created",
        "scheduler_submission_authorized",
        "provider_mutation_authorized",
        "production_ready",
    ):
        assert f'report["{claim}"] is False' in verify

    attest = steps[named["Attest the protected admission evidence"]]
    assert attest["uses"] == "actions/attest-build-provenance@v3"
    assert "chongqing-protected-admission/attestation.json" in attest["with"][
        "subject-path"
    ]
    assert "chongqing-protected-admission/report.json" in attest["with"][
        "subject-path"
    ]
    upload = steps[named["Upload the protected admission evidence"]]
    assert upload["uses"] == "actions/upload-artifact@v4"
    assert upload["with"]["retention-days"] == 90
    assert upload["with"]["if-no-files-found"] == "error"

    for forbidden in (
        "kubectl ",
        "helm ",
        "terraform ",
        "docker ",
        "dolphinscheduler",
        "provider mutation",
    ):
        assert forbidden not in rendered.lower()
