from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_golden_workflow_is_explicit_read_only_and_fail_closed():
    path = ROOT / ".github/workflows/verify-staging-golden.yml"
    rendered = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(rendered)
    job = workflow["jobs"]["verify-staging-golden"]
    steps = job["steps"]
    named = {step.get("name"): index for index, step in enumerate(steps)}

    assert workflow["name"] == "Verify - Protected Staging Golden Slice"
    assert "workflow_dispatch" in rendered
    assert "deployment_run_id" in rendered
    assert "golden_run_id" in rendered
    assert workflow["permissions"] == {
        "actions": "read",
        "attestations": "write",
        "contents": "read",
        "id-token": "write",
    }
    assert job["runs-on"] == ["self-hosted", "linux", "gda-staging"]
    assert job["environment"] == "staging-live"
    assert job["if"] == "github.ref == 'refs/heads/main'"

    assert (
        named["Download the exact deployment observation"]
        < named["Verify the protected deployment observation"]
        < named["Check out the exact protected verifier revision"]
        < named["Require protected read-only environment configuration"]
        < named["Prove observer identity and immutable environment"]
        < named["Collect fresh allowlisted live observation"]
        < named["Build golden slice from protected ledger export"]
        < named["Validate the complete live staging evidence"]
        < named["Assert staging verified without production authority"]
    )
    assert "GDA_STAGING_OBSERVER_KUBECONFIG_B64" in rendered
    checkout = steps[named["Check out the exact protected verifier revision"]]
    assert checkout["with"]["ref"] == (
        "${{ steps.release.outputs.verifier_revision }}"
    )
    assert checkout["with"]["path"] == "protected-source"
    assert job["env"]["PYTHONPATH"] == (
        "${{ github.workspace }}/protected-source"
    )
    assert "python -m data_agent.staging_golden_slice" in rendered
    golden_step = steps[
        named["Build golden slice from protected ledger export"]
    ]
    assert "protected-source/data_agent/staging_golden_ledger.sql" in (
        golden_step["run"]
    )
    assert "/usr/bin/psql -X -qAt" in golden_step["run"]
    assert "--ledger-evidence -" in golden_step["run"]
    assert "staging-golden/ledger-evidence.json" not in rendered
    pipe = golden_step["run"].index("| \\")
    verifier = golden_step["run"].index(
        "python -m data_agent.staging_golden_slice"
    )
    assert pipe < verifier
    assert golden_step["env"]["GDA_STAGING_GOLDEN_RUN_ID"] == (
        "${{ inputs.golden_run_id }}"
    )
    assert '"${{ inputs.golden_run_id }}"' not in golden_step["run"]
    assert "--golden-slice staging-golden/golden-slice.json" in rendered
    assert "--definition-version-id" in rendered
    assert "--input-resource-version-id" in rendered
    assert "--expected-golden-tenant-id" in rendered
    assert "--expected-golden-capability-id" in rendered
    assert "--expected-golden-definition-version-id" in rendered
    assert "--expected-golden-input-resource-version-id" in rendered
    assert "selected Run" not in rendered
    assert "for resource in secrets configmaps" in rendered
    assert "grep -Fx no" in rendered
    assert "kubectl apply" not in rendered
    assert "kubectl create" not in rendered
    assert "kubectl patch" not in rendered
    assert "production_promotion_allowed\"] is False" in rendered
    assert "production" not in workflow["permissions"]


def test_deploy_observation_carries_bound_non_secret_release_inputs():
    rendered = (
        ROOT / ".github/workflows/deploy-staging-live.yml"
    ).read_text(encoding="utf-8")

    assert "staging-live/candidate.json" in rendered
    assert "staging-live/release.json" in rendered
    assert "staging-live/collection.json" in rendered


def test_candidate_runtime_keeps_the_system_postgresql_client():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "postgresql-client" in dockerfile
    assert "apt-get autoremove" in dockerfile
    assert "/usr/bin/psql" in (
        ROOT / ".github/workflows/verify-staging-golden.yml"
    ).read_text(encoding="utf-8")
