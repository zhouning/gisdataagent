#!/usr/bin/env python3
"""Rehearse specialist provider recovery after a worker dies post-commit.

The content plane can be a disposable shared filesystem or a versioned S3/MinIO
bucket. PostgreSQL remains the durable receipt, retry-budget and Artifact authority.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import signal
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from data_agent.agentops_specialist_operation_authority import (
    AGENTOPS_SPECIALIST_OPERATION_AUTHORITY_MIGRATION,
    AGENTOPS_SPECIALIST_OPERATION_UNCERTAINTY_MIGRATION,
    PostgresSpecialistOperationAuthority,
)
from data_agent.agentops_specialist_providers import (
    BoundSpecialistExecutor,
    FilesystemArtifactContentBackend,
    PostgresArtifactAuthoritySpecialistStore,
    S3ArtifactContentBackend,
    SpecialistOperationStatus,
    build_gwm_provider_spec,
)
from data_agent.agentops_specialist_retry_budget import (
    RETRY_BUDGET_MIGRATION,
    PostgresSpecialistRetryBudgetAuthority,
    provider_operation_family_key,
)
from data_agent.agentops_temporal_contracts import (
    TemporalActivityOutcome,
    TemporalActivityRequest,
    derive_temporal_activity_id,
    temporal_contract_fingerprint,
)
from data_agent.cross_store_projection_postgres_rehearsal import (
    _execute_migration,
    _temporary_postgres,
)
from data_agent.platform_contracts import (
    Artifact,
    ArtifactRole,
    FrozenContract,
    canonical_json_fingerprint,
)
from data_agent.platform_gateway import PlatformGateway
from data_agent.test_agentops_specialist_operation_authority import _request

REPORT_SCHEMA = "gda.agentops_specialist_worker_recovery_postgres_rehearsal.v1"
_BASE_MIGRATIONS = ("092_platform_control_ledger.sql", "094_platform_control_gateway.sql")
_INPUT_ID = UUID("00000000-0000-4000-8000-000000002481")


class WorkerRecoveryReport(FrozenContract):
    schema_id: str = REPORT_SCHEMA
    checked_at: datetime
    database_scope: str = "temporary_database_only"
    checks: dict[str, bool]
    passed: bool
    failure_reasons: tuple[str, ...]
    child_exit_code: int
    child_result_outcome: str
    child_failure_type: str | None
    recovered_result_outcome: str
    recovered_failure_type: str | None
    provider_receipt_history_count: int
    retry_budget_attempt_count: int
    retry_budget_admission_count: int
    content_plane: dict[str, Any] | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    production_readiness_claimed: bool = False
    report_sha256: str

    @model_validator(mode="after")
    def _hash_matches(self) -> WorkerRecoveryReport:
        if self.report_sha256 != _report_hash(self.model_dump(mode="json")):
            raise ValueError("worker recovery report hash is invalid")
        return self


def _report_hash(payload: dict[str, Any]) -> str:
    normalized = json.loads(
        json.dumps(
            payload,
            ensure_ascii=True,
            default=lambda value: value.astimezone(UTC)
            .isoformat()
            .replace("+00:00", "Z"),
        )
    )
    return canonical_json_fingerprint(
        {key: value for key, value in normalized.items() if key != "report_sha256"}
    )


def _request_with_gwm_input() -> TemporalActivityRequest:
    request = _request()
    spec = build_gwm_provider_spec(
        input_artifact_ids=(_INPUT_ID,), observation_id="worker-recovery"
    )
    values = request.model_dump(mode="python")
    values["input_artifact_ids"] = (_INPUT_ID,)
    values["provider_spec"] = spec
    values["activity_id"] = derive_temporal_activity_id(
        run_id=request.run_id, tool_call_id=request.tool_call_id, attempt_no=1
    )
    values["request_sha256"] = temporal_contract_fingerprint(
        TemporalActivityRequest.schema_id, values, "request_sha256"
    )
    return TemporalActivityRequest(**values)


def _worker(args: argparse.Namespace) -> None:
    request = TemporalActivityRequest.model_validate(
        json.loads(Path(args.request).read_text(encoding="utf-8"))
    )
    from sqlalchemy import create_engine

    engine = create_engine(args.database_url)
    if args.s3_endpoint:
        if not args.s3_bucket:
            raise RuntimeError("worker S3 content backend requires a bucket")
        import boto3

        content_client = boto3.client(
            "s3",
            endpoint_url=args.s3_endpoint,
            region_name="us-east-1",
            aws_access_key_id=args.s3_access_key,
            aws_secret_access_key=args.s3_secret_key,
        )
        content_backend = S3ArtifactContentBackend(
            content_client,
            bucket=args.s3_bucket,
            prefix=args.s3_prefix,
            require_version_id=True,
        )
    else:
        content_backend = FilesystemArtifactContentBackend(Path(args.content_root))
    gateway = PlatformGateway(engine)
    store = PostgresArtifactAuthoritySpecialistStore(
        request.tenant_id,
        gateway=gateway,
        content_backend=content_backend,
        materialization_root=Path(args.materialization_root),
    )
    operation_authority = PostgresSpecialistOperationAuthority(
        request.tenant_id, engine, recorded_by="workload:agentops-recovery-worker-a"
    )
    retry_authority = PostgresSpecialistRetryBudgetAuthority(
        request.tenant_id, engine, recorded_by="workload:agentops-recovery-worker-a"
    )
    result = asyncio.run(
        BoundSpecialistExecutor(
            store,
            operation_authority=operation_authority,
            retry_budget_authority=retry_authority,
            retry_budget_max_attempts=1,
            worker_id="workload:agentops-recovery-worker-a",
            unknown_after_commit=True,
        )(request)
    )
    Path(args.result).write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.kill(os.getpid(), signal.SIGKILL)


def run_rehearsal(
    admin_url: str,
    *,
    s3_endpoint: str | None = None,
    s3_access_key: str = "minio_admin",
    s3_secret_key: str = "local_dev_minio_secret",
) -> WorkerRecoveryReport:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    def check(name: str, passed: bool, reason: str) -> None:
        checks[name] = passed
        if not passed:
            failures.append(reason)

    request = _request_with_gwm_input()
    operation_ref = f"{request.provider_spec.operation_ref}://{request.activity_id}"
    operation_key = provider_operation_family_key(request)
    with _temporary_postgres(admin_url) as sandbox:
        if sandbox.runtime_engine is None or sandbox.database_url is None:
            raise RuntimeError("temporary PostgreSQL runtime was not initialized")
        with sandbox.admin_connection() as connection:
            connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public")
            for filename in _BASE_MIGRATIONS:
                migration = (
                    Path(__file__).resolve().parent.parent
                    / "data_agent"
                    / "migrations"
                    / filename
                )
                _execute_migration(connection, migration.read_text(encoding="utf-8"))
            for migration in (
                AGENTOPS_SPECIALIST_OPERATION_AUTHORITY_MIGRATION,
                AGENTOPS_SPECIALIST_OPERATION_UNCERTAINTY_MIGRATION,
                RETRY_BUDGET_MIGRATION,
            ):
                _execute_migration(connection, migration.read_text(encoding="utf-8"))

        # The database name is only used to derive a unique workspace under /tmp;
        # no production data is touched.
        workspace = Path("/tmp") / f"gda-agentops-worker-recovery-{os.getpid()}"
        workspace.mkdir(parents=True, exist_ok=True)
        content_root = workspace / "authority-content"
        materialization_root = workspace / "materialized"
        s3_client = None
        s3_bucket = None
        s3_prefix = "agentops-worker-recovery"
        if s3_endpoint:
            import boto3

            s3_client = boto3.client(
                "s3",
                endpoint_url=s3_endpoint,
                region_name="us-east-1",
                aws_access_key_id=s3_access_key,
                aws_secret_access_key=s3_secret_key,
            )
            s3_bucket = f"gda-agentops-recovery-{uuid4().hex[:12]}"
            s3_client.create_bucket(Bucket=s3_bucket)
            s3_client.put_bucket_versioning(
                Bucket=s3_bucket,
                VersioningConfiguration={"Status": "Enabled"},
            )
            content_backend = S3ArtifactContentBackend(
                s3_client,
                bucket=s3_bucket,
                prefix=s3_prefix,
                require_version_id=True,
            )
        else:
            content_backend = FilesystemArtifactContentBackend(content_root)
        gateway = PlatformGateway(sandbox.runtime_engine)
        input_path = workspace / "state.json"
        input_path.write_text(
            json.dumps(
                {
                    "schema": "mmfe.uwm_state_input.v1",
                    "version": "0.1",
                    "source_product": {"product_id": "worker-recovery-v1"},
                    "urban_spatial_unit": {"unit_type": "district"},
                    "object_role_registry": [],
                    "state_components": {},
                    "graph_summary": {},
                    "production_policy": {"authoritative_data_required_for_production": True},
                }
            ),
            encoding="utf-8",
        )
        input_content = input_path.read_bytes()
        input_uri = content_backend.uri_for(
            tenant_id=request.tenant_id,
            artifact_id=_INPUT_ID,
            media_type="application/json",
        )
        input_storage = content_backend.write(
            storage_uri=input_uri,
            content=input_content,
            media_type="application/json",
        )
        gateway.record_artifact(
            Artifact(
                tenant_id=request.tenant_id,
                artifact_id=_INPUT_ID,
                artifact_key=f"agentops-input:{_INPUT_ID}",
                artifact_role=ArtifactRole.INPUT,
                storage_uri=input_uri,
                media_type="application/json",
                content_sha256=hashlib.sha256(input_content).hexdigest(),
                size_bytes=len(input_content),
                run_id=None,
                resource_version_id=None,
                manifest={
                    "schema": "gda.agentops.input_artifact.v1",
                    "source_name": input_path.name,
                    **({"storage": input_storage} if input_storage else {}),
                },
                created_by="workload:agentops-recovery-rehearsal",
                created_at=datetime.now(UTC),
            )
        )
        store = PostgresArtifactAuthoritySpecialistStore(
            request.tenant_id,
            gateway=gateway,
            content_backend=content_backend,
            materialization_root=materialization_root,
        )
        request_path = workspace / "request.json"
        result_path = workspace / "child-result.json"
        request_path.write_text(
            json.dumps(request.model_dump(mode="json"), ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        # The child still enters the same gateway role through the authority's
        # transaction boundary. The temporary admin URL is used only to avoid
        # platform-specific libpq role-resolution differences between processes.
        db_url = sandbox.database_url.render_as_string(hide_password=False)
        child = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                "--database-url",
                db_url,
                "--content-root",
                str(content_root),
                "--s3-endpoint",
                s3_endpoint or "",
                "--s3-bucket",
                s3_bucket or "",
                "--s3-prefix",
                s3_prefix,
                "--s3-access-key",
                s3_access_key,
                "--s3-secret-key",
                s3_secret_key,
                "--materialization-root",
                str(materialization_root),
                "--request",
                str(request_path),
                "--result",
                str(result_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if not result_path.is_file():
            raise RuntimeError(f"worker A did not persist its result: {child.stderr[-2000:]}")
        child_result_payload = json.loads(result_path.read_text(encoding="utf-8"))
        check(
            "worker_a_died_after_provider_commit",
            child.returncode == -signal.SIGKILL
            and child_result_payload.get("outcome") == TemporalActivityOutcome.UNKNOWN.value,
            "worker A did not die after returning an unknown post-commit activity result",
        )
        engine = sandbox.runtime_engine
        operation_authority = PostgresSpecialistOperationAuthority(
            request.tenant_id, engine, recorded_by="workload:agentops-recovery-worker-b"
        )
        retry_authority = PostgresSpecialistRetryBudgetAuthority(
            request.tenant_id, engine, recorded_by="workload:agentops-recovery-worker-b"
        )
        recovered = asyncio.run(
            BoundSpecialistExecutor(
                store,
                operation_authority=operation_authority,
                retry_budget_authority=retry_authority,
                retry_budget_max_attempts=1,
                worker_id="workload:agentops-recovery-worker-b",
            )(request)
        )
        receipt = operation_authority.observe(operation_ref)
        receipt_history = operation_authority.history(operation_ref)
        budget = retry_authority.observe(
            tenant_id=request.tenant_id, operation_key=operation_key
        )
        if s3_client is not None and s3_bucket is not None:
            object_versions = s3_client.list_object_versions(
                Bucket=s3_bucket,
                Prefix=f"{s3_prefix}/{request.tenant_id}/",
            ).get("Versions", ())
            input_key = f"{s3_prefix}/{request.tenant_id}/{_INPUT_ID}.json"
            output_versions = tuple(item for item in object_versions if item["Key"] != input_key)
            output_object_keys = {item["Key"] for item in output_versions}
            output_files_count = len(output_object_keys)
            output_version_count = len(output_versions)
            input_version_id = next(
                (item["VersionId"] for item in object_versions if item["Key"] == input_key),
                None,
            )
            output_version_ids = tuple(sorted(item["VersionId"] for item in output_versions))
            output_artifact = (
                gateway.get_artifact(request.tenant_id, recovered.output_artifact_id)
                if recovered.output_artifact_id is not None
                else None
            )
            bound_output_version_id = (
                (output_artifact.manifest.get("storage") or {}).get("version_id")
                if output_artifact is not None
                else None
            )
            check(
                "immutable_object_versions_bound",
                bool(input_version_id)
                and len(output_version_ids) == 1
                and bound_output_version_id == output_version_ids[0],
                "input or output Artifact did not bind the exact MinIO VersionId",
            )
        else:
            output_files = tuple(
                path
                for path in (content_root / request.tenant_id).glob("*")
                if path.is_file() and path.name != f"{_INPUT_ID}.json"
            )
            output_files_count = len(output_files)
            output_version_count = output_files_count
            input_version_id = None
            output_version_ids = ()
        check(
            "new_worker_recovers_same_terminal_receipt",
            recovered.outcome is TemporalActivityOutcome.SUCCEEDED
            and receipt is not None
            and receipt.status is SpecialistOperationStatus.SUCCEEDED,
            "worker B could not recover the durable provider receipt",
        )
        check(
            "provider_operation_not_reexecuted",
            recovered.output_artifact_id is not None
            and len(receipt_history) == 2
            and output_files_count == 1
            and output_version_count == 1,
            "worker B created a second provider receipt transition or output Artifact",
        )
        check(
            "retry_budget_survives_worker_replacement",
            budget is not None
            and budget.attempt_count == 1
            and len(budget.admissions) == 1,
            "worker replacement reset or consumed the retry budget",
        )
        child_outcome = str(child_result_payload.get("outcome"))
        child_failure_type = child_result_payload.get("failure_type")
        recovered_outcome = recovered.outcome.value
        recovered_failure_type = recovered.failure_type
        receipt_count = len(receipt_history)
        budget_count = budget.attempt_count if budget is not None else -1
        admission_count = len(budget.admissions) if budget is not None else -1
        backend_name = "minio_s3_versioned" if s3_client is not None else "temporary_filesystem"
        if s3_client is not None and s3_bucket is not None:
            cleanup_verified = False
            try:
                versions = s3_client.list_object_versions(Bucket=s3_bucket)
                objects = [
                    {"Key": item["Key"], "VersionId": item["VersionId"]}
                    for item in (*versions.get("Versions", ()), *versions.get("DeleteMarkers", ()))
                ]
                if objects:
                    s3_client.delete_objects(
                        Bucket=s3_bucket,
                        Delete={"Objects": objects},
                    )
                s3_client.delete_bucket(Bucket=s3_bucket)
                try:
                    s3_client.head_bucket(Bucket=s3_bucket)
                except Exception:
                    cleanup_verified = True
            except Exception:
                cleanup_verified = False
            check(
                "temporary_object_store_cleanup_verified",
                cleanup_verified,
                "temporary MinIO bucket or object versions were not removed",
            )
        try:
            for path in workspace.rglob("*"):
                if path.is_file():
                    path.unlink()
            for path in sorted(workspace.glob("**/*"), reverse=True):
                if path.is_dir():
                    path.rmdir()
            workspace.rmdir()
        except OSError:
            pass

    values: dict[str, Any] = {
        "schema_id": REPORT_SCHEMA,
        "checked_at": datetime.now(UTC),
        "database_scope": "temporary_database_only",
        "checks": checks,
        "passed": not failures,
        "failure_reasons": tuple(failures),
        "child_exit_code": child.returncode,
        "child_result_outcome": child_outcome,
        "child_failure_type": child_failure_type,
        "recovered_result_outcome": recovered_outcome,
        "recovered_failure_type": recovered_failure_type,
        "provider_receipt_history_count": receipt_count,
        "retry_budget_attempt_count": budget_count,
        "retry_budget_admission_count": admission_count,
        "content_plane": {
            "backend": backend_name,
            "output_object_count": output_files_count,
            "output_object_version_count": output_version_count,
            "input_version_id": input_version_id,
            "output_version_ids": output_version_ids,
        },
        "production_readiness_claimed": False,
    }
    values["report_sha256"] = _report_hash(values)
    return WorkerRecoveryReport(**values)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--report", type=Path)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--content-root")
    parser.add_argument("--materialization-root")
    parser.add_argument("--s3-endpoint")
    parser.add_argument("--s3-bucket")
    parser.add_argument("--s3-prefix", default="agentops-worker-recovery")
    parser.add_argument(
        "--s3-access-key",
        default=os.environ.get("AWS_ACCESS_KEY_ID", "minio_admin"),
    )
    parser.add_argument(
        "--s3-secret-key",
        default=os.environ.get("AWS_SECRET_ACCESS_KEY", "local_dev_minio_secret"),
    )
    parser.add_argument("--request")
    parser.add_argument("--result")
    args = parser.parse_args()
    if args.worker:
        _worker(args)
        return
    if not args.database_url:
        raise SystemExit("--database-url or DATABASE_URL is required")
    if args.report is None:
        raise SystemExit("--report is required")
    report = run_rehearsal(
        args.database_url,
        s3_endpoint=args.s3_endpoint,
        s3_access_key=args.s3_access_key,
        s3_secret_key=args.s3_secret_key,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
