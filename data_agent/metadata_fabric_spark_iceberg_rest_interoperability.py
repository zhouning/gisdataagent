"""Verify local Spark interoperability through Gravitino's Iceberg REST server.

The rehearsal creates an Iceberg table through a bounded Gravitino Basic user,
then uses Spark 3.5 through the standard Iceberg REST protocol to read, append,
evolve, snapshot and time-travel the same table. Gravitino must read back the
evolved metadata and the bounded user must remain unable to create a catalog.
All workloads share one Docker Desktop node and one local RWO warehouse PVC, so
the result is local interoperability evidence, never production conformance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import subprocess
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote
from uuid import UUID

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints

from . import metadata_fabric_gravitino_identity as identity
from . import metadata_fabric_gravitino_jdbc_restart as jdbc_restart
from . import metadata_fabric_ingestion_replay as ingestion_replay
from . import metadata_fabric_provider_metrics as provider_metrics
from . import metadata_fabric_recovery_rehearsal as recovery


PROFILE_SCHEMA = (
    "gda.metadata_fabric_spark_iceberg_rest_interoperability_profile.v1"
)
CONTRACT_SCHEMA = (
    "gda.metadata_fabric_spark_iceberg_rest_interoperability_contract.v1"
)
OBSERVATION_SCHEMA = (
    "gda.metadata_fabric_spark_iceberg_rest_interoperability_observation.v1"
)
EVIDENCE_SCHEMA = (
    "gda.metadata_fabric_spark_iceberg_rest_interoperability_evidence.v1"
)
VALIDATION_SCHEMA = (
    "gda.metadata_fabric_spark_iceberg_rest_interoperability_validation.v1"
)

CONTEXT = "docker-desktop"
SOURCE_NAMESPACE = "gda-metadata-sandbox"
REHEARSAL_NAMESPACE = "gda-metadata-spark-interop"
NODE_NAME = "desktop-worker"
GRAVITINO_SCHEMA_SHA256 = identity.GRAVITINO_SCHEMA_SHA256
GRAVITINO_HOST_IMAGE_ID = jdbc_restart.GRAVITINO_HOST_IMAGE_ID
GRAVITINO_KUBERNETES_IMAGE_ID = jdbc_restart.GRAVITINO_KUBERNETES_IMAGE_ID
POSTGRESQL_IMAGE_DIGEST = jdbc_restart.POSTGRESQL_IMAGE_DIGEST
SPARK_HOST_IMAGE_ID = (
    "sha256:f201367640c7583add224796a629150e63d3859ddd7fe9fd47741662a6d415bb"
)
SPARK_KUBERNETES_IMAGE_ID = (
    "sha256:4a4522bfd4e6d1c6c90a244d0145841fbfbbf21ed16ee29ca8b681b5cec60058"
)
JDBC_RESTART_EVIDENCE_FINGERPRINT = (
    "34792bb47ad71041a87adeb644439bf9b6aa3f4855cdc98782d6e3b4282bf1aa"
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = (
    REPO_ROOT
    / "config/metadata-fabric-spark-iceberg-rest-interoperability.local.yaml"
)
DEFAULT_EVIDENCE_PATH = (
    REPO_ROOT
    / "docs/evidence/metadata-fabric-spark-iceberg-rest-interoperability-2026-07-29.json"
)
DEFAULT_WRAPPER_PATH = (
    REPO_ROOT / "scripts/metadata-fabric-spark-iceberg-rest-interoperability.sh"
)
MANIFEST_DIR = REPO_ROOT / "k8s/metadata-fabric-spark-iceberg-rest-interoperability"

NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1024),
]


class MetadataFabricSparkIcebergRestInteroperabilityError(RuntimeError):
    """The local Spark/Iceberg REST interoperability contract failed closed."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ClusterProfile(_FrozenModel):
    context: Literal["docker-desktop"]
    source_namespace: Literal["gda-metadata-sandbox"]
    rehearsal_namespace: Literal["gda-metadata-spark-interop"]
    source_schema_configmap: Literal["metadata-gravitino-schema-1-3-0"]
    storage_class: Literal["standard"]
    node: Literal["desktop-worker"]


class RuntimeProfile(_FrozenModel):
    manifest: Literal[
        "k8s/metadata-fabric-spark-iceberg-rest-interoperability"
    ]
    gravitino_version: Literal["1.3.0"]
    gravitino_image: Literal["gda/gravitino:1.3.0-local-arm64"]
    gravitino_host_image_id: Literal[GRAVITINO_HOST_IMAGE_ID]
    gravitino_kubernetes_image_id: Literal[GRAVITINO_KUBERNETES_IMAGE_ID]
    iceberg_rest_version: Literal["1.11.0"]
    postgresql_version: Literal["16.10-bookworm"]
    postgresql_image: Literal["postgres:16.10-bookworm"]
    postgresql_image_digest: Literal[POSTGRESQL_IMAGE_DIGEST]
    spark_version: Literal["3.5.0"]
    iceberg_spark_runtime_version: Literal["1.6.1"]
    spark_image: Literal["gisdataagent/mmfe-spark-runtime:local"]
    spark_host_image_id: Literal[SPARK_HOST_IMAGE_ID]
    spark_kubernetes_image_id: Literal[SPARK_KUBERNETES_IMAGE_ID]
    service: Literal["gravitino-persistence"]
    gravitino_service_port: Literal[8090]
    iceberg_rest_service_port: Literal[9001]
    iceberg_rest_path: Literal["/iceberg"]
    spark_job: Literal["spark-iceberg-rest-probe"]
    authenticator: Literal["basic"]
    access_control_enabled: Literal[True]
    transport: Literal["local_cluster_http"]


