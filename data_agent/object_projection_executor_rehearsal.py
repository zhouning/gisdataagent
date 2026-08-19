"""Isolated MinIO and PostgreSQL rehearsal for object projection repair."""

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
from botocore.exceptions import ClientError
from pydantic import Field, model_validator
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from .cross_store_projection_authority import (
    PostgresProjectionCheckpointAuthority,
    ProjectionCheckpointAuthorityConfigurationError,
)
from .cross_store_projection_consistency import (
    ProjectionDesiredState,
    ProjectionEngine,
    build_projection_repair_plan,
)
from .object_projection_executor import (
    ObjectProjectionRepairExecutor,
    ObjectProjectionTarget,
    ObjectProjectionTargetRegistry,
)
from .object_projection_service import (
    ObjectProjectionRepairRequest,
    ObjectProjectionServiceConfigurationError,
    ObjectProjectionServiceConflictError,
    execute_object_projection_repair,
)
from .platform_contracts import FrozenContract, canonical_json_fingerprint

_MIGRATIONS = (
    "092_platform_control_ledger.sql",
    "094_platform_control_gateway.sql",
    "169_cross_store_projection_checkpoint_authority.sql",
)
_DEFAULT_IMAGE = "minio/minio:RELEASE.2025-04-22T22-12-26Z"
_DEFAULT_BUNDLE = (
    Path(__file__).resolve().parent / "demo_data" / "natural_resource_ontology_customer_v1"
)
_ARTIFACT_NAME = "heping_changed_parcels.geojson"
_BUNDLE_ID = "natural-resource-ontology-customer-demo-v1"
_BUNDLE_VERSION = "1.0.0"
_ONTOLOGY_PACKAGE_ID = "natural-resource-one-map:2.3.0:587915868b1221af"
_ONTOLOGY_PACKAGE_SHA256 = "587915868b1221af2315508ede7bf7babced063cba8b261de2f10afa23841019"


class ObjectProjectionExecutorRehearsalReport(FrozenContract):
    schema_id: str = "gda.object-projection-executor-rehearsal.v2"
    checked_at: datetime
    database_scope: str = "temporary_database_only"
    object_store_scope: str = "temporary_container_volume_and_bucket_only"
    atomicity_scope: str = (
        "rebuild_payload_and_receipt_metadata_single_put_delete_intent_and_marker_separate_"
        "checkpoint_authority_separate"
    )
    minio_image: str
    minio_image_id: str
    migration_ids: tuple[str, ...]
    bundle_id: str
    bundle_version: str
    artifact_name: str
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_size_bytes: int = Field(ge=1)
    ontology_package_id: str
    ontology_package_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checks: dict[str, bool]
    passed: bool
    failure_reasons: tuple[str, ...]
    technical_baseline_status: str = "technical_baseline_unreviewed"
    decision_status: str = "assisted_precheck_not_for_production_decision"
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _hash(self) -> ObjectProjectionExecutorRehearsalReport:
        payload = self.model_dump(mode="json")
        expected = canonical_json_fingerprint(
            {key: value for key, value in payload.items() if key != "report_sha256"}
        )
        if self.report_sha256 != expected:
            raise ValueError("object projection rehearsal report fingerprint is invalid")
        return self


class _TemporaryPostgres:
    def __init__(self, admin_url: str) -> None:
        parsed = make_url(admin_url)
        self.maintenance_url = parsed.set(database=parsed.database or "postgres")
        self.database = f"gda_object_exec_{uuid4().hex[:12]}"
        self.admin_engine: Engine | None = None
        self.engine: Engine | None = None

    def create(self) -> None:
        self.admin_engine = create_engine(
            self.maintenance_url,
            isolation_level="AUTOCOMMIT",
        )
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
            self.maintenance_url,
            isolation_level="AUTOCOMMIT",
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


