from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_staging_worker_workflow_is_protected_read_only_and_fail_closed():
    path = ROOT / ".github/workflows/verify-staging-dolphinscheduler-worker.yml"
    rendered = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(rendered)
    job = workflow["jobs"]["verify-staging-dolphinscheduler-worker"]
    steps = job["steps"]
    named = {step.get("name"): index for index, step in enumerate(steps)}

    assert workflow["name"] == "Verify - Protected Staging DolphinScheduler Worker"
    assert "workflow_dispatch" in rendered
    assert "deployment_run_id" in rendered
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
        named["Download the exact protected deployment observation"]
        < named["Verify the protected deployment observation"]
        < named["Check out the protected worker verifier revision"]
        < named["Require protected read-only environment configuration"]
        < named["Prove observer identity and deny mutation or secret reads"]
        < named["Materialize external redacted activation inputs"]
        < named["Render the release-bound single-replica activation candidate"]
        < named["Validate external activation evidence without scaling"]
        < named["Collect allowlisted live worker snapshots"]
        < named["Build fail-closed staging worker readiness evidence"]
        < named["Upload staging worker readiness evidence"]
        < named["Preserve no-scale and production promotion boundaries"]
    )
    assert "GDA_STAGING_DOLPHINSCHEDULER_CONFIG_MAP_B64" in rendered
    assert "GDA_STAGING_DOLPHINSCHEDULER_SECRET_ATTESTATION_B64" in rendered
    assert "GDA_STAGING_OBSERVER_KUBECONFIG_B64" in rendered
    assert "data_agent.dolphinscheduler_worker_staging render" in rendered
    assert "data_agent.dolphinscheduler_worker_activation validate" in rendered
    assert "data_agent.dolphinscheduler_worker_staging validate-readiness" in rendered
    assert "--namespace \"$GDA_STAGING_NAMESPACE\"" in rendered
    assert "--expected-cluster-uid" in rendered
    assert "--expected-namespace-uid" in rendered
    assert "automatic_scale_allowed" in rendered

    checkout = steps[named["Check out the protected worker verifier revision"]]
    assert checkout["with"]["ref"] == "${{ github.sha }}"
    assert checkout["with"]["path"] == "worker-verifier-source"
    assert job["env"]["PYTHONPATH"] == (
        "${{ github.workspace }}/worker-verifier-source"
    )
    assert checkout["with"]["ref"] != (
        "${{ steps.release.outputs.verifier_revision }}"
    )

    observer = steps[
        named["Prove observer identity and deny mutation or secret reads"]
    ]["run"]
    assert "require_denied()" in observer
    assert "for resource in secrets configmaps" in observer
    assert '[[ "$exit_code" -ne 1 || "$output" != "no" ]]' in observer
    assert "kubectl get secret" not in rendered
    assert "kubectl get configmap" not in rendered
    assert "kubectl apply" not in rendered
    assert "kubectl patch" not in rendered
    assert "kubectl scale" not in rendered
    assert "production" not in workflow["permissions"]

    activation = steps[
        named["Validate external activation evidence without scaling"]
    ]
    assert "--secret-attestation" in activation["run"]
    assert "--environment staging" in activation["run"]
    assert "--namespace \"$GDA_STAGING_NAMESPACE\"" in activation["run"]

    readiness = steps[
        named["Build fail-closed staging worker readiness evidence"]
    ]
    assert readiness["continue-on-error"] is True
    assert "--output staging-worker-readiness/readiness.json" in readiness["run"]

    attestation = steps[named["Attest staging worker readiness evidence"]]
    assert attestation["if"].startswith("always()")
    upload = steps[named["Upload staging worker readiness evidence"]]
    assert upload["if"] == "always()"

    boundary = steps[
        named["Preserve no-scale and production promotion boundaries"]
    ]
    assert boundary["if"] == "always()"
    assert "production_promotion_allowed" in boundary["run"]
    assert "SystemExit" in boundary["run"]