class DependencyProfile(_FrozenModel):
    evidence_path: Literal[
        "docs/evidence/metadata-fabric-gravitino-jdbc-restart-2026-07-29.json"
    ]
    evidence_fingerprint: Literal[JDBC_RESTART_EVIDENCE_FINGERPRINT]
    required_claim: Literal["local_gravitino_jdbc_catalog_restart_verified"]


class IdentityProfile(_FrozenModel):
    service_admin: Literal["gda-interop-admin"]
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
    gravitino_jdbc_driver_mount: Literal[
        "/opt/gravitino/catalogs/lakehouse-iceberg/libs/postgresql-42.7.0.jar"
    ]
    rest_jdbc_driver_mount: Literal[
        "/opt/gravitino/iceberg-rest-server/libs/postgresql-42.7.0.jar"
    ]
    jdbc_initialize: Literal[True]
    warehouse: Literal["file:///var/lib/gravitino/warehouse"]
    postgresql_pvc: Literal["data-gravitino-persistence-postgresql-0"]
    warehouse_pvc: Literal["warehouse-gravitino-persistence-0"]
    interoperability_scope: Literal["local_same_node_shared_rwo_pvc"]


class PrivilegeProfile(_FrozenModel):
    name: Literal["USE_CATALOG", "USE_SCHEMA", "CREATE_TABLE"]
    condition: Literal["ALLOW"]


class SecurableObjectProfile(_FrozenModel):
    full_name: Literal["lakehouse", "lakehouse.published"]
    type: Literal["CATALOG", "SCHEMA"]
    privileges: tuple[PrivilegeProfile, ...]


class ScopeProfile(_FrozenModel):
    metalake: Literal["gda_interop"]
    catalog: Literal["lakehouse"]
    schema_name: Literal["published"] = Field(alias="schema")
    table: Literal["gda_spark_interop_probe"]
    denied_catalog: Literal["unauthorized_catalog"]
    role_securable_objects: tuple[SecurableObjectProfile, ...]


class ClaimProfile(_FrozenModel):
    local_spark_iceberg_rest_interoperability_verified: Literal[False]
    local_spark_create_read_write_verified: Literal[False]
    local_spark_schema_evolution_verified: Literal[False]
    local_spark_snapshot_time_travel_verified: Literal[False]
    gravitino_api_metadata_readback_verified: Literal[False]
    local_same_node_shared_pvc_verified: Literal[False]
    persistent_catalog_identity_binding_verified: Literal[False]
    protected_workload_identity_verified: Literal[False]
    oidc_verified: Literal[False]
    tls_verified: Literal[False]
    spark_conformance_verified: Literal[False]
    flink_conformance_verified: Literal[False]
    production_ingestion_verified: Literal[False]
    production_ready: Literal[False]


class SparkIcebergRestInteroperabilityProfile(_FrozenModel):
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
    profile: SparkIcebergRestInteroperabilityProfile,
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


def _load_dependency(
    profile: SparkIcebergRestInteroperabilityProfile,
) -> dict[str, Any]:
    path = (REPO_ROOT / profile.dependency.evidence_path).resolve()
    try:
        path.relative_to(REPO_ROOT)
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise MetadataFabricSparkIcebergRestInteroperabilityError(
            "Gravitino JDBC restart dependency is unavailable"
        ) from exc
    if not isinstance(value, dict):
        raise MetadataFabricSparkIcebergRestInteroperabilityError(
            "Gravitino JDBC restart dependency is not an object"
        )
    if (
        value.get("evidence_fingerprint")
        != profile.dependency.evidence_fingerprint
        or value.get(profile.dependency.required_claim) is not True
        or jdbc_restart.verify_evidence_integrity(value)
    ):
        raise MetadataFabricSparkIcebergRestInteroperabilityError(
            "Gravitino JDBC restart dependency does not match"
        )
    return value


