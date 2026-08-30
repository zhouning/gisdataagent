"""Collect and assess protected staging readiness without changing remote state."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

READINESS_SCHEMA = "gda.staging_environment_readiness.v2"
DEFAULT_REPOSITORY = "zhouning/gisdataagent"

WORKFLOW_CONTRACTS = {
    ".github/workflows/cd-staging.yml": "Publish - Staging Candidate Image",
    ".github/workflows/verify-staging-provenance.yml": (
        "Verify - Staging Image Provenance"
    ),
    ".github/workflows/deploy-staging-live.yml": (
        "Deploy - Protected Live Staging"
    ),
    ".github/workflows/verify-staging-golden.yml": (
        "Verify - Protected Staging Golden Slice"
    ),
}

# These files execute before a candidate can be admitted or after an immutable
# release has been selected.  Checking only the workflow YAML can therefore
# produce a false-ready result when the protected verifier source is absent or
# differs on the default branch.
PROTECTED_RELEASE_SOURCE_PATHS = (
    "data_agent/staging_candidate_evidence.py",
    "data_agent/staging_registry_evidence.py",
    "data_agent/staging_provenance_evidence.py",
    "data_agent/staging_release_evidence.py",
    "data_agent/staging_platform_preflight.py",
    # The preflight Job runs this module from the attested candidate image.
    # Keep it in the release-source contract so a missing runtime entry point
    # cannot be discovered only after a protected deployment starts.
    "data_agent/staging_platform_snapshot.py",
    "data_agent/staging_workload_manifest.py",
    "data_agent/staging_live_evidence.py",
    "data_agent/staging_golden_slice.py",
    "data_agent/staging_golden_ledger.sql",
)

PROVENANCE_VARIABLES = {
    "GDA_STAGING_PROVENANCE_PROTECTED": "true",
}
LIVE_EXACT_VARIABLES = {
    "GDA_STAGING_LIVE_PROTECTED": "true",
    "GDA_STAGING_NAMESPACE": "gis-agent-staging",
}
LIVE_REQUIRED_VARIABLES = (
    "GDA_STAGING_CLUSTER_UID",
    "GDA_STAGING_NAMESPACE_UID",
    "GDA_STAGING_CONFIG_MAP",
    "GDA_STAGING_SECRET",
    "GDA_STAGING_IMAGE_PULL_SECRET",
    "GDA_STAGING_GOLDEN_TENANT_ID",
    "GDA_STAGING_GOLDEN_CAPABILITY_ID",
    "GDA_STAGING_GOLDEN_DEFINITION_VERSION_ID",
    "GDA_STAGING_GOLDEN_INPUT_RESOURCE_VERSION_ID",
)
LIVE_REQUIRED_SECRETS = (
    "GDA_STAGING_KUBECONFIG_B64",
    "GDA_STAGING_OBSERVER_KUBECONFIG_B64",
)
RUNNER_LABELS = frozenset({"self-hosted", "linux", "gda-staging"})


class StagingReadinessError(ValueError):
    """Raised when a readiness input or remote response is invalid."""


class GitHubReadError(RuntimeError):
    """Raised when a read-only GitHub API request fails."""


class GitHubNotFoundError(GitHubReadError):
    """Raised when GitHub confirms that an optional resource is absent."""


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _workflow_name(content: str) -> str | None:
    match = re.search(r"(?m)^name:\s*([^#\r\n]+?)\s*$", content)
    if match is None:
        return None
    return match.group(1).strip('"\'')


def _gh_json(endpoint: str) -> Any:
    try:
        completed = subprocess.run(
            ["gh", "api", endpoint],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitHubReadError(f"GitHub API request could not run: {endpoint}") from exc
    if completed.returncode != 0:
        message = completed.stderr.strip().splitlines()
        detail = message[-1] if message else "request failed"
        error_type = (
            GitHubNotFoundError
            if re.search(r"(?:HTTP\s+404|\bNot Found\b)", detail, re.IGNORECASE)
            else GitHubReadError
        )
        raise error_type(f"GitHub API read failed for {endpoint}: {detail}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise GitHubReadError(
            f"GitHub API returned invalid JSON for {endpoint}"
        ) from exc


def _read_endpoint(
    endpoint: str,
    *,
    api: Callable[[str], Any],
    default: Any,
    allow_not_found: bool = False,
) -> tuple[Any, str | None]:
    try:
        return api(endpoint), None
    except GitHubNotFoundError:
        if allow_not_found:
            return default, None
        raise
    except GitHubReadError as exc:
        return default, str(exc)


def _collect_artifacts(
    repository: str,
    *,
    api: Callable[[str], Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    artifacts: list[dict[str, Any]] = []
    errors: list[str] = []
    for page in range(1, 11):
        endpoint = (
            f"repos/{repository}/actions/artifacts?per_page=100&page={page}"
        )
        payload, error = _read_endpoint(
            endpoint,
            api=api,
            default={},
            allow_not_found=True,
        )
        if error is not None:
            errors.append(error)
            break
        batch = payload.get("artifacts", []) if isinstance(payload, Mapping) else []
        if not isinstance(batch, list):
            errors.append(f"GitHub API returned invalid artifacts payload: {endpoint}")
            break
        artifacts.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < 100:
            break
    return artifacts, errors


def collect_repository_snapshot(
    repository: str,
    *,
    root: Path,
    cluster_observation: Mapping[str, Any] | None = None,
    api: Callable[[str], Any] = _gh_json,
) -> dict[str, Any]:
    """Collect only metadata, names, and public workflow/run information."""

    repository_payload, repository_error = _read_endpoint(
        f"repos/{repository}", api=api, default={}
    )
    default_branch = (
        repository_payload.get("default_branch")
        if isinstance(repository_payload, Mapping)
        else None
    )
    branch_payload: Mapping[str, Any] = {}
    branch_error = None
    if isinstance(default_branch, str) and default_branch:
        raw_branch, branch_error = _read_endpoint(
            f"repos/{repository}/branches/{default_branch}",
            api=api,
            default={},
        )
        if isinstance(raw_branch, Mapping):
            branch_payload = raw_branch
    workflows: dict[str, dict[str, Any]] = {}
    errors = [
        item for item in (repository_error, branch_error) if item is not None
    ]

    for workflow_path, expected_name in WORKFLOW_CONTRACTS.items():
        local_path = root / workflow_path
        local_exists = local_path.is_file()
        local_digest = _file_sha256(local_path) if local_exists else None
        endpoint = f"repos/{repository}/contents/{workflow_path}"
        if default_branch:
            endpoint += f"?ref={default_branch}"
        payload, error = _read_endpoint(
            endpoint,
            api=api,
            default={},
            allow_not_found=True,
        )
        remote_content: str | None = None
        if error is None and isinstance(payload, Mapping):
            encoded = payload.get("content")
            if isinstance(encoded, str):
                try:
                    remote_content = base64.b64decode(encoded).decode("utf-8")
                except (ValueError, UnicodeDecodeError):
                    error = f"remote workflow content is invalid: {workflow_path}"
        if error:
            errors.append(error)
        workflows[workflow_path] = {
            "expected_name": expected_name,
            "local_exists": local_exists,
            "local_sha256": local_digest,
            "remote_exists": remote_content is not None,
            "remote_name": (
                _workflow_name(remote_content) if remote_content is not None else None
            ),
            "remote_sha256": (
                hashlib.sha256(remote_content.encode("utf-8")).hexdigest()
                if remote_content is not None
                else None
            ),
            "read_error": error,
        }

    protected_release_sources: dict[str, dict[str, Any]] = {}
    for source_path in PROTECTED_RELEASE_SOURCE_PATHS:
        local_path = root / source_path
        local_exists = local_path.is_file()
        endpoint = f"repos/{repository}/contents/{source_path}"
        if default_branch:
            endpoint += f"?ref={default_branch}"
        payload, error = _read_endpoint(
            endpoint,
            api=api,
            default={},
            allow_not_found=True,
        )
        remote_content: bytes | None = None
        if error is None and isinstance(payload, Mapping):
            encoded = payload.get("content")
            if isinstance(encoded, str):
                try:
                    remote_content = base64.b64decode(encoded)
                except ValueError:
                    error = f"remote protected source is invalid: {source_path}"
        if error:
            errors.append(error)
        protected_release_sources[source_path] = {
            "local_exists": local_exists,
            "local_sha256": _file_sha256(local_path) if local_exists else None,
            "remote_exists": remote_content is not None,
            "remote_sha256": (
                hashlib.sha256(remote_content).hexdigest()
                if remote_content is not None
                else None
            ),
            "read_error": error,
        }

    environment_list, error = _read_endpoint(
        f"repos/{repository}/environments?per_page=100", api=api, default={}
    )
    if error:
        errors.append(error)
    environment_names = {
        item.get("name")
        for item in (
            environment_list.get("environments", [])
            if isinstance(environment_list, Mapping)
            else []
        )
        if isinstance(item, Mapping) and isinstance(item.get("name"), str)
    }
    environments: dict[str, dict[str, Any]] = {}
    for environment_name in ("staging-provenance", "staging-live"):
        if environment_name not in environment_names:
            environments[environment_name] = {
                "exists": False,
                "variables": {},
                "secret_names": [],
            }
            continue
        detail, detail_error = _read_endpoint(
            f"repos/{repository}/environments/{environment_name}",
            api=api,
            default={},
        )
        variables_payload, variables_error = _read_endpoint(
            f"repos/{repository}/environments/{environment_name}/variables",
            api=api,
            default={},
        )
        secrets_payload, secrets_error = _read_endpoint(
            f"repos/{repository}/environments/{environment_name}/secrets",
            api=api,
            default={},
        )
        errors.extend(
            item
            for item in (detail_error, variables_error, secrets_error)
            if item is not None
        )
        variables = {
            item["name"]: item.get("value")
            for item in (
                variables_payload.get("variables", [])
                if isinstance(variables_payload, Mapping)
                else []
            )
            if isinstance(item, Mapping) and isinstance(item.get("name"), str)
        }
        secret_names = sorted(
            item["name"]
            for item in (
                secrets_payload.get("secrets", [])
                if isinstance(secrets_payload, Mapping)
                else []
            )
            if isinstance(item, Mapping) and isinstance(item.get("name"), str)
        )
        environments[environment_name] = {
            "exists": True,
            "can_admins_bypass": detail.get("can_admins_bypass"),
            "protection_rules": detail.get("protection_rules", []),
            "deployment_branch_policy": detail.get("deployment_branch_policy"),
            "variables": variables,
            "secret_names": secret_names,
        }

    runners_payload, error = _read_endpoint(
        f"repos/{repository}/actions/runners?per_page=100", api=api, default={}
    )
    if error:
        errors.append(error)
    runners = (
        runners_payload.get("runners", [])
        if isinstance(runners_payload, Mapping)
        else []
    )

    workflow_runs: dict[str, list[dict[str, Any]]] = {}
    for workflow_path in WORKFLOW_CONTRACTS:
        workflow_file = Path(workflow_path).name
        payload, run_error = _read_endpoint(
            f"repos/{repository}/actions/workflows/{workflow_file}/runs?per_page=100",
            api=api,
            default={},
            allow_not_found=True,
        )
        if run_error:
            errors.append(run_error)
        runs = payload.get("workflow_runs", []) if isinstance(payload, Mapping) else []
        workflow_runs[workflow_path] = [
            item for item in runs if isinstance(item, dict)
        ]

    artifacts, artifact_errors = _collect_artifacts(repository, api=api)
    errors.extend(artifact_errors)
    return {
        "repository": repository,
        "default_branch": default_branch,
        "default_branch_protected": branch_payload.get("protected") is True,
        "workflows": workflows,
        "protected_release_sources": protected_release_sources,
        "environments": environments,
        "runners": [item for item in runners if isinstance(item, dict)],
        "workflow_runs": workflow_runs,
        "artifacts": artifacts,
        "cluster_observation": dict(cluster_observation or {}),
        "collection_errors": errors,
    }


def _required_reviewer_protection(environment: Mapping[str, Any]) -> dict[str, Any]:
    rules = environment.get("protection_rules", [])
    reviewer_rules = [
        rule
        for rule in rules
        if isinstance(rule, Mapping) and rule.get("type") == "required_reviewers"
    ]
    reviewer_count = sum(
        len(rule.get("reviewers", []))
        for rule in reviewer_rules
        if isinstance(rule.get("reviewers", []), list)
    )
    prevent_self_review = bool(reviewer_rules) and all(
        rule.get("prevent_self_review") is True for rule in reviewer_rules
    )
    branch_policy = environment.get("deployment_branch_policy")
    protected_branches_only = bool(
        isinstance(branch_policy, Mapping)
        and branch_policy.get("protected_branches") is True
        and branch_policy.get("custom_branch_policies") is False
    )
    no_admin_bypass = environment.get("can_admins_bypass") is False
    ready = (
        environment.get("exists") is True
        and reviewer_count > 0
        and prevent_self_review
        and protected_branches_only
        and no_admin_bypass
    )
    return {
        "ready": ready,
        "required_reviewer_count": reviewer_count,
        "prevent_self_review": prevent_self_review,
        "protected_branches_only": protected_branches_only,
        "admin_bypass_disabled": no_admin_bypass,
    }


def _variable_contract(
    environment: Mapping[str, Any],
    *,
    exact: Mapping[str, str],
    required: Sequence[str] = (),
    secrets: Sequence[str] = (),
) -> dict[str, Any]:
    variables = environment.get("variables", {})
    if not isinstance(variables, Mapping):
        variables = {}
    secret_names = environment.get("secret_names", [])
    if not isinstance(secret_names, list):
        secret_names = []
    exact_checks = [
        {
            "name": name,
            "configured": name in variables,
            "expected_value_matches": variables.get(name) == expected,
        }
        for name, expected in exact.items()
    ]
    variable_checks = [
        {
            "name": name,
            "configured": (
                name in variables
                and isinstance(variables.get(name), str)
                and bool(str(variables.get(name)).strip())
            ),
        }
        for name in required
    ]
    secret_checks = [
        {"name": name, "configured": name in secret_names} for name in secrets
    ]
    ready = (
        environment.get("exists") is True
        and all(item["expected_value_matches"] for item in exact_checks)
        and all(item["configured"] for item in variable_checks)
        and all(item["configured"] for item in secret_checks)
    )
    return {
        "ready": ready,
        "exact_variables": exact_checks,
        "required_variables": variable_checks,
        "required_secrets": secret_checks,
    }


def _runner_readiness(runners: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    eligible = []
    for runner in runners:
        labels = {
            label.get("name")
            for label in runner.get("labels", [])
            if isinstance(label, Mapping)
        }
        if (
            runner.get("status") == "online"
            and RUNNER_LABELS.issubset(labels)
        ):
            eligible.append(
                {
                    "id": runner.get("id"),
                    "online": True,
                    "busy": runner.get("busy") is True,
                    "required_labels_present": True,
                }
            )
    return {
        "ready": bool(eligible),
        "required_labels": sorted(RUNNER_LABELS),
        "eligible_runners": eligible,
    }


def _artifact_names_for_run(
    artifacts: Sequence[Mapping[str, Any]], run_id: int
) -> set[str]:
    names = set()
    for artifact in artifacts:
        workflow_run = artifact.get("workflow_run")
        if (
            artifact.get("expired") is False
            and isinstance(workflow_run, Mapping)
            and workflow_run.get("id") == run_id
            and isinstance(artifact.get("name"), str)
        ):
            names.add(str(artifact["name"]))
    return names


def _run_matches(
    run: Mapping[str, Any], *, event: str, conclusion: str
) -> bool:
    return (
        run.get("event") == event
        and run.get("head_branch") == "main"
        and run.get("status") == "completed"
        and run.get("conclusion") == conclusion
        and isinstance(run.get("id"), int)
    )


def _stage_evidence(
    runs: Sequence[Mapping[str, Any]],
    artifacts: Sequence[Mapping[str, Any]],
    *,
    event: str,
    conclusion: str,
    exact_names: Sequence[str] = (),
    prefixes: Sequence[str] = (),
) -> dict[str, Any]:
    latest_observed = None
    if runs:
        latest = runs[0]
        latest_observed = {
            "run_id": latest.get("id"),
            "event": latest.get("event"),
            "head_branch": latest.get("head_branch"),
            "conclusion": latest.get("conclusion"),
            "eligible": _run_matches(
                latest, event=event, conclusion=conclusion
            ),
        }
    for run in runs:
        if not _run_matches(run, event=event, conclusion=conclusion):
            continue
        run_id = int(run["id"])
        names = _artifact_names_for_run(artifacts, run_id)
        exact_ready = all(name in names for name in exact_names)
        prefix_ready = all(
            any(name.startswith(prefix) for name in names) for prefix in prefixes
        )
        if exact_ready and prefix_ready:
            return {
                "ready": True,
                "run_id": run_id,
                "source_revision": run.get("head_sha"),
                "latest_observed_run": latest_observed,
            }
    return {
        "ready": False,
        "run_id": None,
        "source_revision": None,
        "latest_observed_run": latest_observed,
    }


def _kubernetes_readiness(
    live_environment: Mapping[str, Any],
    observation: Mapping[str, Any],
) -> dict[str, Any]:
    variables = live_environment.get("variables", {})
    if not isinstance(variables, Mapping):
        variables = {}
    expected_cluster_uid = variables.get("GDA_STAGING_CLUSTER_UID")
    expected_namespace_uid = variables.get("GDA_STAGING_NAMESPACE_UID")
    expected_namespace = variables.get("GDA_STAGING_NAMESPACE")
    observed = bool(observation)
    cluster_matches = bool(
        observed
        and expected_cluster_uid
        and observation.get("cluster_uid") == expected_cluster_uid
    )
    namespace_matches = bool(
        observed
        and expected_namespace_uid
        and expected_namespace
        and observation.get("namespace_uid") == expected_namespace_uid
        and observation.get("namespace_name") == expected_namespace
    )
    deploy_authorized = observation.get("deploy_identity_authorized") is True
    observer_read_only = observation.get("observer_identity_read_only") is True
    return {
        "ready": (
            observed
            and cluster_matches
            and namespace_matches
            and deploy_authorized
            and observer_read_only
        ),
        "observed": observed,
        "cluster_identity_matches": cluster_matches,
        "namespace_identity_matches": namespace_matches,
        "deploy_identity_authorized": deploy_authorized,
        "observer_identity_read_only": observer_read_only,
    }


def assess_readiness(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    workflows = snapshot.get("workflows", {})
    if not isinstance(workflows, Mapping):
        raise StagingReadinessError("workflow snapshot must be an object")
    workflow_checks = []
    for path, expected_name in WORKFLOW_CONTRACTS.items():
        item = workflows.get(path, {})
        if not isinstance(item, Mapping):
            item = {}
        matches_local = bool(
            item.get("local_exists") is True
            and item.get("remote_exists") is True
            and item.get("local_sha256") == item.get("remote_sha256")
        )
        name_matches = item.get("remote_name") == expected_name
        workflow_checks.append(
            {
                "path": path,
                "expected_name": expected_name,
                "remote_exists": item.get("remote_exists") is True,
                "name_matches": name_matches,
                "matches_local_contract": matches_local,
                "ready": matches_local and name_matches,
            }
        )
    repository_workflows_ready = (
        snapshot.get("default_branch") == "main"
        and snapshot.get("default_branch_protected") is True
        and all(item["ready"] for item in workflow_checks)
    )

    raw_protected_sources = snapshot.get("protected_release_sources", {})
    if not isinstance(raw_protected_sources, Mapping):
        raise StagingReadinessError(
            "protected release source snapshot must be an object"
        )
    protected_source_checks = []
    for path in PROTECTED_RELEASE_SOURCE_PATHS:
        item = raw_protected_sources.get(path, {})
        if not isinstance(item, Mapping):
            item = {}
        matches_local = bool(
            item.get("local_exists") is True
            and item.get("remote_exists") is True
            and item.get("local_sha256") == item.get("remote_sha256")
        )
        protected_source_checks.append(
            {
                "path": path,
                "remote_exists": item.get("remote_exists") is True,
                "matches_local_contract": matches_local,
                "ready": matches_local,
            }
        )
    protected_release_sources_ready = (
        snapshot.get("default_branch") == "main"
        and snapshot.get("default_branch_protected") is True
        and all(item["ready"] for item in protected_source_checks)
    )
    raw_collection_errors = snapshot.get("collection_errors", [])
    collection_errors = [
        error
        for error in raw_collection_errors
        if isinstance(error, str) and error.strip()
    ] if isinstance(raw_collection_errors, list) else []
    repository_metadata_reads_complete = not collection_errors

    environments = snapshot.get("environments", {})
    if not isinstance(environments, Mapping):
        environments = {}
    provenance_environment = environments.get("staging-provenance", {})
    live_environment = environments.get("staging-live", {})
    if not isinstance(provenance_environment, Mapping):
        provenance_environment = {}
    if not isinstance(live_environment, Mapping):
        live_environment = {}

    provenance_protection = _required_reviewer_protection(provenance_environment)
    live_protection = _required_reviewer_protection(live_environment)
    provenance_configuration = _variable_contract(
        provenance_environment,
        exact=PROVENANCE_VARIABLES,
    )
    live_configuration = _variable_contract(
        live_environment,
        exact=LIVE_EXACT_VARIABLES,
        required=LIVE_REQUIRED_VARIABLES,
        secrets=LIVE_REQUIRED_SECRETS,
    )
    protected_environment_metadata_ready = (
        provenance_protection["ready"] and live_protection["ready"]
    )
    required_configuration_ready = (
        provenance_configuration["ready"] and live_configuration["ready"]
    )

    raw_runners = snapshot.get("runners", [])
    runner = _runner_readiness(
        [item for item in raw_runners if isinstance(item, Mapping)]
        if isinstance(raw_runners, list)
        else []
    )
    observation = snapshot.get("cluster_observation", {})
    if not isinstance(observation, Mapping):
        observation = {}
    kubernetes = _kubernetes_readiness(live_environment, observation)

    workflow_runs = snapshot.get("workflow_runs", {})
    if not isinstance(workflow_runs, Mapping):
        workflow_runs = {}
    raw_artifacts = snapshot.get("artifacts", [])
    artifacts = (
        [item for item in raw_artifacts if isinstance(item, Mapping)]
        if isinstance(raw_artifacts, list)
        else []
    )
    candidate = _stage_evidence(
        workflow_runs.get(".github/workflows/cd-staging.yml", []),
        artifacts,
        event="workflow_dispatch",
        conclusion="success",
        prefixes=(
            "staging-candidate-evidence-",
            "staging-registry-evidence-",
        ),
    )
    provenance = _stage_evidence(
        workflow_runs.get(
            ".github/workflows/verify-staging-provenance.yml", []
        ),
        artifacts,
        event="workflow_run",
        conclusion="success",
        exact_names=("staging-release-evidence",),
        prefixes=("staging-provenance-evidence-",),
    )
    deployment = _stage_evidence(
        workflow_runs.get(".github/workflows/deploy-staging-live.yml", []),
        artifacts,
        event="workflow_run",
        conclusion="failure",
        prefixes=("staging-live-observation-",),
    )
    golden = _stage_evidence(
        workflow_runs.get(".github/workflows/verify-staging-golden.yml", []),
        artifacts,
        event="workflow_dispatch",
        conclusion="success",
        prefixes=("staging-golden-evidence-",),
    )
    evidence_chain_complete = all(
        stage["ready"] for stage in (candidate, provenance, deployment, golden)
    )

    gates = {
        "repository_workflows_ready": repository_workflows_ready,
        "protected_release_sources_ready": protected_release_sources_ready,
        "repository_metadata_reads_complete": repository_metadata_reads_complete,
        "protected_environment_metadata_ready": (
            protected_environment_metadata_ready
        ),
        "runner_ready": runner["ready"],
        "required_configuration_ready": required_configuration_ready,
        "kubernetes_identity_ready": kubernetes["ready"],
        "candidate_artifacts_ready": candidate["ready"],
        "provenance_release_artifacts_ready": provenance["ready"],
        "deployment_observation_ready": deployment["ready"],
        "golden_evidence_ready": golden["ready"],
    }
    blocker_messages = {
        "repository_workflows_ready": (
            "Publish the reviewed four-workflow staging contract on main, "
            "together with its protected execution sources."
        ),
        "protected_release_sources_ready": (
            "Publish every reviewed protected staging verifier, renderer, and "
            "ledger source on main without drift."
        ),
        "repository_metadata_reads_complete": (
            "Repeat the read-only GitHub readiness collection until every "
            "required metadata endpoint is observed without an API error."
        ),
        "protected_environment_metadata_ready": (
            "Create both protected environments with required review, no admin "
            "bypass, prevent-self-review, and protected-branch policy."
        ),
        "runner_ready": (
            "Provision an online self-hosted Linux runner labelled gda-staging."
        ),
        "required_configuration_ready": (
            "Configure all required staging-live variable and secret names."
        ),
        "kubernetes_identity_ready": (
            "Record an authorized cluster/namespace and least-privilege identity "
            "observation; configured UIDs alone are not proof."
        ),
        "candidate_artifacts_ready": (
            "Run the main-only candidate publisher and retain candidate plus "
            "registry evidence."
        ),
        "provenance_release_artifacts_ready": (
            "Approve protected provenance verification and retain its release bundle."
        ),
        "deployment_observation_ready": (
            "Apply the admitted digest to protected staging and retain the "
            "intentional fail-closed deployment observation."
        ),
        "golden_evidence_ready": (
            "Complete a post-rollout governed Run and verify its golden evidence."
        ),
    }
    blockers = [
        {"gate": gate, "message": blocker_messages[gate]}
        for gate, ready in gates.items()
        if not ready
    ]
    stable = {
        "schema": READINESS_SCHEMA,
        "repository": snapshot.get("repository"),
        "default_branch": snapshot.get("default_branch"),
        "default_branch_protected": (
            snapshot.get("default_branch_protected") is True
        ),
        "status": "ready" if not blockers else "blocked",
        "ar0_status": "in_progress",
        "production_promotion_allowed": False,
        # Keep endpoint/read failures visible without exposing any environment
        # variable or secret values. A blocked report must explain whether a
        # resource is absent or the read itself was incomplete.
        "collection_errors": collection_errors,
        "gates": gates,
        "repository_workflows": workflow_checks,
        "protected_release_sources": protected_source_checks,
        "protected_environments": {
            "staging-provenance": {
                "exists": provenance_environment.get("exists") is True,
                "protection": provenance_protection,
                "configuration": provenance_configuration,
            },
            "staging-live": {
                "exists": live_environment.get("exists") is True,
                "protection": live_protection,
                "configuration": live_configuration,
            },
        },
        "runner": runner,
        "kubernetes_identity": kubernetes,
        "evidence_chain": {
            "all_required_artifacts_observed": evidence_chain_complete,
            "artifact_metadata_only": True,
            "content_binding_verified": False,
            "candidate": candidate,
            "provenance_release": provenance,
            "deployment_observation": deployment,
            "golden": golden,
        },
        "blockers": blockers,
        "next_required_action": blockers[0] if blockers else None,
    }
    return {
        **stable,
        "observed_at": datetime.now(UTC).isoformat(),
        "evidence_fingerprint": _canonical_sha256(stable),
    }


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise StagingReadinessError(f"JSON input must be an object: {path}")
    return payload


def _write_report(report: Mapping[str, Any], output: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect = subparsers.add_parser("collect")
    collect.add_argument("--repository", default=DEFAULT_REPOSITORY)
    collect.add_argument("--root", type=Path, default=Path.cwd())
    collect.add_argument("--cluster-observation", type=Path)
    collect.add_argument("--output", type=Path)
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--snapshot", type=Path, required=True)
    evaluate.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.command == "collect":
            cluster_observation = (
                _load_json_object(args.cluster_observation)
                if args.cluster_observation
                else None
            )
            snapshot = collect_repository_snapshot(
                args.repository,
                root=args.root.resolve(),
                cluster_observation=cluster_observation,
            )
        else:
            snapshot = _load_json_object(args.snapshot)
        report = assess_readiness(snapshot)
    except (
        OSError,
        json.JSONDecodeError,
        GitHubReadError,
        StagingReadinessError,
    ) as exc:
        report = {
            "schema": READINESS_SCHEMA,
            "status": "blocked",
            "ar0_status": "in_progress",
            "production_promotion_allowed": False,
            "error": str(exc),
        }
    _write_report(report, args.output)
    return 0 if report.get("status") == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
