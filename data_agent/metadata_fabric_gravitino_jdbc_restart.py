"""Rehearse authenticated Gravitino JDBC catalog continuity across restarts.

The local rehearsal creates a Basic-authenticated, minimum-privilege table in
an Iceberg JDBC catalog whose metadata and warehouse use isolated PVCs. It then
restarts PostgreSQL and Gravitino and requires the same bounded principal to
read the same table while an administrative mutation remains denied. The
result is local Docker Desktop evidence only, never OIDC, production durability
or Spark/Flink conformance.
"""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote
from uuid import UUID

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints

from . import metadata_fabric_gravitino_identity as identity
from . import metadata_fabric_ingestion_replay as ingestion_replay
from . import metadata_fabric_provider_metrics as provider_metrics
from . import metadata_fabric_recovery_rehearsal as recovery


PROFILE_SCHEMA = "gda.metadata_fabric_gravitino_jdbc_restart_profile.v1"
CONTRACT_SCHEMA = "gda.metadata_fabric_gravitino_jdbc_restart_contract.v1"
OBSERVATION_SCHEMA = "gda.metadata_fabric_gravitino_jdbc_restart_observation.v1"
EVIDENCE_SCHEMA = "gda.metadata_fabric_gravitino_jdbc_restart_evidence.v1"
VALIDATION_SCHEMA = "gda.metadata_fabric_gravitino_jdbc_restart_validation.v1"

CONTEXT = "docker-desktop"
SOURCE_NAMESPACE = "gda-metadata-sandbox"
REHEARSAL_NAMESPACE = "gda-metadata-catalog-persistence"
GRAVITINO_SCHEMA_SHA256 = identity.GRAVITINO_SCHEMA_SHA256
GRAVITINO_HOST_IMAGE_ID = (
    "sha256:d355dc7e92f9e3545d717f3eab2cbdf412115f2b82e1e544d7f6235c1eacd5a5"
)
GRAVITINO_KUBERNETES_IMAGE_ID = (
    "sha256:18e24b43be854dabdc13e96b1019eb3dc691d59cc64e411aa6a3cc49225fe2d3"
)
POSTGRESQL_IMAGE_DIGEST = (
    "sha256:38471f330eb885e04de130b768d6db4e10469e2311879c7e5c699f6d2d8a1c74"
)
IDENTITY_EVIDENCE_FINGERPRINT = (
    "f0b0de1f80f079d43318937e0a0cc151a8546e9e307bef204738b1367f9b29fd"
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = (
    REPO_ROOT / "config/metadata-fabric-gravitino-jdbc-restart.local.yaml"
)
DEFAULT_EVIDENCE_PATH = (
    REPO_ROOT
    / "docs/evidence/metadata-fabric-gravitino-jdbc-restart-2026-07-29.json"
)
DEFAULT_WRAPPER_PATH = REPO_ROOT / "scripts/metadata-fabric-gravitino-jdbc-restart.sh"
MANIFEST_DIR = REPO_ROOT / "k8s/metadata-fabric-gravitino-jdbc-restart"

NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1024),
]


