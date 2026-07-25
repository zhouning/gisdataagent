"""Validate the inert Kubernetes contract for the DolphinScheduler worker."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPORT_SCHEMA = "gda.dolphinscheduler_worker_deployment.v1"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "k8s/base/dolphinscheduler-command-worker.yaml"
DEFAULT_KUSTOMIZATION = REPO_ROOT / "k8s/base/kustomization.yaml"
DEFAULT_NETWORK_POLICY = REPO_ROOT / "k8s/base/networkpolicy.yaml"
DEPLOYMENT_NAME = "gis-agent-dolphinscheduler-command-worker"
CONFIG_NAME = "gis-agent-dolphinscheduler-command-worker"
SECRET_NAME = "gis-agent-dolphinscheduler-command-worker"
TOKEN_FILE = "/var/run/gis-agent/dolphinscheduler/access-token"
STATUS_FILE = "/var/run/gis-agent/worker/status.json"

REQUIRED_LITERAL_ENV = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "DOLPHINSCHEDULER_COMMAND_WORKER_ENABLED": "true",
    "DOLPHINSCHEDULER_TOKEN_FILE": TOKEN_FILE,
    "DOLPHINSCHEDULER_COMMAND_STATUS_FILE": STATUS_FILE,
    "DOLPHINSCHEDULER_COMMAND_BATCH_SIZE": "1",
    "DOLPHINSCHEDULER_REQUEST_TIMEOUT_SECONDS": "15",
    "DOLPHINSCHEDULER_RECONCILIATION_PAGE_LIMIT": "5",
    "DOLPHINSCHEDULER_COMMAND_LEASE_SECONDS": "300",
    "DOLPHINSCHEDULER_COMMAND_POLL_INTERVAL_SECONDS": "5",
    "DOLPHINSCHEDULER_COMMAND_HEALTH_MAX_AGE_SECONDS": "30",
}
REQUIRED_CONFIG_ENV = {
    "DOLPHINSCHEDULER_BASE_URL": "base-url",
    "DOLPHINSCHEDULER_PROJECT_CODE": "project-code",
    "DOLPHINSCHEDULER_WORKLOAD_SUBJECT": "workload-subject",
    "DOLPHINSCHEDULER_POLICY_EVALUATOR_SUBJECT": (
        "policy-evaluator-subject"
    ),
    "DOLPHINSCHEDULER_COMMAND_TENANT_ID": "command-tenant-id",
    "DOLPHINSCHEDULER_TENANT_CODE": "provider-tenant-code",
    "DOLPHINSCHEDULER_WORKER_GROUP": "provider-worker-group",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_documents(path: Path) -> list[dict[str, Any]]:
    documents = yaml.safe_load_all(path.read_text(encoding="utf-8"))
    return [item for item in documents if isinstance(item, dict)]


def _resource(
    documents: list[dict[str, Any]], kind: str, name: str
) -> dict[str, Any] | None:
    for document in documents:
        if document.get("kind") != kind:
            continue
        metadata = document.get("metadata") or {}
        if metadata.get("name") == name:
            return document
    return None


def _named(items: Any, name: str) -> dict[str, Any] | None:
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get("name") == name:
            return item
    return None


def _command_text(container: dict[str, Any]) -> str:
    values = list(container.get("command") or []) + list(container.get("args") or [])
    return "\n".join(str(value) for value in values)


def _env_index(container: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    entries = container.get("env") or []
    names = [entry.get("name") for entry in entries if isinstance(entry, dict)]
    if len(names) != len(set(names)):
        errors.append("worker environment variable names must be unique")
    return {
        entry["name"]: entry
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }


def _validate_probe(
    container: dict[str, Any],
    probe_name: str,
    probe_command: str,
    errors: list[str],
) -> None:
    probe = container.get(probe_name) or {}
    command = ((probe.get("exec") or {}).get("command") or [])
    required = (
        "python",
        "-m",
        "data_agent.dolphinscheduler_command_worker",
        probe_command,
        "--status-file",
        STATUS_FILE,
        "--max-age-seconds",
    )
    try:
        max_age = float(command[len(required)])
    except (IndexError, TypeError, ValueError):
        max_age = 0
    if tuple(command[: len(required)]) != required or max_age <= 0:
        errors.append(f"{probe_name} must execute the worker {probe_command} command")


def build_deployment_report(
    manifest_path: Path | None = None,
    kustomization_path: Path | None = None,
    network_policy_path: Path | None = None,
) -> dict[str, Any]:
    """Validate deployment safety without claiming that it has been applied."""
    manifest = (manifest_path or DEFAULT_MANIFEST).resolve()
    kustomization = (kustomization_path or DEFAULT_KUSTOMIZATION).resolve()
    network_policy = (network_policy_path or DEFAULT_NETWORK_POLICY).resolve()
    errors: list[str] = []
    documents: list[dict[str, Any]] = []
    kustomization_document: dict[str, Any] = {}
    network_documents: list[dict[str, Any]] = []

    try:
        documents = _load_documents(manifest)
    except (OSError, yaml.YAMLError) as exc:
        errors.append(f"worker manifest is unavailable or invalid: {type(exc).__name__}")
    try:
        loaded = yaml.safe_load(kustomization.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            kustomization_document = loaded
        else:
            errors.append("Kustomization must be a YAML object")
    except (OSError, yaml.YAMLError) as exc:
        errors.append(f"Kustomization is unavailable or invalid: {type(exc).__name__}")
    try:
        network_documents = _load_documents(network_policy)
    except (OSError, yaml.YAMLError) as exc:
        errors.append(f"NetworkPolicy is unavailable or invalid: {type(exc).__name__}")

    deployment = _resource(documents, "Deployment", DEPLOYMENT_NAME)
    service_account = _resource(documents, "ServiceAccount", DEPLOYMENT_NAME)
    if deployment is None:
        errors.append("worker manifest must define the managed Deployment")
    if service_account is None:
        errors.append("worker manifest must define a dedicated ServiceAccount")
    if _resource(documents, "Role", DEPLOYMENT_NAME) is not None or _resource(
        documents, "RoleBinding", DEPLOYMENT_NAME
    ) is not None:
        errors.append("worker must not receive Kubernetes API RBAC")

    resources = kustomization_document.get("resources") or []
    if "dolphinscheduler-command-worker.yaml" not in resources:
        errors.append("base Kustomization must register the worker manifest")

    postgres_policy = _resource(network_documents, "NetworkPolicy", "postgres-access")
    if postgres_policy is None:
        errors.append("base must define the PostgreSQL NetworkPolicy")
    else:
        ingress = (postgres_policy.get("spec") or {}).get("ingress") or []
        sources = [
            source
            for rule in ingress
            if isinstance(rule, dict)
            for source in rule.get("from") or []
            if isinstance(source, dict)
        ]
        worker_allowed = any(
            ((source.get("podSelector") or {}).get("matchLabels") or {}).get(
                "app.kubernetes.io/name"
            )
            == DEPLOYMENT_NAME
            for source in sources
        )
        if not worker_allowed:
            errors.append("PostgreSQL NetworkPolicy must allow the worker Pod label")

    if deployment is not None:
        spec = deployment.get("spec") or {}
        if spec.get("replicas") != 0:
            errors.append("base worker Deployment must default to zero replicas")
        if (spec.get("strategy") or {}).get("type") != "RollingUpdate":
            errors.append("worker Deployment must use RollingUpdate")

        pod = ((spec.get("template") or {}).get("spec") or {})
        if pod.get("serviceAccountName") != DEPLOYMENT_NAME:
            errors.append("worker must use its dedicated ServiceAccount")
        if pod.get("automountServiceAccountToken") is not False:
            errors.append("worker must not mount a Kubernetes API token")
        if int(pod.get("terminationGracePeriodSeconds") or 0) < 120:
            errors.append("worker termination grace period must be at least 120 seconds")

        worker = _named(pod.get("containers"), "worker")
        token_init = _named(pod.get("initContainers"), "prepare-provider-token")
        if worker is None:
            errors.append("worker Deployment must define the worker container")
        else:
            command = _command_text(worker)
            for marker in (
                'DOLPHINSCHEDULER_COMMAND_WORKER_ID="worker:dolphinscheduler:${POD_UID}"',
                "exec python -m data_agent.dolphinscheduler_command_worker run",
            ):
                if marker not in command:
                    errors.append(f"worker command is missing marker: {marker}")
            if worker.get("envFrom"):
                errors.append("worker must not import broad ConfigMap or Secret environments")

            environment = _env_index(worker, errors)
            for name, value in REQUIRED_LITERAL_ENV.items():
                if (environment.get(name) or {}).get("value") != value:
                    errors.append(f"worker environment must pin {name}")
            for name, key in REQUIRED_CONFIG_ENV.items():
                reference = (
                    ((environment.get(name) or {}).get("valueFrom") or {}).get(
                        "configMapKeyRef"
                    )
                    or {}
                )
                if reference.get("name") != CONFIG_NAME or reference.get("key") != key:
                    errors.append(f"worker environment must source {name} from ConfigMap")

            database_reference = (
                ((environment.get("DATABASE_URL") or {}).get("valueFrom") or {}).get(
                    "secretKeyRef"
                )
                or {}
            )
            if database_reference != {"name": SECRET_NAME, "key": "database-url"}:
                errors.append("worker DATABASE_URL must use its dedicated Secret key")
            pod_uid_reference = (
                ((environment.get("POD_UID") or {}).get("valueFrom") or {}).get(
                    "fieldRef"
                )
                or {}
            )
            if pod_uid_reference.get("fieldPath") != "metadata.uid":
                errors.append("worker ID must derive from the Kubernetes Pod UID")
            if "DOLPHINSCHEDULER_COMMAND_WORKER_ID" in environment:
                errors.append("worker ID must not be shared as a static environment value")
            for name in environment:
                if "TOKEN" in name and name != "DOLPHINSCHEDULER_TOKEN_FILE":
                    errors.append("provider token must not be injected as an environment value")

            mounts = {
                item.get("name")
                for item in worker.get("volumeMounts") or []
                if isinstance(item, dict)
            }
            if "worker-runtime" not in mounts or "provider-token-source" in mounts:
                errors.append("worker may mount runtime files but not the raw token Secret")
            for probe_name, probe_command in (
                ("startupProbe", "liveness"),
                ("readinessProbe", "health"),
                ("livenessProbe", "liveness"),
            ):
                _validate_probe(worker, probe_name, probe_command, errors)
            startup_probe = worker.get("startupProbe") or {}
            startup_window = int(startup_probe.get("periodSeconds") or 0) * int(
                startup_probe.get("failureThreshold") or 0
            )
            if startup_window < 600:
                errors.append("worker startup probe must tolerate ten minutes of recovery")
            security = worker.get("securityContext") or {}
            if security.get("allowPrivilegeEscalation") is not False:
                errors.append("worker must disable privilege escalation")
            if security.get("readOnlyRootFilesystem") is not True:
                errors.append("worker root filesystem must be read-only")

        if token_init is None:
            errors.append("worker must prepare an owner-only provider token file")
        else:
            token_command = _command_text(token_init)
            for marker in ("-m 0600", "-o agent", TOKEN_FILE):
                if marker not in token_command:
                    errors.append(f"token init command is missing marker: {marker}")
            if (token_init.get("securityContext") or {}).get("runAsUser") != 0:
                errors.append("token init must run as root only to set file ownership")

        volumes = {
            item.get("name"): item
            for item in pod.get("volumes") or []
            if isinstance(item, dict)
        }
        token_secret = (volumes.get("provider-token-source") or {}).get("secret") or {}
        if token_secret.get("secretName") != SECRET_NAME:
            errors.append("raw provider token must come from the dedicated Secret")
        if token_secret.get("defaultMode") != 0o400:
            errors.append("raw provider token projection must use mode 0400")
        runtime_volume = (volumes.get("worker-runtime") or {}).get("emptyDir") or {}
        if runtime_volume.get("medium") != "Memory":
            errors.append("worker token and status runtime volume must be memory-backed")

    files: dict[str, dict[str, str]] = {}
    for name, path in (
        ("manifest", manifest),
        ("kustomization", kustomization),
        ("network_policy", network_policy),
    ):
        if path.is_file():
            files[name] = {"path": path.as_posix(), "sha256": _sha256(path)}
    return {
        "schema": REPORT_SCHEMA,
        "status": "valid" if not errors else "invalid",
        "deployment_name": DEPLOYMENT_NAME,
        "default_replicas": (
            ((deployment or {}).get("spec") or {}).get("replicas")
        ),
        "resource_count": len(documents),
        "files": files,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate",))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--kustomization", type=Path, default=DEFAULT_KUSTOMIZATION)
    parser.add_argument("--network-policy", type=Path, default=DEFAULT_NETWORK_POLICY)
    args = parser.parse_args(argv)
    report = build_deployment_report(
        args.manifest,
        args.kustomization,
        args.network_policy,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "valid" else 1


if __name__ == "__main__":
    sys.exit(main())
