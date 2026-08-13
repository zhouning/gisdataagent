"""Render a workload-only manifest from protected staging release evidence.

The renderer emits only the migration and application resources owned by this
release. Namespace, ConfigMap, Secret, database, cache, object storage, ingress,
and background workers must already be managed by the protected environment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from .staging_live_evidence import (
    CANDIDATE_FINGERPRINT_ANNOTATION,
    ENVIRONMENT_ACCESS_FINGERPRINT_ANNOTATION,
    ENVIRONMENT_ANNOTATION,
    PLATFORM_FINGERPRINT_ANNOTATION,
    PLATFORM_TRUTH_SCHEMA,
    RELEASE_FINGERPRINT_ANNOTATION,
    RUNTIME_FINGERPRINT_ANNOTATION,
    SCHEMA_FINGERPRINT_ANNOTATION,
    SOURCE_REVISION_ANNOTATION,
)
from .staging_registry_evidence import SHA256_PATTERN
from .staging_release_evidence import (
    RELEASE_EVIDENCE_SCHEMA,
    build_staging_release_evidence,
    release_evidence_fingerprint,
)

MANIFEST_SCHEMA = "gda.staging_workload_manifest.v1"
DEFAULT_NAMESPACE = "gis-agent-staging"
DEVELOPMENT_NAMESPACE = "gis-agent"
DEPLOYMENT_NAME = "gis-agent-app"
SERVICE_NAME = "gis-agent-app"
APP_SERVICE_ACCOUNT = "gis-agent-app"
MIGRATION_SERVICE_ACCOUNT = "gis-agent-migrate"
DNS_LABEL_PATTERN = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
SOURCE_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
IMMUTABLE_IMAGE_PATTERN = re.compile(
    r"^ghcr\.io/[a-z0-9](?:[a-z0-9._-]{0,127})"
    r"(?:/[a-z0-9](?:[a-z0-9._-]{0,127}))*"
    r"@sha256:[0-9a-f]{64}$"
)
ALLOWED_RESOURCES = {
    ("v1", "ServiceAccount", APP_SERVICE_ACCOUNT),
    ("v1", "ServiceAccount", MIGRATION_SERVICE_ACCOUNT),
    ("batch/v1", "Job", "migration"),
    ("apps/v1", "Deployment", DEPLOYMENT_NAME),
    ("v1", "Service", SERVICE_NAME),
}


class StagingWorkloadManifestError(RuntimeError):
    """Protected staging inputs cannot produce a safe workload manifest."""


def _canonical_sha256(value: object) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise StagingWorkloadManifestError("JSON evidence must be an object")
    return value


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_PATTERN.fullmatch(value))


def staging_release_input_errors(
    candidate: Mapping[str, Any],
    registry: Mapping[str, Any],
    provenance: Mapping[str, Any],
    release: Mapping[str, Any],
    *,
    source_repository: str,
    source_revision: str,
    verifier_revision: str,
) -> list[str]:
    expected = build_staging_release_evidence(
        candidate,
        registry,
        provenance,
        source_repository=source_repository,
        source_revision=source_revision,
        verifier_revision=verifier_revision,
    )
    errors: list[str] = []
    if release.get("schema") != RELEASE_EVIDENCE_SCHEMA:
        errors.append("release evidence schema is unsupported")
    if release.get("status") != "staging_release_admitted":
        errors.append("release status must be staging_release_admitted")
    if release.get("staging_apply_allowed") is not True:
        errors.append("release does not allow staging apply")
    for field in (
        "staging_deployed",
        "live_cluster_verified",
        "golden_slice_verified",
        "promotion_authority_verified",
        "production_promotion_allowed",
    ):
        if release.get(field) is not False:
            errors.append(f"release {field} must remain false before apply")
    for field in (
        "schema",
        "source_revision",
        "verifier_revision",
        "candidate_evidence_fingerprint",
        "registry_evidence_fingerprint",
        "provenance_evidence_fingerprint",
        "repository",
        "digest",
        "image",
        "schema_fingerprint",
        "platform_fingerprint",
        "config_fingerprint",
        "environment_access_fingerprint",
        "runtime_fingerprint",
        "staging_apply_allowed",
        "errors",
        "required_post_apply_evidence",
    ):
        if release.get(field) != expected.get(field):
            errors.append(f"release {field} does not match its protected inputs")
    if release.get("evidence_fingerprint") != release_evidence_fingerprint(
        release
    ):
        errors.append("release evidence fingerprint does not match its content")
    if release.get("evidence_fingerprint") != expected.get("evidence_fingerprint"):
        errors.append("release evidence fingerprint does not match protected inputs")
    return errors


def _platform_errors(
    platform: Mapping[str, Any],
    release: Mapping[str, Any],
) -> tuple[list[str], str | None]:
    errors: list[str] = []
    if platform.get("schema") != PLATFORM_TRUTH_SCHEMA:
        errors.append("platform snapshot schema is unsupported")
    config = _mapping(platform.get("config"))
    environment_access = _mapping(platform.get("environment_access"))
    runtime = _mapping(platform.get("runtime"))
    if config.get("profile") != "staging" or config.get("strict") is not True:
        errors.append("platform config must be strict staging")
    if config.get("valid") is not True or config.get("startup_allowed") is not True:
        errors.append("platform config must be valid and startable")
    config_fingerprint = config.get("config_fingerprint")
    if not _valid_sha256(config_fingerprint):
        errors.append("platform config fingerprint must be sha256")
        config_fingerprint = None
    if environment_access.get("matches_baseline") is not True:
        errors.append("platform environment access does not match the baseline")
    if environment_access.get("parse_errors") != []:
        errors.append("platform environment access scan contains parse errors")
    environment_access_fingerprint = environment_access.get("fingerprint")
    if environment_access_fingerprint != release.get(
        "environment_access_fingerprint"
    ):
        errors.append("platform environment access does not match the release")
    if not _valid_sha256(environment_access_fingerprint):
        errors.append("platform environment access fingerprint must be sha256")
        environment_access_fingerprint = None
    if runtime.get("status") != "valid" or runtime.get("errors"):
        errors.append("platform runtime inventory is invalid")
    if runtime.get("matches_primitive_baseline") is not True:
        errors.append("platform runtime primitives do not match the baseline")
    runtime_fingerprint = runtime.get("inventory_fingerprint")
    if runtime_fingerprint != release.get("runtime_fingerprint"):
        errors.append("platform runtime fingerprint does not match the release")
    if not _valid_sha256(runtime_fingerprint):
        errors.append("platform runtime fingerprint must be sha256")
        runtime_fingerprint = None
    computed = (
        _canonical_sha256(
            {
                "config": config_fingerprint,
                "environment_access": environment_access_fingerprint,
                "runtime": runtime_fingerprint,
            }
        )
        if config_fingerprint
        and environment_access_fingerprint
        and runtime_fingerprint
        else None
    )
    if platform.get("platform_fingerprint") != computed:
        errors.append("platform fingerprint does not match its components")
    return errors, computed


def _metadata(
    *,
    name: str,
    namespace: str,
    labels: Mapping[str, str],
    annotations: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "name": name,
        "namespace": namespace,
        "labels": dict(labels),
        "annotations": dict(annotations),
    }


def _container_security_context() -> dict[str, Any]:
    return {
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
        "runAsNonRoot": True,
    }


def build_staging_workload_documents(
    candidate: Mapping[str, Any],
    registry: Mapping[str, Any],
    provenance: Mapping[str, Any],
    release: Mapping[str, Any],
    platform: Mapping[str, Any],
    *,
    source_repository: str,
    source_revision: str,
    verifier_revision: str,
    namespace: str = DEFAULT_NAMESPACE,
    config_map_name: str = "gis-agent-staging-config",
    secret_name: str = "gis-agent-staging-secret",
    image_pull_secret_name: str = "gis-agent-staging-registry",
) -> list[dict[str, Any]]:
    """Return deterministic workload resources after all evidence gates pass."""
    errors = staging_release_input_errors(
        candidate,
        registry,
        provenance,
        release,
        source_repository=source_repository,
        source_revision=source_revision,
        verifier_revision=verifier_revision,
    )
    platform_errors, platform_fingerprint = _platform_errors(platform, release)
    errors.extend(platform_errors)
    for label, value in (
        ("namespace", namespace),
        ("ConfigMap", config_map_name),
        ("Secret", secret_name),
        ("image pull Secret", image_pull_secret_name),
    ):
        if not DNS_LABEL_PATTERN.fullmatch(value):
            errors.append(f"{label} name is invalid")
    if namespace == DEVELOPMENT_NAMESPACE:
        errors.append("protected staging cannot target the development namespace")
    image = release.get("image")
    if not isinstance(image, str) or not IMMUTABLE_IMAGE_PATTERN.fullmatch(image):
        errors.append("release image must be an immutable GHCR digest")
    if release.get("source_revision") != source_revision or not (
        isinstance(source_revision, str)
        and SOURCE_REVISION_PATTERN.fullmatch(source_revision)
    ):
        errors.append("source revision is invalid or does not match the release")
    if not _valid_sha256(platform_fingerprint):
        errors.append("live staging platform fingerprint is unavailable")
    if errors:
        raise StagingWorkloadManifestError("; ".join(errors))

    common_labels = {
        "app.kubernetes.io/part-of": "gis-data-agent",
        "app.kubernetes.io/managed-by": "gda-staging-release",
        "gisdataagent.io/source-revision": source_revision,
    }
    annotations = {
        SOURCE_REVISION_ANNOTATION: source_revision,
        CANDIDATE_FINGERPRINT_ANNOTATION: str(
            release["candidate_evidence_fingerprint"]
        ),
        ENVIRONMENT_ANNOTATION: "staging",
        PLATFORM_FINGERPRINT_ANNOTATION: str(platform_fingerprint),
        RELEASE_FINGERPRINT_ANNOTATION: str(release["evidence_fingerprint"]),
        SCHEMA_FINGERPRINT_ANNOTATION: str(release["schema_fingerprint"]),
        ENVIRONMENT_ACCESS_FINGERPRINT_ANNOTATION: str(
            release["environment_access_fingerprint"]
        ),
        RUNTIME_FINGERPRINT_ANNOTATION: str(release["runtime_fingerprint"]),
    }
    app_labels = {**common_labels, "app.kubernetes.io/name": DEPLOYMENT_NAME}
    migration_labels = {
        **common_labels,
        "app.kubernetes.io/name": "gis-agent-migrate",
        "app.kubernetes.io/component": "migration",
    }
    release_fingerprint = str(release["evidence_fingerprint"])
    migration_name = (
        f"gis-agent-migrate-{source_revision[:8]}-{release_fingerprint[:8]}"
    )
    env_from = [
        {"configMapRef": {"name": config_map_name}},
        {"secretRef": {"name": secret_name}},
    ]
    documents = [
        {
            "apiVersion": "v1",
            "kind": "ServiceAccount",
            "metadata": _metadata(
                name=APP_SERVICE_ACCOUNT,
                namespace=namespace,
                labels=app_labels,
                annotations=annotations,
            ),
            "automountServiceAccountToken": False,
        },
        {
            "apiVersion": "v1",
            "kind": "ServiceAccount",
            "metadata": _metadata(
                name=MIGRATION_SERVICE_ACCOUNT,
                namespace=namespace,
                labels=migration_labels,
                annotations=annotations,
            ),
            "automountServiceAccountToken": False,
        },
        {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": _metadata(
                name=migration_name,
                namespace=namespace,
                labels=migration_labels,
                annotations=annotations,
            ),
            "spec": {
                "backoffLimit": 1,
                "ttlSecondsAfterFinished": 86400,
                "template": {
                    "metadata": {
                        "labels": migration_labels,
                        "annotations": annotations,
                    },
                    "spec": {
                        "automountServiceAccountToken": False,
                        "imagePullSecrets": [{"name": image_pull_secret_name}],
                        "restartPolicy": "Never",
                        "serviceAccountName": MIGRATION_SERVICE_ACCOUNT,
                        "securityContext": {
                            "runAsNonRoot": True,
                            "seccompProfile": {"type": "RuntimeDefault"},
                        },
                        "containers": [
                            {
                                "name": "migrate",
                                "image": image,
                                "imagePullPolicy": "Always",
                                "envFrom": env_from,
                                "command": ["/bin/bash", "-c"],
                                "args": [
                                    "set -euo pipefail\n"
                                    'export MIGRATION_RUNTIME_DB_ROLE="${POSTGRES_USER}"\n'
                                    'export POSTGRES_USER="${POSTGRES_ADMIN_USER}"\n'
                                    'export POSTGRES_PASSWORD="${POSTGRES_ADMIN_PASSWORD}"\n'
                                    "unset DATABASE_URL\n"
                                    "python -m data_agent.migration_runner migrate\n"
                                    "bash /app/scripts/grant-platform-gateway-role.sh\n"
                                ],
                                "securityContext": _container_security_context(),
                                "resources": {
                                    "requests": {"cpu": "500m", "memory": "1Gi"},
                                    "limits": {"cpu": "2", "memory": "4Gi"},
                                },
                            }
                        ],
                    },
                },
            },
        },
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": _metadata(
                name=DEPLOYMENT_NAME,
                namespace=namespace,
                labels=app_labels,
                annotations=annotations,
            ),
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app.kubernetes.io/name": DEPLOYMENT_NAME}},
                "strategy": {
                    "type": "RollingUpdate",
                    "rollingUpdate": {"maxUnavailable": 0, "maxSurge": 1},
                },
                "template": {
                    "metadata": {"labels": app_labels, "annotations": annotations},
                    "spec": {
                        "automountServiceAccountToken": False,
                        "imagePullSecrets": [{"name": image_pull_secret_name}],
                        "serviceAccountName": APP_SERVICE_ACCOUNT,
                        "securityContext": {
                            "runAsNonRoot": True,
                            "seccompProfile": {"type": "RuntimeDefault"},
                        },
                        "initContainers": [
                            {
                                "name": "wait-for-migration-ledger",
                                "image": image,
                                "imagePullPolicy": "Always",
                                "envFrom": env_from,
                                "env": [
                                    {"name": "POSTGRES_ADMIN_USER", "value": ""},
                                    {"name": "POSTGRES_ADMIN_PASSWORD", "value": ""},
                                ],
                                "command": ["/bin/bash", "-c"],
                                "args": [
                                    "set -euo pipefail\n"
                                    "until python -m data_agent.migration_runner status "
                                    ">/tmp/schema-status.json; do\n"
                                    '  echo "[init] migration ledger not ready"\n'
                                    "  sleep 5\n"
                                    "done\n"
                                ],
                                "securityContext": _container_security_context(),
                                "resources": {
                                    "requests": {"cpu": "100m", "memory": "256Mi"},
                                    "limits": {"cpu": "500m", "memory": "1Gi"},
                                },
                            }
                        ],
                        "containers": [
                            {
                                "name": "app",
                                "image": image,
                                "imagePullPolicy": "Always",
                                "ports": [{"name": "http", "containerPort": 8080}],
                                "envFrom": env_from,
                                "env": [
                                    {"name": "GDA_DEPLOYMENT_PROFILE", "value": "staging"},
                                    {"name": "POSTGRES_ADMIN_USER", "value": ""},
                                    {"name": "POSTGRES_ADMIN_PASSWORD", "value": ""},
                                ],
                                "securityContext": _container_security_context(),
                                "volumeMounts": [
                                    {
                                        "name": "scratch",
                                        "mountPath": "/app/data_agent/uploads",
                                    }
                                ],
                                "readinessProbe": {
                                    "httpGet": {"path": "/ready", "port": "http"},
                                    "initialDelaySeconds": 30,
                                    "periodSeconds": 10,
                                    "timeoutSeconds": 5,
                                    "failureThreshold": 6,
                                },
                                "livenessProbe": {
                                    "httpGet": {"path": "/health", "port": "http"},
                                    "initialDelaySeconds": 60,
                                    "periodSeconds": 30,
                                    "timeoutSeconds": 10,
                                    "failureThreshold": 3,
                                },
                                "resources": {
                                    "requests": {"cpu": "1", "memory": "2Gi"},
                                    "limits": {"cpu": "4", "memory": "8Gi"},
                                },
                            }
                        ],
                        "volumes": [
                            {"name": "scratch", "emptyDir": {"sizeLimit": "5Gi"}}
                        ],
                    },
                },
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": _metadata(
                name=SERVICE_NAME,
                namespace=namespace,
                labels=app_labels,
                annotations=annotations,
            ),
            "spec": {
                "selector": {"app.kubernetes.io/name": DEPLOYMENT_NAME},
                "ports": [{"name": "http", "port": 80, "targetPort": "http"}],
            },
        },
    ]
    return documents


def render_staging_workload_manifest(documents: list[Mapping[str, Any]]) -> str:
    """Render the already validated workload documents as stable YAML."""
    return yaml.safe_dump_all(
        list(documents),
        explicit_start=True,
        sort_keys=False,
    )


def split_staging_workload_documents(
    documents: list[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """Split validated resources into migration-first apply phases."""
    migration: list[Mapping[str, Any]] = []
    application: list[Mapping[str, Any]] = []
    for document in documents:
        kind = document.get("kind")
        name = _mapping(document.get("metadata")).get("name")
        if kind == "ServiceAccount" and name == MIGRATION_SERVICE_ACCOUNT:
            migration.append(document)
        elif kind == "Job" and isinstance(name, str) and name.startswith(
            "gis-agent-migrate-"
        ):
            migration.append(document)
        elif (kind, name) in {
            ("ServiceAccount", APP_SERVICE_ACCOUNT),
            ("Deployment", DEPLOYMENT_NAME),
            ("Service", SERVICE_NAME),
        }:
            application.append(document)
        else:
            raise StagingWorkloadManifestError(
                "renderer produced a resource outside the staging ownership boundary"
            )
    if len(migration) != 2 or len(application) != 3:
        raise StagingWorkloadManifestError(
            "renderer did not produce the complete staged workload"
        )
    return migration, application


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-evidence", type=Path, required=True)
    parser.add_argument("--registry-evidence", type=Path, required=True)
    parser.add_argument("--provenance-evidence", type=Path, required=True)
    parser.add_argument("--release-evidence", type=Path, required=True)
    parser.add_argument("--platform-snapshot", type=Path, required=True)
    parser.add_argument("--source-repository", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--verifier-revision", required=True)
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    parser.add_argument("--config-map-name", default="gis-agent-staging-config")
    parser.add_argument("--secret-name", default="gis-agent-staging-secret")
    parser.add_argument(
        "--image-pull-secret-name",
        default="gis-agent-staging-registry",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--migration-output", type=Path)
    parser.add_argument("--application-output", type=Path)
    args = parser.parse_args(argv)
    try:
        documents = build_staging_workload_documents(
            _load_json_object(args.candidate_evidence),
            _load_json_object(args.registry_evidence),
            _load_json_object(args.provenance_evidence),
            _load_json_object(args.release_evidence),
            _load_json_object(args.platform_snapshot),
            source_repository=args.source_repository,
            source_revision=args.source_revision,
            verifier_revision=args.verifier_revision,
            namespace=args.namespace,
            config_map_name=args.config_map_name,
            secret_name=args.secret_name,
            image_pull_secret_name=args.image_pull_secret_name,
        )
        rendered = render_staging_workload_manifest(documents)
        migration, application = split_staging_workload_documents(documents)
        if bool(args.migration_output) != bool(args.application_output):
            raise StagingWorkloadManifestError(
                "migration and application outputs must be requested together"
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        if args.migration_output and args.application_output:
            args.migration_output.parent.mkdir(parents=True, exist_ok=True)
            args.application_output.parent.mkdir(parents=True, exist_ok=True)
            args.migration_output.write_text(
                render_staging_workload_manifest(migration),
                encoding="utf-8",
            )
            args.application_output.write_text(
                render_staging_workload_manifest(application),
                encoding="utf-8",
            )
    except (OSError, json.JSONDecodeError, StagingWorkloadManifestError) as exc:
        print(
            json.dumps(
                {
                    "schema": MANIFEST_SCHEMA,
                    "status": "blocked",
                    "manifest_rendered": False,
                    "production_promotion_allowed": False,
                    "error": f"staging workload manifest blocked: {type(exc).__name__}",
                },
                sort_keys=True,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "schema": MANIFEST_SCHEMA,
                "status": "rendered",
                "manifest_rendered": True,
                "resource_count": len(documents),
                "output": str(args.output),
                "production_promotion_allowed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
