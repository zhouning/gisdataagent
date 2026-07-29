"""Verify Spark and Gravitino interoperability through an S3 object store.

The rehearsal keeps PostgreSQL, Gravitino and Spark on the Docker Desktop worker
while MinIO runs on the control-plane node. Both Gravitino catalog paths and
Spark use the same JDBC catalog and S3 warehouse without mounting a shared
warehouse PVC. The result is bounded local cross-node interoperability evidence,
not production object-store, identity, TLS or full engine conformance evidence.
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

import boto3
import yaml
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints

from . import metadata_fabric_gravitino_identity as identity
from . import metadata_fabric_gravitino_jdbc_restart as jdbc_restart
from . import metadata_fabric_ingestion_replay as ingestion_replay
from . import metadata_fabric_provider_metrics as provider_metrics
from . import metadata_fabric_recovery_rehearsal as recovery
from . import metadata_fabric_spark_iceberg_rest_interoperability as spark_interop


PROFILE_SCHEMA = "gda.metadata_fabric_spark_object_store_interoperability_profile.v1"
CONTRACT_SCHEMA = "gda.metadata_fabric_spark_object_store_interoperability_contract.v1"
OBSERVATION_SCHEMA = "gda.metadata_fabric_spark_object_store_interoperability_observation.v1"
EVIDENCE_SCHEMA = "gda.metadata_fabric_spark_object_store_interoperability_evidence.v1"
VALIDATION_SCHEMA = "gda.metadata_fabric_spark_object_store_interoperability_validation.v1"

CONTEXT = "docker-desktop"
SOURCE_NAMESPACE = "gda-metadata-sandbox"
REHEARSAL_NAMESPACE = "gda-metadata-spark-object-store"
OBJECT_STORE_NODE = "desktop-control-plane"
COMPUTE_NODE = "desktop-worker"
GRAVITINO_SCHEMA_SHA256 = identity.GRAVITINO_SCHEMA_SHA256
GRAVITINO_HOST_IMAGE_ID = spark_interop.GRAVITINO_HOST_IMAGE_ID
GRAVITINO_KUBERNETES_IMAGE_ID = spark_interop.GRAVITINO_KUBERNETES_IMAGE_ID
POSTGRESQL_IMAGE_DIGEST = spark_interop.POSTGRESQL_IMAGE_DIGEST
SPARK_HOST_IMAGE_ID = spark_interop.SPARK_HOST_IMAGE_ID
SPARK_KUBERNETES_IMAGE_ID = spark_interop.SPARK_KUBERNETES_IMAGE_ID
MINIO_HOST_IMAGE_ID = (
    "sha256:a1ea29fa28355559ef137d71fc570e508a214ec84ff8083e39bc5428980b015e"
)
MINIO_KUBERNETES_IMAGE_ID = MINIO_HOST_IMAGE_ID
SPARK_INTEROPERABILITY_EVIDENCE_FINGERPRINT = (
    "50f9d0021db11e22364697d1ad8928ee068d28dc8046556bbca1a4e1c819f8e0"
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = (
    REPO_ROOT / "config/metadata-fabric-spark-object-store-interoperability.local.yaml"
)
DEFAULT_EVIDENCE_PATH = (
    REPO_ROOT
    / "docs/evidence/metadata-fabric-spark-object-store-interoperability-2026-07-29.json"
)
DEFAULT_WRAPPER_PATH = (
    REPO_ROOT / "scripts/metadata-fabric-spark-object-store-interoperability.sh"
)
MANIFEST_DIR = REPO_ROOT / "k8s/metadata-fabric-spark-object-store-interoperability"

NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1024),
]


class MetadataFabricSparkObjectStoreInteroperabilityError(RuntimeError):
    """The local Spark/object-store interoperability contract failed closed."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ClusterProfile(_FrozenModel):
    context: Literal["docker-desktop"]
    source_namespace: Literal["gda-metadata-sandbox"]
    rehearsal_namespace: Literal["gda-metadata-spark-object-store"]
    source_schema_configmap: Literal["metadata-gravitino-schema-1-3-0"]
    storage_class: Literal["standard"]
    object_store_node: Literal["desktop-control-plane"]
    compute_node: Literal["desktop-worker"]


class RuntimeProfile(_FrozenModel):
    manifest: Literal["k8s/metadata-fabric-spark-object-store-interoperability"]
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
    minio_version: Literal["RELEASE.2025-04-22T22-12-26Z"]
    minio_image: Literal["minio/minio:RELEASE.2025-04-22T22-12-26Z"]
    minio_host_image_id: Literal[MINIO_HOST_IMAGE_ID]
    minio_kubernetes_image_id: Literal[MINIO_KUBERNETES_IMAGE_ID]
    service: Literal["gravitino-persistence"]
    gravitino_service_port: Literal[8090]
    iceberg_rest_service_port: Literal[9001]
    iceberg_rest_path: Literal["/iceberg"]
    object_store_service: Literal["metadata-object-store"]
    object_store_service_port: Literal[9000]
    spark_job: Literal["spark-object-store-probe"]
    authenticator: Literal["basic"]
    access_control_enabled: Literal[True]
    transport: Literal["local_cluster_http"]


class DependencyProfile(_FrozenModel):
    evidence_path: Literal[
        "docs/evidence/metadata-fabric-spark-iceberg-rest-interoperability-2026-07-29.json"
    ]
    evidence_fingerprint: Literal[SPARK_INTEROPERABILITY_EVIDENCE_FINGERPRINT]
    required_claim: Literal["local_spark_iceberg_rest_interoperability_verified"]


class IdentityProfile(_FrozenModel):
    service_admin: Literal["gda-object-store-admin"]
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
    warehouse: Literal["s3://gda-metadata-warehouse/warehouse"]
    io_impl: Literal["org.apache.iceberg.aws.s3.S3FileIO"]
    s3_endpoint: Literal["http://metadata-object-store:9000"]
    s3_region: Literal["us-east-1"]
    s3_path_style_access: Literal[True]
    bucket: Literal["gda-metadata-warehouse"]
    object_prefix: Literal[
        "warehouse/published/gda_spark_object_store_probe/"
    ]
    authentication_mode: Literal["runtime_generated_static_local_material"]
    postgresql_pvc: Literal["data-gravitino-persistence-postgresql-0"]
    object_store_pvc: Literal["data-metadata-object-store-0"]
    interoperability_scope: Literal[
        "local_cross_node_s3_compatible_object_store"
    ]


class PrivilegeProfile(_FrozenModel):
    name: Literal["USE_CATALOG", "USE_SCHEMA", "CREATE_TABLE"]
    condition: Literal["ALLOW"]


class SecurableObjectProfile(_FrozenModel):
    full_name: Literal["lakehouse", "lakehouse.published"]
    type: Literal["CATALOG", "SCHEMA"]
    privileges: tuple[PrivilegeProfile, ...]


class ScopeProfile(_FrozenModel):
    metalake: Literal["gda_object_store"]
    catalog: Literal["lakehouse"]
    schema_name: Literal["published"] = Field(alias="schema")
    table: Literal["gda_spark_object_store_probe"]
    denied_catalog: Literal["unauthorized_catalog"]
    role_securable_objects: tuple[SecurableObjectProfile, ...]


class ClaimProfile(_FrozenModel):
    local_spark_object_store_interoperability_verified: Literal[False]
    local_spark_create_read_write_verified: Literal[False]
    local_spark_schema_evolution_verified: Literal[False]
    local_spark_snapshot_time_travel_verified: Literal[False]
    gravitino_api_metadata_readback_verified: Literal[False]
    local_cross_node_object_store_verified: Literal[False]
    object_store_metadata_verified: Literal[False]
    persistent_catalog_identity_binding_verified: Literal[False]
    protected_workload_identity_verified: Literal[False]
    oidc_verified: Literal[False]
    tls_verified: Literal[False]
    production_object_store_verified: Literal[False]
    spark_conformance_verified: Literal[False]
    flink_conformance_verified: Literal[False]
    production_ingestion_verified: Literal[False]
    production_ready: Literal[False]


