"""Verify restart recovery of the retained M3-24 real-feature authority chain.

M3-25 attaches to the exact retained namespace, PVC-backed JDBC/S3 Iceberg
runtime and dedicated GDA Control PostgreSQL database recorded by M3-24. It
does not ingest again or create a new authority record. Instead, it records a
read-only baseline, restarts every retained stateful process in dependency
order, and requires byte-stable material, catalog and ledger readback before
an exact terminal replay.

This is a bounded local process-restart rehearsal. It does not prove backup
restore, point-in-time recovery, independent failure domains or production
readiness.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import create_engine, text

from . import metadata_fabric_object_store_active_metadata_promotion as m321
from . import metadata_fabric_retained_real_feature_terminal_success as m324
from . import metadata_fabric_spark_object_store_interoperability as m310
from .platform_contracts import RunStatus, canonical_json_fingerprint
from .platform_gateway import PlatformGateway

CONTRACT_SCHEMA = "gda.retained_real_feature_restart_recovery_contract.v1"
OBSERVATION_SCHEMA = "gda.retained_real_feature_restart_recovery_observation.v1"
EVIDENCE_SCHEMA = "gda.retained_real_feature_restart_recovery_evidence.v1"
VALIDATION_SCHEMA = "gda.retained_real_feature_restart_recovery_validation.v1"
SOURCE_EVIDENCE_SHA256 = "d966668b5a2ea57c7a4b2a3bc9824daab9b0128d9f94e515d7be649b145de418"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_EVIDENCE_PATH = m324.DEFAULT_EVIDENCE_PATH
DEFAULT_EVIDENCE_PATH = (
    REPO_ROOT
    / "docs/evidence/metadata-fabric-retained-real-feature-restart-recovery-2026-07-31.json"
)
DEFAULT_WRAPPER_PATH = (
    REPO_ROOT / "scripts/metadata-fabric-retained-real-feature-restart-recovery.sh"
)
PROVIDER_OBSERVATION_ID = UUID("85bead83-1901-5649-b6e4-fe46d01c9ea9")
EXPECTED_LEDGER_COUNTS = {
    "artifacts": 5,
    "execution_plans": 1,
    "policy_decisions": 1,
    "approvals": 1,
    "evaluator_evidence": 1,
    "attempts": 2,
    "quality_results": 1,
    "lineage_events": 1,
    "run_events": 4,
}
FALSE_CLAIMS = (
    "source_dataset_committed",
    "source_absolute_path_committed",
    "source_feature_payload_committed",
    "new_ingestion_executed",
    "new_authority_facts_created",
    "persistent_scheduler_verified",
    "protected_workload_identity_verified",
    "durable_catalog_verified",
    "production_object_store_verified",
    "production_scheduler_verified",
    "production_ingestion_verified",
    "production_tenant_attestation_verified",
    "backup_restore_verified",
    "point_in_time_recovery_verified",
    "independent_failure_domains_verified",
    "production_restart_recovery_verified",
    "oidc_verified",
    "tls_verified",
    "production_ready",
)


class RetainedRealFeatureRestartRecoveryError(RuntimeError):
    """The retained real-feature restart/recovery gate failed closed."""


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("JSON document must be an object")
    return value


def _file_record(path: Path) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
        relative = str(path.resolve().relative_to(REPO_ROOT))
    except (OSError, ValueError):
        return {"path": None, "size_bytes": None, "sha256": None}
    return {
        "path": relative,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _run_command(args: list[str], *, label: str, timeout: float = 180) -> str:
    try:
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RetainedRealFeatureRestartRecoveryError(f"{label} is unavailable") from exc
    if completed.returncode != 0:
        raise RetainedRealFeatureRestartRecoveryError(f"{label} failed")
    return completed.stdout.strip()


def _checked_source_evidence(
    path: Path = DEFAULT_SOURCE_EVIDENCE_PATH,
) -> dict[str, Any]:
    evidence = _load_json_object(path)
    errors = m324.validate_evidence(evidence)
    if errors or evidence.get("evidence_sha256") != SOURCE_EVIDENCE_SHA256:
        raise RetainedRealFeatureRestartRecoveryError(
            "checked M3-24 evidence is unavailable or drifted"
        )
    return evidence


def build_contract_report() -> dict[str, Any]:
    errors: list[str] = []
    files = {
        "restart_recovery": _file_record(Path(__file__).resolve()),
        "wrapper": _file_record(DEFAULT_WRAPPER_PATH),
        "terminal_success": _file_record(Path(m324.__file__).resolve()),
        "terminal_success_evidence": _file_record(DEFAULT_SOURCE_EVIDENCE_PATH),
    }
    try:
        _checked_source_evidence()
    except (OSError, TypeError, ValueError, RetainedRealFeatureRestartRecoveryError):
        errors.append("M3-24 checked evidence is unavailable")
    if files["wrapper"]["sha256"] is None:
        errors.append("M3-25 wrapper is unavailable")
    stable = {
        "schema": CONTRACT_SCHEMA,
        "source_evidence_sha256": SOURCE_EVIDENCE_SHA256,
        "files": files,
        "requires_same_retention_identity": True,
        "requires_ordered_stateful_restart": True,
        "requires_stable_namespace_statefulset_service_pvc_identity": True,
        "requires_kubernetes_pod_rotation": True,
        "requires_control_container_and_volume_identity": True,
        "requires_control_process_rotation": True,
        "requires_iceberg_snapshot_and_object_continuity": True,
        "requires_independent_parquet_re_evaluation": True,
        "requires_gravitino_table_readback": True,
        "requires_control_ledger_fingerprint_continuity": True,
        "requires_exact_terminal_replay_without_new_facts": True,
        "creates_new_resource_version_or_run": False,
        "retained_local_restart_is_production_recovery": False,
        "writes_to_legacy": False,
        "errors": errors,
    }
    return {
        **stable,
        "status": "valid" if not errors else "invalid",
        "contract_sha256": canonical_json_fingerprint(stable),
        **{claim: False for claim in FALSE_CLAIMS},
    }


def _decode_runtime_material(secret: Mapping[str, Any], key: str, *, label: str) -> SecretStr:
    encoded = _mapping(secret.get("data")).get(key)
    if not isinstance(encoded, str) or not encoded:
        raise RetainedRealFeatureRestartRecoveryError(f"{label} runtime material is unavailable")
    try:
        value = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise RetainedRealFeatureRestartRecoveryError(
            f"{label} runtime material is invalid"
        ) from exc
    if not value:
        raise RetainedRealFeatureRestartRecoveryError(f"{label} runtime material is empty")
    return SecretStr(value)


def _read_runtime_materials(
    runtime: m310.IsolatedSparkObjectStoreRuntime,
) -> tuple[SecretStr, SecretStr, SecretStr, SecretStr]:
    namespace = runtime.profile.cluster.rehearsal_namespace
    catalog = runtime.kubectl.get_json(
        [
            "-n",
            namespace,
            "get",
            "secret",
            "gravitino-persistence-runtime",
        ],
        label="retained catalog runtime material lookup",
    )
    object_store = runtime.kubectl.get_json(
        [
            "-n",
            namespace,
            "get",
            "secret",
            "metadata-object-store-runtime",
        ],
        label="retained object-store runtime material lookup",
    )
    if catalog is None or object_store is None:
        raise RetainedRealFeatureRestartRecoveryError(
            "retained runtime material objects are unavailable"
        )
    return (
        _decode_runtime_material(catalog, "admin-password", label="catalog admin"),
        _decode_runtime_material(catalog, "database-password", label="catalog database"),
        _decode_runtime_material(object_store, "access-key-id", label="object store user"),
        _decode_runtime_material(
            object_store, "secret-access-key", label="object store credential"
        ),
    )


def _extract_control_password(environment: Any) -> SecretStr:
    if not isinstance(environment, list):
        raise RetainedRealFeatureRestartRecoveryError("retained control environment is invalid")
    values = [
        item.removeprefix("POSTGRES_PASSWORD=")
        for item in environment
        if isinstance(item, str) and item.startswith("POSTGRES_PASSWORD=")
    ]
    if len(values) != 1 or not values[0]:
        raise RetainedRealFeatureRestartRecoveryError(
            "retained control database credential is unavailable"
        )
    return SecretStr(values[0])


class RetainedControlAttachment:
    """Attach to and restart the identity-bound M3-24 control database."""

    def __init__(
        self,
        source: Mapping[str, Any],
        retention: m324.RetainedMaterialObservation,
    ) -> None:
        recorded = _mapping(source.get("control_database"))
        self.container_name = str(recorded.get("container_name") or "")
        self.volume_name = str(recorded.get("volume_name") or "")
        self.host_port = int(recorded.get("host_port") or 0)
        self.retention_id = retention.retention_id
        self.expires_at = retention.expires_at
        expected_container = f"gda-m3-24-control-{self.retention_id.removeprefix('m3-24-')[:24]}"
        if (
            self.container_name != expected_container
            or self.volume_name != self.container_name
            or self.host_port <= 0
            or recorded.get("database_ref") != self.database_ref
        ):
            raise RetainedRealFeatureRestartRecoveryError(
                "retained control database identity does not match M3-24 evidence"
            )
        environment = json.loads(
            _run_command(
                [
                    "docker",
                    "container",
                    "inspect",
                    self.container_name,
                    "--format",
                    "{{json .Config.Env}}",
                ],
                label="retained control database environment lookup",
            )
        )
        self.password = _extract_control_password(environment)

    @property
    def database_ref(self) -> str:
        return f"docker:{self.container_name}/postgres"

    @property
    def database_url(self) -> str:
        return (
            "postgresql://postgres:"
            f"{self.password.get_secret_value()}@127.0.0.1:{self.host_port}/postgres"
        )

    def observe(self) -> dict[str, Any]:
        state = json.loads(
            _run_command(
                [
                    "docker",
                    "container",
                    "inspect",
                    self.container_name,
                    "--format",
                    "{{json .State}}",
                ],
                label="retained control database state lookup",
            )
        )
        container_id = _run_command(
            [
                "docker",
                "container",
                "inspect",
                self.container_name,
                "--format",
                "{{.Id}}",
            ],
            label="retained control container identity lookup",
        )
        labels = json.loads(
            _run_command(
                [
                    "docker",
                    "container",
                    "inspect",
                    self.container_name,
                    "--format",
                    "{{json .Config.Labels}}",
                ],
                label="retained control container labels lookup",
            )
        )
        mounts = json.loads(
            _run_command(
                [
                    "docker",
                    "container",
                    "inspect",
                    self.container_name,
                    "--format",
                    "{{json .Mounts}}",
                ],
                label="retained control container mounts lookup",
            )
        )
        volume = json.loads(
            _run_command(
                [
                    "docker",
                    "volume",
                    "inspect",
                    self.volume_name,
                    "--format",
                    "{{json .}}",
                ],
                label="retained control volume lookup",
            )
        )
        volume_labels = _mapping(volume).get("Labels")
        expected_expiry = self.expires_at.isoformat().replace("+00:00", "Z")
        expected_labels = {
            "gda.retention-id": self.retention_id,
            "gda.owner": "team:metadata-platform",
            "gda.expires-at": expected_expiry,
        }
        volume_mounts = [
            _mapping(item)
            for item in mounts
            if _mapping(item).get("Type") == "volume"
            and _mapping(item).get("Destination") == "/var/lib/postgresql/data"
        ]
        if (
            not isinstance(labels, dict)
            or any(labels.get(key) != value for key, value in expected_labels.items())
            or not isinstance(volume_labels, dict)
            or any(volume_labels.get(key) != value for key, value in expected_labels.items())
            or len(volume_mounts) != 1
            or volume_mounts[0].get("Name") != self.volume_name
        ):
            raise RetainedRealFeatureRestartRecoveryError(
                "retained control ownership or volume binding drifted"
            )
        return {
            "database_ref": self.database_ref,
            "container_name": self.container_name,
            "container_id": container_id,
            "container_running": state.get("Running") is True,
            "container_status": state.get("Status"),
            "process_id": state.get("Pid"),
            "started_at": state.get("StartedAt"),
            "volume_name": self.volume_name,
            "volume_retained": isinstance(volume, dict),
            "host_port": self.host_port,
            "retention_id": self.retention_id,
            "owner": "team:metadata-platform",
            "expires_at": expected_expiry,
            "credential_material_recorded": False,
        }

    def wait_ready(self, timeout_seconds: float = 120) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            engine = create_engine(self.database_url, pool_pre_ping=True)
            try:
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1")).scalar_one()
                return
            except Exception:
                time.sleep(1)
            finally:
                engine.dispose()
        raise RetainedRealFeatureRestartRecoveryError("retained control database did not recover")

    def restart(self) -> dict[str, Any]:
        before = self.observe()
        _run_command(
            ["docker", "restart", self.container_name],
            label="retained control database restart",
            timeout=180,
        )
        self.wait_ready()
        return {"before": before, "after": self.observe()}


def _attach_runtime(
    source: Mapping[str, Any],
) -> tuple[
    m310.IsolatedSparkObjectStoreRuntime,
    m324.m322.RealFeatureIngestionProfile,
]:
    profile = m324.m322.load_profile()
    _, runtime_profile = m324.m322._load_dependencies(profile)
    runtime = m310.IsolatedSparkObjectStoreRuntime(runtime_profile)
    runtime.gravitino_host_image_id = runtime._inspect_host_image(
        runtime_profile.runtime.gravitino_image,
        runtime_profile.runtime.gravitino_host_image_id,
        "Gravitino",
    )
    runtime.spark_host_image_id = runtime._inspect_host_image(
        runtime_profile.runtime.spark_image,
        runtime_profile.runtime.spark_host_image_id,
        "Spark",
    )
    runtime.minio_host_image_id = runtime._inspect_host_image(
        runtime_profile.runtime.minio_image,
        runtime_profile.runtime.minio_host_image_id,
        "MinIO",
    )
    namespace = runtime_profile.cluster.rehearsal_namespace
    schema_object = runtime.kubectl.get_json(
        [
            "-n",
            namespace,
            "get",
            "configmap",
            "gravitino-persistence-schema",
        ],
        label="retained catalog schema lookup",
    )
    schema_sql = _mapping(_mapping(schema_object).get("data")).get("001-schema.sql")
    if not isinstance(schema_sql, str):
        raise RetainedRealFeatureRestartRecoveryError("retained catalog schema is unavailable")
    runtime.schema_sha256 = hashlib.sha256(schema_sql.encode()).hexdigest()
    expected_schema = _mapping(source.get("initial_runtime")).get("source_schema_sha256")
    if runtime.schema_sha256 != expected_schema:
        raise RetainedRealFeatureRestartRecoveryError("retained catalog schema fingerprint drifted")
    return runtime, profile


def _observe_runtime(
    runtime: m310.IsolatedSparkObjectStoreRuntime,
) -> dict[str, Any]:
    observed = runtime.observe_runtime()
    namespace = runtime.profile.cluster.rehearsal_namespace
    service = runtime.kubectl.get_json(
        [
            "-n",
            namespace,
            "get",
            "service",
            "gravitino-persistence-postgresql",
        ],
        label="retained PostgreSQL service observation",
    )
    if service is None:
        raise RetainedRealFeatureRestartRecoveryError("retained PostgreSQL service is unavailable")
    return {
        **observed,
        "postgresql_service": runtime._service_projection(service),
    }


def _runtime_stable_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        key: value.get(key)
        for key in (
            "context",
            "gravitino_host_image_id",
            "spark_host_image_id",
            "minio_host_image_id",
            "namespace",
            "service",
            "object_store_service",
            "postgresql_service",
            "iceberg_rest",
            "gravitino_jdbc_driver_mounted",
            "gravitino_aws_sdk_mounted",
            "source_schema_sha256",
        )
        if key in value
    }
    for name in ("postgresql", "object_store", "gravitino"):
        workload = _mapping(value.get(name))
        result[name] = {key: nested for key, nested in workload.items() if key not in {"pod_uid"}}
    return result


def _valid_uuid(value: Any) -> bool:
    try:
        UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True


def _runtime_continuity_errors(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    predecessor: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    before_stable = _runtime_stable_projection(before)
    after_stable = _runtime_stable_projection(after)
    predecessor_stable = _runtime_stable_projection(predecessor)
    before_without_new_service = {
        key: value for key, value in before_stable.items() if key != "postgresql_service"
    }
    if before_stable != after_stable:
        errors.append("retained Kubernetes stable runtime identity changed")
    if before_without_new_service != predecessor_stable:
        errors.append("retained Kubernetes runtime no longer binds M3-24")
    for service_name in (
        "service",
        "object_store_service",
        "postgresql_service",
    ):
        old = _mapping(before.get(service_name))
        new = _mapping(after.get(service_name))
        if not _valid_uuid(old.get("uid")) or old != new:
            errors.append(f"{service_name} identity changed")
    for workload_name in ("postgresql", "object_store", "gravitino"):
        old = _mapping(before.get(workload_name))
        new = _mapping(after.get(workload_name))
        if not _valid_uuid(old.get("statefulset_uid")) or old.get("statefulset_uid") != new.get(
            "statefulset_uid"
        ):
            errors.append(f"{workload_name} StatefulSet identity changed")
        if (
            not _valid_uuid(old.get("pod_uid"))
            or not _valid_uuid(new.get("pod_uid"))
            or old.get("pod_uid") == new.get("pod_uid")
        ):
            errors.append(f"{workload_name} pod did not rotate")
        if old.get("ready_replicas") != 1 or new.get("ready_replicas") != 1:
            errors.append(f"{workload_name} was not ready around restart")
        old_pvc = old.get("pvc")
        new_pvc = new.get("pvc")
        if old_pvc != new_pvc:
            errors.append(f"{workload_name} PVC identity changed")
        if isinstance(old_pvc, Mapping) and _mapping(old_pvc).get("phase") != "Bound":
            errors.append(f"{workload_name} PVC is not bound")
    return errors


def _restart_kubernetes_runtime(
    runtime: m310.IsolatedSparkObjectStoreRuntime,
    before: Mapping[str, Any],
) -> dict[str, Any]:
    namespace = runtime.profile.cluster.rehearsal_namespace
    order = (
        "statefulset/gravitino-persistence-postgresql",
        "statefulset/metadata-object-store",
        "statefulset/gravitino-persistence",
    )
    for workload in order:
        runtime.kubectl.run(
            ["-n", namespace, "rollout", "restart", workload],
            label=f"M3-25 {workload} restart",
        )
        runtime.kubectl.run(
            ["-n", namespace, "rollout", "status", workload, "--timeout=10m"],
            timeout=660,
            label=f"M3-25 {workload} restart rollout",
        )
    return {
        "order": list(order),
        "before": dict(before),
        "after": _observe_runtime(runtime),
    }


def _control_continuity_errors(restart: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    before = _mapping(restart.get("before"))
    after = _mapping(restart.get("after"))
    for key in (
        "database_ref",
        "container_name",
        "container_id",
        "volume_name",
        "host_port",
        "retention_id",
        "owner",
        "expires_at",
    ):
        if before.get(key) != after.get(key):
            errors.append(f"retained control identity changed: {key}")
    if (
        before.get("container_running") is not True
        or after.get("container_running") is not True
        or before.get("volume_retained") is not True
        or after.get("volume_retained") is not True
    ):
        errors.append("retained control database was not ready around restart")
    if (
        not isinstance(before.get("process_id"), int)
        or not isinstance(after.get("process_id"), int)
        or before.get("process_id") == after.get("process_id")
    ):
        errors.append("retained control PostgreSQL process did not rotate")
    if not before.get("started_at") or before.get("started_at") == after.get("started_at"):
        errors.append("retained control PostgreSQL start time did not rotate")
    return errors


def _source_payload_absent(
    runtime: m310.IsolatedSparkObjectStoreRuntime,
) -> bool:
    value = runtime.kubectl.get_json(
        [
            "-n",
            runtime.profile.cluster.rehearsal_namespace,
            "get",
            "configmap",
            "real-feature-ingestion-input",
        ],
        allow_not_found=True,
        label="retained source payload absence probe",
    )
    return value is None


def _start_forward(
    runtime: m310.IsolatedSparkObjectStoreRuntime,
    *,
    service: str,
    target_port: int,
) -> Any:
    forward = m321.provider_metrics._PortForward(
        kubectl="kubectl",
        context=runtime.profile.cluster.context,
        namespace=runtime.profile.cluster.rehearsal_namespace,
        service=service,
        target_port=target_port,
    )
    forward.start()
    return forward


def _material_projection(store: Mapping[str, Any]) -> dict[str, Any]:
    latest = _mapping(store.get("latest_metadata"))
    return {
        "object_count": store.get("object_count"),
        "object_inventory_sha256": store.get("object_inventory_sha256"),
        "data_file_count": len(store.get("data_keys") or []),
        "metadata_file_count": len(store.get("metadata_keys") or []),
        "manifest_file_count": len(store.get("manifest_keys") or []),
        "metadata_body_sha256": latest.get("body_sha256"),
        "snapshot_id": latest.get("current_snapshot_id"),
        "schema_id": latest.get("current_schema_id"),
        "table_location": latest.get("location"),
        "fields": latest.get("fields"),
    }


def _gravitino_readback(
    rehearsal: m321.ObjectStoreProjectionRehearsal,
    profile: m324.m322.RealFeatureIngestionProfile,
) -> dict[str, Any]:
    status, payload = rehearsal.admin.request(
        "GET",
        rehearsal._table_path(profile.target),
        label="M3-25 retained Gravitino table readback",
    )
    projection = m321.durable._table_projection(_mapping(payload))
    return {
        "read_status": status,
        "table_projection_sha256": canonical_json_fingerprint(projection),
        "table_projection": projection,
    }


def _authority_counts(engine: Any) -> dict[str, int]:
    with engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    """
                SELECT
                  (SELECT count(*) FROM gda_control.resource
                   WHERE tenant_id = :tenant_id) AS resources,
                  (SELECT count(*) FROM gda_control.resource_version
                   WHERE tenant_id = :tenant_id) AS resource_versions,
                  (SELECT count(*) FROM gda_control.platform_definition_version
                   WHERE tenant_id = :tenant_id) AS definition_versions,
                  (SELECT count(*) FROM gda_control.platform_run
                   WHERE tenant_id = :tenant_id) AS platform_runs
                """
                ),
                {"tenant_id": m324.TENANT},
            )
            .mappings()
            .one()
        )
    return {key: int(value) for key, value in row.items()}


def _observe_control_ledger(
    engine: Any,
    gateway: PlatformGateway,
    source: Mapping[str, Any],
    promotion: m324.m323.RunOutputLedgerPromotion,
) -> tuple[dict[str, Any], Any, Any]:
    authorization = _mapping(source.get("authorization"))
    artifact_ids = (
        UUID(str(authorization["execution_plan_artifact_id"])),
        UUID(str(authorization["policy_decision_artifact_id"])),
        UUID(str(authorization["approval_artifact_id"])),
        promotion.output_artifact.artifact_id,
        promotion.quality_evidence_artifact.artifact_id,
    )
    run = gateway.get_run(m324.TENANT, m324.RUN_ID)
    with gateway._transaction(m324.TENANT) as connection:
        observation = gateway._load_observation(connection, m324.TENANT, PROVIDER_OBSERVATION_ID)
        output_version = gateway._load_resource_version(
            connection, m324.TENANT, m324.OUTPUT_RESOURCE_VERSION_ID
        )
        artifacts = [
            gateway._load_artifact(connection, m324.TENANT, artifact_id)
            for artifact_id in artifact_ids
        ]
        quality = gateway._load_quality_result(
            connection,
            m324.TENANT,
            promotion.quality_result.quality_result_id,
        )
        lineage = gateway._load_lineage(
            connection,
            m324.TENANT,
            promotion.lineage_event.lineage_event_id,
        )
    facts = [run, observation, output_version, *artifacts, quality, lineage]
    if any(value is None for value in facts):
        raise RetainedRealFeatureRestartRecoveryError("retained control ledger is incomplete")
    stable_facts = [value.model_dump(mode="json", by_alias=True) for value in facts]
    return (
        {
            "ledger_counts": m324._ledger_counts(engine),
            "authority_counts": _authority_counts(engine),
            "facts_sha256": canonical_json_fingerprint(stable_facts),
            "platform_run_status": run.status.value,
            "platform_run_state_version": run.state_version,
            "provider_observation_id": str(observation.observation_id),
            "provider_observation_sha256": observation.observation_sha256,
        },
        run,
        observation,
    )


def _material_errors(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    retention: m324.RetainedMaterialObservation,
) -> list[str]:
    errors: list[str] = []
    if dict(before) != dict(after):
        errors.append("retained Iceberg material changed across restart")
    expected = {
        "object_inventory_sha256": retention.object_inventory_sha256,
        "data_file_count": retention.data_file_count,
        "metadata_body_sha256": retention.metadata_body_sha256,
        "snapshot_id": retention.snapshot_id,
        "table_location": retention.storage_uri,
    }
    if any(before.get(key) != value for key, value in expected.items()):
        errors.append("retained Iceberg material no longer binds M3-24")
    return errors


def build_evidence(observation: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    contract = build_contract_report()
    if observation.get("schema") != OBSERVATION_SCHEMA:
        errors.append("M3-25 observation schema does not match")
    if observation.get("contract_sha256") != contract.get("contract_sha256"):
        errors.append("M3-25 observation contract binding is stale")
    if observation.get("source_evidence_sha256") != SOURCE_EVIDENCE_SHA256:
        errors.append("M3-25 predecessor evidence binding drifted")
    restart = _mapping(observation.get("kubernetes_restart"))
    errors.extend(
        _runtime_continuity_errors(
            _mapping(restart.get("before")),
            _mapping(restart.get("after")),
            _mapping(observation.get("m324_initial_runtime")),
        )
    )
    errors.extend(_control_continuity_errors(_mapping(observation.get("control_restart"))))
    retention = m324.RetainedMaterialObservation.model_validate(
        observation.get("retention_observation")
    )
    material = _mapping(observation.get("material"))
    errors.extend(
        _material_errors(
            _mapping(material.get("before")),
            _mapping(material.get("after")),
            retention,
        )
    )
    independent = _mapping(observation.get("independent_quality"))
    if independent.get("before") != independent.get("after") or independent.get(
        "after"
    ) != observation.get("m324_independent_quality"):
        errors.append("independent Parquet quality changed across restart")
    gravitino = _mapping(observation.get("gravitino"))
    if (
        gravitino.get("before") != gravitino.get("after")
        or _mapping(gravitino.get("after")).get("read_status") != 200
    ):
        errors.append("Gravitino table readback changed across restart")
    ledger = _mapping(observation.get("control_ledger"))
    if not (
        ledger.get("before") == ledger.get("after_restart") == ledger.get("after_terminal_replay")
    ):
        errors.append("GDA Control ledger changed across restart or replay")
    before_ledger = _mapping(ledger.get("before"))
    if (
        before_ledger.get("ledger_counts") != EXPECTED_LEDGER_COUNTS
        or before_ledger.get("platform_run_status") != "succeeded"
        or before_ledger.get("platform_run_state_version") != 3
        or before_ledger.get("provider_observation_id") != str(PROVIDER_OBSERVATION_ID)
    ):
        errors.append("GDA Control terminal authority no longer matches M3-24")
    replay = _mapping(observation.get("terminal_replay"))
    if (
        replay.get("promotion_created") is not False
        or replay.get("platform_run_status") != "succeeded"
        or replay.get("platform_run_state_version") != 3
    ):
        errors.append("post-restart terminal replay was not an exact no-op")
    for claim in (
        "source_payload_absent_before",
        "source_payload_absent_after",
        "credential_material_recorded",
        "runtime_port_forwards_stopped",
    ):
        expected = False if claim == "credential_material_recorded" else True
        if observation.get(claim) is not expected:
            errors.append(f"M3-25 observation boundary failed: {claim}")
    stable = {
        "schema": EVIDENCE_SCHEMA,
        "status": (
            "local_retained_real_feature_restart_recovery_verified" if not errors else "blocked"
        ),
        "contract_sha256": contract["contract_sha256"],
        "source_evidence_sha256": SOURCE_EVIDENCE_SHA256,
        "retention_id": retention.retention_id,
        "retention_expires_at": retention.expires_at.isoformat().replace("+00:00", "Z"),
        "tenant_id": m324.TENANT,
        "run_id": str(m324.RUN_ID),
        "output_resource_version_id": str(m324.OUTPUT_RESOURCE_VERSION_ID),
        "output_content_sha256": retention.output_content_sha256,
        "kubernetes_restart": restart,
        "control_restart": observation.get("control_restart"),
        "material": material,
        "gravitino": gravitino,
        "independent_quality": independent,
        "control_ledger": ledger,
        "terminal_replay": replay,
        "source_payload_absent_before": observation.get("source_payload_absent_before"),
        "source_payload_absent_after": observation.get("source_payload_absent_after"),
        "credential_material_recorded": False,
        "runtime_port_forwards_stopped": observation.get("runtime_port_forwards_stopped"),
        "same_retention_identity_verified": not errors,
        "ordered_stateful_restart_verified": not errors,
        "kubernetes_runtime_restart_verified": not errors,
        "control_database_restart_verified": not errors,
        "iceberg_material_continuity_verified": not errors,
        "gravitino_catalog_continuity_verified": not errors,
        "independent_quality_continuity_verified": not errors,
        "control_ledger_continuity_verified": not errors,
        "exact_terminal_replay_after_restart_verified": not errors,
        "local_retained_real_feature_restart_recovery_verified": not errors,
        "writes_to_legacy": False,
        **{claim: False for claim in FALSE_CLAIMS},
        "errors": errors,
    }
    return {**stable, "evidence_sha256": canonical_json_fingerprint(stable)}


def validate_evidence(evidence: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    stable = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        errors.append("M3-25 evidence schema does not match")
    if evidence.get("evidence_sha256") != canonical_json_fingerprint(stable):
        errors.append("M3-25 evidence fingerprint does not match")
    contract = build_contract_report()
    if evidence.get("contract_sha256") != contract.get("contract_sha256"):
        errors.append("M3-25 contract binding is stale")
    if evidence.get("source_evidence_sha256") != SOURCE_EVIDENCE_SHA256:
        errors.append("M3-25 source evidence binding drifted")
    for claim in (
        "same_retention_identity_verified",
        "ordered_stateful_restart_verified",
        "kubernetes_runtime_restart_verified",
        "control_database_restart_verified",
        "iceberg_material_continuity_verified",
        "gravitino_catalog_continuity_verified",
        "independent_quality_continuity_verified",
        "control_ledger_continuity_verified",
        "exact_terminal_replay_after_restart_verified",
        "local_retained_real_feature_restart_recovery_verified",
        "source_payload_absent_before",
        "source_payload_absent_after",
        "runtime_port_forwards_stopped",
    ):
        if evidence.get(claim) is not True:
            errors.append(f"M3-25 evidence claim is false: {claim}")
    if evidence.get("credential_material_recorded") is not False:
        errors.append("M3-25 evidence records credential material")
    for claim in FALSE_CLAIMS:
        if evidence.get(claim) is not False:
            errors.append(f"M3-25 evidence may not claim {claim}")
    serialized = json.dumps(evidence, ensure_ascii=True, sort_keys=True).lower()
    for forbidden in (
        "/users/",
        "/home/",
        "downloads/",
        ".tmp/",
        "geometry_wkb_hex",
        '"rows"',
        "postgres_password",
        "password=",
        '"password"',
        '"secret"',
        '"token"',
        '"access_key"',
        '"access-key"',
    ):
        if forbidden in serialized:
            errors.append("M3-25 evidence contains local, source, or credential material")
            break
    return errors


def build_validation_report(*, evidence_path: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    contract = build_contract_report()
    errors = list(contract["errors"])
    evidence: dict[str, Any] | None = None
    try:
        evidence = _load_json_object(evidence_path)
        errors.extend(validate_evidence(evidence))
    except (OSError, TypeError, ValueError, RetainedRealFeatureRestartRecoveryError):
        errors.append("M3-25 checked evidence is unavailable")
    return {
        "schema": VALIDATION_SCHEMA,
        "status": "valid" if not errors else "invalid",
        "contract_sha256": contract["contract_sha256"],
        "evidence_sha256": evidence.get("evidence_sha256") if evidence else None,
        "errors": errors,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_live_rehearsal() -> dict[str, Any]:
    contract = build_contract_report()
    if contract.get("status") != "valid":
        raise RetainedRealFeatureRestartRecoveryError("M3-25 static contract is invalid")
    source = _checked_source_evidence()
    retention = m324.RetainedMaterialObservation.model_validate(source.get("retention_observation"))
    if datetime.now(UTC) >= retention.expires_at:
        raise RetainedRealFeatureRestartRecoveryError("M3-24 retained material has expired")
    runtime, profile = _attach_runtime(source)
    admin_material, database_material, object_store_user, object_store_material = (
        _read_runtime_materials(runtime)
    )
    if not database_material.get_secret_value():
        raise RetainedRealFeatureRestartRecoveryError("retained catalog database material is empty")
    control = RetainedControlAttachment(source, retention)
    checked_ingestion = _load_json_object(m324.DEFAULT_SOURCE_EVIDENCE_PATH)
    plan = m324.m322.RealFeatureIngestionPlan.model_validate(
        _mapping(checked_ingestion.get("observation")).get("plan")
    )
    promotion = m324.build_terminal_promotion(checked_ingestion, retention)
    before_runtime = _observe_runtime(runtime)
    if _mapping(before_runtime.get("namespace")).get("uid") != retention.namespace_uid:
        raise RetainedRealFeatureRestartRecoveryError(
            "retained namespace identity no longer matches M3-24"
        )
    source_absent_before = _source_payload_absent(runtime)
    before_control = control.observe()
    control.wait_ready()

    object_forward: Any = None
    gravitino_forward: Any = None
    rehearsal: m321.ObjectStoreProjectionRehearsal | None = None
    engine: Any = None
    all_forwards_stopped = True
    try:
        object_forward = _start_forward(
            runtime,
            service=runtime.profile.runtime.object_store_service,
            target_port=runtime.profile.runtime.object_store_service_port,
        )
        gravitino_forward = _start_forward(
            runtime,
            service=runtime.profile.runtime.service,
            target_port=runtime.profile.runtime.gravitino_service_port,
        )
        endpoint_url = f"http://127.0.0.1:{object_forward.local_port}"
        rehearsal = m321.ObjectStoreProjectionRehearsal(
            base_url=f"http://127.0.0.1:{gravitino_forward.local_port}/api",
            admin_name=profile.identity.service_admin,
            admin_material=admin_material,
        )
        before_store = m324.m322.observe_ingested_table(
            runtime,
            profile,
            endpoint_url=endpoint_url,
            object_store_user=object_store_user,
            object_store_material=object_store_material,
        )
        before_material = _material_projection(before_store)
        before_quality = m324.independently_evaluate_retained_parquet(
            runtime,
            profile,
            plan,
            {"projection": source["source_projection"]},
            before_store,
            endpoint_url=endpoint_url,
            object_store_user=object_store_user,
            object_store_material=object_store_material,
        )
        before_gravitino = _gravitino_readback(rehearsal, profile)
        engine = create_engine(control.database_url, pool_pre_ping=True)
        gateway = PlatformGateway(engine)
        before_ledger, before_run, _ = _observe_control_ledger(engine, gateway, source, promotion)
        if before_run.status != RunStatus.SUCCEEDED or before_run.state_version != 3:
            raise RetainedRealFeatureRestartRecoveryError("retained PlatformRun is not succeeded@3")
        engine.dispose()
        engine = None
        rehearsal.close()
        rehearsal = None
        all_forwards_stopped = bool(gravitino_forward.stop()) and all_forwards_stopped
        gravitino_forward = None
        all_forwards_stopped = bool(object_forward.stop()) and all_forwards_stopped
        object_forward = None

        kubernetes_restart = _restart_kubernetes_runtime(runtime, before_runtime)
        control_restart = control.restart()
        if control_restart.get("before") != before_control:
            raise RetainedRealFeatureRestartRecoveryError(
                "control database changed before the scheduled restart"
            )
        after_runtime = _mapping(kubernetes_restart.get("after"))
        source_absent_after = _source_payload_absent(runtime)

        object_forward = _start_forward(
            runtime,
            service=runtime.profile.runtime.object_store_service,
            target_port=runtime.profile.runtime.object_store_service_port,
        )
        gravitino_forward = _start_forward(
            runtime,
            service=runtime.profile.runtime.service,
            target_port=runtime.profile.runtime.gravitino_service_port,
        )
        endpoint_url = f"http://127.0.0.1:{object_forward.local_port}"
        rehearsal = m321.ObjectStoreProjectionRehearsal(
            base_url=f"http://127.0.0.1:{gravitino_forward.local_port}/api",
            admin_name=profile.identity.service_admin,
            admin_material=admin_material,
        )
        after_store = m324.m322.observe_ingested_table(
            runtime,
            profile,
            endpoint_url=endpoint_url,
            object_store_user=object_store_user,
            object_store_material=object_store_material,
        )
        after_material = _material_projection(after_store)
        after_quality = m324.independently_evaluate_retained_parquet(
            runtime,
            profile,
            plan,
            {"projection": source["source_projection"]},
            after_store,
            endpoint_url=endpoint_url,
            object_store_user=object_store_user,
            object_store_material=object_store_material,
        )
        after_gravitino = _gravitino_readback(rehearsal, profile)
        engine = create_engine(control.database_url, pool_pre_ping=True)
        gateway = PlatformGateway(engine)
        after_restart_ledger, _, observation = _observe_control_ledger(
            engine, gateway, source, promotion
        )

        def live_probe(observed: m324.RetainedMaterialObservation) -> bool:
            return m324._live_material_probe(
                observed,
                runtime=runtime,
                profile=profile,
                control=control,
                endpoint_url=endpoint_url,
                object_store_user=object_store_user,
                object_store_material=object_store_material,
            )

        coordinator = m324.RetainedTerminalSuccessCoordinator(gateway, material_probe=live_probe)
        replay_promotion, replayed_run = coordinator.finalize(
            promotion,
            retention,
            observation,
        )
        after_replay_ledger, _, _ = _observe_control_ledger(engine, gateway, source, promotion)
        raw_observation = {
            "schema": OBSERVATION_SCHEMA,
            "observed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "contract_sha256": contract["contract_sha256"],
            "source_evidence_sha256": SOURCE_EVIDENCE_SHA256,
            "retention_observation": retention.model_dump(mode="json", by_alias=True),
            "m324_initial_runtime": source["initial_runtime"],
            "m324_independent_quality": source["independent_quality"],
            "kubernetes_restart": {
                "order": kubernetes_restart["order"],
                "before": before_runtime,
                "after": after_runtime,
            },
            "control_restart": control_restart,
            "material": {"before": before_material, "after": after_material},
            "gravitino": {
                "before": before_gravitino,
                "after": after_gravitino,
            },
            "independent_quality": {
                "before": before_quality,
                "after": after_quality,
            },
            "control_ledger": {
                "before": before_ledger,
                "after_restart": after_restart_ledger,
                "after_terminal_replay": after_replay_ledger,
            },
            "terminal_replay": {
                "promotion_created": replay_promotion.created,
                "platform_run_status": replayed_run.status.value,
                "platform_run_state_version": replayed_run.state_version,
            },
            "source_payload_absent_before": source_absent_before,
            "source_payload_absent_after": source_absent_after,
            "credential_material_recorded": False,
            "runtime_port_forwards_stopped": False,
        }
    finally:
        if engine is not None:
            engine.dispose()
        if rehearsal is not None:
            rehearsal.close()
        if gravitino_forward is not None:
            all_forwards_stopped = bool(gravitino_forward.stop()) and all_forwards_stopped
        if object_forward is not None:
            all_forwards_stopped = bool(object_forward.stop()) and all_forwards_stopped
    raw_observation["runtime_port_forwards_stopped"] = all_forwards_stopped
    evidence = build_evidence(raw_observation)
    errors = validate_evidence(evidence)
    if errors:
        raise RetainedRealFeatureRestartRecoveryError(
            "M3-25 live evidence failed self-validation: " + "; ".join(errors)
        )
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("contract")
    validate = subparsers.add_parser("validate")
    validate.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE_PATH)
    live = subparsers.add_parser("live-rehearsal")
    live.add_argument("--output", type=Path, default=DEFAULT_EVIDENCE_PATH)
    args = parser.parse_args(argv)
    if args.command == "contract":
        report = build_contract_report()
    elif args.command == "validate":
        report = build_validation_report(evidence_path=args.evidence)
    else:
        report = run_live_rehearsal()
        _write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return (
        0
        if report["status"]
        in {
            "valid",
            "local_retained_real_feature_restart_recovery_verified",
        }
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
