#!/usr/bin/env python3
"""Run real Temporal MMFE/GWM specialists through PostgreSQL Artifact authority.

This is a bounded integration rehearsal: PostgreSQL is the disposable control/evidence
authority and the content backend is a temporary filesystem.  It deliberately does not
claim production readiness or replace MinIO/Iceberg/PostGIS certification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from rehearse_agentops_temporal_real_specialists import run_rehearsal

from data_agent.agentops_specialist_operation_authority import (
    AGENTOPS_SPECIALIST_OPERATION_AUTHORITY_MIGRATION,
    PostgresSpecialistOperationAuthority,
)
from data_agent.agentops_specialist_providers import (
    FilesystemArtifactContentBackend,
    PostgresArtifactAuthoritySpecialistStore,
    S3ArtifactContentBackend,
)
from data_agent.agentops_specialist_retry_budget import (
    RETRY_BUDGET_MIGRATION,
    PostgresSpecialistRetryBudgetAuthority,
)
from data_agent.cross_store_projection_postgres_rehearsal import (
    _execute_migration,
    _temporary_postgres,
)
from data_agent.platform_contracts import Artifact, ArtifactRole, canonical_json_fingerprint
from data_agent.platform_gateway import PlatformGateway


def _register_inputs(
    root: Path,
    entries: tuple[tuple[UUID, Path, str], ...],
    *,
    gateway: PlatformGateway,
    content_backend: Any | None = None,
):
    backend = content_backend or FilesystemArtifactContentBackend(root / "authority-content")
    for artifact_id, source_path, media_type in entries:
        content = source_path.read_bytes()
        storage_uri = backend.uri_for(
            tenant_id="planning", artifact_id=artifact_id, media_type=media_type
        )
        storage_metadata = backend.write(
            storage_uri=storage_uri, content=content, media_type=media_type
        )
        artifact = Artifact(
            tenant_id="planning",
            artifact_id=artifact_id,
            artifact_key=f"agentops-input:{artifact_id}",
            artifact_role=ArtifactRole.INPUT,
            storage_uri=storage_uri,
            media_type=media_type,
            content_sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            run_id=None,
            resource_version_id=None,
            manifest={
                "schema": "gda.agentops.input_artifact.v1",
                "source_name": source_path.name,
                **({"storage": storage_metadata} if storage_metadata else {}),
            },
            created_by="workload:agentops-rehearsal",
            created_at=datetime.now(UTC),
        )
        gateway.record_artifact(artifact)
    return PostgresArtifactAuthoritySpecialistStore(
        "planning",
        gateway=gateway,
        content_backend=backend,
        materialization_root=root / "materialized",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--frontend", default="127.0.0.1:7233")
    parser.add_argument("--namespace", default="gda-agentops-sandbox")
    parser.add_argument("--task-queue", default="agentops-postgres-artifact-rehearsal")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument(
        "--s3-endpoint",
        default=None,
        help="Use a disposable S3/MinIO bucket for content instead of filesystem",
    )
    parser.add_argument(
        "--s3-access-key",
        default=os.environ.get("AWS_ACCESS_KEY_ID", "minio_admin"),
    )
    parser.add_argument(
        "--s3-secret-key",
        default=os.environ.get("AWS_SECRET_ACCESS_KEY", "local_dev_minio_secret"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.database_url:
        raise SystemExit("--database-url or DATABASE_URL is required")

    authority_context: dict[str, Any] = {}
    s3_client: Any | None = None
    s3_bucket: str | None = None
    content_backend: Any | None = None
    if args.s3_endpoint:
        import boto3

        s3_client = boto3.client(
            "s3",
            endpoint_url=args.s3_endpoint,
            aws_access_key_id=args.s3_access_key,
            aws_secret_access_key=args.s3_secret_key,
            region_name="us-east-1",
        )
        s3_bucket = f"gda-agentops-{uuid4().hex[:12]}"
        s3_client.create_bucket(Bucket=s3_bucket)
        s3_client.put_bucket_versioning(
            Bucket=s3_bucket, VersioningConfiguration={"Status": "Enabled"}
        )
        content_backend = S3ArtifactContentBackend(
            s3_client,
            bucket=s3_bucket,
            prefix="agentops-authority-rehearsal",
            require_version_id=True,
        )

    def factory(root: Path, entries: tuple[tuple[UUID, Path, str], ...]):
        # The temporary database is created outside run_rehearsal and remains alive
        # until the Temporal workflow and history replay are complete.
        gateway = PlatformGateway(sandbox.runtime_engine)
        authority_context["gateway"] = gateway
        authority_context["input_ids"] = tuple(str(item[0]) for item in entries)
        store = _register_inputs(
            root, entries, gateway=gateway, content_backend=content_backend
        )
        authority_context["store"] = store
        return store

    try:
        with _temporary_postgres(args.database_url) as sandbox:
            if sandbox.runtime_engine is None:
                raise RuntimeError("temporary PostgreSQL runtime was not initialized")
            with sandbox.admin_connection() as connection:
                # Migration 246 uses pgcrypto.digest for receipt fingerprints.  The
                # bounded rehearsal intentionally loads only the control-ledger
                # migrations, so install this explicit database prerequisite here;
                # production databases already receive it from the earlier ledger
                # migrations.
                connection.exec_driver_sql(
                    "CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public"
                )
                _execute_migration(
                    connection,
                    AGENTOPS_SPECIALIST_OPERATION_AUTHORITY_MIGRATION.read_text(
                        encoding="utf-8"
                    ),
                )
                _execute_migration(
                    connection,
                    RETRY_BUDGET_MIGRATION.read_text(encoding="utf-8"),
                )
            operation_authority = PostgresSpecialistOperationAuthority(
                "planning",
                sandbox.runtime_engine,
                recorded_by="workload:agentops-specialist-rehearsal",
            )
            retry_budget_authority = PostgresSpecialistRetryBudgetAuthority(
                "planning",
                sandbox.runtime_engine,
                recorded_by="workload:agentops-specialist-rehearsal",
            )
            report, history = __import__("asyncio").run(
                run_rehearsal(
                    frontend_target=args.frontend,
                    namespace_ref=args.namespace,
                    task_queue_ref=args.task_queue,
                    artifact_store_factory=factory,
                    operation_authority=operation_authority,
                    retry_budget_authority=retry_budget_authority,
                )
            )
            history_text = history + ("" if history.endswith("\n") else "\n")
            report["history_sha256"] = hashlib.sha256(history_text.encode("utf-8")).hexdigest()
            report["scope"] = (
                "docker_desktop_temporal_postgres_artifact_authority_s3_bounded"
                if args.s3_endpoint
                else "docker_desktop_temporal_postgres_artifact_authority_bounded"
            )
            report["artifact_authority"] = {
                "control_plane": "postgresql",
                "content_backend": "minio_s3" if args.s3_endpoint else "temporary_filesystem",
                "bucket": s3_bucket,
                "registered_input_count": len(authority_context.get("input_ids", ())),
                "registered_output_count": len(report.get("provider_artifacts", ())),
                "authority_lookup_verified": all(
                    authority_context["gateway"].get_artifact(
                        "planning", UUID(item["artifact_id"])
                    ).artifact_id
                    == UUID(item["artifact_id"])
                    for item in report.get("provider_artifacts", ())
                ),
                "production_readiness_claimed": False,
            }
            receipt_report = report.get("operation_authority")
            if not isinstance(receipt_report, dict):
                raise RuntimeError("real specialist rehearsal did not report operation receipts")
            receipts = receipt_report.get("provider_operation_receipts", ())
            if (
                len(receipts) != len(report.get("provider_artifacts", ()))
                or not receipt_report.get("replay_same_artifacts")
                or any(
                    item.get("status") != "succeeded"
                    or item.get("history_count") != 2
                    for item in receipts
                )
                ):
                    raise RuntimeError(
                        "PostgreSQL provider operation receipts did not reach the expected "
                        "durable state"
                    )
            budget_observations = []
            for item in receipts:
                operation_key = (
                    f"{item['provider_ref']}://{item['run_id']}/{item['tool_call_id']}"
                )
                budget = retry_budget_authority.observe(
                    tenant_id="planning", operation_key=operation_key
                )
                if budget is None or budget.attempt_count != 1 or len(budget.admissions) != 1:
                    raise RuntimeError(
                        "retry budget did not remain idempotent across worker replay"
                    )
                budget_observations.append(
                    {
                        "operation_key": operation_key,
                        "attempt_count": budget.attempt_count,
                        "admission_count": len(budget.admissions),
                        "status": budget.status,
                    }
                )
            report["retry_budget"] = {
                "backend": retry_budget_authority.__class__.__name__,
                "worker_replacement_replay_verified": True,
                "observations": budget_observations,
                "production_readiness_claimed": False,
            }
            receipt_report.update(
                {
                    "control_plane": "postgresql",
                    "ledger_migration": AGENTOPS_SPECIALIST_OPERATION_AUTHORITY_MIGRATION.name,
                    "durable_receipt_count": len(receipts),
                    "terminal_success_cas_verified": True,
                    "worker_restart_replay_verified": True,
                    "retry_budget_backend": retry_budget_authority.__class__.__name__,
                    "retry_budget_worker_replacement_verified": True,
                    "production_readiness_claimed": False,
                }
            )
            if s3_client is not None and s3_bucket is not None:
                versions = s3_client.list_object_versions(Bucket=s3_bucket)
                version_counts: dict[str, int] = {}
                for item in versions.get("Versions", ()):
                    version_counts[item["Key"]] = version_counts.get(item["Key"], 0) + 1
                output_version_ids = [
                    item.get("manifest", {}).get("storage", {}).get("version_id")
                    for item in report.get("provider_artifacts", ())
                ]
                report["artifact_authority"].update(
                    {
                        "object_version_counts": version_counts,
                        "output_version_ids_bound": all(output_version_ids),
                        "each_object_single_version": all(
                            count == 1 for count in version_counts.values()
                        ),
                    }
                )
            report["report_sha256"] = canonical_json_fingerprint(
                {key: value for key, value in report.items() if key != "report_sha256"}
            )
    finally:
        if s3_client is not None and s3_bucket is not None:
            try:
                versions = s3_client.list_object_versions(Bucket=s3_bucket)
                objects = [
                    {"Key": item["Key"], "VersionId": item["VersionId"]}
                    for item in (*versions.get("Versions", ()), *versions.get("DeleteMarkers", ()))
                ]
                if objects:
                    s3_client.delete_objects(Bucket=s3_bucket, Delete={"Objects": objects})
                s3_client.delete_bucket(Bucket=s3_bucket)
            except Exception:
                # Cleanup is best effort; the report remains explicit about its bounded scope.
                pass

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.history.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.history.write_text(history_text, encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
