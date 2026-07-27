"""Validate the isolated AR-1 metadata fabric foundation sandbox."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import yaml

REPORT_SCHEMA = "gda.metadata_fabric_sandbox.v1"
NAMESPACE = "gda-metadata-sandbox"
OPENMETADATA_VERSION = "1.13.1"
OPENMETADATA_CHART_VERSION = "1.13.1"
OPENMETADATA_CHART_SHA256 = (
    "63081a24174e7061686780ab3186fa4e8076a0533e68b053acbcd2ba2000cf9a"
)
OPENMETADATA_SERVER_COMMIT = "afcb2d2cd7e7c28f1d0ce60538c60a96f4eb9dc9"
OPENMETADATA_CHART_COMMIT = "039a208f0b9f2c40f6ce68d87e1e39b1d0819a57"
OPENMETADATA_ARM64_MANIFEST = (
    "sha256:13df068569cd975fddea58ee53127c48423eb582912b9384524e483a937ef538"
)
GRAVITINO_VERSION = "1.3.0"
GRAVITINO_TAG_COMMIT = "40fdf6ab96ac87b47e6d3e14e7c4dc0d815e68f0"
GRAVITINO_BINARY_SHA256 = (
    "bed7e51701628f651bc53a03307eed16ae04c15b083ee9be40af7fb776b625cd"
)
GRAVITINO_SCHEMA_SHA256 = (
    "7a2d605a677a462ca619dba594ce7ebcf500358345560ad084c1b67a25c722df"
)
GRAVITINO_LOCAL_IMAGE = "gda/gravitino:1.3.0-local-arm64"
OPENSEARCH_VERSION = "3.3.2"
POSTGRESQL_VERSION = "16.10-bookworm"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST_DIR = REPO_ROOT / "k8s/metadata-fabric-sandbox"
DEFAULT_KUSTOMIZATION = DEFAULT_MANIFEST_DIR / "kustomization.yaml"
DEFAULT_OPENMETADATA_VALUES = (
    REPO_ROOT / "helm/metadata-fabric-sandbox/openmetadata-values.yaml"
)
DEFAULT_GRAVITINO_DOCKERFILE = REPO_ROOT / "docker/gravitino-release/Dockerfile"
DEFAULT_BOOTSTRAP_SCRIPT = REPO_ROOT / "scripts/metadata-fabric-sandbox.sh"

REQUIRED_NETWORK_POLICIES = {
    "metadata-default-deny",
    "metadata-dns-egress",
    "metadata-provider-ingress",
    "metadata-openmetadata-egress",
    "metadata-gravitino-egress",
    "metadata-openmetadata-postgresql-ingress",
    "metadata-gravitino-postgresql-ingress",
    "metadata-opensearch-ingress",
}
REQUIRED_SERVICES = {
    "metadata-openmetadata-postgresql",
    "metadata-gravitino-postgresql",
    "metadata-opensearch",
    "metadata-gravitino",
}
REQUIRED_STATEFULSETS = {
    "metadata-openmetadata-postgresql",
    "metadata-gravitino-postgresql",
    "metadata-opensearch",
    "metadata-gravitino",
}
_SENSITIVE_KEY = re.compile(
    r"(^|[-_.])(password|passwd|secret|token|private[-_.]?key|access[-_.]?key)($|[-_.])",
    re.IGNORECASE,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_documents(path: Path) -> list[dict[str, Any]]:
    return [
        item
        for item in yaml.safe_load_all(path.read_text(encoding="utf-8"))
        if isinstance(item, dict)
    ]


def _resource(
    documents: Iterable[dict[str, Any]], kind: str, name: str
) -> dict[str, Any] | None:
    for document in documents:
        if document.get("kind") != kind:
            continue
        if ((document.get("metadata") or {}).get("name")) == name:
            return document
    return None


def _pod_spec(document: dict[str, Any]) -> dict[str, Any] | None:
    kind = document.get("kind")
    spec = document.get("spec") or {}
    if kind in {"Deployment", "StatefulSet", "DaemonSet", "ReplicaSet"}:
        return ((spec.get("template") or {}).get("spec") or {})
    if kind == "Job":
        return ((spec.get("template") or {}).get("spec") or {})
    if kind == "CronJob":
        job = ((spec.get("jobTemplate") or {}).get("spec") or {})
        return ((job.get("template") or {}).get("spec") or {})
    return None


def _container_images(pod: dict[str, Any]) -> list[str]:
    containers = list(pod.get("initContainers") or []) + list(
        pod.get("containers") or []
    )
    return [
        item.get("image")
        for item in containers
        if isinstance(item, dict) and isinstance(item.get("image"), str)
    ]


def _secret_refs(value: Any) -> set[tuple[str, str]]:
    refs: set[tuple[str, str]] = set()
    if isinstance(value, dict):
        reference = value.get("secretKeyRef")
        if isinstance(reference, dict):
            name = reference.get("name")
            key = reference.get("key")
            if isinstance(name, str) and isinstance(key, str):
                refs.add((name, key))
        volume_secret = value.get("secret")
        if isinstance(volume_secret, dict):
            name = volume_secret.get("secretName")
            for item in volume_secret.get("items") or []:
                key = item.get("key") if isinstance(item, dict) else None
                if isinstance(name, str) and isinstance(key, str):
                    refs.add((name, key))
        for nested in value.values():
            refs.update(_secret_refs(nested))
    elif isinstance(value, list):
        for nested in value:
            refs.update(_secret_refs(nested))
    return refs


def _configmap_contains_sensitive_material(document: dict[str, Any]) -> bool:
    for section in ("data", "binaryData"):
        values = document.get(section) or {}
        if not isinstance(values, dict):
            continue
        for key, value in values.items():
            if _SENSITIVE_KEY.search(str(key)):
                return True
            for line in str(value).splitlines():
                name = line.split("=", 1)[0].strip()
                if _SENSITIVE_KEY.search(name):
                    return True
    return False


def _validate_openmetadata_values(values: dict[str, Any], errors: list[str]) -> None:
    image = values.get("image") or {}
    if image.get("repository") != "docker.getcollate.io/openmetadata/server":
        errors.append("OpenMetadata must use the official server image repository")
    if str(image.get("tag")) != OPENMETADATA_VERSION:
        errors.append("OpenMetadata image tag must pin 1.13.1")
    if image.get("pullPolicy") != "Never":
        errors.append("OpenMetadata pinned image must be preloaded with pullPolicy Never")
    if values.get("automountServiceAccountToken") is not False:
        errors.append("OpenMetadata must not mount a Kubernetes API token")
    if (values.get("service") or {}).get("type") != "ClusterIP":
        errors.append("OpenMetadata Service must remain ClusterIP")
    for key in ("ingress", "gateway", "route", "istio"):
        if (values.get(key) or {}).get("enabled") is not False:
            errors.append(f"OpenMetadata {key} must be disabled")

    config = ((values.get("openmetadata") or {}).get("config") or {})
    database = config.get("database") or {}
    if database.get("host") != "metadata-openmetadata-postgresql":
        errors.append("OpenMetadata must use its dedicated PostgreSQL Service")
    if database.get("dbScheme") != "postgresql":
        errors.append("OpenMetadata database scheme must be PostgreSQL")
    password = ((database.get("auth") or {}).get("password") or {})
    if password != {
        "secretRef": "metadata-openmetadata-postgresql",
        "secretKey": "password",
    }:
        errors.append("OpenMetadata database password must use the external Secret")

    search = config.get("elasticsearch") or {}
    if search.get("host") != "metadata-opensearch":
        errors.append("OpenMetadata must use the sandbox OpenSearch Service")
    if search.get("searchType") != "opensearch":
        errors.append("OpenMetadata search type must be OpenSearch")
    pipeline = config.get("pipelineServiceClientConfig") or {}
    if pipeline.get("enabled") is not False:
        errors.append("OpenMetadata pipeline client must be disabled in M2")
    airflow_auth = ((pipeline.get("airflow") or {}).get("auth")) or {}
    if pipeline.get("type") == "airflow" and airflow_auth.get("enabled") is not False:
        errors.append("OpenMetadata Airflow authentication must be explicitly disabled")
    if (config.get("deployPipelinesConfig") or {}).get("enabled") is not False:
        errors.append("OpenMetadata pipeline deployment must be disabled in M2")
    authentication = config.get("authentication") or {}
    if authentication.get("provider") != "basic":
        errors.append("OpenMetadata foundation sandbox must pin basic authentication")
    if ((authentication.get("oidcConfiguration") or {}).get("enabled")) is not False:
        errors.append("OpenMetadata OIDC must remain disabled until separately verified")
    fernet = config.get("fernetkey") or {}
    if fernet != {
        "secretRef": "metadata-openmetadata-runtime",
        "secretKey": "fernet-key",
    }:
        errors.append("OpenMetadata Fernet key must use the external runtime Secret")


def _validate_workloads(documents: list[dict[str, Any]], errors: list[str]) -> None:
    for document in documents:
        metadata = document.get("metadata") or {}
        kind = document.get("kind")
        name = metadata.get("name", "<unnamed>")
        if kind != "Namespace" and metadata.get("namespace") != NAMESPACE:
            errors.append(f"{kind}/{name} must be isolated in {NAMESPACE}")
        if kind == "Secret":
            errors.append("Secret objects and secret contents must not be committed")
        if kind == "ConfigMap" and _configmap_contains_sensitive_material(document):
            errors.append(f"ConfigMap/{name} contains a secret-bearing key")
        if kind in {"Ingress", "Gateway", "HTTPRoute", "Route"}:
            errors.append(f"{kind}/{name} must not be present in the foundation sandbox")
        if kind == "Service":
            service_type = (document.get("spec") or {}).get("type", "ClusterIP")
            if service_type != "ClusterIP":
                errors.append(f"Service/{name} must remain ClusterIP")

        pod = _pod_spec(document)
        if pod is None:
            continue
        if pod.get("automountServiceAccountToken") is not False:
            errors.append(f"{kind}/{name} must disable service account token mounting")
        service_account = pod.get("serviceAccountName")
        if not service_account or service_account == "default":
            errors.append(f"{kind}/{name} must use a dedicated ServiceAccount")
        for volume in pod.get("volumes") or []:
            if isinstance(volume, dict) and "hostPath" in volume:
                errors.append(f"{kind}/{name} must not use hostPath")
        for image in _container_images(pod):
            if image.endswith(":latest") or ":latest@" in image:
                errors.append(f"{kind}/{name} must not use a latest image")

    gravitino = _resource(documents, "StatefulSet", "metadata-gravitino")
    if gravitino is not None:
        pod = _pod_spec(gravitino) or {}
        containers = pod.get("containers") or []
        server = next(
            (
                item
                for item in containers
                if isinstance(item, dict) and item.get("name") == "gravitino"
            ),
            {},
        )
        if server.get("image") != GRAVITINO_LOCAL_IMAGE:
            errors.append("Gravitino must use the versioned local release image")
        if server.get("imagePullPolicy") != "Never":
            errors.append("Gravitino local image must use imagePullPolicy Never")
        command = "\n".join(
            str(item)
            for item in list(server.get("command") or [])
            + list(server.get("args") or [])
        )
        if "gravitino.entity.store.relational.jdbcPassword" not in command:
            errors.append("Gravitino must assemble its JDBC password from a Secret at runtime")
        if "install -d -m 0700 /var/run/gravitino/conf" not in command:
            errors.append("Gravitino must create its owner-only runtime config directory")
        if "/opt/gravitino/conf/gravitino-env.sh" not in command:
            errors.append("Gravitino must preserve official release environment metadata")
        required_refs = {
            ("metadata-gravitino-postgresql", "password"),
        }
        if not required_refs.issubset(_secret_refs(gravitino)):
            errors.append("Gravitino must reference its dedicated PostgreSQL Secret")


def build_sandbox_report(
    manifest_dir: Path | None = None,
    openmetadata_values_path: Path | None = None,
    dockerfile_path: Path | None = None,
    bootstrap_script_path: Path | None = None,
) -> dict[str, Any]:
    """Validate source configuration without claiming a live deployment."""
    manifest_root = (manifest_dir or DEFAULT_MANIFEST_DIR).resolve()
    kustomization_path = manifest_root / "kustomization.yaml"
    values_path = (openmetadata_values_path or DEFAULT_OPENMETADATA_VALUES).resolve()
    dockerfile = (dockerfile_path or DEFAULT_GRAVITINO_DOCKERFILE).resolve()
    bootstrap_script = (bootstrap_script_path or DEFAULT_BOOTSTRAP_SCRIPT).resolve()
    errors: list[str] = []
    documents: list[dict[str, Any]] = []
    resource_paths: list[Path] = []
    kustomization: dict[str, Any] = {}
    values: dict[str, Any] = {}

    try:
        loaded = _load_yaml(kustomization_path)
        if not isinstance(loaded, dict):
            raise TypeError("Kustomization is not an object")
        kustomization = loaded
        if kustomization.get("namespace") != NAMESPACE:
            errors.append("Kustomization must target the isolated sandbox namespace")
        for relative in kustomization.get("resources") or []:
            path = (manifest_root / relative).resolve()
            if path.parent != manifest_root:
                errors.append("Kustomization resources must stay inside the sandbox directory")
                continue
            resource_paths.append(path)
            documents.extend(_load_documents(path))
    except (OSError, TypeError, yaml.YAMLError) as exc:
        errors.append(f"sandbox Kustomization is unavailable or invalid: {type(exc).__name__}")

    try:
        loaded_values = _load_yaml(values_path)
        if not isinstance(loaded_values, dict):
            raise TypeError("OpenMetadata values is not an object")
        values = loaded_values
        _validate_openmetadata_values(values, errors)
    except (OSError, TypeError, yaml.YAMLError) as exc:
        errors.append(f"OpenMetadata values are unavailable or invalid: {type(exc).__name__}")

    namespace = _resource(documents, "Namespace", NAMESPACE)
    if namespace is None:
        errors.append("sandbox must define its isolated Namespace")
    quota = _resource(documents, "ResourceQuota", "metadata-fabric-foundation") or {}
    quota_hard = ((quota.get("spec") or {}).get("hard") or {})
    if str(quota_hard.get("limits.cpu")) != "15":
        errors.append(
            "sandbox CPU quota must reserve bounded OpenMetadata rolling-update headroom"
        )
    _validate_workloads(documents, errors)

    service_names = {
        (item.get("metadata") or {}).get("name")
        for item in documents
        if item.get("kind") == "Service"
    }
    if not REQUIRED_SERVICES.issubset(service_names):
        errors.append("sandbox is missing one or more required ClusterIP Services")
    statefulset_names = {
        (item.get("metadata") or {}).get("name")
        for item in documents
        if item.get("kind") == "StatefulSet"
    }
    if statefulset_names != REQUIRED_STATEFULSETS:
        errors.append("sandbox StatefulSet inventory does not match the foundation contract")
    policy_names = {
        (item.get("metadata") or {}).get("name")
        for item in documents
        if item.get("kind") == "NetworkPolicy"
    }
    if not REQUIRED_NETWORK_POLICIES.issubset(policy_names):
        errors.append("sandbox NetworkPolicy inventory is incomplete")

    database_pvcs: dict[str, str] = {}
    for name in (
        "metadata-openmetadata-postgresql",
        "metadata-gravitino-postgresql",
    ):
        statefulset = _resource(documents, "StatefulSet", name) or {}
        templates = ((statefulset.get("spec") or {}).get("volumeClaimTemplates") or [])
        pvc_names = [
            (item.get("metadata") or {}).get("name")
            for item in templates
            if isinstance(item, dict)
        ]
        if len(pvc_names) != 1 or not isinstance(pvc_names[0], str):
            errors.append(f"StatefulSet/{name} must define exactly one data PVC")
        else:
            database_pvcs[name] = pvc_names[0]
            pod = _pod_spec(statefulset) or {}
            mount_names = {
                mount.get("name")
                for container in pod.get("containers") or []
                if isinstance(container, dict)
                for mount in container.get("volumeMounts") or []
                if isinstance(mount, dict)
            }
            if pvc_names[0] not in mount_names:
                errors.append(
                    f"StatefulSet/{name} must mount its declared data PVC"
                )
    if len(set(database_pvcs.values())) != len(database_pvcs):
        errors.append("OpenMetadata and Gravitino PostgreSQL PVC names must be distinct")

    opensearch = _resource(documents, "StatefulSet", "metadata-opensearch") or {}
    opensearch_templates = ((opensearch.get("spec") or {}).get("volumeClaimTemplates") or [])
    if len(opensearch_templates) != 1:
        errors.append("OpenSearch must define exactly one data PVC")

    dockerfile_text = ""
    try:
        dockerfile_text = dockerfile.read_text(encoding="utf-8")
        for marker in (
            "gravitino-1.3.0-bin.tar.gz",
            GRAVITINO_BINARY_SHA256,
            "postgresql-42.7.0.jar",
            'org.opencontainers.image.version="1.3.0"',
        ):
            if marker not in dockerfile_text:
                errors.append(f"Gravitino Dockerfile is missing provenance marker: {marker}")
        if ":latest" in dockerfile_text:
            errors.append("Gravitino Dockerfile must not use a latest base image")
    except OSError as exc:
        errors.append(f"Gravitino Dockerfile is unavailable: {type(exc).__name__}")

    try:
        script_text = bootstrap_script.read_text(encoding="utf-8")
        for marker in (
            OPENMETADATA_CHART_SHA256,
            GRAVITINO_BINARY_SHA256,
            GRAVITINO_SCHEMA_SHA256,
            "--from-file=${key}=${secret_file}",
            "--skip-tests",
        ):
            if marker not in script_text:
                errors.append(f"bootstrap script is missing safety marker: {marker}")
        if "--from-literal" in script_text:
            errors.append("bootstrap script must not put secret values on the command line")
    except OSError as exc:
        errors.append(f"bootstrap script is unavailable: {type(exc).__name__}")

    files: dict[str, dict[str, str]] = {}
    for path in [
        kustomization_path,
        *resource_paths,
        values_path,
        dockerfile,
        bootstrap_script,
    ]:
        if path.is_file():
            files[path.name] = {"path": path.as_posix(), "sha256": _sha256(path)}

    return {
        "schema": REPORT_SCHEMA,
        "status": "valid" if not errors else "invalid",
        "namespace": NAMESPACE,
        "static_contract_verified": not errors,
        "live_deployment_verified": False,
        "production_provider_verified": False,
        "production_table_catalog_provider_verified": False,
        "oidc_verified": False,
        "backup_restore_verified": False,
        "upgrade_verified": False,
        "network_policy_enforcement_verified": False,
        "writes_to_gda_enabled": False,
        "persistence_configured": len(database_pvcs) == 2
        and len(opensearch_templates) == 1,
        "providers": {
            "openmetadata": {
                "version": OPENMETADATA_VERSION,
                "server_commit": OPENMETADATA_SERVER_COMMIT,
                "chart_version": OPENMETADATA_CHART_VERSION,
                "chart_commit": OPENMETADATA_CHART_COMMIT,
                "chart_sha256": OPENMETADATA_CHART_SHA256,
                "arm64_manifest_digest": OPENMETADATA_ARM64_MANIFEST,
            },
            "gravitino": {
                "version": GRAVITINO_VERSION,
                "tag_commit": GRAVITINO_TAG_COMMIT,
                "binary_sha256": GRAVITINO_BINARY_SHA256,
                "postgresql_schema_sha256": GRAVITINO_SCHEMA_SHA256,
                "image": GRAVITINO_LOCAL_IMAGE,
                "image_provenance": "local_release_build",
            },
            "opensearch": {"version": OPENSEARCH_VERSION},
            "postgresql": {"version": POSTGRESQL_VERSION},
        },
        "database_services": sorted(database_pvcs),
        "database_pvcs": database_pvcs,
        "resource_count": len(documents),
        "files": files,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate",))
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument(
        "--openmetadata-values",
        type=Path,
        default=DEFAULT_OPENMETADATA_VALUES,
    )
    parser.add_argument(
        "--gravitino-dockerfile", type=Path, default=DEFAULT_GRAVITINO_DOCKERFILE
    )
    args = parser.parse_args(argv)
    report = build_sandbox_report(
        args.manifest_dir,
        args.openmetadata_values,
        args.gravitino_dockerfile,
        DEFAULT_BOOTSTRAP_SCRIPT,
    )
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if report["status"] == "valid" else 1


if __name__ == "__main__":
    sys.exit(main())
