import base64
import json
import subprocess
from pathlib import Path

import pytest

from data_agent import staging_environment_readiness as readiness


def _environment(*, complete: bool = True) -> dict:
    variables = {
        **readiness.LIVE_EXACT_VARIABLES,
        **{name: f"configured-{name}" for name in readiness.LIVE_REQUIRED_VARIABLES},
    }
    return {
        "exists": complete,
        "can_admins_bypass": False,
        "protection_rules": [
            {
                "type": "required_reviewers",
                "prevent_self_review": True,
                "reviewers": [{"type": "User"}],
            }
        ],
        "deployment_branch_policy": {
            "protected_branches": True,
            "custom_branch_policies": False,
        },
        "variables": variables,
        "secret_names": list(readiness.LIVE_REQUIRED_SECRETS),
    }


def _snapshot() -> dict:
    workflows = {
        path: {
            "local_exists": True,
            "remote_exists": True,
            "local_sha256": path,
            "remote_sha256": path,
            "remote_name": name,
        }
        for path, name in readiness.WORKFLOW_CONTRACTS.items()
    }
    protected_release_sources = {
        path: {
            "local_exists": True,
            "remote_exists": True,
            "local_sha256": path,
            "remote_sha256": path,
        }
        for path in readiness.PROTECTED_RELEASE_SOURCE_PATHS
    }
    live = _environment()
    provenance = _environment()
    provenance["variables"] = dict(readiness.PROVENANCE_VARIABLES)
    provenance["secret_names"] = []
    runs = {
        ".github/workflows/cd-staging.yml": [
            {
                "id": 1,
                "event": "workflow_dispatch",
                "head_branch": "main",
                "head_sha": "a" * 40,
                "status": "completed",
                "conclusion": "success",
            }
        ],
        ".github/workflows/verify-staging-provenance.yml": [
            {
                "id": 2,
                "event": "workflow_run",
                "head_branch": "main",
                "head_sha": "b" * 40,
                "status": "completed",
                "conclusion": "success",
            }
        ],
        ".github/workflows/deploy-staging-live.yml": [
            {
                "id": 3,
                "event": "workflow_run",
                "head_branch": "main",
                "head_sha": "c" * 40,
                "status": "completed",
                "conclusion": "failure",
            }
        ],
        ".github/workflows/verify-staging-golden.yml": [
            {
                "id": 4,
                "event": "workflow_dispatch",
                "head_branch": "main",
                "head_sha": "d" * 40,
                "status": "completed",
                "conclusion": "success",
            }
        ],
    }
    artifact_names = {
        1: ["staging-candidate-evidence-a", "staging-registry-evidence-a"],
        2: ["staging-provenance-evidence-a", "staging-release-evidence"],
        3: ["staging-live-observation-3"],
        4: ["staging-golden-evidence-run"],
    }
    artifacts = [
        {
            "name": name,
            "expired": False,
            "workflow_run": {"id": run_id},
        }
        for run_id, names in artifact_names.items()
        for name in names
    ]
    return {
        "repository": readiness.DEFAULT_REPOSITORY,
        "default_branch": "main",
        "default_branch_protected": True,
        "workflows": workflows,
        "protected_release_sources": protected_release_sources,
        "environments": {
            "staging-provenance": provenance,
            "staging-live": live,
        },
        "runners": [
            {
                "id": 9,
                "status": "online",
                "busy": False,
                "labels": [
                    {"name": "self-hosted"},
                    {"name": "linux"},
                    {"name": "gda-staging"},
                ],
            }
        ],
        "workflow_runs": runs,
        "artifacts": artifacts,
        "cluster_observation": {
            "cluster_uid": live["variables"]["GDA_STAGING_CLUSTER_UID"],
            "namespace_name": "gis-agent-staging",
            "namespace_uid": live["variables"]["GDA_STAGING_NAMESPACE_UID"],
            "deploy_identity_authorized": True,
            "observer_identity_read_only": True,
        },
        "collection_errors": [],
    }


def test_complete_readiness_never_grants_production_promotion():
    report = readiness.assess_readiness(_snapshot())

    assert report["schema"] == "gda.staging_environment_readiness.v2"
    assert report["status"] == "ready"
    assert report["ar0_status"] == "in_progress"
    assert report["production_promotion_allowed"] is False
    assert all(report["gates"].values())
    assert report["evidence_chain"]["all_required_artifacts_observed"] is True
    assert report["evidence_chain"]["artifact_metadata_only"] is True
    assert report["evidence_chain"]["content_binding_verified"] is False
    assert report["evidence_chain"]["deployment_observation"]["run_id"] == 3
    assert report["blockers"] == []