class _FailOnceRecordAuthority:
    def __init__(self, delegate: PostgresProjectionCheckpointAuthority) -> None:
        self.delegate = delegate
        self.failed = False

    def current(self, **identity):
        return self.delegate.current(**identity)

    def history(self, **identity):
        return self.delegate.history(**identity)

    def record(self, checkpoint, *, previous_checkpoint_sha256=None):
        if not self.failed:
            self.failed = True
            raise ProjectionCheckpointAuthorityConfigurationError(
                "simulated checkpoint authority outage"
            )
        return self.delegate.record(
            checkpoint,
            previous_checkpoint_sha256=previous_checkpoint_sha256,
        )


class _TemporaryMinio:
    def __init__(self, image: str) -> None:
        suffix = uuid4().hex[:12]
        self.image = image
        self.container = f"gda-object-exec-{suffix}"
        self.volume = f"gda-object-exec-{suffix}"
        self.bucket = f"gda-object-rehearsal-{suffix}"
        self.endpoint: str | None = None
        self.image_id = ""
        self.access_key = "gda_rehearsal"
        self.secret_key = f"gda-rehearsal-{uuid4().hex}"
        self.client: Any | None = None

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
        image = self._docker("image", "inspect", self.image, "--format", "{{.Id}}")
        self.image_id = image.stdout.strip()
        self._docker("volume", "create", self.volume)
        self._docker(
            "run",
            "--detach",
            "--rm",
            "--name",
            self.container,
            "--publish",
            "127.0.0.1::9000",
            "--mount",
            f"type=volume,source={self.volume},target=/data",
            "--env",
            f"MINIO_ROOT_USER={self.access_key}",
            "--env",
            f"MINIO_ROOT_PASSWORD={self.secret_key}",
            self.image,
            "server",
            "/data",
            "--address",
            ":9000",
        )
        port = self._docker("port", self.container, "9000/tcp").stdout.strip()
        host_port = port.rsplit(":", 1)[-1]
        self.endpoint = f"http://127.0.0.1:{host_port}"
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                response = httpx.get(f"{self.endpoint}/minio/health/ready", timeout=2)
                if response.is_success:
                    self.client = boto3.client(
                        "s3",
                        endpoint_url=self.endpoint,
                        region_name="us-east-1",
                        aws_access_key_id=self.access_key,
                        aws_secret_access_key=self.secret_key,
                    )
                    self.client.create_bucket(Bucket=self.bucket)
                    self.client.put_bucket_versioning(
                        Bucket=self.bucket,
                        VersioningConfiguration={"Status": "Enabled"},
                    )
                    return
            except Exception:
                pass
            time.sleep(0.5)
        logs = self._docker("logs", self.container, check=False).stdout[-4000:]
        raise RuntimeError(f"isolated MinIO did not become ready: {logs}")

    def bucket_versioning_enabled(self) -> bool:
        if self.client is None:
            return False
        return self.client.get_bucket_versioning(Bucket=self.bucket).get("Status") == "Enabled"

    def delete_bucket_and_verify(self) -> bool:
        if self.client is None:
            return False
        response = self.client.list_object_versions(Bucket=self.bucket, Prefix="", MaxKeys=1000)
        for item in (*response.get("Versions", []), *response.get("DeleteMarkers", [])):
            self.client.delete_object(
                Bucket=self.bucket,
                Key=item["Key"],
                VersionId=item["VersionId"],
            )
        self.client.delete_bucket(Bucket=self.bucket)
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            return str(exc.response.get("Error", {}).get("Code")) in {"404", "NoSuchBucket"}
        return False

    def stop_and_verify(self) -> tuple[bool, bool]:
        self._docker("rm", "--force", self.container, check=False)
        container_absent = (
            self._docker("container", "inspect", self.container, check=False).returncode != 0
        )
        self._docker("volume", "rm", self.volume, check=False)
        volume_absent = self._docker("volume", "inspect", self.volume, check=False).returncode != 0
        return container_absent, volume_absent


def _request(plan: Any) -> ObjectProjectionRepairRequest:
    return ObjectProjectionRepairRequest(
        plan=plan,
        checkpointed_by="workload:object-rehearsal",
    )