def load_profile(
    path: Path = DEFAULT_PROFILE_PATH,
) -> SparkIcebergRestInteroperabilityProfile:
    try:
        value = yaml.safe_load(path.resolve().read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError("Spark interoperability profile must be an object")
        ingestion_replay._reject_sensitive_fields(value)
        profile = SparkIcebergRestInteroperabilityProfile.model_validate(value)
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise MetadataFabricSparkIcebergRestInteroperabilityError(
            "Spark/Iceberg REST interoperability profile is invalid"
        ) from exc
    if _profile_securable_objects(profile) != identity._expected_securable_objects():
        raise MetadataFabricSparkIcebergRestInteroperabilityError(
            "Spark interoperability role exceeds the bounded table-create scope"
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
        return [f"Spark interoperability manifest is invalid: {type(exc).__name__}"]
    if any(document.get("kind") == "Secret" for document in documents):
        errors.append("Spark interoperability manifest may not commit Secret values")
    kinds = {str(document.get("kind")) for document in documents}
    required = {
        "Namespace",
        "ResourceQuota",
        "ServiceAccount",
        "ConfigMap",
        "Service",
        "StatefulSet",
        "Job",
    }
    if not required.issubset(kinds):
        errors.append("Spark interoperability manifest is incomplete")
    rendered = json.dumps(documents, ensure_ascii=True, sort_keys=True)
    markers = (
        "gravitino.authenticators = basic",
        "gravitino.authorization.enable = true",
        "gravitino.iceberg-rest.catalog-backend = jdbc",
        "gravitino.iceberg-rest.httpPort = 9001",
        "gravitino.iceberg-rest.warehouse = file:///var/lib/gravitino/warehouse",
        "stage-postgresql-jdbc-driver",
        "iceberg_runtime",
        "http://gravitino-persistence:9001/iceberg",
        "VERSION AS OF",
        "snapshot_history_verified",
        "automountServiceAccountToken",
        "warehouse-gravitino-persistence-0",
        "desktop-worker",
    )
    for marker in markers:
        if marker not in rendered:
            errors.append(f"Spark interoperability manifest is missing marker: {marker}")
    if "gravitino.authenticators = simple" in rendered:
        errors.append("Spark interoperability may not enable simple authentication")

    job = next(
        (
            document
            for document in documents
            if document.get("kind") == "Job"
            and _mapping(document.get("metadata")).get("name")
            == "spark-iceberg-rest-probe"
        ),
        {},
    )
    job_spec = _mapping(job.get("spec"))
    pod_spec = _mapping(_mapping(job_spec.get("template")).get("spec"))
    containers = pod_spec.get("containers")
    container_items = containers if isinstance(containers, list) else []
    spark = next(
        (
            _mapping(item)
            for item in container_items
            if _mapping(item).get("name") == "spark"
        ),
        {},
    )
    resources = _mapping(spark.get("resources"))
    security = _mapping(spark.get("securityContext"))
    if job_spec.get("suspend") is not True:
        errors.append("Spark interoperability Job must start suspended")
    if pod_spec.get("automountServiceAccountToken") is not False:
        errors.append("Spark interoperability Job must disable token automount")
    if not {"cpu", "memory"}.issubset(_mapping(resources.get("requests"))) or not {
        "cpu",
        "memory",
    }.issubset(_mapping(resources.get("limits"))):
        errors.append("Spark interoperability Job resources are incomplete")
    if (
        security.get("allowPrivilegeEscalation") is not False
        or security.get("readOnlyRootFilesystem") is not True
    ):
        errors.append("Spark interoperability Job security context is incomplete")
    return errors


def build_contract_report(
    profile_path: Path = DEFAULT_PROFILE_PATH,
    wrapper_path: Path = DEFAULT_WRAPPER_PATH,
) -> dict[str, Any]:
    errors: list[str] = []
    profile: SparkIcebergRestInteroperabilityProfile | None = None
    try:
        profile = load_profile(profile_path)
    except MetadataFabricSparkIcebergRestInteroperabilityError as exc:
        errors.append(str(exc))
    errors.extend(_validate_manifest())
    try:
        wrapper = wrapper_path.resolve().read_text(encoding="utf-8")
        for marker in (
            "set -euo pipefail",
            "metadata_fabric_spark_iceberg_rest_interoperability",
        ):
            if marker not in wrapper:
                errors.append(f"Spark interoperability wrapper is missing: {marker}")
    except OSError as exc:
        errors.append(f"Spark interoperability wrapper is invalid: {type(exc).__name__}")

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
        "node": NODE_NAME,
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
            "spark_host_image_id": (
                profile.runtime.spark_host_image_id if profile else None
            ),
            "spark_kubernetes_image_id": (
                profile.runtime.spark_kubernetes_image_id if profile else None
            ),
        },
        "versions": {
            "gravitino": profile.runtime.gravitino_version if profile else None,
            "iceberg_rest": (
                profile.runtime.iceberg_rest_version if profile else None
            ),
            "spark": profile.runtime.spark_version if profile else None,
            "iceberg_spark_runtime": (
                profile.runtime.iceberg_spark_runtime_version if profile else None
            ),
        },
        "jdbc_restart_evidence_fingerprint": JDBC_RESTART_EVIDENCE_FINGERPRINT,
        "catalog": {
            "provider": profile.catalog.provider if profile else None,
            "backend": profile.catalog.backend if profile else None,
            "uri": profile.catalog.uri if profile else None,
            "warehouse": profile.catalog.warehouse if profile else None,
            "interoperability_scope": (
                profile.catalog.interoperability_scope if profile else None
            ),
        },
        "role_securable_objects": (
            _profile_securable_objects(profile) if profile else None
        ),
        "local_static_contract_verified": not errors,
        "local_spark_iceberg_rest_interoperability_verified": False,
        "spark_conformance_verified": False,
        "flink_conformance_verified": False,
        "persistent_catalog_identity_binding_verified": False,
        "protected_workload_identity_verified": False,
        "oidc_verified": False,
        "tls_verified": False,
        "production_ingestion_verified": False,
        "production_ready": False,
        "files": files,
        "errors": errors,
    }
    return {**stable, "contract_fingerprint": recovery._canonical_sha256(stable)}