def test_readiness_reports_remote_environment_runner_and_artifact_blockers():
    snapshot = _snapshot()
    candidate_workflow = snapshot["workflows"][
        ".github/workflows/cd-staging.yml"
    ]
    candidate_workflow["remote_sha256"] = "old"
    provenance = snapshot["environments"]["staging-provenance"]
    provenance["protection_rules"][0]["prevent_self_review"] = False
    snapshot["environments"]["staging-live"] = {
        "exists": False,
        "variables": {},
        "secret_names": [],
    }
    snapshot["runners"] = []
    snapshot["cluster_observation"] = {}
    snapshot["workflow_runs"] = {
        path: [] for path in readiness.WORKFLOW_CONTRACTS
    }
    snapshot["workflow_runs"][".github/workflows/cd-staging.yml"] = [
        {
            "id": 10,
            "event": "push",
            "head_branch": "feature",
            "status": "completed",
            "conclusion": "failure",
        }
    ]
    snapshot["artifacts"] = []

    report = readiness.assess_readiness(snapshot)

    assert report["status"] == "blocked"
    assert report["next_required_action"]["gate"] == (
        "repository_workflows_ready"
    )
    assert report["runner"]["ready"] is False
    assert report["kubernetes_identity"]["observed"] is False
    assert report["protected_environments"]["staging-provenance"][
        "protection"
    ]["prevent_self_review"] is False
    assert report["protected_environments"]["staging-provenance"][
        "protection"
    ]["ready"] is False
    assert report["evidence_chain"]["candidate"]["latest_observed_run"] == {
        "run_id": 10,
        "event": "push",
        "head_branch": "feature",
        "conclusion": "failure",
        "eligible": False,
    }
    assert any(
        blocker["gate"] == "protected_environment_metadata_ready"
        for blocker in report["blockers"]
    )


def test_readiness_rejects_protected_release_source_drift():
    snapshot = _snapshot()
    drifted_path = "data_agent/staging_golden_slice.py"
    snapshot["protected_release_sources"][drifted_path]["remote_sha256"] = (
        "old"
    )

    report = readiness.assess_readiness(snapshot)

    assert report["status"] == "blocked"
    assert report["gates"]["repository_workflows_ready"] is True
    assert report["gates"]["protected_release_sources_ready"] is False
    assert report["next_required_action"]["gate"] == (
        "protected_release_sources_ready"
    )
    source = next(
        item
        for item in report["protected_release_sources"]
        if item["path"] == drifted_path
    )
    assert source == {
        "path": drifted_path,
        "remote_exists": True,
        "matches_local_contract": False,
        "ready": False,
    }


def test_readiness_requires_preflight_runtime_entrypoint():
    snapshot = _snapshot()
    snapshot["protected_release_sources"].pop(
        "data_agent/staging_platform_snapshot.py"
    )

    report = readiness.assess_readiness(snapshot)

    assert report["status"] == "blocked"
    assert report["gates"]["protected_release_sources_ready"] is False
    source = next(
        item
        for item in report["protected_release_sources"]
        if item["path"] == "data_agent/staging_platform_snapshot.py"
    )
    assert source == {
        "path": "data_agent/staging_platform_snapshot.py",
        "remote_exists": False,
        "matches_local_contract": False,
        "ready": False,
    }


def test_readiness_fails_closed_on_partial_metadata_collection():
    snapshot = _snapshot()
    snapshot["collection_errors"] = ["artifact page 2 could not be read"]

    report = readiness.assess_readiness(snapshot)

    assert report["status"] == "blocked"
    assert report["gates"]["repository_workflows_ready"] is True
    assert report["gates"]["protected_release_sources_ready"] is True
    assert report["gates"]["repository_metadata_reads_complete"] is False
    assert report["collection_errors"] == [
        "artifact page 2 could not be read"
    ]
    assert report["next_required_action"]["gate"] == (
        "repository_metadata_reads_complete"
    )


