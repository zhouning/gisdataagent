#!/usr/bin/env python3
"""Fail-closed, read-only preflight for the AgentOps discovery sandbox.

The preflight validates rendered manifests locally and, unless ``--static-only``
is used, observes the target cluster with read-only ``kubectl get`` calls.  It
never creates a namespace, Secret, Job, policy, or Deployment.  A control
database migration report may be supplied from a separately authorized,
read-only ``data_agent.migration_runner status`` invocation; credentials and
database URLs are intentionally not accepted as command-line arguments.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from data_agent.migration_runner import catalog_fingerprint, discover_migrations

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "k8s/overlays/temporal-agentops-discovery-sandbox"
CONTROL_ACCESS = ROOT / "k8s/optional/temporal-agentops-discovery-control-access"
REQUIRED_MIGRATIONS = (
    "240_agentops_temporal_checkpoint_authority",
    "241_agentops_temporal_reconciler_fencing",
    "242_agentops_temporal_start_target_authority",
    "246_agentops_specialist_operation_receipt_authority",
    "247_agentops_specialist_operation_uncertainty",
    "248_agentops_specialist_retry_budget_authority",
)
DISCOVERY_DEPLOYMENT = "gis-agent-agentops-discovery"
DISCOVERY_SECRET = "gis-agent-agentops-discovery-runtime"
CONTROL_ACCESS_POLICY = "gis-agent-postgres-agentops-discovery-access"
DISCOVERY_CONFIG = "gis-agent-agentops-discovery"
_IMMUTABLE_IMAGE_RE = re.compile(r"@sha256:[0-9a-fA-F]{64}$")
_SPECIALIST_CONFIG_PREFIX = "GDA_AGENTOPS_RECONCILER_SPECIALIST_"
_SENSITIVE_SPECIALIST_CONFIG_KEYS = frozenset(
    {
        "GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_ACCESS_KEY_ID",
        "GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_SECRET_ACCESS_KEY",
    }
)


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str

    @property
    def passed(self) -> bool:
        return self.status != "block"


def _kubectl(*args: str) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            ["kubectl", *args],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    output = (completed.stdout or completed.stderr).strip()
    return completed.returncode == 0, output


def _render(path: Path) -> tuple[bool, str]:
    return _kubectl("kustomize", str(path.relative_to(ROOT)))


def _documents(rendered: str) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for value in yaml.safe_load_all(rendered):
        if isinstance(value, dict) and value.get("kind"):
            documents.append(value)
    return documents


def _named(documents: Iterable[dict[str, Any]], kind: str, name: str) -> dict[str, Any] | None:
    for document in documents:
        metadata = document.get("metadata") or {}
        if document.get("kind") == kind and metadata.get("name") == name:
            return document
    return None


def _specialist_content_config(config: dict[str, Any]) -> tuple[bool, str]:
    backend = str(config.get("GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_BACKEND", ""))
    artifact_root = str(config.get("GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_ROOT", ""))
    materialization_root = str(
        config.get("GDA_AGENTOPS_RECONCILER_SPECIALIST_MATERIALIZATION_ROOT", "")
    )
    bucket = str(config.get("GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_BUCKET", ""))
    version_id_required = str(
        config.get("GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_REQUIRE_VERSION_ID", "true")
    ).strip().lower()
    object_lock_required = str(
        config.get(
            "GDA_AGENTOPS_RECONCILER_SPECIALIST_S3_REQUIRE_OBJECT_LOCK_RETENTION", "true"
        )
    ).strip().lower()
    if backend == "filesystem":
        configured = artifact_root.startswith("/") and materialization_root.startswith("/")
    elif backend in {"s3", "minio"}:
        configured = (
            bool(bucket)
            and materialization_root.startswith("/")
            and version_id_required in {"1", "true", "yes", "on"}
            and object_lock_required in {"1", "true", "yes", "on"}
        )
    else:
        configured = False
    detail = (
        f"backend={backend!r}; artifact_root={artifact_root!r}; "
        f"materialization_root={materialization_root!r}; bucket={bucket!r}; "
        f"require_version_id={version_id_required!r}; "
        f"require_object_lock_retention={object_lock_required!r}"
    )
    return configured, detail


def _specialist_config_projection(config: dict[str, Any]) -> dict[str, str]:
    return {
        key: str(config[key])
        for key in sorted(config)
        if key.startswith(_SPECIALIST_CONFIG_PREFIX)
        and key not in _SENSITIVE_SPECIALIST_CONFIG_KEYS
    }


def _rendered_discovery_contract() -> tuple[bool, str, dict[str, str], str]:
    ok, rendered = _render(OVERLAY)
    if not ok:
        return False, "", {}, rendered or "kubectl kustomize failed"
    try:
        documents = _documents(rendered)
    except yaml.YAMLError as exc:
        return False, "", {}, str(exc)
    deployment = _named(documents, "Deployment", DISCOVERY_DEPLOYMENT)
    configmap = _named(documents, "ConfigMap", DISCOVERY_CONFIG)
    containers = (
        (deployment or {})
        .get("spec", {})
        .get("template", {})
        .get("spec", {})
        .get("containers", [])
    )
    discovery = next((item for item in containers if item.get("name") == "discovery"), {})
    image = str(discovery.get("image", ""))
    config = _specialist_config_projection((configmap or {}).get("data") or {})
    if not image or not config:
        return False, image, config, "rendered discovery image or specialist config is absent"
    return True, image, config, f"image={image!r}; specialist_keys={sorted(config)!r}"


def _check_manifest() -> list[Check]:
    checks: list[Check] = []
    ok, rendered = _render(OVERLAY)
    if not ok:
        return [Check("manifest.render", "block", rendered or "kubectl kustomize failed")]
    try:
        documents = _documents(rendered)
    except yaml.YAMLError as exc:
        return [Check("manifest.parse", "block", str(exc))]

    namespace = _named(documents, "Namespace", "gda-agentops-sandbox")
    checks.append(
        Check("manifest.namespace", "pass" if namespace else "block", "gda-agentops-sandbox")
    )

    deployment = _named(documents, "Deployment", DISCOVERY_DEPLOYMENT)
    if deployment is None:
        checks.append(Check("manifest.discovery_deployment", "block", "deployment is absent"))
    else:
        replicas = deployment.get("spec", {}).get("replicas")
        checks.append(
            Check(
                "manifest.discovery_replicas",
                "pass" if replicas == 2 else "block",
                f"replicas={replicas!r}; expected 2",
            )
        )
        strategy = deployment.get("spec", {}).get("strategy", {})
        rolling = (
            strategy.get("rollingUpdate", {}) if strategy.get("type") == "RollingUpdate" else {}
        )
        checks.append(
            Check(
                "manifest.rolling_update",
                "pass"
                if rolling.get("maxUnavailable") == 0 and rolling.get("maxSurge") == 1
                else "block",
                f"strategy={strategy!r}",
            )
        )
        containers = (
            deployment.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        )
        discovery = next((item for item in containers if item.get("name") == "discovery"), {})
        image = str(discovery.get("image", ""))
        checks.append(
            Check(
                "manifest.image",
                "pass" if _IMMUTABLE_IMAGE_RE.search(image) else "block",
                image or "discovery image is absent; immutable digest is required",
            )
        )
        command = tuple(str(item) for item in discovery.get("command", []))
        args_text = " ".join(str(item) for item in discovery.get("args", []))
        image_contract_guarded = (
            command == ("/bin/sh", "-ec")
            and "python -m data_agent.agentops_temporal_reconciler_worker image-contract;"
            in args_text
        )
        checks.append(
            Check(
                "manifest.image_contract_guard",
                "pass" if image_contract_guarded else "block",
                f"command={command!r}; guard_present={image_contract_guarded}",
            )
        )
        pod_spec = deployment.get("spec", {}).get("template", {}).get("spec", {})
        refs = next(
            (item for item in pod_spec.get("containers", []) if item.get("name") == "discovery"),
            {},
        )
        secret_keys = {
            (
                item.get("valueFrom", {}).get("secretKeyRef", {}).get("name"),
                item.get("valueFrom", {}).get("secretKeyRef", {}).get("key"),
            )
            for item in refs.get("env", [])
            if item.get("valueFrom", {}).get("secretKeyRef")
        }
        for volume in pod_spec.get("volumes", []):
            secret = volume.get("secret") or {}
            if secret.get("secretName") != DISCOVERY_SECRET:
                continue
            secret_keys.update(
                (DISCOVERY_SECRET, item.get("key")) for item in secret.get("items", [])
            )
        required_secret_keys = {
            (DISCOVERY_SECRET, "database-url"),
            (DISCOVERY_SECRET, "tenant-id"),
        }
        found = required_secret_keys <= secret_keys
        checks.append(
            Check(
                "manifest.discovery_secret_ref",
                "pass" if found else "block",
                (
                    f"required_keys={sorted(required_secret_keys)!r}"
                    if found
                    else f"observed_refs={sorted(secret_keys)!r}"
                ),
            )
        )
        configmap = _named(documents, "ConfigMap", DISCOVERY_CONFIG)
        config = (configmap or {}).get("data") or {}
        sensitive_config_keys = sorted(_SENSITIVE_SPECIALIST_CONFIG_KEYS & set(config))
        checks.append(
            Check(
                "manifest.specialist_config_secrets",
                "pass" if not sensitive_config_keys else "block",
                f"forbidden_configmap_keys={sensitive_config_keys!r}",
            )
        )
        backend_configured, backend_detail = _specialist_content_config(config)
        backend = str(config.get("GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_BACKEND", ""))
        artifact_root = str(config.get("GDA_AGENTOPS_RECONCILER_SPECIALIST_ARTIFACT_ROOT", ""))
        materialization_root = str(
            config.get("GDA_AGENTOPS_RECONCILER_SPECIALIST_MATERIALIZATION_ROOT", "")
        )
        checks.append(
            Check(
                "manifest.specialist_content_backend",
                "pass" if backend_configured else "block",
                backend_detail,
            )
        )
        mount_paths = tuple(
            str(item.get("mountPath", ""))
            for item in discovery.get("volumeMounts", [])
            if item.get("mountPath")
        )

        def mounted_writable(path: str) -> bool:
            for item in discovery.get("volumeMounts", []):
                mount = str(item.get("mountPath", ""))
                if (
                    mount.startswith("/")
                    and path.startswith("/")
                    and (path == mount or path.startswith(f"{mount.rstrip('/')}/"))
                    and item.get("readOnly") is not True
                ):
                    return True
            return False

        required_mounts = (
            (artifact_root, materialization_root)
            if backend == "filesystem"
            else (materialization_root,)
        )
        mount_configured = bool(required_mounts) and all(
            path.startswith("/") and mounted_writable(path) for path in required_mounts
        )
        checks.append(
            Check(
                "manifest.specialist_content_mounts",
                "pass" if mount_configured else "block",
                f"required_paths={required_mounts!r}; mounts={mount_paths!r}",
            )
        )
        checks.append(
            Check(
                "manifest.no_embedded_secret",
                "pass"
                if not any(
                    document.get("kind") == "Secret"
                    and (document.get("metadata") or {}).get("name") == DISCOVERY_SECRET
                    for document in documents
                )
                else "block",
                "runtime Secret must be externally provisioned",
            )
        )

    pdb = _named(documents, "PodDisruptionBudget", DISCOVERY_DEPLOYMENT)
    min_available = (pdb or {}).get("spec", {}).get("minAvailable")
    checks.append(
        Check(
            "manifest.pdb",
            "pass" if min_available == 1 else "block",
            f"minAvailable={min_available!r}; expected 1",
        )
    )

    ok, rendered_policy = _render(CONTROL_ACCESS)
    if not ok:
        checks.append(
            Check(
                "manifest.control_access_policy", "block", rendered_policy or "policy render failed"
            )
        )
    else:
        policy = _named(_documents(rendered_policy), "NetworkPolicy", CONTROL_ACCESS_POLICY)
        checks.append(
            Check(
                "manifest.control_access_policy",
                "pass" if policy else "block",
                CONTROL_ACCESS_POLICY if policy else "policy is absent",
            )
        )
    return checks


def _check_schema_report(path: Path | None) -> list[Check]:
    if path is None:
        return [
            Check(
                "control_database.migrations",
                "block",
                "migration_runner status report was not supplied",
            )
        ]
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [Check("control_database.migrations", "block", f"cannot read report: {exc}")]
    if not isinstance(report, dict):
        return [Check("control_database.migrations", "block", "migration report is not an object")]
    pending = set(report.get("pending") or ())
    status = report.get("status")
    missing = [migration for migration in REQUIRED_MIGRATIONS if migration in pending]
    migrations = discover_migrations()
    expected_count = len(migrations)
    expected_fingerprint = catalog_fingerprint(migrations)
    catalog_matches = (
        report.get("catalog_count") == expected_count
        and report.get("catalog_fingerprint") == expected_fingerprint
    )
    passed = (
        status == "in_sync"
        and catalog_matches
        and not missing
        and not report.get("checksum_mismatches")
        and not report.get("metadata_mismatches")
    )
    detail = (
        f"status={status!r}; pending_required={missing!r}; "
        f"catalog={report.get('catalog_count')!r}/{expected_count}; "
        f"fingerprint_match={catalog_matches}"
    )
    return [Check("control_database.migrations", "pass" if passed else "block", detail)]


def _check_cluster(
    namespace: str,
    control_namespace: str,
    *,
    expect_deployed: bool,
    expected_image: str | None = None,
    expected_specialist_config: dict[str, str] | None = None,
) -> list[Check]:
    checks: list[Check] = []
    ok, output = _kubectl("get", "namespace", namespace, "-o", "name")
    checks.append(
        Check("cluster.sandbox_namespace", "pass" if ok else "block", output or namespace)
    )
    ok, output = _kubectl("get", "secret", DISCOVERY_SECRET, "-n", namespace, "-o", "json")
    if not ok:
        checks.append(Check("cluster.discovery_secret", "block", output or "Secret is absent"))
    else:
        try:
            data = set((json.loads(output).get("data") or {}).keys())
        except (json.JSONDecodeError, AttributeError):
            data = set()
        required = {"database-url", "tenant-id"}
        checks.append(
            Check(
                "cluster.discovery_secret_keys",
                "pass" if required <= data else "block",
                f"present_keys={sorted(data)!r}",
            )
        )
    ok, output = _kubectl(
        "get", "networkpolicy", CONTROL_ACCESS_POLICY, "-n", control_namespace, "-o", "name"
    )
    checks.append(
        Check(
            "cluster.control_access_policy",
            "pass" if ok else "block",
            output or CONTROL_ACCESS_POLICY,
        )
    )
    ok, output = _kubectl("get", "deployment", DISCOVERY_DEPLOYMENT, "-n", namespace, "-o", "json")
    if not ok:
        checks.append(
            Check(
                "cluster.discovery_deployment",
                "block" if expect_deployed else "pass",
                output or "deployment is absent; apply gate not yet executed",
            )
        )
    else:
        try:
            deployment_payload = json.loads(output)
            replicas = deployment_payload.get("spec", {}).get("replicas")
        except (json.JSONDecodeError, AttributeError):
            deployment_payload = {}
            replicas = None
        checks.append(
            Check(
                "cluster.discovery_replicas",
                "pass" if replicas == 2 else "block",
                f"replicas={replicas!r}",
            )
        )
        if expected_image is not None:
            observed_image = ""
            try:
                containers = (
                    deployment_payload.get("spec", {})
                    .get("template", {})
                    .get("spec", {})
                    .get("containers", [])
                )
                observed_image = str(
                    next(
                        item.get("image", "")
                        for item in containers
                        if item.get("name") == "discovery"
                    )
                )
            except (AttributeError, StopIteration):
                observed_image = ""
            checks.append(
                Check(
                    "cluster.discovery_image",
                    "pass" if observed_image == expected_image else "block",
                    f"observed={observed_image!r}; expected={expected_image!r}",
                )
            )
        status = deployment_payload.get("status") or {}
        ready = status.get("readyReplicas", 0)
        available = status.get("availableReplicas", 0)
        updated = status.get("updatedReplicas", 0)
        generation = deployment_payload.get("metadata", {}).get("generation")
        observed_generation = status.get("observedGeneration")
        rollout_ready = (
            replicas == 2
            and ready == 2
            and available == 2
            and updated == 2
            and observed_generation == generation
            and not status.get("unavailableReplicas")
        )
        checks.append(
            Check(
                "cluster.discovery_readiness",
                "pass" if rollout_ready else ("block" if expect_deployed else "warn"),
                (
                    f"replicas={replicas!r}; ready={ready!r}; available={available!r}; "
                    f"updated={updated!r}; generation={generation!r}; "
                    f"observed_generation={observed_generation!r}"
                ),
            )
        )

    ok, output = _kubectl("get", "configmap", DISCOVERY_CONFIG, "-n", namespace, "-o", "json")
    if not ok:
        checks.append(
            Check(
                "cluster.specialist_content_config",
                "block" if expect_deployed else "pass",
                output
                or (
                    "ConfigMap is absent; apply gate not yet executed"
                    if not expect_deployed
                    else "ConfigMap is absent"
                ),
            )
        )
    else:
        try:
            config = json.loads(output).get("data") or {}
        except (json.JSONDecodeError, AttributeError):
            config = {}
        sensitive_config_keys = sorted(_SENSITIVE_SPECIALIST_CONFIG_KEYS & set(config))
        checks.append(
            Check(
                "cluster.specialist_config_secrets",
                "pass" if not sensitive_config_keys else "block",
                f"forbidden_configmap_keys={sensitive_config_keys!r}",
            )
        )
        configured, detail = _specialist_content_config(config)
        checks.append(
            Check("cluster.specialist_content_config", "pass" if configured else "block", detail)
        )
        if expected_specialist_config is not None:
            observed_projection = _specialist_config_projection(config)
            checks.append(
                Check(
                    "cluster.specialist_content_config_binding",
                    "pass"
                    if observed_projection == expected_specialist_config
                    else "block",
                    (
                        f"observed_keys={sorted(observed_projection)!r}; "
                        f"expected_keys={sorted(expected_specialist_config)!r}"
                    ),
                )
            )
    return checks


def build_report(
    *,
    static_only: bool,
    schema_report: Path | None,
    namespace: str,
    control_namespace: str,
    expect_deployed: bool = False,
) -> dict[str, Any]:
    checks = _check_manifest() + _check_schema_report(schema_report)
    if not static_only:
        contract_ok, expected_image, expected_config, contract_detail = (
            _rendered_discovery_contract()
        )
        if not contract_ok:
            checks.append(Check("cluster.rendered_contract", "block", contract_detail))
        checks += _check_cluster(
            namespace,
            control_namespace,
            expect_deployed=expect_deployed,
            expected_image=expected_image if contract_ok else None,
            expected_specialist_config=expected_config if contract_ok else None,
        )
    payload = {
        "schema": "gda.agentops-temporal-discovery-sandbox-preflight.v1",
        "checked_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "scope": "disposable_sandbox_preflight",
        "static_only": static_only,
        "expect_deployed": expect_deployed,
        "namespace": namespace,
        "control_namespace": control_namespace,
        "checks": [
            {"name": item.name, "status": item.status, "detail": item.detail} for item in checks
        ],
        "passed": all(item.passed for item in checks),
        "decision": "eligible_for_operator_review"
        if all(item.passed for item in checks)
        else "blocked",
        "claim_boundary": (
            "This report does not prove production HA, RPO/RTO, backup/restore, "
            "identity rotation, or rollout safety."
        ),
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--static-only",
        action="store_true",
        help="Only render and inspect manifests; do not call cluster APIs",
    )
    parser.add_argument(
        "--schema-report",
        type=Path,
        help="JSON output from an authorized migration_runner status command",
    )
    parser.add_argument("--namespace", default="gda-agentops-sandbox")
    parser.add_argument("--control-namespace", default="gis-agent")
    parser.add_argument(
        "--expect-deployed",
        action="store_true",
        help="Require the discovery Deployment and two replicas in the cluster",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = build_report(
        static_only=args.static_only,
        schema_report=args.schema_report,
        namespace=args.namespace,
        control_namespace=args.control_namespace,
        expect_deployed=args.expect_deployed,
    )
    rendered = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