class SparkObjectStoreInteroperabilityProfile(_FrozenModel):
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
    profile: SparkObjectStoreInteroperabilityProfile,
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
    profile: SparkObjectStoreInteroperabilityProfile,
) -> dict[str, Any]:
    path = REPO_ROOT / profile.dependency.evidence_path
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError("Spark interoperability dependency must be an object")
        errors = spark_interop.verify_evidence_integrity(value)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MetadataFabricSparkObjectStoreInteroperabilityError(
            "Spark object-store dependency is invalid"
        ) from exc
    if (
        errors
        or value.get("evidence_fingerprint")
        != profile.dependency.evidence_fingerprint
        or value.get(profile.dependency.required_claim) is not True
        or value.get("production_ready") is not False
    ):
        raise MetadataFabricSparkObjectStoreInteroperabilityError(
            "Spark object-store dependency does not match"
        )
    return value


def load_profile(
    path: Path = DEFAULT_PROFILE_PATH,
) -> SparkObjectStoreInteroperabilityProfile:
    try:
        value = yaml.safe_load(path.resolve().read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError("Spark object-store profile must be an object")
        ingestion_replay._reject_sensitive_fields(value)
        profile = SparkObjectStoreInteroperabilityProfile.model_validate(value)
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise MetadataFabricSparkObjectStoreInteroperabilityError(
            "Spark object-store interoperability profile is invalid"
        ) from exc
    if _profile_securable_objects(profile) != identity._expected_securable_objects():
        raise MetadataFabricSparkObjectStoreInteroperabilityError(
            "Spark object-store role exceeds the bounded table-create scope"
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
        return [f"Spark object-store manifest is invalid: {type(exc).__name__}"]
    if any(document.get("kind") == "Secret" for document in documents):
        errors.append("Spark object-store manifest may not commit Secret values")
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
        errors.append("Spark object-store manifest is incomplete")
    rendered = json.dumps(documents, ensure_ascii=True, sort_keys=True)
    markers = (
        "gravitino.authenticators = basic",
        "gravitino.authorization.enable = true",
        "gravitino.iceberg-rest.catalog-backend = jdbc",
        "gravitino.iceberg-rest.warehouse = s3://gda-metadata-warehouse/warehouse",
        "gravitino.iceberg-rest.io-impl = org.apache.iceberg.aws.s3.S3FileIO",
        "gravitino.iceberg-rest.s3-endpoint = http://metadata-object-store:9000",
        "gravitino.iceberg-rest.s3-path-style-access = true",
        "stage-object-store-runtime-libs",
        "minio/minio:RELEASE.2025-04-22T22-12-26Z",
        "spark.sql.catalog.rest.s3.endpoint",
        "spark.sql.catalog.rest.s3.path-style-access",
        "object_store_data_files_verified",
        "GDA_SPARK_OBJECT_STORE_RESULT",
        "VERSION AS OF",
        "desktop-control-plane",
        "desktop-worker",
        "automountServiceAccountToken",
    )
    for marker in markers:
        if marker not in rendered:
            errors.append(f"Spark object-store manifest is missing marker: {marker}")
    for forbidden in (
        "gravitino.authenticators = simple",
        "file:///var/lib/gravitino/warehouse",
        "warehouse-gravitino-persistence-0",
        '"mountPath": "/var/lib/gravitino/warehouse"',
    ):
        if forbidden in rendered:
            errors.append(f"Spark object-store manifest contains forbidden marker: {forbidden}")

    job = next(
        (
            document
            for document in documents
            if document.get("kind") == "Job"
            and _mapping(document.get("metadata")).get("name")
            == "spark-object-store-probe"
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
    volumes = pod_spec.get("volumes")
    volume_items = volumes if isinstance(volumes, list) else []
    if job_spec.get("suspend") is not True:
        errors.append("Spark object-store Job must start suspended")
    if pod_spec.get("automountServiceAccountToken") is not False:
        errors.append("Spark object-store Job must disable token automount")
    if any(_mapping(item).get("persistentVolumeClaim") for item in volume_items):
        errors.append("Spark object-store Job may not mount a warehouse PVC")
    if not {"cpu", "memory"}.issubset(_mapping(resources.get("requests"))) or not {
        "cpu",
        "memory",
    }.issubset(_mapping(resources.get("limits"))):
        errors.append("Spark object-store Job resources are incomplete")
    if (
        security.get("allowPrivilegeEscalation") is not False
        or security.get("readOnlyRootFilesystem") is not True
    ):
        errors.append("Spark object-store Job security context is incomplete")
    return errors


def build_contract_report(
    profile_path: Path = DEFAULT_PROFILE_PATH,
    wrapper_path: Path = DEFAULT_WRAPPER_PATH,
) -> dict[str, Any]:
    errors: list[str] = []
    profile: SparkObjectStoreInteroperabilityProfile | None = None
    try:
        profile = load_profile(profile_path)
    except MetadataFabricSparkObjectStoreInteroperabilityError as exc:
        errors.append(str(exc))
    errors.extend(_validate_manifest())
    try:
        wrapper = wrapper_path.resolve().read_text(encoding="utf-8")
        for marker in (
            "set -euo pipefail",
            "metadata_fabric_spark_object_store_interoperability",
        ):
            if marker not in wrapper:
                errors.append(f"Spark object-store wrapper is missing: {marker}")
    except OSError as exc:
        errors.append(f"Spark object-store wrapper is invalid: {type(exc).__name__}")

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
        "object_store_node": OBJECT_STORE_NODE,
        "compute_node": COMPUTE_NODE,
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
            "minio_host_image_id": (
                profile.runtime.minio_host_image_id if profile else None
            ),
            "minio_kubernetes_image_id": (
                profile.runtime.minio_kubernetes_image_id if profile else None
            ),
        },
        "versions": {
            "gravitino": profile.runtime.gravitino_version if profile else None,
            "iceberg_rest": profile.runtime.iceberg_rest_version if profile else None,
            "spark": profile.runtime.spark_version if profile else None,
            "iceberg_spark_runtime": (
                profile.runtime.iceberg_spark_runtime_version if profile else None
            ),
            "minio": profile.runtime.minio_version if profile else None,
        },
        "spark_interoperability_evidence_fingerprint": (
            SPARK_INTEROPERABILITY_EVIDENCE_FINGERPRINT
        ),
        "catalog": {
            "provider": profile.catalog.provider if profile else None,
            "backend": profile.catalog.backend if profile else None,
            "uri": profile.catalog.uri if profile else None,
            "warehouse": profile.catalog.warehouse if profile else None,
            "io_impl": profile.catalog.io_impl if profile else None,
            "s3_endpoint": profile.catalog.s3_endpoint if profile else None,
            "s3_region": profile.catalog.s3_region if profile else None,
            "s3_path_style_access": (
                profile.catalog.s3_path_style_access if profile else None
            ),
            "bucket": profile.catalog.bucket if profile else None,
            "interoperability_scope": (
                profile.catalog.interoperability_scope if profile else None
            ),
        },
        "role_securable_objects": (
            _profile_securable_objects(profile) if profile else None
        ),
        "local_static_contract_verified": not errors,
        "local_spark_object_store_interoperability_verified": False,
        "local_cross_node_object_store_verified": False,
        "object_store_metadata_verified": False,
        "production_object_store_verified": False,
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
        raise MetadataFabricSparkObjectStoreInteroperabilityError(
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


class IsolatedSparkObjectStoreRuntime:
    """Own the temporary two-node object-store interoperability namespace."""

    def __init__(self, profile: SparkObjectStoreInteroperabilityProfile) -> None:
        self.profile = profile
        self.kubectl = identity._Kubectl(profile.cluster.context)
        self.owned_namespace = False
        self.schema_sha256: str | None = None
        self.gravitino_host_image_id: str | None = None
        self.spark_host_image_id: str | None = None
        self.minio_host_image_id: str | None = None
        self.persistent_volumes: set[str] = set()

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
            raise MetadataFabricSparkObjectStoreInteroperabilityError(
                f"{label} host image identity is unavailable"
            ) from exc
        image_id = completed.stdout.strip()
        if completed.returncode != 0 or image_id != expected_id:
            raise MetadataFabricSparkObjectStoreInteroperabilityError(
                f"{label} host image identity does not match: "
                f"expected {expected_id}, observed {image_id or 'unavailable'}"
            )
        return image_id

    def _runtime_inputs(
        self,
        *,
        admin_material: SecretStr,
        database_material: SecretStr,
        object_store_user: SecretStr,
        object_store_material: SecretStr,
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
            raise MetadataFabricSparkObjectStoreInteroperabilityError(
                "verified Gravitino PostgreSQL schema is unavailable"
            )
        self.schema_sha256 = identity._sha256_text(schema_sql)
        if self.schema_sha256 != GRAVITINO_SCHEMA_SHA256:
            raise MetadataFabricSparkObjectStoreInteroperabilityError(
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
                    "kind": "Secret",
                    "metadata": {
                        "name": "metadata-object-store-runtime",
                        "namespace": self.profile.cluster.rehearsal_namespace,
                    },
                    "type": "Opaque",
                    "stringData": {
                        "access-key-id": object_store_user.get_secret_value(),
                        "secret-access-key": object_store_material.get_secret_value(),
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
        self,
        *,
        admin_material: SecretStr,
        database_material: SecretStr,
        object_store_user: SecretStr,
        object_store_material: SecretStr,
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
        self.minio_host_image_id = self._inspect_host_image(
            self.profile.runtime.minio_image,
            self.profile.runtime.minio_host_image_id,
            "MinIO",
        )
        existing = self.kubectl.get_json(
            ["get", "namespace", self.profile.cluster.rehearsal_namespace],
            allow_not_found=True,
            label="Spark object-store namespace preflight",
        )
        if existing is not None:
            raise MetadataFabricSparkObjectStoreInteroperabilityError(
                "Spark object-store interoperability namespace already exists"
            )
        self.kubectl.run(
            ["apply", "-f", str(MANIFEST_DIR / "namespace.yaml")],
            label="Spark object-store namespace apply",
        )
        self.owned_namespace = True
        self.kubectl.run(
            ["apply", "-f", "-"],
            input_text=self._runtime_inputs(
                admin_material=admin_material,
                database_material=database_material,
                object_store_user=object_store_user,
                object_store_material=object_store_material,
            ),
            label="ephemeral Spark object-store inputs apply",
        )
        self.kubectl.run(
            ["apply", "-k", str(MANIFEST_DIR)],
            label="Spark object-store runtime apply",
        )
        for workload in (
            "statefulset/metadata-object-store",
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
        pvc_name: str | None,
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
        assert statefulset is not None and pod_list is not None
        pod = _single_list_item(pod_list, statefulset_name)
        pod_spec = _mapping(pod.get("spec"))
        status = _container_status(pod, container_name)
        claim_names: list[str] = []
        volumes = pod_spec.get("volumes")
        if isinstance(volumes, list):
            for volume in volumes:
                claim = _mapping(_mapping(volume).get("persistentVolumeClaim")).get(
                    "claimName"
                )
                if isinstance(claim, str):
                    claim_names.append(claim)
        pvc_projection: dict[str, Any] | None = None
        if pvc_name is not None:
            pvc = self.kubectl.get_json(
                ["-n", namespace, "get", "pvc", pvc_name],
                label=f"{pvc_name} observation",
            )
            assert pvc is not None
            pvc_spec = _mapping(pvc.get("spec"))
            volume_name = pvc_spec.get("volumeName")
            if isinstance(volume_name, str) and volume_name:
                self.persistent_volumes.add(volume_name)
            pvc_projection = {
                "name": _mapping(pvc.get("metadata")).get("name"),
                "uid": _mapping(pvc.get("metadata")).get("uid"),
                "storage_class": pvc_spec.get("storageClassName"),
                "volume_name": volume_name,
                "phase": _mapping(pvc.get("status")).get("phase"),
            }
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
            "persistent_volume_claims": sorted(claim_names),
            "pvc": pvc_projection,
        }

    @staticmethod
    def _service_projection(service: Mapping[str, Any]) -> dict[str, Any]:
        ports = _mapping(service.get("spec")).get("ports")
        service_ports = (
            sorted(
                [
                    {
                        "name": _mapping(item).get("name"),
                        "port": _mapping(item).get("port"),
                    }
                    for item in ports
                ],
                key=lambda item: str(item["name"]),
            )
            if isinstance(ports, list)
            else []
        )
        return {
            "name": _mapping(service.get("metadata")).get("name"),
            "uid": _mapping(service.get("metadata")).get("uid"),
            "type": _mapping(service.get("spec")).get("type"),
            "ports": service_ports,
        }

    def observe_runtime(self) -> dict[str, Any]:
        namespace_name = self.profile.cluster.rehearsal_namespace
        namespace = self.kubectl.get_json(
            ["get", "namespace", namespace_name], label="namespace observation"
        )
        service = self.kubectl.get_json(
            ["-n", namespace_name, "get", "service", self.profile.runtime.service],
            label="Gravitino object-store service observation",
        )
        object_store_service = self.kubectl.get_json(
            [
                "-n",
                namespace_name,
                "get",
                "service",
                self.profile.runtime.object_store_service,
            ],
            label="object-store service observation",
        )
        pod = self.kubectl.get_json(
            ["-n", namespace_name, "get", "pod", "gravitino-persistence-0"],
            label="Gravitino object-store pod observation",
        )
        assert (
            namespace is not None
            and service is not None
            and object_store_service is not None
            and pod is not None
        )
        probes: dict[str, bool] = {}
        for name, container, path in (
            (
                "gravitino_jdbc_driver_mounted",
                "gravitino",
                self.profile.catalog.gravitino_jdbc_driver_mount,
            ),
            (
                "rest_jdbc_driver_mounted",
                "iceberg-rest",
                self.profile.catalog.rest_jdbc_driver_mount,
            ),
            (
                "gravitino_aws_sdk_mounted",
                "gravitino",
                "/opt/gravitino/catalogs/lakehouse-iceberg/libs/s3-2.31.73.jar",
            ),
            (
                "rest_aws_sdk_mounted",
                "iceberg-rest",
                "/opt/gravitino/iceberg-rest-server/libs/s3-2.31.73.jar",
            ),
        ):
            result = self.kubectl.run(
                [
                    "-n",
                    namespace_name,
                    "exec",
                    "gravitino-persistence-0",
                    "-c",
                    container,
                    "--",
                    "test",
                    "-r",
                    path,
                ],
                expected=frozenset({0, 1}),
                timeout=60,
                label=f"{name} probe",
            )
            probes[name] = result.returncode == 0
        rest_status = _container_status(pod, "iceberg-rest")
        return {
            "context": self.profile.cluster.context,
            "gravitino_host_image_id": self.gravitino_host_image_id,
            "spark_host_image_id": self.spark_host_image_id,
            "minio_host_image_id": self.minio_host_image_id,
            "namespace": {
                "name": _mapping(namespace.get("metadata")).get("name"),
                "uid": _mapping(namespace.get("metadata")).get("uid"),
            },
            "service": self._service_projection(service),
            "object_store_service": self._service_projection(object_store_service),
            "postgresql": self._workload(
                statefulset_name="gravitino-persistence-postgresql",
                label_name="gravitino-persistence-postgresql",
                container_name="postgresql",
                pvc_name=self.profile.catalog.postgresql_pvc,
            ),
            "object_store": self._workload(
                statefulset_name="metadata-object-store",
                label_name="metadata-object-store",
                container_name="minio",
                pvc_name=self.profile.catalog.object_store_pvc,
            ),
            "gravitino": self._workload(
                statefulset_name="gravitino-persistence",
                label_name="gravitino-persistence",
                container_name="gravitino",
                pvc_name=None,
            ),
            "iceberg_rest": {
                "image": rest_status.get("image"),
                "image_id": rest_status.get("imageID"),
                "ready": rest_status.get("ready"),
                "jdbc_driver_mounted": probes["rest_jdbc_driver_mounted"],
                "aws_sdk_mounted": probes["rest_aws_sdk_mounted"],
                "path": self.profile.runtime.iceberg_rest_path,
            },
            "gravitino_jdbc_driver_mounted": probes[
                "gravitino_jdbc_driver_mounted"
            ],
            "gravitino_aws_sdk_mounted": probes["gravitino_aws_sdk_mounted"],
            "source_schema_sha256": self.schema_sha256,
        }

    def _s3_client(
        self,
        *,
        endpoint_url: str,
        object_store_user: SecretStr,
        object_store_material: SecretStr,
    ) -> Any:
        return boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=self.profile.catalog.s3_region,
            aws_access_key_id=object_store_user.get_secret_value(),
            aws_secret_access_key=object_store_material.get_secret_value(),
            config=Config(
                connect_timeout=5,
                read_timeout=10,
                retries={"max_attempts": 3, "mode": "standard"},
                signature_version="s3v4",
                s3={"addressing_style": "path"},
            ),
        )

    def prepare_object_store(
        self,
        *,
        endpoint_url: str,
        object_store_user: SecretStr,
        object_store_material: SecretStr,
    ) -> dict[str, Any]:
        client = self._s3_client(
            endpoint_url=endpoint_url,
            object_store_user=object_store_user,
            object_store_material=object_store_material,
        )
        created = False
        try:
            try:
                client.head_bucket(Bucket=self.profile.catalog.bucket)
            except ClientError as exc:
                code = str(_mapping(exc.response.get("Error")).get("Code") or "")
                if code not in {"404", "NoSuchBucket", "NotFound"}:
                    raise
                client.create_bucket(Bucket=self.profile.catalog.bucket)
                created = True
            response = client.head_bucket(Bucket=self.profile.catalog.bucket)
            status = _mapping(response.get("ResponseMetadata")).get("HTTPStatusCode")
            return {
                "service": self.profile.runtime.object_store_service,
                "bucket": self.profile.catalog.bucket,
                "created": created,
                "head_bucket_verified": status == 200,
                "path_style_access": self.profile.catalog.s3_path_style_access,
                "region": self.profile.catalog.s3_region,
                "material_recorded": False,
            }
        finally:
            client.close()

    def observe_object_store(
        self,
        *,
        endpoint_url: str,
        object_store_user: SecretStr,
        object_store_material: SecretStr,
    ) -> dict[str, Any]:
        client = self._s3_client(
            endpoint_url=endpoint_url,
            object_store_user=object_store_user,
            object_store_material=object_store_material,
        )
        try:
            objects: list[dict[str, Any]] = []
            continuation: str | None = None
            while True:
                request: dict[str, Any] = {
                    "Bucket": self.profile.catalog.bucket,
                    "Prefix": self.profile.catalog.object_prefix,
                }
                if continuation is not None:
                    request["ContinuationToken"] = continuation
                response = client.list_objects_v2(**request)
                for item in response.get("Contents") or []:
                    objects.append(
                        {
                            "key": item.get("Key"),
                            "size": item.get("Size"),
                            "etag": str(item.get("ETag") or "").strip('"'),
                        }
                    )
                if response.get("IsTruncated") is not True:
                    break
                continuation = response.get("NextContinuationToken")
                if not isinstance(continuation, str) or not continuation:
                    raise MetadataFabricSparkObjectStoreInteroperabilityError(
                        "object-store listing continuation is invalid"
                    )
            objects.sort(key=lambda item: str(item.get("key")))
            data_keys = sorted(
                str(item["key"])
                for item in objects
                if str(item.get("key") or "").endswith(".parquet")
            )
            metadata_keys = sorted(
                str(item["key"])
                for item in objects
                if str(item.get("key") or "").endswith(".metadata.json")
            )
            manifest_keys = sorted(
                str(item["key"])
                for item in objects
                if str(item.get("key") or "").endswith(".avro")
            )
            if not metadata_keys:
                raise MetadataFabricSparkObjectStoreInteroperabilityError(
                    "object-store Iceberg metadata is absent"
                )
            latest_key = metadata_keys[-1]
            metadata_response = client.get_object(
                Bucket=self.profile.catalog.bucket,
                Key=latest_key,
            )
            metadata = json.loads(metadata_response["Body"].read())
            if not isinstance(metadata, dict):
                raise TypeError("Iceberg metadata object must be an object")
            current_schema_id = metadata.get("current-schema-id")
            schemas = metadata.get("schemas")
            schema_items = schemas if isinstance(schemas, list) else []
            current_schema = next(
                (
                    _mapping(item)
                    for item in schema_items
                    if _mapping(item).get("schema-id") == current_schema_id
                ),
                {},
            )
            fields = current_schema.get("fields")
            field_items = fields if isinstance(fields, list) else []
            latest_projection = {
                "key": latest_key,
                "location": metadata.get("location"),
                "current_snapshot_id": metadata.get("current-snapshot-id"),
                "current_schema_id": current_schema_id,
                "fields": [
                    {
                        "name": _mapping(item).get("name"),
                        "required": _mapping(item).get("required"),
                        "type": _mapping(item).get("type"),
                    }
                    for item in field_items
                ],
            }
            return {
                "bucket": self.profile.catalog.bucket,
                "prefix": self.profile.catalog.object_prefix,
                "object_count": len(objects),
                "objects": objects,
                "data_keys": data_keys,
                "metadata_keys": metadata_keys,
                "manifest_keys": manifest_keys,
                "latest_metadata": latest_projection,
                "material_recorded": False,
            }
        finally:
            client.close()

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
            label="Spark object-store Job release",
        )
        deadline = time.monotonic() + 900
        terminal_condition: str | None = None
        while time.monotonic() < deadline:
            current_job = self.kubectl.get_json(
                ["-n", namespace, "get", "job", job_name],
                label="Spark object-store Job wait",
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
            label="Spark object-store Job observation",
        )
        pod_list = self.kubectl.get_json(
            [
                "-n",
                namespace,
                "get",
                "pods",
                "-l",
                "job-name=spark-object-store-probe",
            ],
            label="Spark object-store pod observation",
        )
        assert job is not None and pod_list is not None
        pod = _single_list_item(pod_list, "Spark object-store Job")
        pod_name = _mapping(pod.get("metadata")).get("name")
        logs = self.kubectl.run(
            ["-n", namespace, "logs", str(pod_name), "-c", "spark"],
            expected=frozenset({0, 1}),
            timeout=120,
            label="Spark object-store result collection",
        )
        result_lines = [
            line.removeprefix("GDA_SPARK_OBJECT_STORE_RESULT=")
            for line in logs.stdout.splitlines()
            if line.startswith("GDA_SPARK_OBJECT_STORE_RESULT=")
        ]
        result: dict[str, Any] | None = None
        if len(result_lines) == 1:
            try:
                candidate = json.loads(result_lines[0])
                if isinstance(candidate, dict):
                    result = candidate
            except json.JSONDecodeError:
                result = None
        failure_diagnostic: list[str] = []
        if result is None:
            sensitive_markers = (
                "access-key",
                "access.key",
                "authorization",
                "credential",
                "password",
                "secret",
                "token",
            )
            for line in logs.stdout.splitlines()[-80:]:
                if any(marker in line.lower() for marker in sensitive_markers):
                    failure_diagnostic.append("<redacted sensitive log line>")
                else:
                    failure_diagnostic.append(line[:1000])
        pod_spec = _mapping(pod.get("spec"))
        volumes = pod_spec.get("volumes")
        claims: list[str] = []
        if isinstance(volumes, list):
            for volume in volumes:
                claim = _mapping(_mapping(volume).get("persistentVolumeClaim")).get(
                    "claimName"
                )
                if isinstance(claim, str):
                    claims.append(claim)
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
                "persistent_volume_claims": sorted(claims),
            },
            "result_line_count": len(result_lines),
            "log_sha256": hashlib.sha256(logs.stdout.encode("utf-8")).hexdigest(),
            "log_recorded": False,
            "failure_diagnostic": failure_diagnostic,
            "result": result,
        }

    def cleanup(self) -> dict[str, Any]:
        deleted = False
        if self.owned_namespace:
            pvc_list = self.kubectl.get_json(
                [
                    "-n",
                    self.profile.cluster.rehearsal_namespace,
                    "get",
                    "pvc",
                ],
                allow_not_found=True,
                label="Spark object-store PVC cleanup inventory",
            )
            if pvc_list is not None:
                items = pvc_list.get("items")
                if isinstance(items, list):
                    for item in items:
                        volume_name = _mapping(_mapping(item).get("spec")).get(
                            "volumeName"
                        )
                        if isinstance(volume_name, str) and volume_name:
                            self.persistent_volumes.add(volume_name)
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
                    label="Spark object-store namespace cleanup",
                )
                deleted = True
            finally:
                self.owned_namespace = False
        absent = (
            self.kubectl.get_json(
                ["get", "namespace", self.profile.cluster.rehearsal_namespace],
                allow_not_found=True,
                label="Spark object-store cleanup verification",
            )
            is None
        )
        deadline = time.monotonic() + 60
        retained: list[str] = []
        while True:
            retained = [
                name
                for name in sorted(self.persistent_volumes)
                if self.kubectl.get_json(
                    ["get", "persistentvolume", name],
                    allow_not_found=True,
                    label=f"persistent volume cleanup verification: {name}",
                )
                is not None
            ]
            if not retained or time.monotonic() >= deadline:
                break
            time.sleep(1)
        return {
            "namespace_delete_completed": deleted,
            "namespace_absent": absent,
            "persistent_volume_names": sorted(self.persistent_volumes),
            "persistent_volumes_absent": not retained,
            "provider_objects_retained": False,
            "object_store_objects_retained": False,
        }


class ObjectStoreCatalogRehearsal(jdbc_restart.PersistentCatalogRehearsal):
    """Create the Gravitino JDBC catalog with the same S3 properties as REST."""

    def bootstrap(
        self,
        profile: SparkObjectStoreInteroperabilityProfile,
        *,
        database_material: SecretStr,
        user_material: SecretStr,
        object_store_user: SecretStr,
        object_store_material: SecretStr,
    ) -> dict[str, Any]:
        admin_status, _version = self.admin.request(
            "GET", "version", label="pre-Spark admin authentication"
        )
        _status, metalake_payload = self.admin.request(
            "POST",
            "metalakes",
            json_body={
                "name": profile.scope.metalake,
                "comment": "Local Spark object-store interoperability rehearsal",
                "properties": {"gda.environment": "local_object_store_interop"},
            },
            label="object-store metalake create",
        )
        metalake = identity._response_entity(
            metalake_payload, "metalake", "object-store metalake create"
        )
        _status, catalog_payload = self.admin.request(
            "POST",
            f"metalakes/{quote(profile.scope.metalake)}/catalogs",
            json_body={
                "name": profile.scope.catalog,
                "type": "RELATIONAL",
                "provider": profile.catalog.provider,
                "comment": "JDBC Iceberg catalog with S3-compatible warehouse",
                "properties": {
                    "catalog-backend": profile.catalog.backend,
                    "uri": profile.catalog.uri,
                    "warehouse": profile.catalog.warehouse,
                    "jdbc-user": "gravitino",
                    "jdbc-password": database_material.get_secret_value(),
                    "gravitino.bypass.jdbc-driver": profile.catalog.jdbc_driver,
                    "gravitino.bypass.jdbc-initialize": "true",
                    "io-impl": profile.catalog.io_impl,
                    "s3-access-key-id": object_store_user.get_secret_value(),
                    "s3-secret-access-key": (
                        object_store_material.get_secret_value()
                    ),
                    "s3-endpoint": profile.catalog.s3_endpoint,
                    "s3-region": profile.catalog.s3_region,
                    "s3-path-style-access": "true",
                },
            },
            label="object-store JDBC catalog create",
        )
        catalog = identity._response_entity(catalog_payload, "catalog", "catalog create")
        _status, schema_payload = self.admin.request(
            "POST",
            f"{self._catalog_path(profile, profile.scope.catalog)}/schemas",
            json_body={
                "name": profile.scope.schema_name,
                "comment": "Cross-node object-store projection schema",
                "properties": {},
            },
            label="object-store schema create",
        )
        schema = identity._response_entity(schema_payload, "schema", "schema create")

        self.admin.request(
            "POST",
            "idp/users",
            json_body={
                "user": profile.identity.user,
                "password": user_material.get_secret_value(),
            },
            label="object-store IdP user create",
        )
        self.admin.request(
            "POST",
            f"metalakes/{quote(profile.scope.metalake)}/users",
            json_body={"name": profile.identity.user},
            label="object-store metalake user register",
        )
        self.admin.request(
            "POST",
            f"metalakes/{quote(profile.scope.metalake)}/roles",
            json_body={
                "name": profile.identity.role,
                "properties": {"gda.scope": "bounded_table_projection"},
                "securableObjects": identity._expected_securable_objects(),
            },
            label="object-store bounded role create",
        )
        self.admin.request(
            "PUT",
            (
                f"metalakes/{quote(profile.scope.metalake)}/permissions/users/"
                f"{quote(profile.identity.user)}/grant"
            ),
            json_body={"roleNames": [profile.identity.role]},
            label="object-store bounded role grant",
        )
        _status, role_payload = self.admin.request(
            "GET",
            (
                f"metalakes/{quote(profile.scope.metalake)}/roles/"
                f"{quote(profile.identity.role)}"
            ),
            label="object-store role readback",
        )
        role = identity._response_entity(role_payload, "role", "role readback")

        bounded = self._user(profile, user_material)
        bounded_status, _payload = bounded.request(
            "GET", "version", label="pre-Spark bounded authentication"
        )
        create_status, table_payload = bounded.request(
            "POST",
            f"{self._schema_path(profile)}/tables",
            json_body={
                "name": profile.scope.table,
                "comment": "Cross-node object-store interoperability probe",
                "columns": [
                    {
                        "name": "probe_id",
                        "type": "string",
                        "nullable": False,
                        "comment": "Object-store probe identifier",
                    }
                ],
                "properties": {"gda.persistence_probe": "true"},
            },
            label="pre-Spark object-store table create",
        )
        table = identity._response_entity(table_payload, "table", "table create")
        read_status, read_payload = bounded.request(
            "GET", self._table_path(profile), label="pre-Spark object-store table readback"
        )
        read_table = identity._response_entity(read_payload, "table", "table readback")
        denied_status, _payload = bounded.request(
            "POST",
            f"metalakes/{quote(profile.scope.metalake)}/catalogs",
            json_body=self._denied_catalog_body(profile),
            expected=frozenset({200, 403}),
            label="pre-Spark administrative denial",
        )
        projection = jdbc_restart._table_projection(read_table)
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
                "io_impl": profile.catalog.io_impl,
                "s3_endpoint": profile.catalog.s3_endpoint,
                "s3_region": profile.catalog.s3_region,
                "s3_path_style_access": profile.catalog.s3_path_style_access,
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


def _runtime_errors(runtime: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    namespace = _mapping(runtime.get("namespace"))
    service = _mapping(runtime.get("service"))
    object_service = _mapping(runtime.get("object_store_service"))
    postgresql = _mapping(runtime.get("postgresql"))
    object_store = _mapping(runtime.get("object_store"))
    gravitino = _mapping(runtime.get("gravitino"))
    iceberg_rest = _mapping(runtime.get("iceberg_rest"))
    if (
        runtime.get("context") != CONTEXT
        or runtime.get("gravitino_host_image_id") != GRAVITINO_HOST_IMAGE_ID
        or runtime.get("spark_host_image_id") != SPARK_HOST_IMAGE_ID
        or runtime.get("minio_host_image_id") != MINIO_HOST_IMAGE_ID
        or namespace.get("name") != REHEARSAL_NAMESPACE
        or not _valid_uuid(namespace.get("uid"))
        or service.get("name") != "gravitino-persistence"
        or service.get("type") != "ClusterIP"
        or service.get("ports")
        != [
            {"name": "http", "port": 8090},
            {"name": "iceberg-rest", "port": 9001},
        ]
        or object_service.get("name") != "metadata-object-store"
        or object_service.get("type") != "ClusterIP"
        or object_service.get("ports") != [{"name": "api", "port": 9000}]
        or runtime.get("source_schema_sha256") != GRAVITINO_SCHEMA_SHA256
    ):
        errors.append("Spark object-store runtime boundary does not match")

    for name, value, image_id, pvc_name, account, node in (
        (
            "postgresql",
            postgresql,
            POSTGRESQL_IMAGE_DIGEST,
            "data-gravitino-persistence-postgresql-0",
            "gravitino-persistence-postgresql",
            COMPUTE_NODE,
        ),
        (
            "object_store",
            object_store,
            MINIO_KUBERNETES_IMAGE_ID,
            "data-metadata-object-store-0",
            "metadata-object-store",
            OBJECT_STORE_NODE,
        ),
    ):
        pvc = _mapping(value.get("pvc"))
        if (
            not _valid_uuid(value.get("statefulset_uid"))
            or not _valid_uuid(value.get("pod_uid"))
            or value.get("ready_replicas") != 1
            or value.get("node_name") != node
            or not str(value.get("image_id") or "").endswith(image_id)
            or value.get("service_account") != account
            or value.get("service_account_automount_disabled") is not True
            or value.get("persistent_volume_claims") != [pvc_name]
            or pvc.get("name") != pvc_name
            or not _valid_uuid(pvc.get("uid"))
            or pvc.get("storage_class") != "standard"
            or not pvc.get("volume_name")
            or pvc.get("phase") != "Bound"
        ):
            errors.append(f"{name} runtime observation does not match")

    if (
        not _valid_uuid(gravitino.get("statefulset_uid"))
        or not _valid_uuid(gravitino.get("pod_uid"))
        or gravitino.get("ready_replicas") != 1
        or gravitino.get("node_name") != COMPUTE_NODE
        or not str(gravitino.get("image_id") or "").endswith(
            GRAVITINO_KUBERNETES_IMAGE_ID
        )
        or gravitino.get("service_account") != "gravitino-persistence"
        or gravitino.get("service_account_automount_disabled") is not True
        or gravitino.get("persistent_volume_claims") != []
        or gravitino.get("pvc") is not None
        or runtime.get("gravitino_jdbc_driver_mounted") is not True
        or runtime.get("gravitino_aws_sdk_mounted") is not True
    ):
        errors.append("gravitino runtime observation does not match")
    if (
        not str(iceberg_rest.get("image_id") or "").endswith(
            GRAVITINO_KUBERNETES_IMAGE_ID
        )
        or iceberg_rest.get("ready") is not True
        or iceberg_rest.get("jdbc_driver_mounted") is not True
        or iceberg_rest.get("aws_sdk_mounted") is not True
        or iceberg_rest.get("path") != "/iceberg"
    ):
        errors.append("Iceberg REST object-store sidecar boundary does not match")
    if (
        object_store.get("node_name") == gravitino.get("node_name")
        or object_store.get("node_name") == postgresql.get("node_name")
    ):
        errors.append("Object store is not isolated on the second Kubernetes node")
    return errors


def _spark_errors(spark: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    job = _mapping(spark.get("job"))
    pod = _mapping(spark.get("pod"))
    result = _mapping(spark.get("result"))
    if (
        spark.get("wait_completed") is not True
        or job.get("name") != "spark-object-store-probe"
        or not _valid_uuid(job.get("uid"))
        or job.get("succeeded") != 1
        or job.get("failed") != 0
        or not job.get("completion_time")
        or pod.get("phase") != "Succeeded"
        or not _valid_uuid(pod.get("uid"))
    ):
        errors.append("Spark object-store Job did not complete exactly once")
    if (
        pod.get("node_name") != COMPUTE_NODE
        or pod.get("service_account") != "spark-object-store-probe"
        or pod.get("service_account_automount_disabled") is not True
        or not str(pod.get("image_id") or "").endswith(
            SPARK_KUBERNETES_IMAGE_ID
        )
        or pod.get("persistent_volume_claims") != []
    ):
        errors.append("Spark object-store runtime boundary does not match")
    if (
        spark.get("result_line_count") != 1
        or not _valid_sha256(spark.get("log_sha256"))
        or spark.get("log_recorded") is not False
        or result.get("schema") != "gda.spark_object_store_probe_result.v1"
        or result.get("spark_version") != "3.5.0"
        or result.get("iceberg_runtime") != "1.6.1"
        or result.get("catalog_uri")
        != "http://gravitino-persistence:9001/iceberg"
        or result.get("warehouse") != "s3://gda-metadata-warehouse/warehouse"
        or result.get("object_store_endpoint")
        != "http://metadata-object-store:9000"
        or result.get("file_io") != "org.apache.iceberg.aws.s3.S3FileIO"
        or result.get("table")
        != "rest.published.gda_spark_object_store_probe"
        or spark.get("failure_diagnostic") != []
    ):
        errors.append("Spark object-store result envelope does not match")
    if (
        result.get("initial_columns") != ["probe_id"]
        or result.get("initial_row_count") != 0
        or result.get("current_columns") != ["probe_id", "quality"]
        or result.get("current_rows")
        != [["spark-a", None], ["spark-b", None], ["spark-c", "verified"]]
        or result.get("create_read_write_verified") is not True
    ):
        errors.append("Spark object-store create/read/write result does not match")
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
        errors.append("Spark object-store snapshot/time-travel result does not match")
    if result.get("schema_evolution_verified") is not True:
        errors.append("Spark object-store schema evolution result does not match")
    data_paths = result.get("data_file_paths")
    if (
        not isinstance(data_paths, list)
        or len(data_paths) != 2
        or len(set(data_paths)) != 2
        or not all(
            isinstance(path, str)
            and path.startswith(
                "s3://gda-metadata-warehouse/warehouse/published/"
                "gda_spark_object_store_probe/data/"
            )
            and path.endswith(".parquet")
            for path in data_paths
        )
        or result.get("object_store_data_files_verified") is not True
    ):
        errors.append("Spark object-store data file result does not match")
    return errors


def _object_store_errors(
    prepared: Mapping[str, Any],
    observed: Mapping[str, Any],
    spark: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    if (
        prepared.get("service") != "metadata-object-store"
        or prepared.get("bucket") != "gda-metadata-warehouse"
        or prepared.get("created") is not True
        or prepared.get("head_bucket_verified") is not True
        or prepared.get("path_style_access") is not True
        or prepared.get("region") != "us-east-1"
        or prepared.get("material_recorded") is not False
    ):
        errors.append("Object-store bucket preparation does not match")
    objects = observed.get("objects")
    object_items = objects if isinstance(objects, list) else []
    data_keys = observed.get("data_keys")
    metadata_keys = observed.get("metadata_keys")
    manifest_keys = observed.get("manifest_keys")
    if (
        observed.get("bucket") != "gda-metadata-warehouse"
        or observed.get("prefix")
        != "warehouse/published/gda_spark_object_store_probe/"
        or observed.get("object_count") != len(object_items)
        or len(object_items) < 8
        or not all(
            str(_mapping(item).get("key") or "").startswith(
                "warehouse/published/gda_spark_object_store_probe/"
            )
            and isinstance(_mapping(item).get("size"), int)
            and _mapping(item).get("size") > 0
            and bool(_mapping(item).get("etag"))
            for item in object_items
        )
        or not isinstance(data_keys, list)
        or len(data_keys) != 2
        or not isinstance(metadata_keys, list)
        or len(metadata_keys) < 3
        or not isinstance(manifest_keys, list)
        or len(manifest_keys) < 4
        or observed.get("material_recorded") is not False
    ):
        errors.append("Object-store Iceberg object inventory does not match")
    result = _mapping(spark.get("result"))
    data_paths = result.get("data_file_paths")
    expected_paths = (
        sorted(f"s3://gda-metadata-warehouse/{key}" for key in data_keys)
        if isinstance(data_keys, list)
        else []
    )
    latest = _mapping(observed.get("latest_metadata"))
    snapshot_ids = result.get("snapshot_ids")
    if (
        data_paths != expected_paths
        or latest.get("location")
        != (
            "s3://gda-metadata-warehouse/warehouse/published/"
            "gda_spark_object_store_probe"
        )
        or not isinstance(snapshot_ids, list)
        or len(snapshot_ids) != 2
        or latest.get("current_snapshot_id") != snapshot_ids[-1]
        or not isinstance(latest.get("current_schema_id"), int)
        or latest.get("fields")
        != [
            {"name": "probe_id", "required": True, "type": "string"},
            {"name": "quality", "required": False, "type": "string"},
        ]
        or latest.get("key") not in (metadata_keys or [])
    ):
        errors.append("Object-store Iceberg metadata projection does not match")
    return errors


def _expected_post_spark_projection() -> dict[str, Any]:
    return {
        "name": "gda_spark_object_store_probe",
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
        errors.append("Spark object-store observation contains sensitive material")
    if observation.get("schema") != OBSERVATION_SCHEMA:
        errors.append("Spark object-store observation schema does not match")
    contract = _mapping(observation.get("contract"))
    if (
        contract.get("local_static_contract_verified") is not True
        or not _valid_sha256(contract.get("contract_fingerprint"))
        or contract.get("spark_interoperability_evidence_fingerprint")
        != SPARK_INTEROPERABILITY_EVIDENCE_FINGERPRINT
    ):
        errors.append("Spark object-store contract binding does not match")

    runtime = _mapping(observation.get("runtime"))
    runtime_errors = _runtime_errors(runtime)
    errors.extend(runtime_errors)
    prepared = _mapping(observation.get("object_store_prepared"))
    pre_spark = _mapping(observation.get("pre_spark"))
    pre_table = _mapping(pre_spark.get("table"))
    expected_pre_projection = {
        "name": "gda_spark_object_store_probe",
        "columns": [{"name": "probe_id", "type": "string", "nullable": False}],
        "probe_property": "true",
    }
    pre_catalog = _mapping(pre_spark.get("catalog"))
    if (
        _mapping(pre_spark.get("authentication")).get("admin_status") != 200
        or _mapping(pre_spark.get("authentication")).get("bounded_status") != 200
        or pre_catalog.get("warehouse")
        != "s3://gda-metadata-warehouse/warehouse"
        or pre_catalog.get("io_impl") != "org.apache.iceberg.aws.s3.S3FileIO"
        or pre_catalog.get("s3_endpoint") != "http://metadata-object-store:9000"
        or pre_catalog.get("s3_region") != "us-east-1"
        or pre_catalog.get("s3_path_style_access") is not True
        or pre_catalog.get("material_recorded") is not False
        or pre_table.get("create_status") != 200
        or pre_table.get("read_status") != 200
        or pre_table.get("projection") != expected_pre_projection
        or pre_table.get("fingerprint")
        != recovery._canonical_sha256(expected_pre_projection)
        or pre_spark.get("denied_catalog_create_status") != 403
    ):
        errors.append("Gravitino bounded pre-Spark object-store boundary does not match")

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
        errors.append("Gravitino API did not read back object-store schema evolution")
    if post_spark.get("denied_catalog_create_status") != 403:
        errors.append("Post-Spark object-store catalog mutation was not denied")

    object_store = _mapping(observation.get("object_store"))
    object_errors = _object_store_errors(prepared, object_store, spark)
    errors.extend(object_errors)

    runtime_checks = _mapping(observation.get("runtime_checks"))
    if (
        runtime_checks.get("namespace_delete_completed") is not True
        or runtime_checks.get("namespace_absent") is not True
        or runtime_checks.get("persistent_volumes_absent") is not True
        or runtime_checks.get("provider_objects_retained") is not False
        or runtime_checks.get("object_store_objects_retained") is not False
        or runtime_checks.get("all_port_forwards_stopped") is not True
        or runtime_checks.get("material_recorded") is not False
        or runtime_checks.get("kubernetes_service_account_used_for_provider_login")
        is not False
    ):
        errors.append("Spark object-store interoperability cleanup is incomplete")

    result = _mapping(spark.get("result"))
    spark_runtime_verified = not any(
        error
        in {
            "Spark object-store Job did not complete exactly once",
            "Spark object-store runtime boundary does not match",
            "Spark object-store result envelope does not match",
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
    object_store_metadata_verified = not object_errors
    cross_node_verified = (
        not runtime_errors
        and spark_runtime_verified
        and object_store_metadata_verified
        and _mapping(runtime.get("object_store")).get("node_name")
        == OBJECT_STORE_NODE
        and _mapping(runtime.get("gravitino")).get("node_name") == COMPUTE_NODE
        and _mapping(spark.get("pod")).get("node_name") == COMPUTE_NODE
        and _mapping(runtime.get("gravitino")).get("persistent_volume_claims")
        == []
        and _mapping(spark.get("pod")).get("persistent_volume_claims") == []
    )
    verified = not errors
    stable = {
        "schema": EVIDENCE_SCHEMA,
        "observed_at": observation.get("observed_at"),
        "local_static_contract_verified": (
            contract.get("local_static_contract_verified") is True
        ),
        "local_spark_object_store_interoperability_verified": verified,
        "local_spark_create_read_write_verified": create_read_write_verified,
        "local_spark_schema_evolution_verified": schema_evolution_verified,
        "local_spark_snapshot_time_travel_verified": (
            snapshot_time_travel_verified
        ),
        "gravitino_api_metadata_readback_verified": api_readback_verified,
        "local_cross_node_object_store_verified": cross_node_verified,
        "object_store_metadata_verified": object_store_metadata_verified,
        "persistent_catalog_identity_binding_verified": False,
        "protected_workload_identity_verified": False,
        "oidc_verified": False,
        "tls_verified": False,
        "production_object_store_verified": False,
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
        errors.append("Spark object-store evidence fingerprint does not match")
    for key, expected in rebuilt.items():
        if key == "evidence_fingerprint":
            continue
        if evidence.get(key) != expected:
            errors.append(f"Spark object-store evidence field drift: {key}")
    for claim in (
        "persistent_catalog_identity_binding_verified",
        "protected_workload_identity_verified",
        "oidc_verified",
        "tls_verified",
        "production_object_store_verified",
        "spark_conformance_verified",
        "flink_conformance_verified",
        "production_ingestion_verified",
        "production_ready",
    ):
        if evidence.get(claim) is not False:
            errors.append(f"Spark object-store evidence may not claim {claim}")
    return errors


def run_live_rehearsal(
    profile_path: Path = DEFAULT_PROFILE_PATH,
) -> dict[str, Any]:
    profile = load_profile(profile_path)
    contract = build_contract_report(profile_path)
    if contract.get("local_static_contract_verified") is not True:
        raise MetadataFabricSparkObjectStoreInteroperabilityError(
            "Spark object-store static contract is invalid"
        )

    admin_material = SecretStr(secrets.token_urlsafe(24))
    database_material = SecretStr(secrets.token_urlsafe(24))
    user_material = SecretStr(secrets.token_urlsafe(24))
    object_store_user = SecretStr("gda" + secrets.token_hex(8))
    object_store_material = SecretStr(secrets.token_urlsafe(32))
    runtime = IsolatedSparkObjectStoreRuntime(profile)
    provider_forward: provider_metrics._PortForward | None = None
    object_forward: provider_metrics._PortForward | None = None
    rehearsal: ObjectStoreCatalogRehearsal | None = None
    runtime_observation: dict[str, Any] | None = None
    object_store_prepared: dict[str, Any] | None = None
    pre_spark: dict[str, Any] | None = None
    spark: dict[str, Any] | None = None
    post_spark: dict[str, Any] | None = None
    object_store: dict[str, Any] | None = None
    provider_forward_stopped = False
    object_forward_stopped = False
    cleanup: dict[str, Any] = {
        "namespace_delete_completed": False,
        "namespace_absent": False,
        "persistent_volumes_absent": False,
        "provider_objects_retained": True,
        "object_store_objects_retained": True,
    }
    try:
        runtime_observation = runtime.start(
            admin_material=admin_material,
            database_material=database_material,
            object_store_user=object_store_user,
            object_store_material=object_store_material,
        )
        object_forward = provider_metrics._PortForward(
            kubectl="kubectl",
            context=profile.cluster.context,
            namespace=profile.cluster.rehearsal_namespace,
            service=profile.runtime.object_store_service,
            target_port=profile.runtime.object_store_service_port,
        )
        object_forward.start()
        object_endpoint = f"http://127.0.0.1:{object_forward.local_port}"
        object_store_prepared = runtime.prepare_object_store(
            endpoint_url=object_endpoint,
            object_store_user=object_store_user,
            object_store_material=object_store_material,
        )
        provider_forward = provider_metrics._PortForward(
            kubectl="kubectl",
            context=profile.cluster.context,
            namespace=profile.cluster.rehearsal_namespace,
            service=profile.runtime.service,
            target_port=profile.runtime.gravitino_service_port,
        )
        provider_forward.start()
        rehearsal = ObjectStoreCatalogRehearsal(
            base_url=f"http://127.0.0.1:{provider_forward.local_port}/api",
            admin_name=profile.identity.service_admin,
            admin_material=admin_material,
        )
        pre_spark = rehearsal.bootstrap(
            profile,
            database_material=database_material,
            user_material=user_material,
            object_store_user=object_store_user,
            object_store_material=object_store_material,
        )
        spark = runtime.run_spark_probe()
        post_spark = spark_interop._post_spark_readback(
            rehearsal, profile, user_material
        )
        object_store = runtime.observe_object_store(
            endpoint_url=object_endpoint,
            object_store_user=object_store_user,
            object_store_material=object_store_material,
        )
    finally:
        if rehearsal is not None:
            rehearsal.close()
        if provider_forward is not None:
            provider_forward_stopped = provider_forward.stop()
        if object_forward is not None:
            object_forward_stopped = object_forward.stop()
        cleanup = runtime.cleanup()

    if (
        runtime_observation is None
        or object_store_prepared is None
        or pre_spark is None
        or spark is None
        or post_spark is None
        or object_store is None
    ):
        raise MetadataFabricSparkObjectStoreInteroperabilityError(
            "Spark object-store rehearsal did not produce an outcome"
        )
    observation = {
        "schema": OBSERVATION_SCHEMA,
        "observed_at": datetime.now(UTC).isoformat(),
        "contract": {
            "contract_fingerprint": contract["contract_fingerprint"],
            "local_static_contract_verified": True,
            "spark_interoperability_evidence_fingerprint": (
                SPARK_INTEROPERABILITY_EVIDENCE_FINGERPRINT
            ),
        },
        "runtime": runtime_observation,
        "object_store_prepared": object_store_prepared,
        "pre_spark": pre_spark,
        "spark": spark,
        "post_spark": post_spark,
        "object_store": object_store,
        "runtime_checks": {
            **cleanup,
            "all_port_forwards_stopped": (
                provider_forward_stopped and object_forward_stopped
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
            raise TypeError("Spark object-store evidence must be an object")
        evidence = value
        errors.extend(verify_evidence_integrity(evidence))
        observed_contract = _mapping(
            _mapping(evidence.get("observation")).get("contract")
        ).get("contract_fingerprint")
        if observed_contract != contract.get("contract_fingerprint"):
            errors.append("Spark object-store evidence contract fingerprint drift")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"Spark object-store evidence is invalid: {type(exc).__name__}")
    verified = not errors
    return {
        "schema": VALIDATION_SCHEMA,
        "local_static_contract_verified": contract["local_static_contract_verified"],
        "local_spark_object_store_interoperability_verified": (
            verified
            and evidence is not None
            and evidence.get("local_spark_object_store_interoperability_verified")
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
        "local_cross_node_object_store_verified": (
            verified
            and evidence is not None
            and evidence.get("local_cross_node_object_store_verified") is True
        ),
        "object_store_metadata_verified": (
            verified
            and evidence is not None
            and evidence.get("object_store_metadata_verified") is True
        ),
        "persistent_catalog_identity_binding_verified": False,
        "protected_workload_identity_verified": False,
        "oidc_verified": False,
        "tls_verified": False,
        "production_object_store_verified": False,
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
                raise TypeError("Spark object-store evidence must be an object")
            errors = verify_evidence_integrity(value)
            print(json.dumps({"verified": not errors, "errors": errors}, indent=2))
            return 0 if not errors else 1
        evidence = run_live_rehearsal(args.profile)
        _write_json(args.evidence_out, evidence)
        print(json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if not evidence["errors"] else 1
    except (
        BotoCoreError,
        ClientError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        identity.MetadataFabricGravitinoIdentityError,
        jdbc_restart.MetadataFabricGravitinoJdbcRestartError,
        MetadataFabricSparkObjectStoreInteroperabilityError,
        KeyboardInterrupt,
    ) as exc:
        print(f"metadata fabric Spark/object-store interoperability: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