def _target(bundle: Path, endpoint: str, bucket: str) -> ObjectProjectionTarget:
    manifest_path = bundle / "manifest.json"
    artifact_path = bundle / _ARTIFACT_NAME
    manifest_bytes = manifest_path.read_bytes()
    artifact_bytes = artifact_path.read_bytes()
    return ObjectProjectionTarget(
        tenant_id="cq-object-rehearsal",
        projection_id="cq.customer.heping_changed_parcels",
        target_ref=f"s3://{bucket}/{_BUNDLE_ID}/{_ARTIFACT_NAME}",
        endpoint_url=endpoint,
        region_name="us-east-1",
        bucket=bucket,
        key=f"{_BUNDLE_ID}/{_ARTIFACT_NAME}",
        bundle_manifest_path=str(manifest_path),
        bundle_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        bundle_id=_BUNDLE_ID,
        bundle_version=_BUNDLE_VERSION,
        artifact_path=str(artifact_path),
        artifact_name=_ARTIFACT_NAME,
        artifact_sha256=hashlib.sha256(artifact_bytes).hexdigest(),
        artifact_size_bytes=len(artifact_bytes),
        media_type="application/geo+json",
        ontology_package_id=_ONTOLOGY_PACKAGE_ID,
        ontology_package_content_sha256=_ONTOLOGY_PACKAGE_SHA256,
    )


def _desired(
    target: ObjectProjectionTarget,
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
        target_engine=ProjectionEngine.OBJECT_STORE,
        target_ref=target.target_ref,
        target_exists=exists,
        expected_target_content_sha256=target.artifact_sha256 if exists else None,
        expected_row_count=1 if exists else 0,
    )


