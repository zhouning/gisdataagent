"""Validate the inert Kubernetes contract for the Active Metadata consumer."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPORT_SCHEMA = "gda.active_metadata_consumer_deployment.v1"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "k8s/base/active-metadata-consumer.yaml"
DEFAULT_KUSTOMIZATION = REPO_ROOT / "k8s/base/kustomization.yaml"
DEFAULT_NETWORK_POLICY = REPO_ROOT / "k8s/base/networkpolicy.yaml"
DEPLOYMENT_NAME = "gis-agent-active-metadata-consumer"
STATUS_FILE = "/var/run/gis-agent/active-metadata/status.json"

REQUIRED_LITERAL_ENV = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "ACTIVE_METADATA_CONSUMER_ENABLED": "true",
    "ACTIVE_METADATA_CONSUMER_STATUS_FILE": STATUS_FILE,
    "ACTIVE_METADATA_CONSUMER_BATCH_SIZE": "1",
    "ACTIVE_METADATA_CONSUMER_LEASE_SECONDS": "60",
    "ACTIVE_METADATA_CONSUMER_POLL_INTERVAL_SECONDS": "5",
    "ACTIVE_METADATA_CONSUMER_HEALTH_MAX_AGE_SECONDS": "30",
}
REQUIRED_CONFIG_ENV = {
    "ACTIVE_METADATA_CONSUMER_TENANT_ID": "tenant-id",
    "ACTIVE_METADATA_CONSUMER_SUBJECT": "consumer-subject",
}
FORBIDDEN_ENV_MARKERS = (
    "DOLPHINSCHEDULER",
    "OPENMETADATA",
    "GRAVITINO",
    "PROVIDER_TOKEN",
    "ACCESS_TOKEN",
    "PASSWORD",
)


def _load_documents(path: Path) -> list[dict[str, Any]]:
    return [
        value
        for value in yaml.safe_load_all(path.read_text(encoding="utf-8"))
        if isinstance(value, dict)
    ]


def _resource(
    documents: list[dict[str, Any]], kind: str, name: str
) -> dict[str, Any] | None:
    for document in documents:
        if document.get("kind") != kind:
            continue
        if (document.get("metadata") or {}).get("name") == name:
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


def _probe_valid(container: dict[str, Any], name: str, command: str) -> bool:
    values = (((container.get(name) or {}).get("exec") or {}).get("command") or [])
    prefix = (
        "python",
        "-m",
        "data_agent.active_metadata_consumer_worker",
        command,
        "--status-file",
        STATUS_FILE,
        "--max-age-seconds",
    )
    try:
        max_age = float(values[len(prefix)])
    except (IndexError, TypeError, ValueError):
        return False
    return tuple(values[: len(prefix)]) == prefix and max_age > 0


def build_deployment_report(
    manifest_path: Path | None = None,
    kustomization_path: Path | None = None,
    network_policy_path: Path | None = None,
    *,
    expected_replicas: int = 0,
) -> dict[str, Any]:
    manifest = (manifest_path or DEFAULT_MANIFEST).resolve()
    kustomization = (kustomization_path or DEFAULT_KUSTOMIZATION).resolve()
    network_policy = (network_policy_path or DEFAULT_NETWORK_POLICY).resolve()
    errors: list[str] = []
    try:
        documents = _load_documents(manifest)
    except (OSError, yaml.YAMLError) as exc:
        documents = []
        errors.append(f"consumer manifest is invalid: {type(exc).__name__}")
    try:
        kustom = yaml.safe_load(kustomization.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        kustom = {}
        errors.append(f"Kustomization is invalid: {type(exc).__name__}")
    try:
        policies = _load_documents(network_policy)
    except (OSError, yaml.YAMLError) as exc:
        policies = []
        errors.append(f"NetworkPolicy is invalid: {type(exc).__name__}")

    deployment = _resource(documents, "Deployment", DEPLOYMENT_NAME)
    service_account = _resource(documents, "ServiceAccount", DEPLOYMENT_NAME)
    if deployment is None:
        errors.append("manifest must define the managed consumer Deployment")
    if service_account is None:
        errors.append("manifest must define a dedicated ServiceAccount")
    if _resource(documents, "Role", DEPLOYMENT_NAME) is not None or _resource(
        documents, "RoleBinding", DEPLOYMENT_NAME
    ) is not None:
        errors.append("consumer must not receive Kubernetes API RBAC")
    if "active-metadata-consumer.yaml" not in (kustom.get("resources") or []):
        errors.append("base Kustomization must register the consumer manifest")

    postgres_policy = _resource(policies, "NetworkPolicy", "postgres-access")
    allowed_names = set()
    if postgres_policy is not None:
        ingress = (postgres_policy.get("spec") or {}).get("ingress") or []
        for rule in ingress:
            for source in (rule or {}).get("from") or []:
                labels = ((source or {}).get("podSelector") or {}).get(
                    "matchLabels"
                ) or {}
                if labels.get("app.kubernetes.io/name"):
                    allowed_names.add(labels["app.kubernetes.io/name"])
    if DEPLOYMENT_NAME not in allowed_names:
        errors.append("PostgreSQL NetworkPolicy must admit the consumer selector")

    if deployment is not None:
        spec = deployment.get("spec") or {}
        pod_spec = ((spec.get("template") or {}).get("spec") or {})
        if spec.get("replicas") != expected_replicas:
            errors.append("consumer replicas do not match the inert deployment gate")
        if pod_spec.get("serviceAccountName") != DEPLOYMENT_NAME:
            errors.append("consumer must use its dedicated ServiceAccount")
        if pod_spec.get("automountServiceAccountToken") is not False:
            errors.append("consumer must disable Kubernetes API token mounting")
        if pod_spec.get("initContainers"):
            errors.append("consumer must not prepare provider credentials")
        containers = pod_spec.get("containers") or []
        container = _named(containers, "worker")
        if container is None:
            errors.append("consumer Deployment must contain the worker container")
        else:
            command_text = _command_text(container)
            if (
                "data_agent.active_metadata_consumer_worker run" not in command_text
                or "worker:active-metadata:${POD_UID}" not in command_text
            ):
                errors.append("consumer command must derive identity and run worker")
            if container.get("envFrom"):
                errors.append("consumer must not import bulk environment sources")
            entries = container.get("env") or []
            names = [item.get("name") for item in entries if isinstance(item, dict)]
            if len(names) != len(set(names)):
                errors.append("consumer environment names must be unique")
            env = {
                item["name"]: item
                for item in entries
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            }
            for name, value in REQUIRED_LITERAL_ENV.items():
                if (env.get(name) or {}).get("value") != value:
                    errors.append(f"{name} must use the fixed safe value")
            for name, key in REQUIRED_CONFIG_ENV.items():
                ref = ((env.get(name) or {}).get("valueFrom") or {}).get(
                    "configMapKeyRef"
                ) or {}
                if ref != {"name": DEPLOYMENT_NAME, "key": key}:
                    errors.append(f"{name} must use the dedicated ConfigMap key")
            database_ref = (
                ((env.get("DATABASE_URL") or {}).get("valueFrom") or {}).get(
                    "secretKeyRef"
                )
                or {}
            )
            if database_ref != {"name": DEPLOYMENT_NAME, "key": "database-url"}:
                errors.append("DATABASE_URL must use the dedicated Secret key")
            pod_uid_ref = (
                ((env.get("POD_UID") or {}).get("valueFrom") or {}).get("fieldRef")
                or {}
            )
            if pod_uid_ref.get("fieldPath") != "metadata.uid":
                errors.append("worker identity must bind the immutable Pod UID")
            forbidden = [
                name
                for name in names
                if isinstance(name, str)
                and any(marker in name.upper() for marker in FORBIDDEN_ENV_MARKERS)
            ]
            if forbidden:
                errors.append("consumer must not receive provider or scheduler secrets")
            if not _probe_valid(container, "readinessProbe", "health"):
                errors.append("readinessProbe must execute the worker health command")
            for probe in ("startupProbe", "livenessProbe"):
                if not _probe_valid(container, probe, "liveness"):
                    errors.append(f"{probe} must execute the worker liveness command")
            security = container.get("securityContext") or {}
            if (
                security.get("allowPrivilegeEscalation") is not False
                or security.get("readOnlyRootFilesystem") is not True
                or ((security.get("capabilities") or {}).get("drop") or [])
                != ["ALL"]
            ):
                errors.append("consumer container security context is incomplete")
        volumes = pod_spec.get("volumes") or []
        if len(volumes) != 1 or "emptyDir" not in (volumes[0] if volumes else {}):
            errors.append("consumer may mount only its ephemeral status volume")

    files = {}
    for name, path in (
        ("manifest", manifest),
        ("kustomization", kustomization),
        ("network_policy", network_policy),
    ):
        files[name] = {
            "path": path.relative_to(REPO_ROOT).as_posix()
            if path.is_relative_to(REPO_ROOT)
            else path.as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()
            if path.is_file()
            else None,
        }
    return {
        "schema": REPORT_SCHEMA,
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "expected_replicas": expected_replicas,
        "files": files,
        "provider_credentials_present": False,
        "scheduler_credentials_present": False,
        "deployment_applied": False,
        "production_scheduler_submission_verified": False,
        "production_ready": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate",))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--kustomization", type=Path, default=DEFAULT_KUSTOMIZATION)
    parser.add_argument("--network-policy", type=Path, default=DEFAULT_NETWORK_POLICY)
    parser.add_argument("--expected-replicas", type=int, default=0)
    args = parser.parse_args(argv)
    report = build_deployment_report(
        args.manifest,
        args.kustomization,
        args.network_policy,
        expected_replicas=args.expected_replicas,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "valid" else 1


if __name__ == "__main__":
    sys.exit(main())
