"""Isolated Spark, Iceberg, MinIO, and PostgreSQL lakehouse rehearsal."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import boto3
import httpx
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError
from pydantic import Field, model_validator
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from .cross_store_projection_authority import PostgresProjectionCheckpointAuthority
from .cross_store_projection_consistency import (
    ProjectionDesiredState,
    ProjectionEngine,
    build_projection_repair_plan,
)
from .lakehouse_projection_executor import (
    LakehouseProjectionRepairExecutor,
    LakehouseProjectionTarget,
    LakehouseProjectionTargetRegistry,
    lakehouse_records_from_artifact,
)
from .lakehouse_projection_service import (
    LakehouseProjectionRepairRequest,
    LakehouseProjectionServiceConflictError,
    execute_lakehouse_projection_repair,
)
from .lakehouse_projection_spark_provider import DockerSparkIcebergProjectionProvider
from .platform_contracts import FrozenContract, canonical_json_fingerprint

_MIGRATIONS = (
    "092_platform_control_ledger.sql",
    "094_platform_control_gateway.sql",
    "169_cross_store_projection_checkpoint_authority.sql",
)
_DEFAULT_MINIO_IMAGE = "minio/minio:RELEASE.2025-04-22T22-12-26Z"
_DEFAULT_SPARK_IMAGE = "gisdataagent/mmfe-spark-runtime:local"
_DEFAULT_BUNDLE = (
    Path(__file__).resolve().parent / "demo_data" / "natural_resource_ontology_customer_v1"
)
_ARTIFACT_NAME = "heping_changed_parcels.geojson"
_BUNDLE_ID = "natural-resource-ontology-customer-demo-v1"
_BUNDLE_VERSION = "1.0.0"
_ONTOLOGY_PACKAGE_ID = "natural-resource-one-map:2.3.0:587915868b1221af"
_ONTOLOGY_PACKAGE_SHA256 = "587915868b1221af2315508ede7bf7babced063cba8b261de2f10afa23841019"


class LakehouseProjectionExecutorRehearsalReport(FrozenContract):
    schema_id: str = "gda.lakehouse-projection-executor-rehearsal.v2"
    checked_at: datetime
    database_scope: str = "temporary_database_only"
    lakehouse_scope: str = "temporary_network_container_volume_bucket_and_table_only"
    atomicity_scope: str = "iceberg_commit_and_checkpoint_authority_not_distributed_atomic"
    minio_image: str
    minio_image_id: str
    spark_image: str
    spark_image_id: str
    migration_ids: tuple[str, ...]
    bundle_id: str
    bundle_version: str
    artifact_name: str
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_size_bytes: int = Field(ge=1)
    table_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_count: int = Field(ge=1)
    distinct_parcel_count: int = Field(ge=1)
    ontology_package_id: str
    ontology_package_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checks: dict[str, bool]
    passed: bool
    failure_reasons: tuple[str, ...]
    technical_baseline_status: str = "technical_baseline_unreviewed"
    decision_status: str = "assisted_precheck_not_for_production_decision"
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _hash(self) -> LakehouseProjectionExecutorRehearsalReport:
        payload = self.model_dump(mode="json")
        expected = canonical_json_fingerprint(
            {key: value for key, value in payload.items() if key != "report_sha256"}
        )
        if self.report_sha256 != expected:
            raise ValueError("lakehouse rehearsal report fingerprint is invalid")
        return self


class _TemporaryPostgres:
    def __init__(self, admin_url: str) -> None:
        parsed = make_url(admin_url)
        self.maintenance_url = parsed.set(database=parsed.database or "postgres")
        self.database = f"gda_lakehouse_exec_{uuid4().hex[:12]}"
        self.admin_engine: Engine | None = None
        self.engine: Engine | None = None

    def create(self) -> None:
        self.admin_engine = create_engine(self.maintenance_url, isolation_level="AUTOCOMMIT")
        with self.admin_engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{self.database}"')
        self.engine = create_engine(self.maintenance_url.set(database=self.database))
        for filename in _MIGRATIONS:
            migration = Path(__file__).resolve().parent / "migrations" / filename
            with self.engine.begin() as connection:
                connection.exec_driver_sql(migration.read_text(encoding="utf-8").replace("%", "%%"))

    def drop_and_verify(self) -> bool:
        if self.engine is not None:
            self.engine.dispose()
        verifier = self.admin_engine or create_engine(
            self.maintenance_url, isolation_level="AUTOCOMMIT"
        )
        try:
            with verifier.connect() as connection:
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :database AND pid <> pg_backend_pid()"
                    ),
                    {"database": self.database},
                )
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{self.database}"')
                remaining = connection.execute(
                    text("SELECT count(*) FROM pg_database WHERE datname = :database"),
                    {"database": self.database},
                ).scalar_one()
            return remaining == 0
        finally:
            verifier.dispose()


class _TemporaryLakehouse:
    def __init__(self, minio_image: str) -> None:
        suffix = uuid4().hex[:12]
        self.minio_image = minio_image
        self.network = f"gda-lakehouse-exec-{suffix}"
        self.container = f"gda-lakehouse-minio-{suffix}"
        self.volume = f"gda-lakehouse-exec-{suffix}"
        self.bucket = f"gda-lakehouse-{suffix}"
        self.access_key = "gda_lakehouse"
        self.secret_key = f"gda-lakehouse-{uuid4().hex}"
        self.host_endpoint: str | None = None
        self.container_endpoint = f"http://{self.container}:9000"
        self.client: Any | None = None
        self.minio_image_id = ""

    @staticmethod
    def _docker(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ("docker", *arguments),
            check=check,
            capture_output=True,
            text=True,
            timeout=180,
        )

    def start(self) -> None:
        self.minio_image_id = self._docker(
            "image", "inspect", self.minio_image, "--format", "{{.Id}}"
        ).stdout.strip()
        self._docker("network", "create", self.network)
        self._docker("volume", "create", self.volume)
        self._docker(
            "run",
            "--detach",
            "--rm",
            "--name",
            self.container,
            "--network",
            self.network,
            "--publish",
            "127.0.0.1::9000",
            "--mount",
            f"type=volume,source={self.volume},target=/data",
            "--env",
            f"MINIO_ROOT_USER={self.access_key}",
            "--env",
            f"MINIO_ROOT_PASSWORD={self.secret_key}",
            self.minio_image,
            "server",
            "/data",
            "--address",
            ":9000",
        )
        port = self._docker("port", self.container, "9000/tcp").stdout.strip()
        self.host_endpoint = f"http://127.0.0.1:{port.rsplit(':', 1)[-1]}"
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                response = httpx.get(f"{self.host_endpoint}/minio/health/ready", timeout=2)
                if response.is_success:
                    self.client = boto3.client(
                        "s3",
                        endpoint_url=self.host_endpoint,
                        region_name="us-east-1",
                        aws_access_key_id=self.access_key,
                        aws_secret_access_key=self.secret_key,
                        config=BotoConfig(s3={"addressing_style": "path"}),
                    )
                    self.client.create_bucket(Bucket=self.bucket)
                    return
            except Exception:
                pass
            time.sleep(0.5)
        logs = self._docker("logs", self.container, check=False).stdout[-4000:]
        raise RuntimeError(f"isolated MinIO did not become ready: {logs}")

    def delete_bucket_and_verify(self) -> bool:
        if self.client is None:
            return False
        while True:
            response = self.client.list_objects_v2(Bucket=self.bucket)
            objects = [{"Key": item["Key"]} for item in response.get("Contents", [])]
            if not objects:
                break
            self.client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": objects, "Quiet": True},
            )
        self.client.delete_bucket(Bucket=self.bucket)
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            return str(exc.response.get("Error", {}).get("Code")) in {"404", "NoSuchBucket"}
        return False

    def stop_and_verify(self) -> tuple[bool, bool, bool]:
        self._docker("rm", "--force", self.container, check=False)
        container_absent = (
            self._docker("container", "inspect", self.container, check=False).returncode != 0
        )
        self._docker("volume", "rm", self.volume, check=False)
        volume_absent = self._docker("volume", "inspect", self.volume, check=False).returncode != 0
        self._docker("network", "rm", self.network, check=False)
        network_absent = (
            self._docker("network", "inspect", self.network, check=False).returncode != 0
        )
        return container_absent, volume_absent, network_absent


def _request(plan: Any) -> LakehouseProjectionRepairRequest:
    return LakehouseProjectionRepairRequest(
        plan=plan,
        checkpointed_by="workload:lakehouse-rehearsal",
    )


def _target(bundle: Path, lakehouse: _TemporaryLakehouse) -> LakehouseProjectionTarget:
    manifest = bundle / "manifest.json"
    artifact = bundle / _ARTIFACT_NAME
    records, content_sha256 = lakehouse_records_from_artifact(artifact)
    artifact_bytes = artifact.read_bytes()
    return LakehouseProjectionTarget(
        tenant_id="cq-lakehouse-rehearsal",
        projection_id="cq.customer.heping_changed_parcels_lakehouse",
        target_ref="iceberg://lakehouse/cq_customer/heping_changed_parcels",
        catalog="lakehouse",
        namespace="cq_customer",
        table="heping_changed_parcels",
        warehouse_uri=f"s3://{lakehouse.bucket}/warehouse",
        endpoint_url=lakehouse.container_endpoint,
        region_name="us-east-1",
        bucket=lakehouse.bucket,
        bundle_manifest_path=str(manifest),
        bundle_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
        bundle_id=_BUNDLE_ID,
        bundle_version=_BUNDLE_VERSION,
        artifact_path=str(artifact),
        artifact_name=artifact.name,
        artifact_sha256=hashlib.sha256(artifact_bytes).hexdigest(),
        artifact_size_bytes=len(artifact_bytes),
        expected_table_content_sha256=content_sha256,
        expected_row_count=len(records),
        ontology_package_id=_ONTOLOGY_PACKAGE_ID,
        ontology_package_content_sha256=_ONTOLOGY_PACKAGE_SHA256,
    )


def _desired(
    target: LakehouseProjectionTarget,
    *,
    source_sha256: str,
    source_version: str,
    exists: bool = True,
) -> ProjectionDesiredState:
    return ProjectionDesiredState(
        tenant_id=target.tenant_id,
        projection_id=target.projection_id,
        source_resource_version_ref=(f"gda://{target.tenant_id}/customer-bundle/{source_version}"),
        source_content_sha256=source_sha256,
        target_engine=ProjectionEngine.LAKEHOUSE,
        target_ref=target.target_ref,
        target_exists=exists,
        expected_target_content_sha256=(target.expected_table_content_sha256 if exists else None),
        expected_row_count=target.expected_row_count if exists else 0,
    )


def run_rehearsal(
    admin_url: str,
    *,
    minio_image: str = _DEFAULT_MINIO_IMAGE,
    spark_image: str = _DEFAULT_SPARK_IMAGE,
    bundle_dir: Path = _DEFAULT_BUNDLE,
) -> LakehouseProjectionExecutorRehearsalReport:
    checked_at = datetime.now(UTC)
    checks: dict[str, bool] = {}
    failures: list[str] = []
    postgres = _TemporaryPostgres(admin_url)
    lakehouse = _TemporaryLakehouse(minio_image)
    spark_image_id = ""
    target: LakehouseProjectionTarget | None = None
    artifact_sha256 = "0" * 64
    artifact_size_bytes = 0
    table_content_sha256 = "0" * 64
    feature_count = 0
    distinct_parcel_count = 0
    try:
        postgres.create()
        lakehouse.start()
        spark_image_id = lakehouse._docker(
            "image", "inspect", spark_image, "--format", "{{.Id}}"
        ).stdout.strip()
        assert postgres.engine is not None
        target = _target(bundle_dir, lakehouse)
        artifact_sha256 = target.artifact_sha256
        artifact_size_bytes = target.artifact_size_bytes
        table_content_sha256 = target.expected_table_content_sha256
        feature_count = target.expected_row_count
        records, _ = lakehouse_records_from_artifact(target.artifact_path)
        distinct_parcel_count = len({record["parcel_id"] for record in records})
        checks["customer_feature_and_parcel_cardinality_preserved"] = (
            feature_count == 445 and distinct_parcel_count == 439
        )
        provider = DockerSparkIcebergProjectionProvider(
            repository_root=Path(__file__).resolve().parents[1],
            image=spark_image,
            docker_network=lakehouse.network,
            access_key_id=lakehouse.access_key,
            secret_access_key=lakehouse.secret_key,
            java_home="/usr/lib/jvm/java-17-openjdk-arm64",
            timeout_seconds=900,
        )
        executor = LakehouseProjectionRepairExecutor(
            LakehouseProjectionTargetRegistry((target,)), provider=provider
        )
        authority = PostgresProjectionCheckpointAuthority(postgres.engine)
        initial = executor.observe(target)
        rebuild = build_projection_repair_plan(
            _desired(
                target,
                source_sha256=target.artifact_sha256,
                source_version=target.bundle_version,
            ),
            initial,
            None,
        )
        committed_before_authority = executor.execute(rebuild)
        restarted_executor = LakehouseProjectionRepairExecutor(
            LakehouseProjectionTargetRegistry((target,)), provider=provider
        )
        first_result = execute_lakehouse_projection_repair(
            _request(rebuild), executor=restarted_executor, authority=authority
        )
        first = first_result.receipt
        checks["rebuild_materializes_customer_rows_and_snapshot"] = (
            committed_before_authority.status == "completed"
            and first.target_content_sha256 == target.expected_table_content_sha256
            and first.target_row_count == target.expected_row_count
            and first.snapshot_id is not None
        )
        checks["rebuild_snapshot_receipt_recovers_after_authority_gap"] = (
            first.status == "replayed"
            and first.snapshot_id == committed_before_authority.snapshot_id
            and first.provider_commit_ref.get("receipt_sha256")
            == committed_before_authority.provider_commit_ref.get("receipt_sha256")
        )
        checks["rebuild_receipt_automatically_checkpointed"] = (
            first_result.checkpoint_created
            and first_result.checkpoint.checkpoint_version == 1
            and first.provider_commit_ref.get("provider") == "spark_iceberg"
            and first_result.checkpoint.target_commit_ref == first.provider_commit_ref
        )
        replay = execute_lakehouse_projection_repair(
            _request(rebuild), executor=executor, authority=authority
        )
        checks["rebuild_replay_is_idempotent"] = (
            replay.status == "replayed"
            and not replay.checkpoint_created
            and replay.checkpoint == first_result.checkpoint
        )

        drift = provider.replace(
            target,
            records,
            plan_sha256="a" * 64,
            idempotency_key="b" * 64,
        )
        checks["same_content_rebuild_creates_new_snapshot"] = (
            drift.snapshot_id is not None and drift.snapshot_id != first.snapshot_id
        )
        try:
            execute_lakehouse_projection_repair(
                _request(rebuild), executor=executor, authority=authority
            )
        except LakehouseProjectionServiceConflictError:
            checks["checkpoint_replay_rejects_same_content_new_snapshot"] = True
        else:
            checks["checkpoint_replay_rejects_same_content_new_snapshot"] = False

        post = executor.observe(target)
        checkpoint_plan = build_projection_repair_plan(
            _desired(
                target,
                source_sha256="c" * 64,
                source_version="checkpoint-2",
            ),
            post,
            first_result.checkpoint,
        )
        checkpoint_result = execute_lakehouse_projection_repair(
            _request(checkpoint_plan), executor=executor, authority=authority
        )
        checks["checkpoint_action_rechecks_without_rebuild"] = (
            checkpoint_result.receipt.status == "checkpointed"
            and checkpoint_result.receipt.snapshot_id == drift.snapshot_id
            and checkpoint_result.checkpoint.checkpoint_version == 2
        )

        stale_plan = build_projection_repair_plan(
            _desired(target, source_sha256="d" * 64, source_version="stale"),
            initial,
            None,
        )
        before_stale = executor.observe(target)
        try:
            execute_lakehouse_projection_repair(
                _request(stale_plan), executor=executor, authority=authority
            )
        except LakehouseProjectionServiceConflictError:
            after_stale = executor.observe(target)
            checks["stale_predecessor_rejected_before_provider_mutation"] = (
                before_stale.observed_content_sha256 == after_stale.observed_content_sha256
                and before_stale.observed_row_count == after_stale.observed_row_count
            )
        else:
            checks["stale_predecessor_rejected_before_provider_mutation"] = False

        delete_plan = build_projection_repair_plan(
            _desired(
                target,
                source_sha256="e" * 64,
                source_version="deleted",
                exists=False,
            ),
            post,
            checkpoint_result.checkpoint,
        )
        provider_delete = provider.drop(
            target,
            plan_sha256=delete_plan.plan_sha256,
            idempotency_key=delete_plan.plan_idempotency_key,
        )
        delete_result = execute_lakehouse_projection_repair(
            _request(delete_plan), executor=executor, authority=authority
        )
        deleted = delete_result.receipt
        checks["delete_side_effect_recovers_after_authority_gap"] = (
            deleted.status == "replayed"
            and not deleted.target_exists
            and deleted.deleted_snapshot_id == drift.snapshot_id
            and deleted.drop_evidence_sha256 is not None
            and deleted.deleted_snapshot_id == provider_delete.deleted_snapshot_id
            and deleted.drop_evidence_sha256 == provider_delete.drop_evidence_sha256
        )
        checks["delete_receipt_automatically_checkpointed"] = (
            delete_result.checkpoint_created
            and delete_result.checkpoint.checkpoint_version == 3
            and not delete_result.checkpoint.target_exists
        )
        delete_replay = execute_lakehouse_projection_repair(
            _request(delete_plan), executor=executor, authority=authority
        )
        checks["delete_replay_is_idempotent"] = (
            delete_replay.status == "replayed"
            and not delete_replay.checkpoint_created
            and delete_replay.checkpoint == delete_result.checkpoint
        )
        history = authority.history(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_engine=ProjectionEngine.LAKEHOUSE,
            target_ref=target.target_ref,
        )
        checks["checkpoint_history_is_append_only_and_sequential"] = (
            tuple(item.checkpoint_version for item in history) == (1, 2, 3)
            and history[0].checkpoint_sha256 == first_result.checkpoint.checkpoint_sha256
            and history[1].checkpoint_sha256 == checkpoint_result.checkpoint.checkpoint_sha256
            and history[2].checkpoint_sha256 == delete_result.checkpoint.checkpoint_sha256
        )
    except Exception as exc:  # pragma: no cover - external runtime surfaced in report
        failures.append(f"{type(exc).__name__}: {exc}")
    finally:
        try:
            checks["temporary_lakehouse_bucket_removed"] = lakehouse.delete_bucket_and_verify()
        except Exception as exc:  # pragma: no cover
            checks["temporary_lakehouse_bucket_removed"] = False
            failures.append(f"LakehouseBucketCleanupError: {exc}")
        try:
            container_removed, volume_removed, network_removed = lakehouse.stop_and_verify()
        except Exception as exc:  # pragma: no cover
            container_removed = False
            volume_removed = False
            network_removed = False
            failures.append(f"LakehouseCleanupError: {exc}")
        try:
            database_removed = postgres.drop_and_verify()
        except Exception as exc:  # pragma: no cover
            database_removed = False
            failures.append(f"PostgresCleanupError: {exc}")
        checks["temporary_minio_container_removed"] = container_removed
        checks["temporary_minio_volume_removed"] = volume_removed
        checks["temporary_docker_network_removed"] = network_removed
        checks["temporary_checkpoint_database_removed"] = database_removed

    failures.extend(key for key, value in checks.items() if not value)
    if target is None:
        artifact = bundle_dir / _ARTIFACT_NAME
        records, table_content_sha256 = lakehouse_records_from_artifact(artifact)
        artifact_bytes = artifact.read_bytes()
        artifact_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
        artifact_size_bytes = len(artifact_bytes)
        feature_count = len(records)
        distinct_parcel_count = len({record["parcel_id"] for record in records})
    payload = {
        "schema_id": "gda.lakehouse-projection-executor-rehearsal.v2",
        "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
        "database_scope": "temporary_database_only",
        "lakehouse_scope": "temporary_network_container_volume_bucket_and_table_only",
        "atomicity_scope": (
            "iceberg_rebuild_snapshot_receipt_single_commit_delete_tombstone_and_"
            "checkpoint_not_distributed_atomic"
        ),
        "minio_image": minio_image,
        "minio_image_id": lakehouse.minio_image_id or "unavailable",
        "spark_image": spark_image,
        "spark_image_id": spark_image_id or "unavailable",
        "migration_ids": _MIGRATIONS,
        "bundle_id": _BUNDLE_ID,
        "bundle_version": _BUNDLE_VERSION,
        "artifact_name": _ARTIFACT_NAME,
        "artifact_sha256": artifact_sha256,
        "artifact_size_bytes": artifact_size_bytes,
        "table_content_sha256": table_content_sha256,
        "feature_count": feature_count,
        "distinct_parcel_count": distinct_parcel_count,
        "ontology_package_id": _ONTOLOGY_PACKAGE_ID,
        "ontology_package_content_sha256": _ONTOLOGY_PACKAGE_SHA256,
        "checks": checks,
        "passed": not failures and bool(checks),
        "failure_reasons": tuple(sorted(set(failures))),
        "technical_baseline_status": "technical_baseline_unreviewed",
        "decision_status": "assisted_precheck_not_for_production_decision",
    }
    return LakehouseProjectionExecutorRehearsalReport(
        **payload,
        report_sha256=canonical_json_fingerprint(payload),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--admin-url", default="postgresql://postgres:postgres@localhost:5433/gis_agent"
    )
    parser.add_argument("--minio-image", default=_DEFAULT_MINIO_IMAGE)
    parser.add_argument("--spark-image", default=_DEFAULT_SPARK_IMAGE)
    parser.add_argument("--bundle-dir", type=Path, default=_DEFAULT_BUNDLE)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = run_rehearsal(
        args.admin_url,
        minio_image=args.minio_image,
        spark_image=args.spark_image,
        bundle_dir=args.bundle_dir,
    )
    document = json.dumps(
        report.model_dump(mode="json"), ensure_ascii=True, indent=2, sort_keys=True
    )
    print(document)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(document + "\n", encoding="utf-8")
    if not report.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