class MetadataFabricGravitinoJdbcRestartError(RuntimeError):
    """The local JDBC catalog restart contract failed closed."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ClusterProfile(_FrozenModel):
    context: Literal["docker-desktop"]
    source_namespace: Literal["gda-metadata-sandbox"]
    rehearsal_namespace: Literal["gda-metadata-catalog-persistence"]
    source_schema_configmap: Literal["metadata-gravitino-schema-1-3-0"]
    storage_class: Literal["standard"]


class RuntimeProfile(_FrozenModel):
    manifest: Literal["k8s/metadata-fabric-gravitino-jdbc-restart"]
    gravitino_version: Literal["1.3.0"]
    gravitino_image: Literal["gda/gravitino:1.3.0-local-arm64"]
    gravitino_host_image_id: Literal[GRAVITINO_HOST_IMAGE_ID]
    gravitino_kubernetes_image_id: Literal[GRAVITINO_KUBERNETES_IMAGE_ID]
    postgresql_version: Literal["16.10-bookworm"]
    postgresql_image: Literal["postgres:16.10-bookworm"]
    postgresql_image_digest: Literal[POSTGRESQL_IMAGE_DIGEST]
    service: Literal["gravitino-persistence"]
    service_port: Literal[8090]
    authenticator: Literal["basic"]
    idp_extension: Literal["org.apache.gravitino.idp.web.rest.feature"]
    access_control_enabled: Literal[True]
    service_account: Literal["gravitino-persistence"]
    service_account_automount_disabled: Literal[True]
    transport: Literal["local_loopback_http"]


class DependencyProfile(_FrozenModel):
    evidence_path: Literal[
        "docs/evidence/metadata-fabric-gravitino-identity-2026-07-28.json"
    ]
    evidence_fingerprint: Literal[IDENTITY_EVIDENCE_FINGERPRINT]
    required_claim: Literal["local_gravitino_minimum_privilege_verified"]


class IdentityProfile(_FrozenModel):
    service_admin: Literal["gda-persistence-admin"]
    user: Literal["gda-metadata-projection"]
    role: Literal["gda-table-projection"]
    material_delivery: Literal["runtime_generated_ephemeral_kubernetes_object"]


class CatalogProfile(_FrozenModel):
    provider: Literal["lakehouse-iceberg"]
    backend: Literal["jdbc"]
    uri: Literal[
        "jdbc:postgresql://gravitino-persistence-postgresql:5432/iceberg"
    ]
    jdbc_driver: Literal["org.postgresql.Driver"]
    jdbc_driver_source: Literal["/opt/gravitino/libs/postgresql-42.7.0.jar"]
    jdbc_driver_mount: Literal[
        "/opt/gravitino/catalogs/lakehouse-iceberg/libs/postgresql-42.7.0.jar"
    ]
    jdbc_initialize: Literal[True]
    warehouse: Literal["file:///var/lib/gravitino/warehouse"]
    postgresql_pvc: Literal["data-gravitino-persistence-postgresql-0"]
    warehouse_pvc: Literal["warehouse-gravitino-persistence-0"]
    restart_scope: Literal["postgresql_then_gravitino"]


class PrivilegeProfile(_FrozenModel):
    name: Literal["USE_CATALOG", "USE_SCHEMA", "CREATE_TABLE"]
    condition: Literal["ALLOW"]


class SecurableObjectProfile(_FrozenModel):
    full_name: Literal["lakehouse", "lakehouse.published"]
    type: Literal["CATALOG", "SCHEMA"]
    privileges: tuple[PrivilegeProfile, ...]


class ScopeProfile(_FrozenModel):
    metalake: Literal["gda_persistence"]
    catalog: Literal["lakehouse"]
    schema_name: Literal["published"] = Field(alias="schema")
    table: Literal["gda_persistence_probe"]
    denied_catalog: Literal["unauthorized_catalog"]
    role_securable_objects: tuple[SecurableObjectProfile, ...]


class ClaimProfile(_FrozenModel):
    local_gravitino_jdbc_catalog_restart_verified: Literal[False]
    local_authenticated_catalog_persistence_verified: Literal[False]
    local_postgresql_pvc_restart_verified: Literal[False]
    local_warehouse_pvc_restart_verified: Literal[False]
    persistent_catalog_identity_binding_verified: Literal[False]
    protected_workload_identity_verified: Literal[False]
    oidc_verified: Literal[False]
    tls_verified: Literal[False]
    spark_conformance_verified: Literal[False]
    flink_conformance_verified: Literal[False]
    production_ingestion_verified: Literal[False]
    production_ready: Literal[False]


class GravitinoJdbcRestartProfile(_FrozenModel):
    schema_name: Literal[PROFILE_SCHEMA] = Field(alias="schema")
    environment: Literal["local_docker_desktop"]
    cluster: ClusterProfile
    runtime: RuntimeProfile
    dependency: DependencyProfile
    identity: IdentityProfile
    catalog: CatalogProfile
    scope: ScopeProfile
    claims: ClaimProfile


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _valid_uuid(value: Any) -> bool:
    try:
        UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _profile_securable_objects(
    profile: GravitinoJdbcRestartProfile,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in profile.scope.role_securable_objects:
        result.append(
            {
                "fullName": item.full_name,
                "type": item.type,
                "privileges": sorted(
                    [entry.model_dump(mode="json") for entry in item.privileges],
                    key=lambda entry: entry["name"],
                ),
            }
        )
    return sorted(result, key=lambda item: item["fullName"])


def _load_dependency(profile: GravitinoJdbcRestartProfile) -> dict[str, Any]:
    path = (REPO_ROOT / profile.dependency.evidence_path).resolve()
    try:
        path.relative_to(REPO_ROOT)
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise MetadataFabricGravitinoJdbcRestartError(
            "Gravitino identity dependency is unavailable"
        ) from exc
    if not isinstance(value, dict):
        raise MetadataFabricGravitinoJdbcRestartError(
            "Gravitino identity dependency is not an object"
        )
    if (
        value.get("evidence_fingerprint")
        != profile.dependency.evidence_fingerprint
        or value.get(profile.dependency.required_claim) is not True
        or value.get("production_identity_verified") is not False
        or identity.verify_evidence_integrity(value)
    ):
        raise MetadataFabricGravitinoJdbcRestartError(
            "Gravitino identity dependency does not match"
        )
    return value


def load_profile(
    path: Path = DEFAULT_PROFILE_PATH,
) -> GravitinoJdbcRestartProfile:
    try:
        value = yaml.safe_load(path.resolve().read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError("JDBC restart profile must be an object")
        ingestion_replay._reject_sensitive_fields(value)
        profile = GravitinoJdbcRestartProfile.model_validate(value)
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise MetadataFabricGravitinoJdbcRestartError(
            "Gravitino JDBC restart profile is invalid"
        ) from exc
    if _profile_securable_objects(profile) != identity._expected_securable_objects():
        raise MetadataFabricGravitinoJdbcRestartError(
            "Gravitino JDBC restart role exceeds the bounded table-create scope"
        )
    _load_dependency(profile)
    return profile


def _manifest_documents() -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for path in sorted(MANIFEST_DIR.glob("*.yaml")):
        if path.name == "kustomization.yaml":
            continue
        for value in yaml.safe_load_all(path.read_text(encoding="utf-8")):
            if isinstance(value, dict):
                documents.append(value)
    return documents


def _validate_manifest() -> list[str]:
    errors: list[str] = []
    try:
        documents = _manifest_documents()
    except (OSError, yaml.YAMLError) as exc:
        return [f"Gravitino JDBC restart manifest is invalid: {type(exc).__name__}"]
    if any(document.get("kind") == "Secret" for document in documents):
        errors.append("Gravitino JDBC restart manifest may not commit Secret values")
    kinds = {str(document.get("kind")) for document in documents}
    required = {
        "Namespace",
        "ResourceQuota",
        "ServiceAccount",
        "ConfigMap",
        "Service",
        "StatefulSet",
    }
    if not required.issubset(kinds):
        errors.append("Gravitino JDBC restart manifest is incomplete")
    rendered = json.dumps(documents, ensure_ascii=True, sort_keys=True)
    markers = (
        "gravitino.authenticators = basic",
        "gravitino.authorization.enable = true",
        "CREATE DATABASE iceberg OWNER gravitino",
        "stage-postgresql-jdbc-driver",
        "postgresql-42.7.0.jar",
        "volumeClaimTemplates",
        "storageClassName",
        "warehouse",
        "automountServiceAccountToken",
        "ClusterIP",
    )
    for marker in markers:
        if marker not in rendered:
            errors.append(f"Gravitino JDBC restart manifest is missing marker: {marker}")
    if "gravitino.authenticators = simple" in rendered:
        errors.append("Gravitino JDBC restart may not enable simple authentication")
    gravitino = next(
        (
            document
            for document in documents
            if document.get("kind") == "StatefulSet"
            and _mapping(document.get("metadata")).get("name")
            == "gravitino-persistence"
        ),
        {},
    )
    pod_spec = _mapping(
        _mapping(_mapping(gravitino.get("spec")).get("template")).get("spec")
    )
    init_containers = pod_spec.get("initContainers")
    init_items = init_containers if isinstance(init_containers, list) else []
    driver_init = next(
        (
            _mapping(item)
            for item in init_items
            if _mapping(item).get("name") == "stage-postgresql-jdbc-driver"
        ),
        {},
    )
    resources = _mapping(driver_init.get("resources"))
    if not {"cpu", "memory"}.issubset(_mapping(resources.get("requests"))) or not {
        "cpu",
        "memory",
    }.issubset(_mapping(resources.get("limits"))):
        errors.append("Gravitino JDBC driver initContainer resources are incomplete")
    return errors


def build_contract_report(
    profile_path: Path = DEFAULT_PROFILE_PATH,
    wrapper_path: Path = DEFAULT_WRAPPER_PATH,
) -> dict[str, Any]:
    errors: list[str] = []
    profile: GravitinoJdbcRestartProfile | None = None
    try:
        profile = load_profile(profile_path)
    except MetadataFabricGravitinoJdbcRestartError as exc:
        errors.append(str(exc))
    errors.extend(_validate_manifest())
    try:
        wrapper = wrapper_path.resolve().read_text(encoding="utf-8")
        for marker in ("set -euo pipefail", "metadata_fabric_gravitino_jdbc_restart"):
            if marker not in wrapper:
                errors.append(f"Gravitino JDBC restart wrapper is missing: {marker}")
    except OSError as exc:
        errors.append(f"Gravitino JDBC restart wrapper is invalid: {type(exc).__name__}")

    files: dict[str, dict[str, str]] = {}
    paths = [Path(__file__).resolve(), profile_path.resolve(), wrapper_path.resolve()]
    paths.extend(sorted(MANIFEST_DIR.glob("*.yaml")))
    for path in paths:
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            relative = path.name
        files[relative] = {"path": relative, "sha256": recovery._file_sha256(path)}

    stable = {
        "schema": CONTRACT_SCHEMA,
        "context": CONTEXT,
        "source_namespace": SOURCE_NAMESPACE,
        "rehearsal_namespace": REHEARSAL_NAMESPACE,
        "gravitino_version": "1.3.0",
        "runtime_image_identity": {
            "gravitino_host_image_id": (
                profile.runtime.gravitino_host_image_id if profile else None
            ),
            "gravitino_kubernetes_image_id": (
                profile.runtime.gravitino_kubernetes_image_id if profile else None
            ),
            "postgresql_image_digest": (
                profile.runtime.postgresql_image_digest if profile else None
            ),
        },
        "identity_evidence_fingerprint": IDENTITY_EVIDENCE_FINGERPRINT,
        "catalog": {
            "provider": profile.catalog.provider if profile else None,
            "backend": profile.catalog.backend if profile else None,
            "uri": profile.catalog.uri if profile else None,
            "warehouse": profile.catalog.warehouse if profile else None,
            "driver": profile.catalog.jdbc_driver if profile else None,
            "driver_mount": profile.catalog.jdbc_driver_mount if profile else None,
            "jdbc_initialize": profile.catalog.jdbc_initialize if profile else None,
        },
        "restart_scope": profile.catalog.restart_scope if profile else None,
        "role_securable_objects": (
            _profile_securable_objects(profile) if profile else None
        ),
        "local_static_contract_verified": not errors,
        "local_gravitino_jdbc_catalog_restart_verified": False,
        "local_authenticated_catalog_persistence_verified": False,
        "persistent_catalog_identity_binding_verified": False,
        "protected_workload_identity_verified": False,
        "oidc_verified": False,
        "tls_verified": False,
        "spark_conformance_verified": False,
        "flink_conformance_verified": False,
        "production_ingestion_verified": False,
        "production_ready": False,
        "files": files,
        "errors": errors,
    }
    return {**stable, "contract_fingerprint": recovery._canonical_sha256(stable)}


def _single_list_item(value: Mapping[str, Any], label: str) -> dict[str, Any]:
    items = value.get("items")
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        raise MetadataFabricGravitinoJdbcRestartError(
            f"Kubernetes observation is not singular: {label}"
        )
    return items[0]


def _container_status(pod: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    statuses = _mapping(pod.get("status")).get("containerStatuses")
    if not isinstance(statuses, list):
        return {}
    return next(
        (_mapping(item) for item in statuses if _mapping(item).get("name") == name),
        {},
    )


class IsolatedJdbcRestartRuntime:
    """Own the temporary namespace, persistent volumes and restart sequence."""

    def __init__(self, profile: GravitinoJdbcRestartProfile) -> None:
        self.profile = profile
        self.kubectl = identity._Kubectl(profile.cluster.context)
        self.owned_namespace = False
        self.schema_sha256: str | None = None
        self.host_image_id: str | None = None

    def _inspect_host_image(self) -> None:
        try:
            completed = subprocess.run(
                [
                    "docker",
                    "image",
                    "inspect",
                    self.profile.runtime.gravitino_image,
                    "--format",
                    "{{.Id}}",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise MetadataFabricGravitinoJdbcRestartError(
                "Gravitino host image identity is unavailable"
            ) from exc
        self.host_image_id = completed.stdout.strip()
        if (
            completed.returncode != 0
            or self.host_image_id != self.profile.runtime.gravitino_host_image_id
        ):
            raise MetadataFabricGravitinoJdbcRestartError(
                "Gravitino host image identity does not match"
            )

    def _runtime_inputs(
        self, admin_material: SecretStr, database_material: SecretStr
    ) -> str:
        source = self.kubectl.get_json(
            [
                "-n",
                self.profile.cluster.source_namespace,
                "get",
                "configmap",
                self.profile.cluster.source_schema_configmap,
            ],
            label="source schema lookup",
        )
        assert source is not None
        schema_sql = _mapping(source.get("data")).get("001-schema.sql")
        if not isinstance(schema_sql, str):
            raise MetadataFabricGravitinoJdbcRestartError(
                "verified Gravitino PostgreSQL schema is unavailable"
            )
        self.schema_sha256 = identity._sha256_text(schema_sql)
        if self.schema_sha256 != GRAVITINO_SCHEMA_SHA256:
            raise MetadataFabricGravitinoJdbcRestartError(
                "Gravitino PostgreSQL schema checksum drift"
            )
        resources = {
            "apiVersion": "v1",
            "kind": "List",
            "items": [
                {
                    "apiVersion": "v1",
                    "kind": "Secret",
                    "metadata": {
                        "name": "gravitino-persistence-runtime",
                        "namespace": self.profile.cluster.rehearsal_namespace,
                    },
                    "type": "Opaque",
                    "stringData": {
                        "admin-password": admin_material.get_secret_value(),
                        "database-password": database_material.get_secret_value(),
                    },
                },
                {
                    "apiVersion": "v1",
                    "kind": "ConfigMap",
                    "metadata": {
                        "name": "gravitino-persistence-schema",
                        "namespace": self.profile.cluster.rehearsal_namespace,
                    },
                    "data": {"001-schema.sql": schema_sql},
                },
            ],
        }
        return json.dumps(resources, ensure_ascii=True, separators=(",", ":"))

    def start(
        self, *, admin_material: SecretStr, database_material: SecretStr
    ) -> dict[str, Any]:
        self._inspect_host_image()
        existing = self.kubectl.get_json(
            ["get", "namespace", self.profile.cluster.rehearsal_namespace],
            allow_not_found=True,
            label="JDBC restart namespace preflight",
        )
        if existing is not None:
            raise MetadataFabricGravitinoJdbcRestartError(
                "Gravitino JDBC restart namespace already exists"
            )
        self.kubectl.run(
            ["apply", "-f", str(MANIFEST_DIR / "namespace.yaml")],
            label="JDBC restart namespace apply",
        )
        self.owned_namespace = True
        self.kubectl.run(
            ["apply", "-f", "-"],
            input_text=self._runtime_inputs(admin_material, database_material),
            label="ephemeral JDBC restart inputs apply",
        )
        self.kubectl.run(
            ["apply", "-k", str(MANIFEST_DIR)],
            label="JDBC restart runtime apply",
        )
        self._wait_for_rollouts()
        return self.observe()

    def _wait_for_rollouts(self) -> None:
        namespace = self.profile.cluster.rehearsal_namespace
        for workload in (
            "statefulset/gravitino-persistence-postgresql",
            "statefulset/gravitino-persistence",
        ):
            self.kubectl.run(
                ["-n", namespace, "rollout", "status", workload, "--timeout=10m"],
                timeout=660,
                label=f"{workload} rollout",
            )

    def _workload(
        self,
        *,
        statefulset_name: str,
        label_name: str,
        container_name: str,
        pvc_name: str,
    ) -> dict[str, Any]:
        namespace = self.profile.cluster.rehearsal_namespace
        statefulset = self.kubectl.get_json(
            ["-n", namespace, "get", "statefulset", statefulset_name],
            label=f"{statefulset_name} observation",
        )
        pod_list = self.kubectl.get_json(
            [
                "-n",
                namespace,
                "get",
                "pods",
                "-l",
                f"app.kubernetes.io/name={label_name}",
            ],
            label=f"{statefulset_name} pod observation",
        )
        pvc = self.kubectl.get_json(
            ["-n", namespace, "get", "pvc", pvc_name],
            label=f"{pvc_name} observation",
        )
        assert statefulset is not None and pod_list is not None and pvc is not None
        pod = _single_list_item(pod_list, statefulset_name)
        pod_spec = _mapping(pod.get("spec"))
        status = _container_status(pod, container_name)
        pvc_spec = _mapping(pvc.get("spec"))
        return {
            "statefulset_uid": _mapping(statefulset.get("metadata")).get("uid"),
            "pod_uid": _mapping(pod.get("metadata")).get("uid"),
            "pod_name": _mapping(pod.get("metadata")).get("name"),
            "node_name": pod_spec.get("nodeName"),
            "ready_replicas": _mapping(statefulset.get("status")).get(
                "readyReplicas", 0
            ),
            "service_account": pod_spec.get("serviceAccountName"),
            "service_account_automount_disabled": (
                pod_spec.get("automountServiceAccountToken") is False
            ),
            "image": status.get("image"),
            "image_id": status.get("imageID"),
            "pvc": {
                "name": _mapping(pvc.get("metadata")).get("name"),
                "uid": _mapping(pvc.get("metadata")).get("uid"),
                "storage_class": pvc_spec.get("storageClassName"),
                "volume_name": pvc_spec.get("volumeName"),
                "phase": _mapping(pvc.get("status")).get("phase"),
            },
        }

    def observe(self) -> dict[str, Any]:
        namespace_name = self.profile.cluster.rehearsal_namespace
        namespace = self.kubectl.get_json(
            ["get", "namespace", namespace_name], label="namespace observation"
        )
        service = self.kubectl.get_json(
            ["-n", namespace_name, "get", "service", self.profile.runtime.service],
            label="Gravitino persistence service observation",
        )
        assert namespace is not None and service is not None
        driver = self.kubectl.run(
            [
                "-n",
                namespace_name,
                "exec",
                "gravitino-persistence-0",
                "--",
                "test",
                "-r",
                self.profile.catalog.jdbc_driver_mount,
            ],
            expected=frozenset({0, 1}),
            timeout=60,
            label="JDBC driver mount probe",
        )
        return {
            "context": self.profile.cluster.context,
            "gravitino_host_image_id": self.host_image_id,
            "namespace": {
                "name": _mapping(namespace.get("metadata")).get("name"),
                "uid": _mapping(namespace.get("metadata")).get("uid"),
            },
            "service": {
                "name": _mapping(service.get("metadata")).get("name"),
                "uid": _mapping(service.get("metadata")).get("uid"),
                "type": _mapping(service.get("spec")).get("type"),
            },
            "postgresql": self._workload(
                statefulset_name="gravitino-persistence-postgresql",
                label_name="gravitino-persistence-postgresql",
                container_name="postgresql",
                pvc_name=self.profile.catalog.postgresql_pvc,
            ),
            "gravitino": self._workload(
                statefulset_name="gravitino-persistence",
                label_name="gravitino-persistence",
                container_name="gravitino",
                pvc_name=self.profile.catalog.warehouse_pvc,
            ),
            "jdbc_driver_mounted": driver.returncode == 0,
            "source_schema_sha256": self.schema_sha256,
        }

    def restart(self) -> dict[str, Any]:
        before = self.observe()
        namespace = self.profile.cluster.rehearsal_namespace
        for workload in (
            "statefulset/gravitino-persistence-postgresql",
            "statefulset/gravitino-persistence",
        ):
            self.kubectl.run(
                ["-n", namespace, "rollout", "restart", workload],
                label=f"{workload} restart",
            )
            self.kubectl.run(
                ["-n", namespace, "rollout", "status", workload, "--timeout=10m"],
                timeout=660,
                label=f"{workload} restart rollout",
            )
        after = self.observe()
        return {"before": before, "after": after}

    def cleanup(self) -> dict[str, Any]:
        deleted = False
        if self.owned_namespace:
            try:
                self.kubectl.run(
                    [
                        "delete",
                        "namespace",
                        self.profile.cluster.rehearsal_namespace,
                        "--wait=true",
                        "--timeout=5m",
                    ],
                    timeout=330,
                    label="JDBC restart namespace cleanup",
                )
                deleted = True
            finally:
                self.owned_namespace = False
        absent = (
            self.kubectl.get_json(
                ["get", "namespace", self.profile.cluster.rehearsal_namespace],
                allow_not_found=True,
                label="JDBC restart namespace cleanup verification",
            )
            is None
        )
        return {
            "namespace_delete_completed": deleted,
            "namespace_absent": absent,
            "provider_objects_retained": False,
            "persistent_volumes_retained": False,
        }


def _table_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    columns = value.get("columns")
    projected_columns: list[dict[str, Any]] = []
    if isinstance(columns, list):
        for column in columns:
            item = _mapping(column)
            projected_columns.append(
                {
                    "name": item.get("name"),
                    "type": item.get("type"),
                    "nullable": item.get("nullable"),
                }
            )
    properties = _mapping(value.get("properties"))
    return {
        "name": value.get("name"),
        "columns": projected_columns,
        "probe_property": properties.get("gda.persistence_probe"),
    }


class PersistentCatalogRehearsal:
    """Create and re-read a JDBC catalog through one bounded Basic principal."""

    def __init__(
        self,
        *,
        base_url: str,
        admin_name: str,
        admin_material: SecretStr,
    ) -> None:
        self.base_url = base_url
        self.admin = identity._BasicApi(
            base_url=base_url,
            username=admin_name,
            material=admin_material,
        )
        self.clients: list[identity._BasicApi] = []

    def close(self) -> None:
        for client in self.clients:
            client.close()
        self.clients.clear()
        self.admin.close()

    def _user(self, profile: GravitinoJdbcRestartProfile, material: SecretStr) -> identity._BasicApi:
        client = identity._BasicApi(
            base_url=self.base_url,
            username=profile.identity.user,
            material=material,
        )
        self.clients.append(client)
        return client

    @staticmethod
    def _catalog_path(profile: GravitinoJdbcRestartProfile, catalog: str) -> str:
        return f"metalakes/{quote(profile.scope.metalake)}/catalogs/{quote(catalog)}"

    @classmethod
    def _schema_path(cls, profile: GravitinoJdbcRestartProfile) -> str:
        return (
            f"{cls._catalog_path(profile, profile.scope.catalog)}/schemas/"
            f"{quote(profile.scope.schema_name)}"
        )

    @classmethod
    def _table_path(cls, profile: GravitinoJdbcRestartProfile) -> str:
        return f"{cls._schema_path(profile)}/tables/{quote(profile.scope.table)}"

    @staticmethod
    def _denied_catalog_body(profile: GravitinoJdbcRestartProfile) -> dict[str, Any]:
        return {
            "name": profile.scope.denied_catalog,
            "type": "RELATIONAL",
            "provider": "lakehouse-iceberg",
            "comment": "Must remain denied after provider restart",
            "properties": {
                "catalog-backend": "memory",
                "uri": "file:///tmp/gda-denied",
                "warehouse": "file:///tmp/gda-denied",
            },
        }

    def bootstrap(
        self,
        profile: GravitinoJdbcRestartProfile,
        *,
        database_material: SecretStr,
        user_material: SecretStr,
    ) -> dict[str, Any]:
        admin_status, _version = self.admin.request(
            "GET", "version", label="pre-restart admin authentication"
        )
        _status, metalake_payload = self.admin.request(
            "POST",
            "metalakes",
            json_body={
                "name": profile.scope.metalake,
                "comment": "Local authenticated JDBC restart rehearsal",
                "properties": {"gda.environment": "local_jdbc_restart"},
            },
            label="persistent metalake create",
        )
        metalake = identity._response_entity(
            metalake_payload, "metalake", "persistent metalake create"
        )
        _status, catalog_payload = self.admin.request(
            "POST",
            f"metalakes/{quote(profile.scope.metalake)}/catalogs",
            json_body={
                "name": profile.scope.catalog,
                "type": "RELATIONAL",
                "provider": profile.catalog.provider,
                "comment": "Local JDBC-backed Iceberg persistence catalog",
                "properties": {
                    "catalog-backend": profile.catalog.backend,
                    "uri": profile.catalog.uri,
                    "warehouse": profile.catalog.warehouse,
                    "jdbc-user": "gravitino",
                    "jdbc-password": database_material.get_secret_value(),
                    "gravitino.bypass.jdbc-driver": profile.catalog.jdbc_driver,
                    "gravitino.bypass.jdbc-initialize": "true",
                },
            },
            label="JDBC catalog create",
        )
        catalog = identity._response_entity(catalog_payload, "catalog", "catalog create")
        _status, schema_payload = self.admin.request(
            "POST",
            f"{self._catalog_path(profile, profile.scope.catalog)}/schemas",
            json_body={
                "name": profile.scope.schema_name,
                "comment": "Persistent bounded projection schema",
                "properties": {},
            },
            label="persistent schema create",
        )
        schema = identity._response_entity(schema_payload, "schema", "schema create")

        self.admin.request(
            "POST",
            "idp/users",
            json_body={
                "user": profile.identity.user,
                "password": user_material.get_secret_value(),
            },
            label="persistent IdP user create",
        )
        self.admin.request(
            "POST",
            f"metalakes/{quote(profile.scope.metalake)}/users",
            json_body={"name": profile.identity.user},
            label="persistent metalake user register",
        )
        self.admin.request(
            "POST",
            f"metalakes/{quote(profile.scope.metalake)}/roles",
            json_body={
                "name": profile.identity.role,
                "properties": {"gda.scope": "bounded_table_projection"},
                "securableObjects": identity._expected_securable_objects(),
            },
            label="persistent bounded role create",
        )
        self.admin.request(
            "PUT",
            (
                f"metalakes/{quote(profile.scope.metalake)}/permissions/users/"
                f"{quote(profile.identity.user)}/grant"
            ),
            json_body={"roleNames": [profile.identity.role]},
            label="persistent bounded role grant",
        )
        _status, role_payload = self.admin.request(
            "GET",
            (
                f"metalakes/{quote(profile.scope.metalake)}/roles/"
                f"{quote(profile.identity.role)}"
            ),
            label="pre-restart role readback",
        )
        role = identity._response_entity(role_payload, "role", "role readback")

        bounded = self._user(profile, user_material)
        bounded_status, _payload = bounded.request(
            "GET", "version", label="pre-restart bounded authentication"
        )
        create_status, table_payload = bounded.request(
            "POST",
            f"{self._schema_path(profile)}/tables",
            json_body={
                "name": profile.scope.table,
                "comment": "Authenticated JDBC catalog restart probe",
                "columns": [
                    {
                        "name": "probe_id",
                        "type": "string",
                        "nullable": False,
                        "comment": "Persistence probe identifier",
                    }
                ],
                "properties": {"gda.persistence_probe": "true"},
            },
            label="pre-restart table create",
        )
        table = identity._response_entity(table_payload, "table", "table create")
        read_status, read_payload = bounded.request(
            "GET", self._table_path(profile), label="pre-restart table readback"
        )
        read_table = identity._response_entity(read_payload, "table", "table readback")
        denied_status, _payload = bounded.request(
            "POST",
            f"metalakes/{quote(profile.scope.metalake)}/catalogs",
            json_body=self._denied_catalog_body(profile),
            expected=frozenset({200, 403}),
            label="pre-restart administrative denial",
        )
        projection = _table_projection(read_table)
        return {
            "authentication": {
                "admin_status": admin_status,
                "bounded_status": bounded_status,
                "material_recorded": False,
            },
            "catalog": {
                "metalake": metalake.get("name"),
                "catalog": catalog.get("name"),
                "schema": schema.get("name"),
                "provider": profile.catalog.provider,
                "backend": profile.catalog.backend,
                "uri": profile.catalog.uri,
                "warehouse": profile.catalog.warehouse,
                "jdbc_initialize": profile.catalog.jdbc_initialize,
                "material_recorded": False,
            },
            "role": {
                "name": role.get("name"),
                "securable_objects": identity._normalize_securable_objects(
                    role.get("securableObjects")
                ),
            },
            "table": {
                "create_status": create_status,
                "read_status": read_status,
                "name": table.get("name"),
                "projection": projection,
                "fingerprint": recovery._canonical_sha256(projection),
            },
            "denied_catalog_create_status": denied_status,
        }

    def verify_after_restart(
        self,
        profile: GravitinoJdbcRestartProfile,
        *,
        user_material: SecretStr,
    ) -> dict[str, Any]:
        admin_status, _version = self.admin.request(
            "GET", "version", label="post-restart admin authentication"
        )
        bounded = self._user(profile, user_material)
        bounded_status, _payload = bounded.request(
            "GET", "version", label="post-restart bounded authentication"
        )
        read_status, read_payload = bounded.request(
            "GET", self._table_path(profile), label="post-restart table readback"
        )
        table = identity._response_entity(
            read_payload, "table", "post-restart table readback"
        )
        _status, role_payload = self.admin.request(
            "GET",
            (
                f"metalakes/{quote(profile.scope.metalake)}/roles/"
                f"{quote(profile.identity.role)}"
            ),
            label="post-restart role readback",
        )
        role = identity._response_entity(role_payload, "role", "post-restart role")
        denied_status, _payload = bounded.request(
            "POST",
            f"metalakes/{quote(profile.scope.metalake)}/catalogs",
            json_body=self._denied_catalog_body(profile),
            expected=frozenset({200, 403}),
            label="post-restart administrative denial",
        )
        projection = _table_projection(table)
        return {
            "authentication": {
                "admin_status": admin_status,
                "bounded_status": bounded_status,
                "material_recorded": False,
            },
            "role": {
                "name": role.get("name"),
                "securable_objects": identity._normalize_securable_objects(
                    role.get("securableObjects")
                ),
            },
            "table": {
                "read_status": read_status,
                "name": table.get("name"),
                "projection": projection,
                "fingerprint": recovery._canonical_sha256(projection),
            },
            "denied_catalog_create_status": denied_status,
        }


def _restart_errors(restart: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    before = _mapping(restart.get("before"))
    after = _mapping(restart.get("after"))
    for workload_name, expected_image_id, expected_pvc, expected_account in (
        (
            "postgresql",
            POSTGRESQL_IMAGE_DIGEST,
            "data-gravitino-persistence-postgresql-0",
            "gravitino-persistence-postgresql",
        ),
        (
            "gravitino",
            GRAVITINO_KUBERNETES_IMAGE_ID,
            "warehouse-gravitino-persistence-0",
            "gravitino-persistence",
        ),
    ):
        old = _mapping(before.get(workload_name))
        new = _mapping(after.get(workload_name))
        old_pvc = _mapping(old.get("pvc"))
        new_pvc = _mapping(new.get("pvc"))
        if not _valid_uuid(old.get("statefulset_uid")) or (
            old.get("statefulset_uid") != new.get("statefulset_uid")
        ):
            errors.append(f"{workload_name} StatefulSet identity changed")
        if (
            not _valid_uuid(old.get("pod_uid"))
            or not _valid_uuid(new.get("pod_uid"))
            or old.get("pod_uid") == new.get("pod_uid")
        ):
            errors.append(f"{workload_name} pod did not restart")
        if old.get("ready_replicas") != 1 or new.get("ready_replicas") != 1:
            errors.append(f"{workload_name} was not ready around restart")
        if not all(
            str(snapshot.get("image_id") or "").endswith(expected_image_id)
            for snapshot in (old, new)
        ):
            errors.append(f"{workload_name} runtime image ID does not match")
        if old_pvc.get("name") != expected_pvc or new_pvc.get("name") != expected_pvc:
            errors.append(f"{workload_name} PVC name does not match")
        if not _valid_uuid(old_pvc.get("uid")) or old_pvc.get("uid") != new_pvc.get(
            "uid"
        ):
            errors.append(f"{workload_name} PVC identity changed")
        if old_pvc.get("phase") != "Bound" or new_pvc.get("phase") != "Bound":
            errors.append(f"{workload_name} PVC was not bound")
        if old_pvc.get("storage_class") != "standard" or new_pvc.get(
            "storage_class"
        ) != "standard":
            errors.append(f"{workload_name} PVC storage class does not match")
        if (
            old.get("service_account") != expected_account
            or new.get("service_account") != expected_account
            or
            old.get("service_account_automount_disabled") is not True
            or new.get("service_account_automount_disabled") is not True
        ):
            errors.append(f"{workload_name} service account token isolation failed")
    for snapshot_name, snapshot in (("before", before), ("after", after)):
        if (
            snapshot.get("context") != CONTEXT
            or snapshot.get("gravitino_host_image_id") != GRAVITINO_HOST_IMAGE_ID
            or _mapping(snapshot.get("namespace")).get("name")
            != REHEARSAL_NAMESPACE
            or not _valid_uuid(_mapping(snapshot.get("namespace")).get("uid"))
            or _mapping(snapshot.get("service")).get("name")
            != "gravitino-persistence"
            or _mapping(snapshot.get("service")).get("type") != "ClusterIP"
            or snapshot.get("jdbc_driver_mounted") is not True
            or snapshot.get("source_schema_sha256") != GRAVITINO_SCHEMA_SHA256
        ):
            errors.append(f"{snapshot_name} runtime boundary does not match")
    return errors


def build_evidence(observation: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    try:
        ingestion_replay._reject_sensitive_fields(observation)
    except ValueError:
        errors.append("Gravitino JDBC restart observation contains sensitive material")
    if observation.get("schema") != OBSERVATION_SCHEMA:
        errors.append("Gravitino JDBC restart observation schema does not match")
    contract = _mapping(observation.get("contract"))
    if (
        contract.get("local_static_contract_verified") is not True
        or not _valid_sha256(contract.get("contract_fingerprint"))
        or contract.get("identity_evidence_fingerprint")
        != IDENTITY_EVIDENCE_FINGERPRINT
    ):
        errors.append("Gravitino JDBC restart static contract is not bound")
    restart = _mapping(observation.get("restart"))
    errors.extend(_restart_errors(restart))

    pre = _mapping(observation.get("pre_restart"))
    post = _mapping(observation.get("post_restart"))
    pre_auth = _mapping(pre.get("authentication"))
    post_auth = _mapping(post.get("authentication"))
    pre_catalog = _mapping(pre.get("catalog"))
    pre_role = _mapping(pre.get("role"))
    post_role = _mapping(post.get("role"))
    pre_table = _mapping(pre.get("table"))
    post_table = _mapping(post.get("table"))
    expected_projection = {
        "name": "gda_persistence_probe",
        "columns": [
            {"name": "probe_id", "type": "string", "nullable": False},
        ],
        "probe_property": "true",
    }
    if (
        pre_auth.get("admin_status") != 200
        or pre_auth.get("bounded_status") != 200
        or post_auth.get("admin_status") != 200
        or post_auth.get("bounded_status") != 200
        or pre_auth.get("material_recorded") is not False
        or post_auth.get("material_recorded") is not False
    ):
        errors.append("authenticated principals did not survive restart")
    if pre_catalog != {
        "metalake": "gda_persistence",
        "catalog": "lakehouse",
        "schema": "published",
        "provider": "lakehouse-iceberg",
        "backend": "jdbc",
        "uri": "jdbc:postgresql://gravitino-persistence-postgresql:5432/iceberg",
        "warehouse": "file:///var/lib/gravitino/warehouse",
        "jdbc_initialize": True,
        "material_recorded": False,
    }:
        errors.append("JDBC catalog configuration does not match")
    expected_role = identity._expected_securable_objects()
    if (
        pre_role.get("name") != "gda-table-projection"
        or post_role.get("name") != "gda-table-projection"
        or pre_role.get("securable_objects") != expected_role
        or post_role.get("securable_objects") != expected_role
    ):
        errors.append("minimum-privilege role did not survive restart")
    if (
        pre_table.get("create_status") != 200
        or pre_table.get("read_status") != 200
        or post_table.get("read_status") != 200
        or pre_table.get("name") != "gda_persistence_probe"
        or post_table.get("name") != "gda_persistence_probe"
        or pre_table.get("projection") != expected_projection
        or pre_table.get("fingerprint") != post_table.get("fingerprint")
        or pre_table.get("projection") != post_table.get("projection")
        or pre_table.get("fingerprint")
        != recovery._canonical_sha256(expected_projection)
    ):
        errors.append("JDBC-backed table did not survive restart")
    if (
        pre.get("denied_catalog_create_status") != 403
        or post.get("denied_catalog_create_status") != 403
    ):
        errors.append("administrative catalog mutation was not denied")
    checks = _mapping(observation.get("runtime_checks"))
    if (
        checks.get("all_port_forwards_stopped") is not True
        or checks.get("namespace_delete_completed") is not True
        or checks.get("namespace_absent") is not True
        or checks.get("provider_objects_retained") is not False
        or checks.get("persistent_volumes_retained") is not False
        or checks.get("material_recorded") is not False
    ):
        errors.append("Gravitino JDBC restart cleanup is incomplete")

    verified = not errors
    stable = {
        "schema": EVIDENCE_SCHEMA,
        "environment": "local_docker_desktop",
        "catalog_backend": "jdbc",
        "restart_scope": "postgresql_then_gravitino",
        "identity_evidence_fingerprint": IDENTITY_EVIDENCE_FINGERPRINT,
        "local_gravitino_jdbc_catalog_restart_verified": verified,
        "local_authenticated_catalog_persistence_verified": verified,
        "local_postgresql_pvc_restart_verified": verified,
        "local_warehouse_pvc_restart_verified": verified,
        "persistent_catalog_identity_binding_verified": False,
        "protected_workload_identity_verified": False,
        "oidc_verified": False,
        "tls_verified": False,
        "spark_conformance_verified": False,
        "flink_conformance_verified": False,
        "production_ingestion_verified": False,
        "production_ready": False,
        "observation": dict(observation),
        "errors": errors,
    }
    return {**stable, "evidence_fingerprint": recovery._canonical_sha256(stable)}


def verify_evidence_integrity(evidence: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        ingestion_replay._reject_sensitive_fields(evidence)
    except ValueError:
        errors.append("Gravitino JDBC restart evidence contains sensitive material")
    stable = {
        key: value for key, value in evidence.items() if key != "evidence_fingerprint"
    }
    if evidence.get("evidence_fingerprint") != recovery._canonical_sha256(stable):
        errors.append("Gravitino JDBC restart evidence fingerprint does not match")
    if evidence.get("schema") != EVIDENCE_SCHEMA or evidence.get("errors") != []:
        errors.append("Gravitino JDBC restart evidence is not verified")
    for claim in (
        "local_gravitino_jdbc_catalog_restart_verified",
        "local_authenticated_catalog_persistence_verified",
        "local_postgresql_pvc_restart_verified",
        "local_warehouse_pvc_restart_verified",
    ):
        if evidence.get(claim) is not True:
            errors.append(f"Gravitino JDBC restart evidence claim is false: {claim}")
    for claim in (
        "persistent_catalog_identity_binding_verified",
        "protected_workload_identity_verified",
        "oidc_verified",
        "tls_verified",
        "spark_conformance_verified",
        "flink_conformance_verified",
        "production_ingestion_verified",
        "production_ready",
    ):
        if evidence.get(claim) is not False:
            errors.append(f"Gravitino JDBC restart evidence may not claim {claim}")
    return errors


def run_live_rehearsal(
    profile_path: Path = DEFAULT_PROFILE_PATH,
) -> dict[str, Any]:
    profile = load_profile(profile_path)
    contract = build_contract_report(profile_path)
    if contract.get("local_static_contract_verified") is not True:
        raise MetadataFabricGravitinoJdbcRestartError(
            "Gravitino JDBC restart static contract is invalid"
        )

    admin_material = SecretStr(secrets.token_urlsafe(24))
    database_material = SecretStr(secrets.token_urlsafe(24))
    user_material = SecretStr(secrets.token_urlsafe(24))
    runtime = IsolatedJdbcRestartRuntime(profile)
    before_forward: provider_metrics._PortForward | None = None
    after_forward: provider_metrics._PortForward | None = None
    rehearsal: PersistentCatalogRehearsal | None = None
    pre_restart: dict[str, Any] | None = None
    post_restart: dict[str, Any] | None = None
    restart: dict[str, Any] | None = None
    before_forward_stopped = False
    after_forward_stopped = False
    cleanup: dict[str, Any] = {
        "namespace_delete_completed": False,
        "namespace_absent": False,
        "provider_objects_retained": True,
        "persistent_volumes_retained": True,
    }
    try:
        runtime.start(
            admin_material=admin_material,
            database_material=database_material,
        )
        before_forward = provider_metrics._PortForward(
            kubectl="kubectl",
            context=profile.cluster.context,
            namespace=profile.cluster.rehearsal_namespace,
            service=profile.runtime.service,
            target_port=profile.runtime.service_port,
        )
        before_forward.start()
        rehearsal = PersistentCatalogRehearsal(
            base_url=f"http://127.0.0.1:{before_forward.local_port}/api",
            admin_name=profile.identity.service_admin,
            admin_material=admin_material,
        )
        pre_restart = rehearsal.bootstrap(
            profile,
            database_material=database_material,
            user_material=user_material,
        )
        rehearsal.close()
        rehearsal = None
        before_forward_stopped = before_forward.stop()
        before_forward = None

        restart = runtime.restart()

        after_forward = provider_metrics._PortForward(
            kubectl="kubectl",
            context=profile.cluster.context,
            namespace=profile.cluster.rehearsal_namespace,
            service=profile.runtime.service,
            target_port=profile.runtime.service_port,
        )
        after_forward.start()
        rehearsal = PersistentCatalogRehearsal(
            base_url=f"http://127.0.0.1:{after_forward.local_port}/api",
            admin_name=profile.identity.service_admin,
            admin_material=admin_material,
        )
        post_restart = rehearsal.verify_after_restart(
            profile, user_material=user_material
        )
    finally:
        if rehearsal is not None:
            rehearsal.close()
        if before_forward is not None:
            before_forward_stopped = before_forward.stop()
        if after_forward is not None:
            after_forward_stopped = after_forward.stop()
        cleanup = runtime.cleanup()

    if pre_restart is None or post_restart is None or restart is None:
        raise MetadataFabricGravitinoJdbcRestartError(
            "Gravitino JDBC restart rehearsal did not produce an outcome"
        )
    observation = {
        "schema": OBSERVATION_SCHEMA,
        "observed_at": datetime.now(UTC).isoformat(),
        "contract": {
            "contract_fingerprint": contract["contract_fingerprint"],
            "local_static_contract_verified": True,
            "identity_evidence_fingerprint": IDENTITY_EVIDENCE_FINGERPRINT,
        },
        "restart": restart,
        "pre_restart": pre_restart,
        "post_restart": post_restart,
        "runtime_checks": {
            **cleanup,
            "all_port_forwards_stopped": (
                before_forward_stopped and after_forward_stopped
            ),
            "material_recorded": False,
            "kubernetes_service_account_used_for_provider_login": False,
        },
    }
    return build_evidence(observation)


def build_validation_report(
    *,
    profile_path: Path = DEFAULT_PROFILE_PATH,
    evidence_path: Path = DEFAULT_EVIDENCE_PATH,
) -> dict[str, Any]:
    contract = build_contract_report(profile_path)
    errors = list(contract["errors"])
    evidence: dict[str, Any] | None = None
    try:
        value = json.loads(evidence_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError("Gravitino JDBC restart evidence must be an object")
        evidence = value
        errors.extend(verify_evidence_integrity(evidence))
        observed_contract = _mapping(
            _mapping(evidence.get("observation")).get("contract")
        ).get("contract_fingerprint")
        if observed_contract != contract.get("contract_fingerprint"):
            errors.append("Gravitino JDBC restart evidence contract fingerprint drift")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(
            f"Gravitino JDBC restart evidence is invalid: {type(exc).__name__}"
        )
    verified = not errors
    return {
        "schema": VALIDATION_SCHEMA,
        "local_static_contract_verified": contract["local_static_contract_verified"],
        "local_gravitino_jdbc_catalog_restart_verified": (
            verified
            and evidence is not None
            and evidence.get("local_gravitino_jdbc_catalog_restart_verified") is True
        ),
        "local_authenticated_catalog_persistence_verified": (
            verified
            and evidence is not None
            and evidence.get("local_authenticated_catalog_persistence_verified") is True
        ),
        "persistent_catalog_identity_binding_verified": False,
        "protected_workload_identity_verified": False,
        "oidc_verified": False,
        "tls_verified": False,
        "spark_conformance_verified": False,
        "flink_conformance_verified": False,
        "production_ingestion_verified": False,
        "production_ready": False,
        "contract_fingerprint": contract["contract_fingerprint"],
        "evidence_fingerprint": (
            evidence.get("evidence_fingerprint") if evidence else None
        ),
        "errors": errors,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    validate.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE_PATH)
    rehearse = subparsers.add_parser("rehearse")
    rehearse.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    rehearse.add_argument("--evidence-out", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE_PATH)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            report = build_validation_report(
                profile_path=args.profile, evidence_path=args.evidence
            )
            print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
            return 0 if not report["errors"] else 1
        if args.command == "verify":
            value = json.loads(args.evidence.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError("Gravitino JDBC restart evidence must be an object")
            errors = verify_evidence_integrity(value)
            print(json.dumps({"verified": not errors, "errors": errors}, indent=2))
            return 0 if not errors else 1
        evidence = run_live_rehearsal(args.profile)
        _write_json(args.evidence_out, evidence)
        print(json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if not evidence["errors"] else 1
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        identity.MetadataFabricGravitinoIdentityError,
        MetadataFabricGravitinoJdbcRestartError,
        KeyboardInterrupt,
    ) as exc:
        print(f"metadata fabric Gravitino JDBC restart: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