def run_rehearsal(
    admin_url: str,
    *,
    image: str = _DEFAULT_IMAGE,
    bundle_dir: Path = _DEFAULT_BUNDLE,
) -> ObjectProjectionExecutorRehearsalReport:
    checked_at = datetime.now(UTC)
    checks: dict[str, bool] = {}
    failures: list[str] = []
    temporary_database = _TemporaryPostgres(admin_url)
    temporary_minio = _TemporaryMinio(image)
    target: ObjectProjectionTarget | None = None
    artifact_sha256 = "0" * 64
    artifact_size_bytes = 0
    try:
        temporary_database.create()
        temporary_minio.start()
        assert temporary_database.engine is not None
        assert temporary_minio.endpoint is not None
        assert temporary_minio.client is not None
        target = _target(bundle_dir, temporary_minio.endpoint, temporary_minio.bucket)
        artifact_sha256 = target.artifact_sha256
        artifact_size_bytes = target.artifact_size_bytes
        checks["bucket_versioning_enabled"] = temporary_minio.bucket_versioning_enabled()
        executor = ObjectProjectionRepairExecutor(
            ObjectProjectionTargetRegistry((target,)),
            client=temporary_minio.client,
            timeout_seconds=600,
        )
        durable_authority = PostgresProjectionCheckpointAuthority(temporary_database.engine)
        authority = _FailOnceRecordAuthority(durable_authority)
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
        try:
            execute_object_projection_repair(
                _request(rebuild), executor=executor, authority=authority
            )
        except ObjectProjectionServiceConfigurationError:
            checks["rebuild_authority_outage_occurs_after_provider_commit"] = True
        else:
            checks["rebuild_authority_outage_occurs_after_provider_commit"] = False
        committed_observation, committed_version, _ = executor.observe_versioned(target)
        restarted_executor = ObjectProjectionRepairExecutor(
            ObjectProjectionTargetRegistry((target,)),
            client=temporary_minio.client,
            timeout_seconds=600,
        )
        first_result = execute_object_projection_repair(
            _request(rebuild), executor=restarted_executor, authority=authority
        )
        first = first_result.receipt
        checks["rebuild_writes_customer_artifact_and_verifies_content"] = (
            first.status == "replayed"
            and first.target_content_sha256 == target.artifact_sha256
            and first.target_size_bytes == target.artifact_size_bytes
            and first.object_version_id is not None
        )
        checks["rebuild_metadata_receipt_recovers_without_provider_replay"] = (
            committed_observation.target_exists
            and committed_version.version_id == first.object_version_id
            and first.provider_commit_ref.get("provider_atomicity")
            == "target_payload_and_plan_metadata_single_put_object"
            and first.provider_commit_ref.get("receipt_sha256")
            == committed_version.metadata.get("gda-receipt-sha256")
        )
        checks["rebuild_receipt_automatically_checkpointed"] = (
            first_result.checkpoint_created
            and first_result.checkpoint.checkpoint_version == 1
            and first.provider_commit_ref.get("provider") == "s3_object_store"
            and first_result.checkpoint.target_commit_ref == first.provider_commit_ref
        )
        replay = execute_object_projection_repair(
            _request(rebuild), executor=executor, authority=authority
        )
        checks["rebuild_replay_is_idempotent"] = (
            replay.status == "replayed"
            and not replay.checkpoint_created
            and replay.checkpoint == first_result.checkpoint
        )
        temporary_minio.client.put_object(
            Bucket=target.bucket,
            Key=target.key,
            Body=Path(target.artifact_path).read_bytes(),
            ContentType=target.media_type,
        )
        try:
            execute_object_projection_repair(
                _request(rebuild), executor=executor, authority=authority
            )
        except ObjectProjectionServiceConflictError:
            checks["checkpoint_replay_rejects_same_content_new_version"] = True
        else:
            checks["checkpoint_replay_rejects_same_content_new_version"] = False

        post, post_version, _ = executor.observe_versioned(target)
        checkpoint_plan = build_projection_repair_plan(
            _desired(
                target,
                source_sha256="b" * 64,
                source_version="checkpoint-2",
            ),
            post,
            first_result.checkpoint,
        )
        checkpoint_result = execute_object_projection_repair(
            _request(checkpoint_plan), executor=executor, authority=authority
        )
        checks["checkpoint_action_rechecks_without_rebuild"] = (
            checkpoint_result.receipt.status == "checkpointed"
            and checkpoint_result.checkpoint_created
            and checkpoint_result.checkpoint.checkpoint_version == 2
            and checkpoint_result.receipt.object_version_id == post_version.version_id
        )

        stale_plan = build_projection_repair_plan(
            _desired(
                target,
                source_sha256="d" * 64,
                source_version="stale",
            ),
            initial,
            None,
        )
        before_stale = executor.observe(target)
        try:
            execute_object_projection_repair(
                _request(stale_plan), executor=executor, authority=authority
            )
        except ObjectProjectionServiceConflictError:
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
                source_sha256="c" * 64,
                source_version="deleted",
                exists=False,
            ),
            post,
            checkpoint_result.checkpoint,
        )
        delete_authority = _FailOnceRecordAuthority(durable_authority)
        try:
            execute_object_projection_repair(
                _request(delete_plan),
                executor=executor,
                authority=delete_authority,
            )
        except ObjectProjectionServiceConfigurationError:
            checks["delete_authority_outage_occurs_after_delete_marker"] = True
        else:
            checks["delete_authority_outage_occurs_after_delete_marker"] = False
        deleted_observation, deleted_version, _ = executor.observe_versioned(target)
        delete_restart_executor = ObjectProjectionRepairExecutor(
            ObjectProjectionTargetRegistry((target,)),
            client=temporary_minio.client,
            timeout_seconds=600,
        )
        delete_result = execute_object_projection_repair(
            _request(delete_plan),
            executor=delete_restart_executor,
            authority=delete_authority,
        )
        deleted = delete_result.receipt
        checks["delete_creates_immutable_delete_marker"] = (
            deleted.status in {"deleted", "replayed"}
            and not deleted.target_exists
            and deleted.delete_marker_version_id is not None
            and deleted.provider_commit_ref.get("delete_marker_version_id")
            == deleted.delete_marker_version_id
        )
        receipt_key = deleted.provider_commit_ref.get("receipt_object_key")
        receipt_object = temporary_minio.client.get_object(
            Bucket=target.bucket,
            Key=receipt_key,
        )
        receipt_metadata = receipt_object.get("Metadata", {})
        receipt_body = receipt_object["Body"]
        try:
            receipt_document = json.loads(receipt_body.read())
        finally:
            receipt_body.close()
        checks["delete_intent_and_marker_recover_without_provider_replay"] = (
            not deleted_observation.target_exists
            and deleted_version.delete_marker_version_id == deleted.delete_marker_version_id
            and deleted.status == "replayed"
            and receipt_metadata.get("gda-receipt-sha256")
            == deleted.provider_commit_ref.get("receipt_sha256")
            and receipt_document.get("receipt_sha256")
            == deleted.provider_commit_ref.get("receipt_sha256")
        )
        checks["delete_receipt_automatically_checkpointed"] = (
            delete_result.checkpoint_created
            and delete_result.checkpoint.checkpoint_version == 3
            and not delete_result.checkpoint.target_exists
        )
        delete_replay = execute_object_projection_repair(
            _request(delete_plan), executor=delete_restart_executor, authority=delete_authority
        )
        checks["delete_replay_is_idempotent"] = (
            delete_replay.status == "replayed"
            and not delete_replay.checkpoint_created
            and delete_replay.checkpoint == delete_result.checkpoint
        )
        history = durable_authority.history(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_engine=ProjectionEngine.OBJECT_STORE,
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
            checks["temporary_object_bucket_removed"] = temporary_minio.delete_bucket_and_verify()
        except Exception as exc:  # pragma: no cover - external runtime failure
            checks["temporary_object_bucket_removed"] = False
            failures.append(f"MinIOBucketCleanupError: {exc}")
        try:
            container_removed, volume_removed = temporary_minio.stop_and_verify()
        except Exception as exc:  # pragma: no cover - external runtime failure
            container_removed = False
            volume_removed = False
            failures.append(f"MinIOCleanupError: {exc}")
        try:
            database_removed = temporary_database.drop_and_verify()
        except Exception as exc:  # pragma: no cover - external runtime failure
            database_removed = False
            failures.append(f"PostgresCleanupError: {exc}")
        checks["temporary_minio_container_removed"] = container_removed
        checks["temporary_minio_volume_removed"] = volume_removed
        checks["temporary_checkpoint_database_removed"] = database_removed

    failures.extend(key for key, value in checks.items() if not value)
    if target is None:
        manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
        artifact = next(item for item in manifest["files"] if item["name"] == _ARTIFACT_NAME)
        artifact_sha256 = artifact["sha256"]
        artifact_size_bytes = int(artifact["size"])
    payload = {
        "schema_id": "gda.object-projection-executor-rehearsal.v2",
        "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
        "database_scope": "temporary_database_only",
        "object_store_scope": "temporary_container_volume_and_bucket_only",
        "atomicity_scope": (
            "rebuild_payload_and_receipt_metadata_single_put_delete_intent_and_marker_separate_"
            "checkpoint_authority_separate"
        ),
        "minio_image": image,
        "minio_image_id": temporary_minio.image_id or "unavailable",
        "migration_ids": _MIGRATIONS,
        "bundle_id": _BUNDLE_ID,
        "bundle_version": _BUNDLE_VERSION,
        "artifact_name": _ARTIFACT_NAME,
        "artifact_sha256": artifact_sha256,
        "artifact_size_bytes": artifact_size_bytes,
        "ontology_package_id": _ONTOLOGY_PACKAGE_ID,
        "ontology_package_content_sha256": _ONTOLOGY_PACKAGE_SHA256,
        "checks": checks,
        "passed": not failures and bool(checks),
        "failure_reasons": tuple(sorted(set(failures))),
        "technical_baseline_status": "technical_baseline_unreviewed",
        "decision_status": "assisted_precheck_not_for_production_decision",
    }
    return ObjectProjectionExecutorRehearsalReport(
        **payload,
        report_sha256=canonical_json_fingerprint(payload),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--admin-url",
        default="postgresql://postgres:postgres@localhost:5433/gis_agent",
    )
    parser.add_argument("--image", default=_DEFAULT_IMAGE)
    parser.add_argument("--bundle-dir", type=Path, default=_DEFAULT_BUNDLE)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = run_rehearsal(
        args.admin_url,
        image=args.image,
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