def test_read_endpoint_distinguishes_confirmed_absence_from_read_failure():
    def missing(_: str) -> object:
        raise readiness.GitHubNotFoundError("gh: Not Found (HTTP 404)")

    assert readiness._read_endpoint(
        "optional/path",
        api=missing,
        default={},
        allow_not_found=True,
    ) == ({}, None)

    def failed(_: str) -> object:
        raise readiness.GitHubReadError("gh: connection reset")

    value, error = readiness._read_endpoint(
        "required/path",
        api=failed,
        default={},
        allow_not_found=True,
    )
    assert value == {}
    assert error == "gh: connection reset"


def test_gh_json_classifies_cli_http_404(monkeypatch):
    def run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=1,
            stdout="",
            stderr="gh: Not Found (HTTP 404)\n",
        )

    monkeypatch.setattr(readiness.subprocess, "run", run)

    with pytest.raises(readiness.GitHubNotFoundError):
        readiness._gh_json("repos/example/project/contents/missing.py")


def test_report_exposes_configuration_presence_but_not_values():
    snapshot = _snapshot()
    marker = "must-not-appear"
    snapshot["environments"]["staging-live"]["variables"][
        "GDA_STAGING_CLUSTER_UID"
    ] = marker

    report = readiness.assess_readiness(snapshot)
    rendered = json.dumps(report)

    assert marker not in rendered
    assert "GDA_STAGING_CLUSTER_UID" in rendered
    assert "GDA_STAGING_KUBECONFIG_B64" in rendered


def test_collect_snapshot_compares_local_and_remote_workflows_without_writes(
    tmp_path: Path,
):
    responses: dict[str, object] = {
        f"repos/{readiness.DEFAULT_REPOSITORY}": {"default_branch": "main"},
        f"repos/{readiness.DEFAULT_REPOSITORY}/branches/main": {
            "name": "main",
            "protected": True,
        },
        f"repos/{readiness.DEFAULT_REPOSITORY}/environments?per_page=100": {
            "environments": []
        },
        f"repos/{readiness.DEFAULT_REPOSITORY}/actions/runners?per_page=100": {
            "runners": []
        },
        f"repos/{readiness.DEFAULT_REPOSITORY}/actions/artifacts?per_page=100&page=1": {
            "artifacts": []
        },
    }
    for workflow_path, workflow_name in readiness.WORKFLOW_CONTRACTS.items():
        content = f"name: {workflow_name}\non:\n  workflow_dispatch:\n"
        local = tmp_path / workflow_path
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(content, encoding="utf-8")
        responses[
            f"repos/{readiness.DEFAULT_REPOSITORY}/contents/{workflow_path}?ref=main"
        ] = {"content": base64.b64encode(content.encode()).decode()}
        responses[
            "repos/"
            f"{readiness.DEFAULT_REPOSITORY}/actions/workflows/"
            f"{Path(workflow_path).name}/runs?per_page=100"
        ] = {"workflow_runs": []}
    for source_path in readiness.PROTECTED_RELEASE_SOURCE_PATHS:
        content = f"protected staging source: {source_path}\n"
        local = tmp_path / source_path
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(content, encoding="utf-8")
        responses[
            f"repos/{readiness.DEFAULT_REPOSITORY}/contents/{source_path}?ref=main"
        ] = {"content": base64.b64encode(content.encode()).decode()}

    requested: list[str] = []

    def api(endpoint: str) -> object:
        requested.append(endpoint)
        return responses[endpoint]

    snapshot = readiness.collect_repository_snapshot(
        readiness.DEFAULT_REPOSITORY,
        root=tmp_path,
        api=api,
    )

    assert snapshot["default_branch"] == "main"
    assert snapshot["default_branch_protected"] is True
    assert all(
        item["local_sha256"] == item["remote_sha256"]
        for item in snapshot["workflows"].values()
    )
    assert all(
        item["local_sha256"] == item["remote_sha256"]
        for item in snapshot["protected_release_sources"].values()
    )
    assert all(endpoint.startswith("repos/") for endpoint in requested)


def test_cli_evaluate_writes_blocked_report(tmp_path: Path, capsys):
    snapshot = _snapshot()
    snapshot["runners"] = []
    source = tmp_path / "snapshot.json"
    source.write_text(json.dumps(snapshot), encoding="utf-8")
    output = tmp_path / "readiness.json"

    result = readiness.main(
        ["evaluate", "--snapshot", str(source), "--output", str(output)]
    )

    assert result == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "blocked"
    assert report["gates"]["runner_ready"] is False
    assert json.loads(capsys.readouterr().out) == report
