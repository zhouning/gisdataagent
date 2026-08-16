from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_staging_worker_activation_workflow_is_manual_attested_and_fail_closed():
    path = ROOT / ".github/workflows/activate-staging-dolphinscheduler-worker.yml"
    rendered = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(rendered)
    job = workflow["jobs"]["activate-staging-dolphinscheduler-worker"]
    steps = job["steps"]
    named = {step.get("name"): index for index, step in enumerate(steps)}

    assert workflow["name"] == (
        "Activate - Protected Staging DolphinScheduler Worker"
    )
    assert "workflow_dispatch" in rendered
    assert "readiness_run_id" in rendered
    assert "push:" not in rendered
    assert "pull_request:" not in rendered
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
        named["Resolve protected readiness run and artifact identity"]
        < named["Download exact readiness archive and verify digest"]
        < named["Verify readiness artifact and release attestations"]
        < named["Admit exact single-replica activation evidence"]
        < named["Require protected mutation identity and exact cluster"]
        < named["Apply admitted worker manifest and wait for rollout"]
        < named["Collect allowlisted live worker state after activation"]
        < named["Build post-activation live readiness evidence"]
        < named["Attest controlled activation and live evidence"]
        < named["Upload controlled activation evidence"]
        < named["Preserve single-replica and production promotion boundaries"]
    )

    checkout = steps[named["Check out the protected activation verifier revision"]]
    assert checkout["with"]["ref"] == "${{ github.sha }}"
    assert checkout["with"]["path"] == "worker-activation-source"
    assert job["env"]["PYTHONPATH"] == (
        "${{ github.workspace }}/worker-activation-source"
    )

    identity = steps[
        named["Resolve protected readiness run and artifact identity"]
    ]["run"]
    assert "validate-run" in identity
    assert "validate-artifact" in identity
    assert "actions/runs/$READINESS_RUN_ID" in identity
    download = steps[
        named["Download exact readiness archive and verify digest"]
    ]["run"]
    assert "EXPECTED_ARTIFACT_DIGEST" in download
    assert "OBSERVED_ARTIFACT_DIGEST" in download
    assert (
        '[[ "$OBSERVED_ARTIFACT_DIGEST" == "$EXPECTED_ARTIFACT_DIGEST" ]]'
        in download
    )
    assert "unzip" in download

    attestations = steps[
        named["Verify readiness artifact and release attestations"]
    ]["run"]
    for subject in (
        "activation-manifest.yaml",
        "manifest-report.json",
        "activation.json",
        "readiness.json",
        "release.json",
    ):
        assert subject in attestations
    assert "gh attestation verify" in attestations
    assert "verify-staging-dolphinscheduler-worker.yml" in attestations
    assert "verify-staging-provenance.yml" in attestations
    assert "--deny-self-hosted-runners" in attestations

    admission = steps[named["Admit exact single-replica activation evidence"]]
    assert "dolphinscheduler_worker_activation_admission" in admission["run"]
    assert "--manifest" in admission["run"]
    assert "--readiness-evidence" in admission["run"]
    assert "--release-evidence" in admission["run"]
    assert "--expected-cluster-uid" in admission["run"]
    assert "--expected-namespace-uid" in admission["run"]

    apply = steps[named["Apply admitted worker manifest and wait for rollout"]]
    assert rendered.count("kubectl apply") == 1
    assert "activation-manifest.yaml" in apply["run"]
    assert "--server-side" in apply["run"]
    assert "rollout status" in apply["run"]
    assert "kubectl scale" not in rendered
    assert "kubectl patch" not in rendered
    assert "kubectl get secret" not in rendered
    assert "kubectl get configmap" not in rendered
    assert "production" not in workflow["permissions"]

    live = steps[named["Build post-activation live readiness evidence"]]
    assert live["continue-on-error"] is True
    assert "validate-readiness" in live["run"]
    upload = steps[named["Upload controlled activation evidence"]]
    assert upload["if"] == "always()"
    boundary = steps[
        named["Preserve single-replica and production promotion boundaries"]
    ]
    assert boundary["if"] == "always()"
    assert "live_ready" in boundary["run"]
    assert "restart_counts" in boundary["run"]
    assert "automatic_scale_allowed" in boundary["run"]
    assert "production_promotion_allowed" in boundary["run"]
