"""Verify local reconciliation after a committed Iceberg response is lost.

The rehearsal forwards one Spark table commit to Gravitino, receives provider
success, then returns HTTP 504 to Spark instead of the success response. It
uses readback to classify the outcome as committed and does not submit another
write. This remains local Docker Desktop evidence, not production exactly-once.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
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
from . import metadata_fabric_spark_commit_failure_recovery as commit_failure
from . import metadata_fabric_spark_iceberg_rest_interoperability as spark_interop
from . import metadata_fabric_spark_object_store_interoperability as object_interop


PROFILE_SCHEMA = "gda.metadata_fabric_spark_uncertain_commit_reconciliation_profile.v1"
CONTRACT_SCHEMA = (
    "gda.metadata_fabric_spark_uncertain_commit_reconciliation_contract.v1"
)
OBSERVATION_SCHEMA = (
    "gda.metadata_fabric_spark_uncertain_commit_reconciliation_observation.v1"
)
EVIDENCE_SCHEMA = (
    "gda.metadata_fabric_spark_uncertain_commit_reconciliation_evidence.v1"
)
VALIDATION_SCHEMA = (
    "gda.metadata_fabric_spark_uncertain_commit_reconciliation_validation.v1"
)

CONTEXT = commit_failure.CONTEXT
SOURCE_NAMESPACE = commit_failure.SOURCE_NAMESPACE
REHEARSAL_NAMESPACE = commit_failure.REHEARSAL_NAMESPACE
OBJECT_STORE_NODE = commit_failure.OBJECT_STORE_NODE
COMPUTE_NODE = commit_failure.COMPUTE_NODE
DEPENDENCY_EVIDENCE_FINGERPRINT = (
    "39571cdac1e4043bcfc2d03a73b2b12ff925210daf8ae36bc640b8cb14d89401"
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = (
    REPO_ROOT
    / "config/metadata-fabric-spark-uncertain-commit-reconciliation.local.yaml"
)
DEFAULT_EVIDENCE_PATH = (
    REPO_ROOT
    / "docs/evidence/metadata-fabric-spark-uncertain-commit-reconciliation-2026-07-30.json"
)
DEFAULT_WRAPPER_PATH = (
    REPO_ROOT / "scripts/metadata-fabric-spark-uncertain-commit-reconciliation.sh"
)
DEFAULT_PROBE_PATH = (
    REPO_ROOT
    / "k8s/metadata-fabric-spark-uncertain-commit-reconciliation/probe.py"
)
BASE_MANIFEST_DIR = REPO_ROOT / "k8s/metadata-fabric-spark-commit-failure-recovery"

EXPECTED_OBSERVATION_KEYS = commit_failure.EXPECTED_OBSERVATION_KEYS
PRODUCTION_FALSE_CLAIMS = commit_failure.PRODUCTION_FALSE_CLAIMS


class MetadataFabricSparkUncertainCommitReconciliationError(RuntimeError):
    """The local uncertain-commit reconciliation contract failed closed."""


class DependencyProfile(object_interop._FrozenModel):
    evidence_path: Literal[
        "docs/evidence/metadata-fabric-spark-commit-failure-recovery-2026-07-29.json"
    ]
    evidence_fingerprint: Literal[DEPENDENCY_EVIDENCE_FINGERPRINT]
    required_claim: Literal["local_spark_commit_failure_recovery_verified"]


class ClaimProfile(object_interop._FrozenModel):
    local_spark_uncertain_commit_reconciliation_verified: Literal[False]
    local_provider_committed_response_loss_verified: Literal[False]
    local_commit_outcome_readback_verified: Literal[False]
    local_duplicate_resubmission_prevented: Literal[False]
    local_single_visible_commit_verified: Literal[False]
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


class SparkUncertainCommitReconciliationProfile(object_interop._FrozenModel):
    schema_name: Literal[PROFILE_SCHEMA] = Field(alias="schema")
    environment: Literal["local_docker_desktop"]
    cluster: commit_failure.ClusterProfile
    runtime: commit_failure.RuntimeProfile
    dependency: DependencyProfile
    identity: object_interop.IdentityProfile
    catalog: commit_failure.CatalogProfile
    scope: commit_failure.ScopeProfile
    claims: ClaimProfile


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _load_dependency(profile: SparkUncertainCommitReconciliationProfile) -> None:
    path = (REPO_ROOT / profile.dependency.evidence_path).resolve()
    try:
        path.relative_to(REPO_ROOT)
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MetadataFabricSparkUncertainCommitReconciliationError(
            "Spark commit-failure dependency is unavailable"
        ) from exc
    if not isinstance(value, dict):
        raise MetadataFabricSparkUncertainCommitReconciliationError(
            "Spark commit-failure dependency is not an object"
        )
    if (
        commit_failure.verify_evidence_integrity(value)
        or value.get("evidence_fingerprint")
        != profile.dependency.evidence_fingerprint
        or value.get(profile.dependency.required_claim) is not True
        or any(value.get(claim) is not False for claim in PRODUCTION_FALSE_CLAIMS)
    ):
        raise MetadataFabricSparkUncertainCommitReconciliationError(
            "Spark commit-failure dependency does not match"
        )


def load_profile(
    path: Path = DEFAULT_PROFILE_PATH,
) -> SparkUncertainCommitReconciliationProfile:
    try:
        raw = yaml.safe_load(path.resolve().read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TypeError("profile must be an object")
        ingestion_replay._reject_sensitive_fields(raw)
        profile = SparkUncertainCommitReconciliationProfile.model_validate(raw)
    except (OSError, TypeError, ValueError, ValidationError, yaml.YAMLError) as exc:
        raise MetadataFabricSparkUncertainCommitReconciliationError(
            f"Spark uncertain-commit profile is invalid: {type(exc).__name__}"
        ) from exc
    if (
        object_interop._profile_securable_objects(profile)
        != identity._expected_securable_objects()
    ):
        raise MetadataFabricSparkUncertainCommitReconciliationError(
            "Spark uncertain-commit role exceeds the bounded table-create scope"
        )
    _load_dependency(profile)
    return profile


def _validate_probe() -> list[str]:
    errors = list(commit_failure._validate_manifest())
    try:
        probe = DEFAULT_PROBE_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        return [
            *errors,
            f"Spark uncertain-commit probe is invalid: {type(exc).__name__}",
        ]
    for marker in (
        "post_forward_success_response_drop_http_504",
        "injected response loss after provider commit success",
        "committed_do_not_resubmit",
        '"write_resubmitted": False',
        '"provider_commit_forwarded": True',
        '"duplicate_resubmission_prevented": True',
        "GDA_SPARK_COMMIT_FAILURE_RESULT",
    ):
        if marker not in probe:
            errors.append(f"Spark uncertain-commit probe is missing marker: {marker}")
    if probe.count(".writeTo(TABLE)") != 2:
        errors.append("Spark uncertain-commit probe write boundary does not match")
    if "AWS_SECRET_ACCESS_KEY\"]" not in probe:
        errors.append("Spark uncertain-commit probe credential reference is missing")
    return errors


def build_contract_report(
    profile_path: Path = DEFAULT_PROFILE_PATH,
    wrapper_path: Path = DEFAULT_WRAPPER_PATH,
) -> dict[str, Any]:
    errors: list[str] = []
    profile: SparkUncertainCommitReconciliationProfile | None = None
    try:
        profile = load_profile(profile_path)
    except MetadataFabricSparkUncertainCommitReconciliationError as exc:
        errors.append(str(exc))
    errors.extend(_validate_probe())
    try:
        wrapper = wrapper_path.resolve().read_text(encoding="utf-8")
        for marker in (
            "set -euo pipefail",
            "metadata_fabric_spark_uncertain_commit_reconciliation",
        ):
            if marker not in wrapper:
                errors.append(f"Spark uncertain-commit wrapper is missing: {marker}")
    except OSError as exc:
        errors.append(f"Spark uncertain-commit wrapper is invalid: {type(exc).__name__}")

    paths = [
        Path(__file__).resolve(),
        profile_path.resolve(),
        wrapper_path.resolve(),
        DEFAULT_PROBE_PATH.resolve(),
        Path(commit_failure.__file__).resolve(),
    ]
    paths.extend(sorted(BASE_MANIFEST_DIR.glob("*.yaml")))
    files: dict[str, dict[str, str]] = {}
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
            "boundary": "iceberg_rest_table_commit_response",
            "mode": "post_forward_success_response_drop_http_504",
            "scope": "single_spark_driver_loopback_proxy",
            "provider_commit_forwarded": True,
            "provider_success_response_delivered": False,
        },
        "reconciliation": {
            "authority": "table_snapshot_row_and_file_readback",
            "committed_decision": "committed_do_not_resubmit",
            "write_resubmissions": 0,
        },
        "required_invariants": {
            "visible_snapshot_delta": 1,
            "visible_row_delta": 1,
            "visible_data_file_delta": 1,
            "provider_commit_forward_count": 1,
            "provider_success_response_drop_count": 1,
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
        },
        "local_static_contract_verified": not errors,
        "local_spark_uncertain_commit_reconciliation_verified": False,
        **{claim: False for claim in PRODUCTION_FALSE_CLAIMS},
        "files": files,
        "errors": errors,
    }
    return {**stable, "contract_fingerprint": recovery._canonical_sha256(stable)}


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
        errors.append("Spark uncertain-commit Job did not complete exactly once")
    if (
        pod.get("node_name") != COMPUTE_NODE
        or pod.get("service_account") != "spark-commit-failure-probe"
        or pod.get("service_account_automount_disabled") is not True
        or pod.get("persistent_volume_claims") != []
        or not str(pod.get("image_id") or "").endswith(
            commit_failure.SPARK_KUBERNETES_IMAGE_ID
        )
    ):
        errors.append("Spark uncertain-commit Pod boundary does not match")
    if (
        result.get("schema")
        != "gda.spark_uncertain_commit_reconciliation_probe_result.v1"
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
        errors.append("Spark uncertain-commit result envelope does not match")

    baseline = _mapping(result.get("baseline"))
    attempted = _mapping(result.get("uncertain_attempt"))
    reconciled = _mapping(result.get("reconciliation"))
    baseline_snapshots = _list(baseline.get("snapshots"))
    reconciled_snapshots = _list(reconciled.get("snapshots"))
    baseline_files = _list(baseline.get("data_file_paths"))
    reconciled_files = _list(reconciled.get("data_file_paths"))
    if (
        baseline.get("rows") != ["spark-baseline-a", "spark-baseline-b"]
        or len(baseline_snapshots) != 1
        or _mapping(baseline_snapshots[0]).get("parent_id") is not None
        or _mapping(baseline_snapshots[0]).get("operation") != "append"
        or len(baseline_files) != 1
    ):
        errors.append("Spark uncertain-commit baseline does not match")
    if (
        attempted.get("exception_observed") is not True
        or not isinstance(attempted.get("exception_type"), str)
        or not attempted.get("exception_type")
        or attempted.get("logical_row") != "spark-uncertain-commit"
    ):
        errors.append("Spark uncertain-commit attempt was not observed")
    if (
        len(reconciled_snapshots) != 2
        or _mapping(reconciled_snapshots[0]) != _mapping(baseline_snapshots[0])
        or _mapping(reconciled_snapshots[1]).get("parent_id")
        != _mapping(reconciled_snapshots[0]).get("snapshot_id")
        or [_mapping(item).get("operation") for item in reconciled_snapshots]
        != ["append", "append"]
        or reconciled.get("rows")
        != ["spark-baseline-a", "spark-baseline-b", "spark-uncertain-commit"]
        or len(reconciled_files) != 2
        or reconciled.get("decision") != "committed_do_not_resubmit"
        or reconciled.get("readback_attempts") != 1
        or reconciled.get("write_resubmitted") is not False
    ):
        errors.append("Spark uncertain commit was not reconciled from readback")
    proxy = _mapping(result.get("proxy"))
    if (
        proxy.get("forwarded_commit_requests") != 2
        or proxy.get("uncertain_commit_forwarded_requests") != 1
        or proxy.get("provider_success_responses_dropped") != 1
        or proxy.get("suppressed_duplicate_commit_requests") != 1
        or proxy.get("provider_success_status") != 200
        or not isinstance(proxy.get("total_requests"), int)
        or proxy.get("total_requests") < 3
        or proxy.get("injection_mode")
        != "post_forward_success_response_drop_http_504"
        or proxy.get("provider_commit_forwarded") is not True
        or proxy.get("loopback_only") is not True
    ):
        errors.append("Spark uncertain-commit proxy observation does not match")
    if (
        result.get("provider_committed_response_loss_verified") is not True
        or result.get("commit_outcome_readback_verified") is not True
        or result.get("duplicate_resubmission_prevented") is not True
        or result.get("single_visible_commit_verified") is not True
        or result.get("object_store_data_files_verified") is not True
    ):
        errors.append("Spark uncertain-commit local claims do not match")
    return errors


def _object_store_errors(
    prepared: Mapping[str, Any],
    store: Mapping[str, Any],
    spark: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    reconciled = _mapping(_mapping(spark.get("result")).get("reconciliation"))
    paths = _list(reconciled.get("data_file_paths"))
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
        errors.append("Uncertain-commit object-store inventory does not match")
    latest = _mapping(store.get("latest_metadata"))
    snapshots = _list(reconciled.get("snapshots"))
    expected_snapshot = (
        _mapping(snapshots[-1]).get("snapshot_id") if snapshots else None
    )
    if (
        latest.get("location")
        != "s3://gda-metadata-warehouse/warehouse/published/gda_spark_commit_failure_probe"
        or latest.get("current_snapshot_id") != expected_snapshot
        or latest.get("fields")
        != [{"name": "probe_id", "required": True, "type": "string"}]
    ):
        errors.append("Uncertain-commit Iceberg metadata projection does not match")
    return errors


def build_evidence(observation: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    try:
        ingestion_replay._reject_sensitive_fields(observation)
    except ValueError:
        errors.append("Spark uncertain-commit observation contains sensitive material")
    if set(observation) != EXPECTED_OBSERVATION_KEYS:
        errors.append("Spark uncertain-commit observation inventory does not match")
    if observation.get("schema") != OBSERVATION_SCHEMA:
        errors.append("Spark uncertain-commit observation schema does not match")
    contract = _mapping(observation.get("contract"))
    if (
        contract.get("local_static_contract_verified") is not True
        or not object_interop._valid_sha256(contract.get("contract_fingerprint"))
        or contract.get("dependency_evidence_fingerprint")
        != DEPENDENCY_EVIDENCE_FINGERPRINT
    ):
        errors.append("Spark uncertain-commit contract binding does not match")

    runtime = _mapping(observation.get("runtime"))
    runtime_errors = commit_failure._runtime_errors(runtime)
    errors.extend(runtime_errors)
    prepared = _mapping(observation.get("object_store_prepared"))
    pre_spark = _mapping(observation.get("pre_spark"))
    pre_table = _mapping(pre_spark.get("table"))
    expected_projection = commit_failure._expected_table_projection()
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
        errors.append("Gravitino pre-reconciliation boundary does not match")

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
        errors.append("Gravitino did not read back the reconciled table")

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
        errors.append("Spark uncertain-commit rehearsal cleanup is incomplete")

    result = _mapping(spark.get("result"))
    readback_verified = (
        not any("not reconciled" in error.lower() for error in spark_errors)
        and result.get("commit_outcome_readback_verified") is True
    )
    response_loss_verified = (
        not any("proxy observation" in error.lower() for error in spark_errors)
        and result.get("provider_committed_response_loss_verified") is True
    )
    duplicate_prevented = (
        readback_verified
        and _mapping(result.get("reconciliation")).get("write_resubmitted") is False
        and result.get("duplicate_resubmission_prevented") is True
    )
    single_visible_commit = (
        duplicate_prevented and result.get("single_visible_commit_verified") is True
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
        "local_spark_uncertain_commit_reconciliation_verified": verified,
        "local_provider_committed_response_loss_verified": response_loss_verified,
        "local_commit_outcome_readback_verified": readback_verified,
        "local_duplicate_resubmission_prevented": duplicate_prevented,
        "local_single_visible_commit_verified": single_visible_commit,
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
        errors.append("Spark uncertain-commit evidence fingerprint does not match")
    for key, expected in rebuilt.items():
        if key != "evidence_fingerprint" and evidence.get(key) != expected:
            errors.append(f"Spark uncertain-commit evidence field drift: {key}")
    for claim in PRODUCTION_FALSE_CLAIMS:
        if evidence.get(claim) is not False:
            errors.append(f"Spark uncertain-commit evidence may not claim {claim}")
    return errors


class IsolatedSparkUncertainCommitRuntime(
    commit_failure.IsolatedSparkCommitFailureRuntime
):
    """Reuse the frozen M3-12 runtime and replace only its suspended probe."""

    def start(
        self,
        *,
        admin_material: SecretStr,
        database_material: SecretStr,
        object_store_user: SecretStr,
        object_store_material: SecretStr,
    ) -> dict[str, Any]:
        observed = super().start(
            admin_material=admin_material,
            database_material=database_material,
            object_store_user=object_store_user,
            object_store_material=object_store_material,
        )
        try:
            probe = DEFAULT_PROBE_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            raise MetadataFabricSparkUncertainCommitReconciliationError(
                "Spark uncertain-commit probe is unavailable"
            ) from exc
        patch = json.dumps({"data": {"probe.py": probe}}, ensure_ascii=True)
        self.kubectl.run(
            [
                "-n",
                self.profile.cluster.rehearsal_namespace,
                "patch",
                "configmap",
                self.profile.runtime.spark_job,
                "--type=merge",
                "-p",
                patch,
            ],
            label="Spark uncertain-commit suspended probe patch",
        )
        return observed


def run_live_rehearsal(
    profile_path: Path = DEFAULT_PROFILE_PATH,
) -> dict[str, Any]:
    profile = load_profile(profile_path)
    contract = build_contract_report(profile_path)
    if contract.get("local_static_contract_verified") is not True:
        raise MetadataFabricSparkUncertainCommitReconciliationError(
            "Spark uncertain-commit static contract is invalid"
        )

    admin_material = SecretStr(secrets.token_urlsafe(24))
    database_material = SecretStr(secrets.token_urlsafe(24))
    user_material = SecretStr(secrets.token_urlsafe(24))
    object_store_user = SecretStr("gda" + secrets.token_hex(8))
    object_store_material = SecretStr(secrets.token_urlsafe(32))
    runtime = IsolatedSparkUncertainCommitRuntime(profile)
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
        raise MetadataFabricSparkUncertainCommitReconciliationError(
            "Spark uncertain-commit rehearsal did not produce an outcome"
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
            errors.append("Spark uncertain-commit evidence contract fingerprint drift")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"Spark uncertain-commit evidence is invalid: {type(exc).__name__}")
    verified = not errors
    local_claims = (
        "local_spark_uncertain_commit_reconciliation_verified",
        "local_provider_committed_response_loss_verified",
        "local_commit_outcome_readback_verified",
        "local_duplicate_resubmission_prevented",
        "local_single_visible_commit_verified",
        "gravitino_api_metadata_readback_verified",
        "local_cross_node_object_store_verified",
        "object_store_metadata_verified",
    )
    return {
        "schema": VALIDATION_SCHEMA,
        "local_static_contract_verified": contract["local_static_contract_verified"],
        **{
            claim: (
                verified and evidence is not None and evidence.get(claim) is True
            )
            for claim in local_claims
        },
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
        commit_failure.MetadataFabricSparkCommitFailureRecoveryError,
        MetadataFabricSparkUncertainCommitReconciliationError,
        KeyboardInterrupt,
    ) as exc:
        print(f"metadata fabric Spark uncertain-commit reconciliation: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
