#!/usr/bin/env python3
"""Certify specialist Artifact content against disposable MinIO Object Lock."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from botocore.exceptions import ClientError
from certify_metric_query_s3_result_store import _DisposableMinio

from data_agent.agentops_specialist_providers import (
    S3ArtifactContentBackend,
    SpecialistProviderError,
)
from data_agent.platform_contracts import Artifact, ArtifactRole, canonical_json_fingerprint

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO_ROOT / "docs/reports/agentops_specialist_s3_object_lock_2026-08-30.json"
TENANT = "agentops-specialist-object-lock-certification"
PREFIX = "agentops-specialist/v1"


def _error_code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code") or "")


def _report_hash(payload: dict[str, Any]) -> str:
    return canonical_json_fingerprint(
        {key: value for key, value in payload.items() if key != "report_sha256"}
    )


def certify() -> dict[str, Any]:
    sandbox = _DisposableMinio(
        object_prefix=PREFIX,
        name_prefix="gda-agentops-specialist-lock",
    )
    checks: dict[str, bool] = {}
    cleanup: dict[str, bool] = {}
    storage_uri = ""
    version_id = ""
    content_sha256 = ""
    try:
        sandbox.start()
        assert sandbox.admin is not None
        # The helper provisions a scoped writer, but keeps its client private. Build
        # the same credential-scoped client from the helper's generated credentials.
        import boto3
        from botocore.config import Config as BotoConfig

        writer = boto3.client(
            "s3",
            endpoint_url=sandbox.endpoint,
            aws_access_key_id=sandbox.writer,
            aws_secret_access_key=sandbox.writer_secret_key,
            region_name="us-east-1",
            config=BotoConfig(
                connect_timeout=5,
                read_timeout=15,
                retries={"total_max_attempts": 1, "mode": "standard"},
                s3={"addressing_style": "path"},
            ),
        )
        backend = S3ArtifactContentBackend(
            writer,
            bucket=sandbox.bucket,
            prefix=PREFIX,
            require_version_id=True,
            require_object_lock_retention=True,
        )
        contract = backend.probe()
        checks["specialist_backend_probe"] = contract == {
            "versioning": "Enabled",
            "object_lock": "Enabled",
            "retention_mode": "GOVERNANCE",
            "retention_unit": "Days",
            "retention_duration": 1,
        }

        artifact_id = uuid5(UUID("f0dd83a7-3e38-40c8-ae3a-6a1e3d79f27a"), sandbox.container)
        content = b'{"schema":"gda.agentops.specialist.output.v1","status":"ok"}'
        content_sha256 = hashlib.sha256(content).hexdigest()
        storage_uri = backend.uri_for(
            tenant_id=TENANT,
            artifact_id=artifact_id,
            media_type="application/json",
        )
        storage = backend.write(
            storage_uri=storage_uri,
            content=content,
            media_type="application/json",
        )
        version_id = str(storage.get("version_id") or "")
        checks["version_id_captured"] = bool(version_id)
        artifact = Artifact(
            tenant_id=TENANT,
            artifact_id=artifact_id,
            artifact_key=f"agentops-specialist:{artifact_id}",
            artifact_role=ArtifactRole.OUTPUT,
            storage_uri=storage_uri,
            media_type="application/json",
            content_sha256=content_sha256,
            size_bytes=len(content),
            run_id=None,
            resource_version_id=None,
            manifest={"schema": "gda.agentops.specialist.output_manifest.v1", "storage": storage},
            created_by="workload:agentops-specialist-certification",
            created_at=datetime.now(UTC),
        )
        checks["exact_version_readback"] = backend.read(artifact) == content

        retention = sandbox.admin.get_object_retention(
            Bucket=sandbox.bucket,
            Key=storage_uri.removeprefix(f"s3://{sandbox.bucket}/"),
            VersionId=version_id,
        ).get("Retention", {})
        checks["governance_retention_applied"] = (
            retention.get("Mode") == "GOVERNANCE"
            and retention.get("RetainUntilDate") is not None
        )

        # Root is allowed to delete objects, but Governance retention must still
        # reject deletion when no explicit bypass is supplied.
        delete_denied = False
        try:
            sandbox.admin.delete_object(
                Bucket=sandbox.bucket,
                Key=storage_uri.removeprefix(f"s3://{sandbox.bucket}/"),
                VersionId=version_id,
            )
        except ClientError as exc:
            delete_denied = _error_code(exc) in {"AccessDenied", "InvalidRequest"}
        checks["object_lock_blocks_version_delete"] = delete_denied
        checks["object_survives_denied_delete"] = (
            sandbox.admin.get_object(
                Bucket=sandbox.bucket,
                Key=storage_uri.removeprefix(f"s3://{sandbox.bucket}/"),
                VersionId=version_id,
            )["Body"].read()
            == content
        )

        bypass_denied = False
        try:
            writer.delete_object(
                Bucket=sandbox.bucket,
                Key=storage_uri.removeprefix(f"s3://{sandbox.bucket}/"),
                VersionId=version_id,
                BypassGovernanceRetention=True,
            )
        except ClientError as exc:
            bypass_denied = _error_code(exc) in {"AccessDenied", "AllAccessDisabled"}
        checks["scoped_writer_cannot_bypass_retention"] = bypass_denied
    except SpecialistProviderError:
        checks["specialist_backend_probe"] = False
    finally:
        cleanup = sandbox.cleanup()

    checks.update({f"cleanup_{key}": value for key, value in cleanup.items()})
    report: dict[str, Any] = {
        "schema": "gda.agentops_specialist_s3_object_lock_certification.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "provider": "MinIO S3-compatible",
        "scope": "disposable_minio_specialist_content_plane",
        "tenant": TENANT,
        "prefix": PREFIX,
        "storage_uri": storage_uri,
        "version_id_captured": bool(version_id),
        "content_sha256": content_sha256,
        "checks": checks,
        "passed": all(checks.values()) if checks else False,
        "production_readiness_claimed": False,
    }
    report["report_sha256"] = _report_hash(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = certify()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
