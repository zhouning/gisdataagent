"""Verify local Spark/Iceberg commit-failure atomicity and retry recovery.

The rehearsal injects a deterministic HTTP 503 before an Iceberg REST table
commit reaches Gravitino. It verifies that the failed attempt changes no visible
snapshot or row, then retries the same logical row exactly once. This remains
local Docker Desktop evidence, not production storage or full conformance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import Field, SecretStr, ValidationError

from . import metadata_fabric_gravitino_identity as identity
from . import metadata_fabric_gravitino_jdbc_restart as jdbc_restart
from . import metadata_fabric_ingestion_replay as ingestion_replay
from . import metadata_fabric_provider_metrics as provider_metrics
from . import metadata_fabric_recovery_rehearsal as recovery
from . import metadata_fabric_spark_iceberg_rest_interoperability as spark_interop
from . import metadata_fabric_spark_object_store_interoperability as object_interop


PROFILE_SCHEMA = "gda.metadata_fabric_spark_commit_failure_recovery_profile.v1"
CONTRACT_SCHEMA = "gda.metadata_fabric_spark_commit_failure_recovery_contract.v1"
OBSERVATION_SCHEMA = (
    "gda.metadata_fabric_spark_commit_failure_recovery_observation.v1"
)
EVIDENCE_SCHEMA = "gda.metadata_fabric_spark_commit_failure_recovery_evidence.v1"
VALIDATION_SCHEMA = "gda.metadata_fabric_spark_commit_failure_recovery_validation.v1"

CONTEXT = "docker-desktop"
SOURCE_NAMESPACE = "gda-metadata-sandbox"
REHEARSAL_NAMESPACE = "gda-metadata-spark-commit-failure"
OBJECT_STORE_NODE = "desktop-control-plane"
COMPUTE_NODE = "desktop-worker"
DEPENDENCY_EVIDENCE_FINGERPRINT = (
    "05844457efb378581fb7fc2e7ed3c706819b2d8fa5a52b2f82577051d38c2cd1"
)
GRAVITINO_SCHEMA_SHA256 = object_interop.GRAVITINO_SCHEMA_SHA256
GRAVITINO_HOST_IMAGE_ID = object_interop.GRAVITINO_HOST_IMAGE_ID
GRAVITINO_KUBERNETES_IMAGE_ID = object_interop.GRAVITINO_KUBERNETES_IMAGE_ID
POSTGRESQL_IMAGE_DIGEST = object_interop.POSTGRESQL_IMAGE_DIGEST
SPARK_HOST_IMAGE_ID = object_interop.SPARK_HOST_IMAGE_ID
SPARK_KUBERNETES_IMAGE_ID = object_interop.SPARK_KUBERNETES_IMAGE_ID
MINIO_HOST_IMAGE_ID = object_interop.MINIO_HOST_IMAGE_ID
MINIO_KUBERNETES_IMAGE_ID = object_interop.MINIO_KUBERNETES_IMAGE_ID

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = (
    REPO_ROOT / "config/metadata-fabric-spark-commit-failure-recovery.local.yaml"
)
DEFAULT_EVIDENCE_PATH = (
    REPO_ROOT
    / "docs/evidence/metadata-fabric-spark-commit-failure-recovery-2026-07-29.json"
)
DEFAULT_WRAPPER_PATH = (
    REPO_ROOT / "scripts/metadata-fabric-spark-commit-failure-recovery.sh"
)
MANIFEST_DIR = REPO_ROOT / "k8s/metadata-fabric-spark-commit-failure-recovery"

EXPECTED_OBSERVATION_KEYS = {
    "schema",
    "observed_at",
    "contract",
    "runtime",
    "object_store_prepared",
    "pre_spark",
    "spark",
    "post_spark",
    "object_store",
    "runtime_checks",
}
PRODUCTION_FALSE_CLAIMS = {
    "persistent_catalog_identity_binding_verified",
    "protected_workload_identity_verified",
    "oidc_verified",
    "tls_verified",
    "production_object_store_verified",
    "spark_cancel_verified",
    "spark_reconcile_verified",
    "spark_lineage_verified",
    "spark_conformance_verified",
    "flink_conformance_verified",
    "production_ingestion_verified",
    "production_ready",
}
DEPENDENCY_FALSE_CLAIMS = {
    "persistent_catalog_identity_binding_verified",
    "protected_workload_identity_verified",
    "oidc_verified",
    "tls_verified",
    "production_object_store_verified",
    "spark_conformance_verified",
    "flink_conformance_verified",
    "production_ingestion_verified",
    "production_ready",
}


class MetadataFabricSparkCommitFailureRecoveryError(RuntimeError):
    """The local commit-failure recovery contract failed closed."""


class ClusterProfile(object_interop.ClusterProfile):
    rehearsal_namespace: Literal["gda-metadata-spark-commit-failure"]


class RuntimeProfile(object_interop.RuntimeProfile):
    manifest: Literal["k8s/metadata-fabric-spark-commit-failure-recovery"]
    spark_job: Literal["spark-commit-failure-probe"]


class DependencyProfile(object_interop._FrozenModel):
    evidence_path: Literal[
        "docs/evidence/metadata-fabric-spark-object-store-interoperability-2026-07-29.json"
    ]
    evidence_fingerprint: Literal[DEPENDENCY_EVIDENCE_FINGERPRINT]
    required_claim: Literal["local_spark_object_store_interoperability_verified"]


class CatalogProfile(object_interop.CatalogProfile):
    object_prefix: Literal[
        "warehouse/published/gda_spark_commit_failure_probe/"
    ]
    interoperability_scope: Literal[
        "local_cross_node_s3_commit_failure_recovery"
    ]


class ScopeProfile(object_interop.ScopeProfile):
    metalake: Literal["gda_commit_failure"]
    table: Literal["gda_spark_commit_failure_probe"]


class ClaimProfile(object_interop._FrozenModel):
    local_spark_commit_failure_recovery_verified: Literal[False]
    local_failed_commit_atomicity_verified: Literal[False]
    local_retry_recovery_verified: Literal[False]
    local_exactly_once_visible_effect_verified: Literal[False]
    gravitino_api_metadata_readback_verified: Literal[False]
    local_cross_node_object_store_verified: Literal[False]
    object_store_metadata_verified: Literal[False]
    spark_cancel_verified: Literal[False]
    spark_reconcile_verified: Literal[False]
    spark_lineage_verified: Literal[False]
    persistent_catalog_identity_binding_verified: Literal[False]
    protected_workload_identity_verified: Literal[False]
    oidc_verified: Literal[False]
    tls_verified: Literal[False]
    production_object_store_verified: Literal[False]
    spark_conformance_verified: Literal[False]
    flink_conformance_verified: Literal[False]
    production_ingestion_verified: Literal[False]
    production_ready: Literal[False]


class SparkCommitFailureRecoveryProfile(object_interop._FrozenModel):
    schema_name: Literal[PROFILE_SCHEMA] = Field(alias="schema")
    environment: Literal["local_docker_desktop"]
    cluster: ClusterProfile
    runtime: RuntimeProfile
    dependency: DependencyProfile
    identity: object_interop.IdentityProfile
    catalog: CatalogProfile
    scope: ScopeProfile
    claims: ClaimProfile


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _load_dependency(profile: SparkCommitFailureRecoveryProfile) -> None:
    path = (REPO_ROOT / profile.dependency.evidence_path).resolve()
    try:
        path.relative_to(REPO_ROOT)
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MetadataFabricSparkCommitFailureRecoveryError(
            "Spark object-store dependency is unavailable"
        ) from exc
    if not isinstance(value, dict):
        raise MetadataFabricSparkCommitFailureRecoveryError(
            "Spark object-store dependency is not an object"
        )
    if (
        object_interop.verify_evidence_integrity(value)
        or value.get("evidence_fingerprint")
        != profile.dependency.evidence_fingerprint
        or value.get(profile.dependency.required_claim) is not True
        or any(value.get(claim) is not False for claim in DEPENDENCY_FALSE_CLAIMS)
    ):
        raise MetadataFabricSparkCommitFailureRecoveryError(
            "Spark object-store dependency does not match"
        )


def load_profile(path: Path = DEFAULT_PROFILE_PATH) -> SparkCommitFailureRecoveryProfile:
    try:
        raw = yaml.safe_load(path.resolve().read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TypeError("profile must be an object")
        ingestion_replay._reject_sensitive_fields(raw)
        profile = SparkCommitFailureRecoveryProfile.model_validate(raw)
    except (OSError, TypeError, ValueError, ValidationError, yaml.YAMLError) as exc:
        raise MetadataFabricSparkCommitFailureRecoveryError(
            f"Spark commit-failure profile is invalid: {type(exc).__name__}"
        ) from exc
    if (
        object_interop._profile_securable_objects(profile)
        != identity._expected_securable_objects()
    ):
        raise MetadataFabricSparkCommitFailureRecoveryError(
            "Spark commit-failure role exceeds the bounded table-create scope"
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
        return [f"Spark commit-failure manifest is invalid: {type(exc).__name__}"]
    if any(document.get("kind") == "Secret" for document in documents):
        errors.append("Spark commit-failure manifest may not commit Secret values")
    required = {
        "Namespace",
        "ResourceQuota",
        "ServiceAccount",
        "ConfigMap",
        "Service",
        "StatefulSet",
        "Job",
    }
    if not required.issubset({str(document.get("kind")) for document in documents}):
        errors.append("Spark commit-failure manifest is incomplete")
    rendered = json.dumps(documents, ensure_ascii=True, sort_keys=True)
    for marker in (
        "gda-metadata-spark-commit-failure",
        "spark-commit-failure-probe",
        "ThreadingHTTPServer",
        "pre_forward_http_503",
        "injected pre-forward catalog commit failure",
        "failed_commit_atomicity_verified",
        "retry_recovery_verified",
        "exactly_once_visible_effect_verified",
        "GDA_SPARK_COMMIT_FAILURE_RESULT",
        "gravitino.iceberg-rest.catalog-backend = jdbc",
        "gravitino.iceberg-rest.io-impl = org.apache.iceberg.aws.s3.S3FileIO",
        "desktop-control-plane",
        "desktop-worker",
        "automountServiceAccountToken",
    ):
        if marker not in rendered:
            errors.append(f"Spark commit-failure manifest is missing marker: {marker}")
    for forbidden in (
        "gravitino.authenticators = simple",
        "file:///var/lib/gravitino/warehouse",
        '"mountPath": "/var/lib/gravitino/warehouse"',
    ):
        if forbidden in rendered:
            errors.append(
                f"Spark commit-failure manifest contains forbidden marker: {forbidden}"
            )

    job = next(
        (
            document
            for document in documents
            if document.get("kind") == "Job"
            and _mapping(document.get("metadata")).get("name")
            == "spark-commit-failure-probe"
        ),
        {},
    )
    spec = _mapping(job.get("spec"))
    pod_spec = _mapping(_mapping(spec.get("template")).get("spec"))
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
    if spec.get("suspend") is not True or spec.get("backoffLimit") != 0:
        errors.append("Spark commit-failure Job retry boundary does not match")
    if pod_spec.get("automountServiceAccountToken") is not False:
        errors.append("Spark commit-failure Job must disable token automount")
    if any(_mapping(item).get("persistentVolumeClaim") for item in volume_items):
        errors.append("Spark commit-failure Job may not mount a warehouse PVC")
    if not {"cpu", "memory"}.issubset(_mapping(resources.get("requests"))) or not {
        "cpu",
        "memory",
    }.issubset(_mapping(resources.get("limits"))):
        errors.append("Spark commit-failure Job resources are incomplete")
    if (
        security.get("allowPrivilegeEscalation") is not False
        or security.get("readOnlyRootFilesystem") is not True
    ):
        errors.append("Spark commit-failure Job security context is incomplete")
    return errors


def build_contract_report(
    profile_path: Path = DEFAULT_PROFILE_PATH,
    wrapper_path: Path = DEFAULT_WRAPPER_PATH,
) -> dict[str, Any]:
    errors: list[str] = []
    profile: SparkCommitFailureRecoveryProfile | None = None
    try:
        profile = load_profile(profile_path)
    except MetadataFabricSparkCommitFailureRecoveryError as exc:
        errors.append(str(exc))
    errors.extend(_validate_manifest())
    try:
        wrapper = wrapper_path.resolve().read_text(encoding="utf-8")
        for marker in (
            "set -euo pipefail",
            "metadata_fabric_spark_commit_failure_recovery",
        ):
            if marker not in wrapper:
                errors.append(f"Spark commit-failure wrapper is missing: {marker}")
    except OSError as exc:
        errors.append(f"Spark commit-failure wrapper is invalid: {type(exc).__name__}")

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
        "dependency_evidence_fingerprint": DEPENDENCY_EVIDENCE_FINGERPRINT,
        "failure_injection": {
            "boundary": "iceberg_rest_table_commit",
            "mode": "pre_forward_http_503",
            "scope": "single_spark_driver_loopback_proxy",
            "provider_commit_forwarded": False,
        },
        "required_invariants": {
            "failed_attempt_visible_snapshot_delta": 0,
            "failed_attempt_visible_row_delta": 0,
            "retry_visible_snapshot_delta": 1,
            "retry_visible_row_delta": 1,
        },
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
        "catalog": {
            "warehouse": profile.catalog.warehouse if profile else None,
            "io_impl": profile.catalog.io_impl if profile else None,
            "s3_endpoint": profile.catalog.s3_endpoint if profile else None,
            "bucket": profile.catalog.bucket if profile else None,
            "object_prefix": profile.catalog.object_prefix if profile else None,
            "interoperability_scope": (
                profile.catalog.interoperability_scope if profile else None
            ),
        },
        "local_static_contract_verified": not errors,
        "local_spark_commit_failure_recovery_verified": False,
        "production_object_store_verified": False,
        "spark_cancel_verified": False,
        "spark_reconcile_verified": False,
        "spark_lineage_verified": False,
        "spark_conformance_verified": False,
        "flink_conformance_verified": False,
        "production_ready": False,
        "files": files,
        "errors": errors,
    }
    return {**stable, "contract_fingerprint": recovery._canonical_sha256(stable)}


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
        or not object_interop._valid_uuid(namespace.get("uid"))
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
        errors.append("Spark commit-failure runtime boundary does not match")

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
            not object_interop._valid_uuid(value.get("statefulset_uid"))
            or not object_interop._valid_uuid(value.get("pod_uid"))
            or value.get("ready_replicas") != 1
            or value.get("node_name") != node
            or not str(value.get("image_id") or "").endswith(image_id)
            or value.get("service_account") != account
            or value.get("service_account_automount_disabled") is not True
            or value.get("persistent_volume_claims") != [pvc_name]
            or pvc.get("name") != pvc_name
            or not object_interop._valid_uuid(pvc.get("uid"))
            or pvc.get("storage_class") != "standard"
            or not pvc.get("volume_name")
            or pvc.get("phase") != "Bound"
        ):
            errors.append(f"{name} commit-failure runtime observation does not match")

    if (
        not object_interop._valid_uuid(gravitino.get("statefulset_uid"))
        or not object_interop._valid_uuid(gravitino.get("pod_uid"))
        or gravitino.get("ready_replicas") != 1
        or gravitino.get("node_name") != COMPUTE_NODE
        or not str(gravitino.get("image_id") or "").endswith(
            GRAVITINO_KUBERNETES_IMAGE_ID
        )
        or gravitino.get("service_account") != "gravitino-persistence"
        or gravitino.get("service_account_automount_disabled") is not True
        or gravitino.get("persistent_volume_claims") != []
        or runtime.get("gravitino_jdbc_driver_mounted") is not True
        or runtime.get("gravitino_aws_sdk_mounted") is not True
        or iceberg_rest.get("ready") is not True
        or iceberg_rest.get("jdbc_driver_mounted") is not True
        or iceberg_rest.get("aws_sdk_mounted") is not True
    ):
        errors.append("Gravitino commit-failure runtime observation does not match")
    if object_store.get("node_name") == gravitino.get("node_name"):
        errors.append("Commit-failure object store is not on the second node")
    return errors


def _spark_errors(spark: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    job = _mapping(spark.get("job"))
    pod = _mapping(spark.get("pod"))
    result = _mapping(spark.get("result"))
    if (
        spark.get("wait_completed") is not True
        or spark.get("terminal_condition") != "Complete"
        or job.get("name") != "spark-commit-failure-probe"
        or job.get("succeeded") != 1
        or job.get("failed") not in {None, 0}
        or pod.get("phase") != "Succeeded"
        or spark.get("result_line_count") != 1
        or not object_interop._valid_sha256(spark.get("log_sha256"))
        or spark.get("log_recorded") is not False
        or spark.get("failure_diagnostic") != []
    ):
        errors.append("Spark commit-failure Job did not complete exactly once")
    if (
        pod.get("node_name") != COMPUTE_NODE
        or pod.get("service_account") != "spark-commit-failure-probe"
        or pod.get("service_account_automount_disabled") is not True
        or pod.get("persistent_volume_claims") != []
        or not str(pod.get("image_id") or "").endswith(SPARK_KUBERNETES_IMAGE_ID)
    ):
        errors.append("Spark commit-failure Pod boundary does not match")
    if (
        result.get("schema") != "gda.spark_commit_failure_probe_result.v1"
        or result.get("spark_version") != "3.5.0"
        or result.get("iceberg_runtime") != "1.6.1"
        or result.get("catalog_uri") != "http://127.0.0.1:19001/iceberg"
        or result.get("catalog_upstream")
        != "http://gravitino-persistence:9001/iceberg"
        or result.get("warehouse") != "s3://gda-metadata-warehouse/warehouse"
        or result.get("object_store_endpoint")
        != "http://metadata-object-store:9000"
        or result.get("file_io") != "org.apache.iceberg.aws.s3.S3FileIO"
        or result.get("table")
        != "rest.published.gda_spark_commit_failure_probe"
        or result.get("initial_columns") != ["probe_id"]
        or result.get("initial_rows") != []
        or result.get("initial_snapshots") != []
        or result.get("material_recorded") is not False
    ):
        errors.append("Spark commit-failure result envelope does not match")

    baseline = _mapping(result.get("baseline"))
    failed = _mapping(result.get("failed_attempt"))
    retry = _mapping(result.get("retry"))
    baseline_snapshots = _list(baseline.get("snapshots"))
    retry_snapshots = _list(retry.get("snapshots"))
    baseline_data_files = _list(baseline.get("data_file_paths"))
    retry_data_files = _list(retry.get("data_file_paths"))
    if (
        baseline.get("rows") != ["spark-baseline-a", "spark-baseline-b"]
        or len(baseline_snapshots) != 1
        or _mapping(baseline_snapshots[0]).get("parent_id") is not None
        or _mapping(baseline_snapshots[0]).get("operation") != "append"
        or len(baseline_data_files) != 1
    ):
        errors.append("Spark commit-failure baseline does not match")
    if (
        failed.get("exception_observed") is not True
        or not isinstance(failed.get("exception_type"), str)
        or not failed.get("exception_type")
        or failed.get("rows") != baseline.get("rows")
        or failed.get("snapshots") != baseline_snapshots
        or failed.get("data_file_paths") != baseline.get("data_file_paths")
        or result.get("failed_commit_atomicity_verified") is not True
    ):
        errors.append("Spark failed commit changed visible state")
    if (
        len(retry_snapshots) != 2
        or _mapping(retry_snapshots[0]) != _mapping(baseline_snapshots[0])
        or _mapping(retry_snapshots[1]).get("parent_id")
        != _mapping(retry_snapshots[0]).get("snapshot_id")
        or [_mapping(item).get("operation") for item in retry_snapshots]
        != ["append", "append"]
        or retry.get("rows")
        != ["spark-baseline-a", "spark-baseline-b", "spark-recovery"]
        or len(retry_data_files) != 2
        or result.get("retry_recovery_verified") is not True
        or result.get("exactly_once_visible_effect_verified") is not True
        or result.get("object_store_data_files_verified") is not True
    ):
        errors.append("Spark commit retry visible state does not match")
    proxy = _mapping(result.get("proxy"))
    if (
        proxy.get("failed_commit_requests") != 2
        or proxy.get("forwarded_commit_requests") != 2
        or not isinstance(proxy.get("total_requests"), int)
        or proxy.get("total_requests") < 3
        or proxy.get("injection_mode") != "pre_forward_http_503"
        or proxy.get("loopback_only") is not True
    ):
        errors.append("Spark commit-failure proxy observation does not match")
    return errors


def _object_store_errors(
    prepared: Mapping[str, Any],
    store: Mapping[str, Any],
    spark: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    result = _mapping(spark.get("result"))
    retry = _mapping(result.get("retry"))
    paths = _list(retry.get("data_file_paths"))
    expected_data_keys = sorted(
        str(path).removeprefix("s3://gda-metadata-warehouse/") for path in paths
    )
    data_keys = _list(store.get("data_keys"))
    metadata_keys = _list(store.get("metadata_keys"))
    manifest_keys = _list(store.get("manifest_keys"))
    objects = store.get("objects")
    object_items = objects if isinstance(objects, list) else []
    inventory_keys = sorted(
        str(_mapping(item).get("key") or "") for item in object_items
    )
    categorized_keys = sorted(
        [
            *(str(item) for item in data_keys),
            *(str(item) for item in metadata_keys),
            *(str(item) for item in manifest_keys),
        ]
    )
    if (
        prepared.get("bucket") != "gda-metadata-warehouse"
        or prepared.get("head_bucket_verified") is not True
        or prepared.get("path_style_access") is not True
        or prepared.get("material_recorded") is not False
        or store.get("bucket") != "gda-metadata-warehouse"
        or store.get("prefix")
        != "warehouse/published/gda_spark_commit_failure_probe/"
        or data_keys != expected_data_keys
        or len(metadata_keys) != 3
        or len(manifest_keys) != 4
        or store.get("object_count") != 9
        or len(object_items) != 9
        or inventory_keys != categorized_keys
        or any(
            not str(_mapping(item).get("key") or "").startswith(
                "warehouse/published/gda_spark_commit_failure_probe/"
            )
            or not isinstance(_mapping(item).get("size"), int)
            or _mapping(item).get("size") <= 0
            or not _mapping(item).get("etag")
            for item in object_items
        )
    ):
        errors.append("Commit-failure object-store inventory does not match")
    latest = _mapping(store.get("latest_metadata"))
    retry_snapshots = _list(retry.get("snapshots"))
    expected_snapshot = (
        _mapping(retry_snapshots[-1]).get("snapshot_id")
        if retry_snapshots
        else None
    )
    if (
        latest.get("location")
        != "s3://gda-metadata-warehouse/warehouse/published/gda_spark_commit_failure_probe"
        or latest.get("current_snapshot_id") != expected_snapshot
        or latest.get("fields")
        != [{"name": "probe_id", "required": True, "type": "string"}]
    ):
        errors.append("Commit-failure Iceberg metadata projection does not match")
    return errors


def _expected_table_projection() -> dict[str, Any]:
    return {
        "name": "gda_spark_commit_failure_probe",
        "columns": [{"name": "probe_id", "type": "string", "nullable": False}],
        "probe_property": "true",
    }


def build_evidence(observation: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    try:
        ingestion_replay._reject_sensitive_fields(observation)
    except ValueError:
        errors.append("Spark commit-failure observation contains sensitive material")
    if set(observation) != EXPECTED_OBSERVATION_KEYS:
        errors.append("Spark commit-failure observation inventory does not match")
    if observation.get("schema") != OBSERVATION_SCHEMA:
        errors.append("Spark commit-failure observation schema does not match")
    contract = _mapping(observation.get("contract"))
    if (
        contract.get("local_static_contract_verified") is not True
        or not object_interop._valid_sha256(contract.get("contract_fingerprint"))
        or contract.get("dependency_evidence_fingerprint")
        != DEPENDENCY_EVIDENCE_FINGERPRINT
    ):
        errors.append("Spark commit-failure contract binding does not match")

    runtime = _mapping(observation.get("runtime"))
    runtime_errors = _runtime_errors(runtime)
    errors.extend(runtime_errors)
    prepared = _mapping(observation.get("object_store_prepared"))
    pre_spark = _mapping(observation.get("pre_spark"))
    pre_table = _mapping(pre_spark.get("table"))
    expected_projection = _expected_table_projection()
    if (
        _mapping(pre_spark.get("authentication")).get("admin_status") != 200
        or _mapping(pre_spark.get("authentication")).get("bounded_status") != 200
        or _mapping(pre_spark.get("catalog")).get("warehouse")
        != "s3://gda-metadata-warehouse/warehouse"
        or _mapping(pre_spark.get("catalog")).get("io_impl")
        != "org.apache.iceberg.aws.s3.S3FileIO"
        or pre_table.get("create_status") != 200
        or pre_table.get("read_status") != 200
        or pre_table.get("projection") != expected_projection
        or pre_table.get("fingerprint")
        != recovery._canonical_sha256(expected_projection)
        or pre_spark.get("denied_catalog_create_status") != 403
    ):
        errors.append("Gravitino pre-failure bounded boundary does not match")

    spark = _mapping(observation.get("spark"))
    spark_errors = _spark_errors(spark)
    errors.extend(spark_errors)
    post_spark = _mapping(observation.get("post_spark"))
    post_table = _mapping(post_spark.get("table"))
    api_readback_verified = (
        post_spark.get("authentication_status") == 200
        and post_spark.get("read_status") == 200
        and post_table.get("projection") == expected_projection
        and post_table.get("fingerprint")
        == recovery._canonical_sha256(expected_projection)
        and post_spark.get("denied_catalog_create_status") == 403
    )
    if not api_readback_verified:
        errors.append("Gravitino did not read back the recovered table")

    store_errors = _object_store_errors(
        prepared, _mapping(observation.get("object_store")), spark
    )
    errors.extend(store_errors)
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
        errors.append("Spark commit-failure rehearsal cleanup is incomplete")

    result = _mapping(spark.get("result"))
    atomicity_verified = (
        not any("failed commit" in error.lower() for error in spark_errors)
        and result.get("failed_commit_atomicity_verified") is True
    )
    retry_verified = (
        not any("retry visible" in error.lower() for error in spark_errors)
        and result.get("retry_recovery_verified") is True
    )
    exactly_once_verified = (
        retry_verified and result.get("exactly_once_visible_effect_verified") is True
    )
    cross_node_verified = (
        not runtime_errors
        and _mapping(runtime.get("object_store")).get("node_name")
        == OBJECT_STORE_NODE
        and _mapping(runtime.get("gravitino")).get("node_name") == COMPUTE_NODE
        and _mapping(spark.get("pod")).get("node_name") == COMPUTE_NODE
    )
    verified = not errors
    stable = {
        "schema": EVIDENCE_SCHEMA,
        "observed_at": observation.get("observed_at"),
        "local_static_contract_verified": (
            contract.get("local_static_contract_verified") is True
        ),
        "local_spark_commit_failure_recovery_verified": verified,
        "local_failed_commit_atomicity_verified": atomicity_verified,
        "local_retry_recovery_verified": retry_verified,
        "local_exactly_once_visible_effect_verified": exactly_once_verified,
        "gravitino_api_metadata_readback_verified": api_readback_verified,
        "local_cross_node_object_store_verified": cross_node_verified,
        "object_store_metadata_verified": not store_errors,
        **{claim: False for claim in PRODUCTION_FALSE_CLAIMS},
        "observation": dict(observation),
        "errors": errors,
    }
    return {**stable, "evidence_fingerprint": recovery._canonical_sha256(stable)}


def verify_evidence_integrity(evidence: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    rebuilt = build_evidence(_mapping(evidence.get("observation")))
    if evidence.get("evidence_fingerprint") != rebuilt.get("evidence_fingerprint"):
        errors.append("Spark commit-failure evidence fingerprint does not match")
    for key, expected in rebuilt.items():
        if key != "evidence_fingerprint" and evidence.get(key) != expected:
            errors.append(f"Spark commit-failure evidence field drift: {key}")
    for claim in PRODUCTION_FALSE_CLAIMS:
        if evidence.get(claim) is not False:
            errors.append(f"Spark commit-failure evidence may not claim {claim}")
    return errors


class IsolatedSparkCommitFailureRuntime(
    object_interop.IsolatedSparkObjectStoreRuntime
):
    """Adapt the frozen M3-10 runtime without changing its evidence fingerprint."""

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
            label="Spark commit-failure namespace preflight",
        )
        if existing is not None:
            raise MetadataFabricSparkCommitFailureRecoveryError(
                "Spark commit-failure rehearsal namespace already exists"
            )
        self.kubectl.run(
            ["apply", "-f", str(MANIFEST_DIR / "namespace.yaml")],
            label="Spark commit-failure namespace apply",
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
            label="ephemeral Spark commit-failure inputs apply",
        )
        self.kubectl.run(
            ["apply", "-k", str(MANIFEST_DIR)],
            label="Spark commit-failure runtime apply",
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
            label="Spark commit-failure Job release",
        )
        deadline = time.monotonic() + 900
        terminal_condition: str | None = None
        while time.monotonic() < deadline:
            current_job = self.kubectl.get_json(
                ["-n", namespace, "get", "job", job_name],
                label="Spark commit-failure Job wait",
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
            label="Spark commit-failure Job observation",
        )
        pod_list = self.kubectl.get_json(
            [
                "-n",
                namespace,
                "get",
                "pods",
                "-l",
                f"job-name={job_name}",
            ],
            label="Spark commit-failure pod observation",
        )
        assert job is not None and pod_list is not None
        pod = object_interop._single_list_item(
            pod_list, "Spark commit-failure Job"
        )
        pod_name = _mapping(pod.get("metadata")).get("name")
        logs = self.kubectl.run(
            ["-n", namespace, "logs", str(pod_name), "-c", "spark"],
            expected=frozenset({0, 1}),
            timeout=120,
            label="Spark commit-failure result collection",
        )
        result_marker = "GDA_SPARK_COMMIT_FAILURE_RESULT="
        result_lines = [
            line.removeprefix(result_marker)
            for line in logs.stdout.splitlines()
            if line.startswith(result_marker)
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
                claim = _mapping(
                    _mapping(volume).get("persistentVolumeClaim")
                ).get("claimName")
                if isinstance(claim, str):
                    claims.append(claim)
        container = object_interop._container_status(pod, "spark")
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


def run_live_rehearsal(
    profile_path: Path = DEFAULT_PROFILE_PATH,
) -> dict[str, Any]:
    profile = load_profile(profile_path)
    contract = build_contract_report(profile_path)
    if contract.get("local_static_contract_verified") is not True:
        raise MetadataFabricSparkCommitFailureRecoveryError(
            "Spark commit-failure static contract is invalid"
        )

    admin_material = SecretStr(secrets.token_urlsafe(24))
    database_material = SecretStr(secrets.token_urlsafe(24))
    user_material = SecretStr(secrets.token_urlsafe(24))
    object_store_user = SecretStr("gda" + secrets.token_hex(8))
    object_store_material = SecretStr(secrets.token_urlsafe(32))
    runtime = IsolatedSparkCommitFailureRuntime(profile)
    provider_forward: provider_metrics._PortForward | None = None
    object_forward: provider_metrics._PortForward | None = None
    rehearsal: object_interop.ObjectStoreCatalogRehearsal | None = None
    runtime_observation: dict[str, Any] | None = None
    prepared: dict[str, Any] | None = None
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
        prepared = runtime.prepare_object_store(
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
        rehearsal = object_interop.ObjectStoreCatalogRehearsal(
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

    if any(
        value is None
        for value in (
            runtime_observation,
            prepared,
            pre_spark,
            spark,
            post_spark,
            object_store,
        )
    ):
        raise MetadataFabricSparkCommitFailureRecoveryError(
            "Spark commit-failure rehearsal did not produce an outcome"
        )
    observation = {
        "schema": OBSERVATION_SCHEMA,
        "observed_at": datetime.now(UTC).isoformat(),
        "contract": {
            "contract_fingerprint": contract["contract_fingerprint"],
            "local_static_contract_verified": True,
            "dependency_evidence_fingerprint": DEPENDENCY_EVIDENCE_FINGERPRINT,
        },
        "runtime": runtime_observation,
        "object_store_prepared": prepared,
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
            raise TypeError("evidence must be an object")
        evidence = value
        errors.extend(verify_evidence_integrity(evidence))
        observed_contract = _mapping(
            _mapping(evidence.get("observation")).get("contract")
        ).get("contract_fingerprint")
        if observed_contract != contract.get("contract_fingerprint"):
            errors.append("Spark commit-failure evidence contract fingerprint drift")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"Spark commit-failure evidence is invalid: {type(exc).__name__}")
    verified = not errors
    return {
        "schema": VALIDATION_SCHEMA,
        "local_static_contract_verified": contract["local_static_contract_verified"],
        "local_spark_commit_failure_recovery_verified": (
            verified
            and evidence is not None
            and evidence.get("local_spark_commit_failure_recovery_verified") is True
        ),
        "local_failed_commit_atomicity_verified": (
            verified
            and evidence is not None
            and evidence.get("local_failed_commit_atomicity_verified") is True
        ),
        "local_retry_recovery_verified": (
            verified
            and evidence is not None
            and evidence.get("local_retry_recovery_verified") is True
        ),
        "local_exactly_once_visible_effect_verified": (
            verified
            and evidence is not None
            and evidence.get("local_exactly_once_visible_effect_verified") is True
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
        **{claim: False for claim in PRODUCTION_FALSE_CLAIMS},
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
                raise TypeError("evidence must be an object")
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
        object_interop.MetadataFabricSparkObjectStoreInteroperabilityError,
        MetadataFabricSparkCommitFailureRecoveryError,
        KeyboardInterrupt,
    ) as exc:
        print(f"metadata fabric Spark commit-failure recovery: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
