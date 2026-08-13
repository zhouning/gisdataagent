from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_live_staging_workflow_is_protected_staged_and_fail_closed():
    path = ROOT / ".github/workflows/deploy-staging-live.yml"
    text = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    activation = workflow["jobs"]["activate-live-staging"]
    job = workflow["jobs"]["deploy-live-staging"]
    steps = job["steps"]
    named = {step.get("name"): index for index, step in enumerate(steps)}

    assert workflow["name"] == "Deploy - Protected Live Staging"
    assert 'workflows: ["Verify - Staging Image Provenance"]' in text
    assert workflow["permissions"] == {
        "actions": "read",
        "attestations": "write",
        "contents": "read",
        "id-token": "write",
    }
    assert activation["runs-on"] == "ubuntu-latest"
    assert activation["environment"] == "staging-live"
    assert activation["permissions"] == {}
    assert "head_repository.full_name == github.repository" in activation["if"]
    activation_step = activation["steps"][0]
    assert activation_step["name"] == (
        "Reject an unconfigured live staging environment"
    )
    assert activation_step["env"]["GDA_STAGING_LIVE_PROTECTED"] == (
        "${{ vars.GDA_STAGING_LIVE_PROTECTED }}"
    )
    assert '!= "true"' in activation_step["run"]
    assert "exit 1" in activation_step["run"]
    assert job["needs"] == "activate-live-staging"
    assert "needs.activate-live-staging.result == 'success'" in job["if"]
    assert job["runs-on"] == ["self-hosted", "linux", "gda-staging"]
    assert job["environment"] == "staging-live"
    assert "head_repository.full_name == github.repository" in job["if"]
    assert "github.event.workflow_run.head_branch == 'main'" in job["if"]

    download = steps[named["Download the exact protected release bundle"]]
    assert download["uses"] == "actions/download-artifact@v4"
    assert download["with"]["name"] == "staging-release-evidence"
    assert download["with"]["run-id"] == "${{ github.event.workflow_run.id }}"
    assert (
        named["Download the exact protected release bundle"]
        < named["Set up Python 3.13"]
        < named["Verify release attestation and resolve protected revisions"]
        < named["Check out the exact protected verifier revision"]
    )
    checkout = steps[named["Check out the exact protected verifier revision"]]
    assert checkout["with"]["path"] == "protected-source"
    assert checkout["with"]["ref"] == (
        "${{ steps.release.outputs.verifier_revision }}"
    )

    attestation = steps[
        named["Verify release attestation and resolve protected revisions"]
    ]["run"]
    assert "gh attestation verify" in attestation
    assert "--signer-workflow" in attestation
    assert "--source-digest \"$VERIFIER_REVISION\"" in attestation
    assert "--signer-digest \"$VERIFIER_REVISION\"" in attestation
    assert "--deny-self-hosted-runners" in attestation

    identity = steps[named["Verify immutable cluster and namespace identity"]][
        "run"
    ]
    assert "namespace kube-system" in identity
    assert "GDA_STAGING_CLUSTER_UID" in identity
    assert "GDA_STAGING_NAMESPACE_UID" in identity
    assert "create pods --subresource=exec" in identity
    assert "get services --subresource=proxy" in identity
    assert "get pods --subresource=log" in identity
    assert "list endpointslices.discovery.k8s.io" in identity
    assert "for resource in secrets configmaps" in identity
    assert "grep -Fx no" in identity
    assert "kubectl get secret" not in text
    assert "GDA_STAGING_IMAGE_PULL_SECRET" in text
    assert "--image-pull-secret-name" in text

    assert (
        named["Render and run the strict platform preflight"]
        < named["Render migration and application phases"]
        < named["Apply the sole migration authority and wait for completion"]
        < named["Apply immutable application workload and wait for rollout"]
        < named["Collect allowlisted live observation"]
        < named["Validate live evidence without claiming a golden slice"]
    )
    assert "--dry-run=server" in text
    assert "--release-evidence" in text
    assert "--expected-namespace-name" in text
    assert steps[named["Validate live evidence without claiming a golden slice"]][
        "continue-on-error"
    ] is True
    boundary = steps[named["Preserve the golden-slice promotion boundary"]]
    assert boundary["if"] == "always()"
    assert "exit 1" in boundary["run"]
    assert "production" not in workflow["permissions"]