def _single_list_item(value: Mapping[str, Any], label: str) -> dict[str, Any]:
    items = value.get("items")
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        raise MetadataFabricSparkIcebergRestInteroperabilityError(
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


class IsolatedSparkInteroperabilityRuntime:
    """Own the temporary namespace, shared PVC and suspended Spark Job."""

    def __init__(self, profile: SparkIcebergRestInteroperabilityProfile) -> None:
        self.profile = profile
        self.kubectl = identity._Kubectl(profile.cluster.context)
        self.owned_namespace = False
        self.schema_sha256: str | None = None
        self.gravitino_host_image_id: str | None = None
        self.spark_host_image_id: str | None = None

    @staticmethod
    def _inspect_host_image(image: str, expected_id: str, label: str) -> str:
        try:
            completed = subprocess.run(
                ["docker", "image", "inspect", image, "--format", "{{.Id}}"],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise MetadataFabricSparkIcebergRestInteroperabilityError(
                f"{label} host image identity is unavailable"
            ) from exc
        image_id = completed.stdout.strip()
        if completed.returncode != 0 or image_id != expected_id:
            raise MetadataFabricSparkIcebergRestInteroperabilityError(
                f"{label} host image identity does not match"
            )
        return image_id

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
            raise MetadataFabricSparkIcebergRestInteroperabilityError(
                "verified Gravitino PostgreSQL schema is unavailable"
            )
        self.schema_sha256 = identity._sha256_text(schema_sql)
        if self.schema_sha256 != GRAVITINO_SCHEMA_SHA256:
            raise MetadataFabricSparkIcebergRestInteroperabilityError(
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
        self.gravitino_host_image_id = self._inspect_host_image(
            self.profile.runtime.gravitino_image,
            self.profile.runtime.gravitino_host_image_id,
            "Gravitino",
        )
        self.spark_host_image_id = self._inspect_host_image(
            self.profile.runtime.spark_image,
            self.profile.runtime.spark_host_image_id,
            "Spark",
        )
        existing = self.kubectl.get_json(
            ["get", "namespace", self.profile.cluster.rehearsal_namespace],
            allow_not_found=True,
            label="Spark interoperability namespace preflight",
        )
        if existing is not None:
            raise MetadataFabricSparkIcebergRestInteroperabilityError(
                "Spark interoperability namespace already exists"
            )
        self.kubectl.run(
            ["apply", "-f", str(MANIFEST_DIR / "namespace.yaml")],
            label="Spark interoperability namespace apply",
        )
        self.owned_namespace = True
        self.kubectl.run(
            ["apply", "-f", "-"],
            input_text=self._runtime_inputs(admin_material, database_material),
            label="ephemeral Spark interoperability inputs apply",
        )
        self.kubectl.run(
            ["apply", "-k", str(MANIFEST_DIR)],
            label="Spark interoperability runtime apply",
        )
        for workload in (
            "statefulset/gravitino-persistence-postgresql",
            "statefulset/gravitino-persistence",
        ):
            self.kubectl.run(
                [
                    "-n",
                    self.profile.cluster.rehearsal_namespace,
                    "rollout",
                    "status",
                    workload,
                    "--timeout=10m",
                ],
                timeout=660,
                label=f"{workload} rollout",
            )
        return self.observe_runtime()

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

    def observe_runtime(self) -> dict[str, Any]:
        namespace_name = self.profile.cluster.rehearsal_namespace
        namespace = self.kubectl.get_json(
            ["get", "namespace", namespace_name], label="namespace observation"
        )
        service = self.kubectl.get_json(
            ["-n", namespace_name, "get", "service", self.profile.runtime.service],
            label="Gravitino interoperability service observation",
        )
        pod = self.kubectl.get_json(
            ["-n", namespace_name, "get", "pod", "gravitino-persistence-0"],
            label="Gravitino interoperability pod observation",
        )
        assert namespace is not None and service is not None and pod is not None
        main_driver = self.kubectl.run(
            [
                "-n",
                namespace_name,
                "exec",
                "gravitino-persistence-0",
                "-c",
                "gravitino",
                "--",
                "test",
                "-r",
                self.profile.catalog.gravitino_jdbc_driver_mount,
            ],
            expected=frozenset({0, 1}),
            timeout=60,
            label="Gravitino JDBC driver mount probe",
        )
        rest_driver = self.kubectl.run(
            [
                "-n",
                namespace_name,
                "exec",
                "gravitino-persistence-0",
                "-c",
                "iceberg-rest",
                "--",
                "test",
                "-r",
                self.profile.catalog.rest_jdbc_driver_mount,
            ],
            expected=frozenset({0, 1}),
            timeout=60,
            label="Iceberg REST JDBC driver mount probe",
        )
        rest_status = _container_status(pod, "iceberg-rest")
        ports = _mapping(service.get("spec")).get("ports")
        service_ports = sorted(
            [
                {"name": _mapping(item).get("name"), "port": _mapping(item).get("port")}
                for item in ports
            ],
            key=lambda item: str(item["name"]),
        ) if isinstance(ports, list) else []
        return {
            "context": self.profile.cluster.context,
            "gravitino_host_image_id": self.gravitino_host_image_id,
            "spark_host_image_id": self.spark_host_image_id,
            "namespace": {
                "name": _mapping(namespace.get("metadata")).get("name"),
                "uid": _mapping(namespace.get("metadata")).get("uid"),
            },
            "service": {
                "name": _mapping(service.get("metadata")).get("name"),
                "uid": _mapping(service.get("metadata")).get("uid"),
                "type": _mapping(service.get("spec")).get("type"),
                "ports": service_ports,
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
            "iceberg_rest": {
                "image": rest_status.get("image"),
                "image_id": rest_status.get("imageID"),
                "ready": _mapping(rest_status.get("ready")).get("value", False)
                if isinstance(rest_status.get("ready"), Mapping)
                else rest_status.get("ready"),
                "jdbc_driver_mounted": rest_driver.returncode == 0,
                "path": self.profile.runtime.iceberg_rest_path,
            },
            "gravitino_jdbc_driver_mounted": main_driver.returncode == 0,
            "source_schema_sha256": self.schema_sha256,
        }

    def run_spark_probe(self) -> dict[str, Any]:
        namespace = self.profile.cluster.rehearsal_namespace
        job_name = self.profile.runtime.spark_job
        self.kubectl.run(
            [
                "-n",
                namespace,
                "patch",
                "job",
                job_name,
                "--type=merge",
                "-p",
                '{"spec":{"suspend":false}}',
            ],
            label="Spark interoperability Job release",
        )
        deadline = time.monotonic() + 900
        terminal_condition: str | None = None
        while time.monotonic() < deadline:
            current_job = self.kubectl.get_json(
                ["-n", namespace, "get", "job", job_name],
                label="Spark interoperability Job wait",
            )
            assert current_job is not None
            conditions = _mapping(current_job.get("status")).get("conditions")
            if isinstance(conditions, list):
                for condition in conditions:
                    item = _mapping(condition)
                    if item.get("status") == "True" and item.get("type") in {
                        "Complete",
                        "Failed",
                    }:
                        terminal_condition = str(item["type"])
                        break
            if terminal_condition is not None:
                break
            time.sleep(2)
        job = self.kubectl.get_json(
            ["-n", namespace, "get", "job", job_name],
            label="Spark interoperability Job observation",
        )
        pod_list = self.kubectl.get_json(
            [
                "-n",
                namespace,
                "get",
                "pods",
                "-l",
                "job-name=spark-iceberg-rest-probe",
            ],
            label="Spark interoperability pod observation",
        )
        assert job is not None and pod_list is not None
        pod = _single_list_item(pod_list, "Spark interoperability Job")
        pod_name = _mapping(pod.get("metadata")).get("name")
        logs = self.kubectl.run(
            ["-n", namespace, "logs", str(pod_name), "-c", "spark"],
            expected=frozenset({0, 1}),
            timeout=120,
            label="Spark interoperability result collection",
        )
        result_lines = [
            line.removeprefix("GDA_SPARK_RESULT=")
            for line in logs.stdout.splitlines()
            if line.startswith("GDA_SPARK_RESULT=")
        ]
        result: dict[str, Any] | None = None
        if len(result_lines) == 1:
            try:
                candidate = json.loads(result_lines[0])
                if isinstance(candidate, dict):
                    result = candidate
            except json.JSONDecodeError:
                result = None
        pod_spec = _mapping(pod.get("spec"))
        volumes = pod_spec.get("volumes")
        warehouse_claim = None
        if isinstance(volumes, list):
            for volume in volumes:
                item = _mapping(volume)
                if item.get("name") == "warehouse":
                    warehouse_claim = _mapping(item.get("persistentVolumeClaim")).get(
                        "claimName"
                    )
        container = _container_status(pod, "spark")
        job_status = _mapping(job.get("status"))
        return {
            "wait_completed": terminal_condition == "Complete",
            "terminal_condition": terminal_condition,
            "job": {
                "name": _mapping(job.get("metadata")).get("name"),
                "uid": _mapping(job.get("metadata")).get("uid"),
                "succeeded": job_status.get("succeeded", 0),
                "failed": job_status.get("failed", 0),
                "completion_time": job_status.get("completionTime"),
            },
            "pod": {
                "name": pod_name,
                "uid": _mapping(pod.get("metadata")).get("uid"),
                "phase": _mapping(pod.get("status")).get("phase"),
                "node_name": pod_spec.get("nodeName"),
                "service_account": pod_spec.get("serviceAccountName"),
                "service_account_automount_disabled": (
                    pod_spec.get("automountServiceAccountToken") is False
                ),
                "image": container.get("image"),
                "image_id": container.get("imageID"),
                "warehouse_pvc": warehouse_claim,
            },
            "result_line_count": len(result_lines),
            "log_sha256": hashlib.sha256(logs.stdout.encode("utf-8")).hexdigest(),
            "log_recorded": False,
            "result": result,
        }

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
                    label="Spark interoperability namespace cleanup",
                )
                deleted = True
            finally:
                self.owned_namespace = False
        absent = (
            self.kubectl.get_json(
                ["get", "namespace", self.profile.cluster.rehearsal_namespace],
                allow_not_found=True,
                label="Spark interoperability cleanup verification",
            )
            is None
        )
        return {
            "namespace_delete_completed": deleted,
            "namespace_absent": absent,
            "provider_objects_retained": False,
            "persistent_volumes_retained": False,
        }


def _post_spark_readback(
    rehearsal: jdbc_restart.PersistentCatalogRehearsal,
    profile: SparkIcebergRestInteroperabilityProfile,
    user_material: SecretStr,
) -> dict[str, Any]:
    bounded = rehearsal._user(profile, user_material)
    authentication_status, _payload = bounded.request(
        "GET", "version", label="post-Spark bounded authentication"
    )
    read_status, read_payload = bounded.request(
        "GET",
        rehearsal._table_path(profile),
        label="post-Spark Gravitino table readback",
    )
    table = identity._response_entity(
        read_payload, "table", "post-Spark Gravitino table readback"
    )
    denied_status, _payload = bounded.request(
        "POST",
        f"metalakes/{quote(profile.scope.metalake)}/catalogs",
        json_body=rehearsal._denied_catalog_body(profile),
        expected=frozenset({200, 403}),
        label="post-Spark administrative denial",
    )
    projection = jdbc_restart._table_projection(table)
    return {
        "authentication_status": authentication_status,
        "read_status": read_status,
        "table": {
            "name": table.get("name"),
            "projection": projection,
            "fingerprint": recovery._canonical_sha256(projection),
        },
        "denied_catalog_create_status": denied_status,
    }


def _runtime_errors(runtime: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    namespace = _mapping(runtime.get("namespace"))
    service = _mapping(runtime.get("service"))
    postgresql = _mapping(runtime.get("postgresql"))
    gravitino = _mapping(runtime.get("gravitino"))
    iceberg_rest = _mapping(runtime.get("iceberg_rest"))
    if (
        runtime.get("context") != CONTEXT
        or runtime.get("gravitino_host_image_id") != GRAVITINO_HOST_IMAGE_ID
        or runtime.get("spark_host_image_id") != SPARK_HOST_IMAGE_ID
        or namespace.get("name") != REHEARSAL_NAMESPACE
        or not _valid_uuid(namespace.get("uid"))
        or service.get("name") != "gravitino-persistence"
        or service.get("type") != "ClusterIP"
        or service.get("ports")
        != [{"name": "http", "port": 8090}, {"name": "iceberg-rest", "port": 9001}]
        or runtime.get("source_schema_sha256") != GRAVITINO_SCHEMA_SHA256
    ):
        errors.append("Spark interoperability runtime boundary does not match")
    for name, value, image_id, pvc_name, account in (
        (
            "postgresql",
            postgresql,
            POSTGRESQL_IMAGE_DIGEST,
            "data-gravitino-persistence-postgresql-0",
            "gravitino-persistence-postgresql",
        ),
        (
            "gravitino",
            gravitino,
            GRAVITINO_KUBERNETES_IMAGE_ID,
            "warehouse-gravitino-persistence-0",
            "gravitino-persistence",
        ),
    ):
        pvc = _mapping(value.get("pvc"))
        if (
            not _valid_uuid(value.get("statefulset_uid"))
            or not _valid_uuid(value.get("pod_uid"))
            or value.get("ready_replicas") != 1
            or value.get("node_name") != NODE_NAME
            or not str(value.get("image_id") or "").endswith(image_id)
            or value.get("service_account") != account
            or value.get("service_account_automount_disabled") is not True
            or pvc.get("name") != pvc_name
            or not _valid_uuid(pvc.get("uid"))
            or pvc.get("storage_class") != "standard"
            or pvc.get("phase") != "Bound"
        ):
            errors.append(f"{name} runtime observation does not match")
    if (
        not str(iceberg_rest.get("image_id") or "").endswith(
            GRAVITINO_KUBERNETES_IMAGE_ID
        )
        or iceberg_rest.get("ready") is not True
        or iceberg_rest.get("jdbc_driver_mounted") is not True
        or iceberg_rest.get("path") != "/iceberg"
        or runtime.get("gravitino_jdbc_driver_mounted") is not True
    ):
        errors.append("Iceberg REST sidecar boundary does not match")
    return errors


def _spark_errors(spark: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    job = _mapping(spark.get("job"))
    pod = _mapping(spark.get("pod"))
    result = _mapping(spark.get("result"))
    if (
        spark.get("wait_completed") is not True
        or job.get("name") != "spark-iceberg-rest-probe"
        or not _valid_uuid(job.get("uid"))
        or job.get("succeeded") != 1
        or job.get("failed") != 0
        or not job.get("completion_time")
        or pod.get("phase") != "Succeeded"
        or not _valid_uuid(pod.get("uid"))
    ):
        errors.append("Spark interoperability Job did not complete exactly once")
    if (
        pod.get("node_name") != NODE_NAME
        or pod.get("service_account") != "spark-iceberg-rest-probe"
        or pod.get("service_account_automount_disabled") is not True
        or not str(pod.get("image_id") or "").endswith(
            SPARK_KUBERNETES_IMAGE_ID
        )
        or pod.get("warehouse_pvc") != "warehouse-gravitino-persistence-0"
    ):
        errors.append("Spark interoperability runtime boundary does not match")
    if (
        spark.get("result_line_count") != 1
        or not _valid_sha256(spark.get("log_sha256"))
        or spark.get("log_recorded") is not False
        or result.get("schema") != "gda.spark_iceberg_rest_probe_result.v1"
        or result.get("spark_version") != "3.5.0"
        or result.get("iceberg_runtime") != "1.6.1"
        or result.get("catalog_uri")
        != "http://gravitino-persistence:9001/iceberg"
        or result.get("table") != "rest.published.gda_spark_interop_probe"
    ):
        errors.append("Spark interoperability result envelope does not match")
    if (
        result.get("initial_columns") != ["probe_id"]
        or result.get("initial_row_count") != 0
        or result.get("current_columns") != ["probe_id", "quality"]
        or result.get("current_rows")
        != [["spark-a", None], ["spark-b", None], ["spark-c", "verified"]]
        or result.get("create_read_write_verified") is not True
    ):
        errors.append("Spark create/read/write result does not match")
    snapshot_ids = result.get("snapshot_ids")
    if (
        not isinstance(snapshot_ids, list)
        or len(snapshot_ids) != 2
        or len(set(snapshot_ids)) != 2
        or not all(isinstance(value, int) and value > 0 for value in snapshot_ids)
        or result.get("snapshot_operations") != ["append", "append"]
        or result.get("time_travel_snapshot_id") != snapshot_ids[0]
        or result.get("time_travel_rows") != ["spark-a", "spark-b"]
        or result.get("snapshot_history_verified") is not True
        or result.get("time_travel_verified") is not True
    ):
        errors.append("Spark snapshot/time-travel result does not match")
    if result.get("schema_evolution_verified") is not True:
        errors.append("Spark schema evolution result does not match")
    return errors


def _expected_post_spark_projection() -> dict[str, Any]:
    return {
        "name": "gda_spark_interop_probe",
        "columns": [
            {"name": "probe_id", "type": "string", "nullable": False},
            {"name": "quality", "type": "string", "nullable": True},
        ],
        "probe_property": "true",
    }


def build_evidence(observation: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    try:
        ingestion_replay._reject_sensitive_fields(observation)
    except ValueError:
        errors.append("Spark interoperability observation contains sensitive material")
    if observation.get("schema") != OBSERVATION_SCHEMA:
        errors.append("Spark interoperability observation schema does not match")
    contract = _mapping(observation.get("contract"))
    if (
        contract.get("local_static_contract_verified") is not True
        or not _valid_sha256(contract.get("contract_fingerprint"))
        or contract.get("jdbc_restart_evidence_fingerprint")
        != JDBC_RESTART_EVIDENCE_FINGERPRINT
    ):
        errors.append("Spark interoperability contract binding does not match")

    runtime = _mapping(observation.get("runtime"))
    errors.extend(_runtime_errors(runtime))
    pre_spark = _mapping(observation.get("pre_spark"))
    pre_table = _mapping(pre_spark.get("table"))
    expected_pre_projection = {
        "name": "gda_spark_interop_probe",
        "columns": [{"name": "probe_id", "type": "string", "nullable": False}],
        "probe_property": "true",
    }
    if (
        _mapping(pre_spark.get("authentication")).get("admin_status") != 200
        or _mapping(pre_spark.get("authentication")).get("bounded_status") != 200
        or pre_table.get("create_status") != 200
        or pre_table.get("read_status") != 200
        or pre_table.get("projection") != expected_pre_projection
        or pre_table.get("fingerprint")
        != recovery._canonical_sha256(expected_pre_projection)
        or pre_spark.get("denied_catalog_create_status") != 403
    ):
        errors.append("Gravitino bounded pre-Spark table boundary does not match")

    spark = _mapping(observation.get("spark"))
    spark_errors = _spark_errors(spark)
    errors.extend(spark_errors)
    post_spark = _mapping(observation.get("post_spark"))
    post_table = _mapping(post_spark.get("table"))
    expected_post_projection = _expected_post_spark_projection()
    api_readback_verified = (
        post_spark.get("authentication_status") == 200
        and post_spark.get("read_status") == 200
        and post_table.get("projection") == expected_post_projection
        and post_table.get("fingerprint")
        == recovery._canonical_sha256(expected_post_projection)
    )
    if not api_readback_verified:
        errors.append("Gravitino API did not read back Spark schema evolution")
    if post_spark.get("denied_catalog_create_status") != 403:
        errors.append("Post-Spark administrative catalog mutation was not denied")

    spark_pod = _mapping(spark.get("pod"))
    same_node_shared_pvc_verified = (
        _mapping(runtime.get("postgresql")).get("node_name") == NODE_NAME
        and _mapping(runtime.get("gravitino")).get("node_name") == NODE_NAME
        and spark_pod.get("node_name") == NODE_NAME
        and _mapping(_mapping(runtime.get("gravitino")).get("pvc")).get("name")
        == "warehouse-gravitino-persistence-0"
        and spark_pod.get("warehouse_pvc")
        == "warehouse-gravitino-persistence-0"
    )
    if not same_node_shared_pvc_verified:
        errors.append("Spark and Gravitino did not share the bounded local PVC scope")

    runtime_checks = _mapping(observation.get("runtime_checks"))
    if (
        runtime_checks.get("namespace_delete_completed") is not True
        or runtime_checks.get("namespace_absent") is not True
        or runtime_checks.get("provider_objects_retained") is not False
        or runtime_checks.get("persistent_volumes_retained") is not False
        or runtime_checks.get("all_port_forwards_stopped") is not True
        or runtime_checks.get("material_recorded") is not False
        or runtime_checks.get("kubernetes_service_account_used_for_provider_login")
        is not False
    ):
        errors.append("Spark interoperability cleanup is incomplete")

    result = _mapping(spark.get("result"))
    spark_runtime_verified = not any(
        error
        in {
            "Spark interoperability Job did not complete exactly once",
            "Spark interoperability runtime boundary does not match",
            "Spark interoperability result envelope does not match",
        }
        for error in spark_errors
    )
    create_read_write_verified = (
        spark_runtime_verified
        and not any("create/read/write" in error for error in spark_errors)
        and result.get("create_read_write_verified") is True
    )
    schema_evolution_verified = (
        spark_runtime_verified
        and not any("schema evolution" in error for error in spark_errors)
        and result.get("schema_evolution_verified") is True
    )
    snapshot_time_travel_verified = (
        spark_runtime_verified
        and not any("snapshot/time-travel" in error for error in spark_errors)
        and result.get("snapshot_history_verified") is True
        and result.get("time_travel_verified") is True
    )
    verified = not errors
    stable = {
        "schema": EVIDENCE_SCHEMA,
        "observed_at": observation.get("observed_at"),
        "local_static_contract_verified": (
            contract.get("local_static_contract_verified") is True
        ),
        "local_spark_iceberg_rest_interoperability_verified": verified,
        "local_spark_create_read_write_verified": create_read_write_verified,
        "local_spark_schema_evolution_verified": schema_evolution_verified,
        "local_spark_snapshot_time_travel_verified": (
            snapshot_time_travel_verified
        ),
        "gravitino_api_metadata_readback_verified": api_readback_verified,
        "local_same_node_shared_pvc_verified": same_node_shared_pvc_verified,
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
    observation = _mapping(evidence.get("observation"))
    rebuilt = build_evidence(observation)
    if evidence.get("evidence_fingerprint") != rebuilt.get("evidence_fingerprint"):
        errors.append("Spark interoperability evidence fingerprint does not match")
    for key, expected in rebuilt.items():
        if key == "evidence_fingerprint":
            continue
        if evidence.get(key) != expected:
            errors.append(f"Spark interoperability evidence field drift: {key}")
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
            errors.append(f"Spark interoperability evidence may not claim {claim}")
    return errors


def run_live_rehearsal(
    profile_path: Path = DEFAULT_PROFILE_PATH,
) -> dict[str, Any]:
    profile = load_profile(profile_path)
    contract = build_contract_report(profile_path)
    if contract.get("local_static_contract_verified") is not True:
        raise MetadataFabricSparkIcebergRestInteroperabilityError(
            "Spark interoperability static contract is invalid"
        )

    admin_material = SecretStr(secrets.token_urlsafe(24))
    database_material = SecretStr(secrets.token_urlsafe(24))
    user_material = SecretStr(secrets.token_urlsafe(24))
    runtime = IsolatedSparkInteroperabilityRuntime(profile)
    forward: provider_metrics._PortForward | None = None
    rehearsal: jdbc_restart.PersistentCatalogRehearsal | None = None
    runtime_observation: dict[str, Any] | None = None
    pre_spark: dict[str, Any] | None = None
    spark: dict[str, Any] | None = None
    post_spark: dict[str, Any] | None = None
    forward_stopped = False
    cleanup: dict[str, Any] = {
        "namespace_delete_completed": False,
        "namespace_absent": False,
        "provider_objects_retained": True,
        "persistent_volumes_retained": True,
    }
    try:
        runtime_observation = runtime.start(
            admin_material=admin_material,
            database_material=database_material,
        )
        forward = provider_metrics._PortForward(
            kubectl="kubectl",
            context=profile.cluster.context,
            namespace=profile.cluster.rehearsal_namespace,
            service=profile.runtime.service,
            target_port=profile.runtime.gravitino_service_port,
        )
        forward.start()
        rehearsal = jdbc_restart.PersistentCatalogRehearsal(
            base_url=f"http://127.0.0.1:{forward.local_port}/api",
            admin_name=profile.identity.service_admin,
            admin_material=admin_material,
        )
        pre_spark = rehearsal.bootstrap(
            profile,
            database_material=database_material,
            user_material=user_material,
        )
        spark = runtime.run_spark_probe()
        post_spark = _post_spark_readback(rehearsal, profile, user_material)
    finally:
        if rehearsal is not None:
            rehearsal.close()
        if forward is not None:
            forward_stopped = forward.stop()
        cleanup = runtime.cleanup()

    if (
        runtime_observation is None
        or pre_spark is None
        or spark is None
        or post_spark is None
    ):
        raise MetadataFabricSparkIcebergRestInteroperabilityError(
            "Spark interoperability rehearsal did not produce an outcome"
        )
    observation = {
        "schema": OBSERVATION_SCHEMA,
        "observed_at": datetime.now(UTC).isoformat(),
        "contract": {
            "contract_fingerprint": contract["contract_fingerprint"],
            "local_static_contract_verified": True,
            "jdbc_restart_evidence_fingerprint": (
                JDBC_RESTART_EVIDENCE_FINGERPRINT
            ),
        },
        "runtime": runtime_observation,
        "pre_spark": pre_spark,
        "spark": spark,
        "post_spark": post_spark,
        "runtime_checks": {
            **cleanup,
            "all_port_forwards_stopped": forward_stopped,
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
            raise TypeError("Spark interoperability evidence must be an object")
        evidence = value
        errors.extend(verify_evidence_integrity(evidence))
        observed_contract = _mapping(
            _mapping(evidence.get("observation")).get("contract")
        ).get("contract_fingerprint")
        if observed_contract != contract.get("contract_fingerprint"):
            errors.append("Spark interoperability evidence contract fingerprint drift")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"Spark interoperability evidence is invalid: {type(exc).__name__}")
    verified = not errors
    return {
        "schema": VALIDATION_SCHEMA,
        "local_static_contract_verified": contract["local_static_contract_verified"],
        "local_spark_iceberg_rest_interoperability_verified": (
            verified
            and evidence is not None
            and evidence.get("local_spark_iceberg_rest_interoperability_verified")
            is True
        ),
        "local_spark_create_read_write_verified": (
            verified
            and evidence is not None
            and evidence.get("local_spark_create_read_write_verified") is True
        ),
        "local_spark_schema_evolution_verified": (
            verified
            and evidence is not None
            and evidence.get("local_spark_schema_evolution_verified") is True
        ),
        "local_spark_snapshot_time_travel_verified": (
            verified
            and evidence is not None
            and evidence.get("local_spark_snapshot_time_travel_verified") is True
        ),
        "gravitino_api_metadata_readback_verified": (
            verified
            and evidence is not None
            and evidence.get("gravitino_api_metadata_readback_verified") is True
        ),
        "local_same_node_shared_pvc_verified": (
            verified
            and evidence is not None
            and evidence.get("local_same_node_shared_pvc_verified") is True
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
                raise TypeError("Spark interoperability evidence must be an object")
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
        jdbc_restart.MetadataFabricGravitinoJdbcRestartError,
        MetadataFabricSparkIcebergRestInteroperabilityError,
        KeyboardInterrupt,
    ) as exc:
        print(f"metadata fabric Spark/Iceberg REST interoperability: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
