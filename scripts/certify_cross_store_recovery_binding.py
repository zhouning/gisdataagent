#!/usr/bin/env python3
"""Certify one disposable MinIO + PostgreSQL cross-store recovery task."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from certify_tenant_object_recovery import (
    DEFAULT_MC_IMAGE,
    DEFAULT_MINIO_IMAGE,
    _client,
    _put_and_digest,
    _TemporaryMinio,
)
from sqlalchemy import text

from data_agent.cross_store_projection_postgres_rehearsal import _temporary_postgres
from data_agent.platform_contracts import canonical_json_fingerprint
from data_agent.platform_runtime.cross_store_recovery import (
    build_cross_store_recovery_binding,
)
from data_agent.platform_runtime.cross_store_recovery_admission import (
    CrossStoreRecoveryAdmission,
    admit_cross_store_recovery,
)
from data_agent.platform_runtime.cross_store_recovery_authority import (
    CROSS_STORE_RECOVERY_BINDING_AUTHORITY_MIGRATION,
    CrossStoreRecoveryAuthorityValidationError,
    PostgresCrossStoreRecoveryBindingAuthority,
)
from data_agent.platform_runtime.cross_store_recovery_controller import (
    CrossStoreRecoveryController,
    CrossStoreRecoveryRunState,
)
from data_agent.platform_runtime.cross_store_recovery_controller_authority import (
    CONTROLLER_AUTHORITY_MIGRATION,
    PostgresCrossStoreRecoveryControllerLedger,
)
from data_agent.platform_runtime.object_recovery import (
    build_object_recovery_manifest,
    compare_object_recovery_manifests,
    sha256_bytes,
)
from data_agent.platform_runtime.tenant_recovery import (
    build_recovery_manifest,
    fingerprint_tenant_rows,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO_ROOT / ".tmp/cross-store-recovery-binding/acceptance-report.json"
TENANT_PREFIXES = {
    "tenant-a": "tenants/tenant-a/",
    "tenant-b": "tenants/tenant-b/",
}


def _control_manifest():
    return build_recovery_manifest(
        tuple(TENANT_PREFIXES),
        tuple(
            fingerprint_tenant_rows(
                tenant,
                "resource_version",
                [{"resource_version": "source-v1", "tenant": tenant}],
            )
            for tenant in TENANT_PREFIXES
        ),
    )


def _run_minio(sandbox: _TemporaryMinio):
    if sandbox.endpoint is None or sandbox.admin is None:
        raise RuntimeError("MinIO is not ready")
    scopes = {
        tenant: sandbox.add_user(tenant, prefix)
        for tenant, prefix in TENANT_PREFIXES.items()
    }
    clients = {
        tenant: _client(sandbox.endpoint, *sandbox.users[tenant])
        for tenant in TENANT_PREFIXES
    }
    payloads = {
        "tenant-a": {"tenants/tenant-a/roads.json": b"source-a\n"},
        "tenant-b": {"tenants/tenant-b/roads.json": b"source-b\n"},
    }
    source_objects = tuple(
        _put_and_digest(
            clients[tenant],
            scopes[tenant],
            sandbox.source_bucket,
            key,
            payload,
        )
        for tenant, entries in payloads.items()
        for key, payload in entries.items()
    )
    restored_objects = tuple(
        _put_and_digest(
            clients[tenant],
            scopes[tenant],
            sandbox.restored_bucket,
            key,
            payload,
        )
        for tenant, entries in payloads.items()
        for key, payload in entries.items()
    )
    source_manifest = build_object_recovery_manifest(TENANT_PREFIXES, source_objects)
    restored_manifest = build_object_recovery_manifest(TENANT_PREFIXES, restored_objects)
    compare_object_recovery_manifests(
        source_manifest, restored_manifest, allow_version_id_remap=True
    )
    return source_manifest, restored_manifest


def _install_binding_authority(sandbox: Any) -> None:
    with sandbox.admin_connection() as connection:
        migration_dir = CROSS_STORE_RECOVERY_BINDING_AUTHORITY_MIGRATION.parent
        for filename in ("092_platform_control_ledger.sql", "094_platform_control_gateway.sql"):
            connection.exec_driver_sql(
                (migration_dir / filename).read_text(encoding="utf-8").replace("%", "%%")
            )
        connection.exec_driver_sql(
            CROSS_STORE_RECOVERY_BINDING_AUTHORITY_MIGRATION.read_text(
                encoding="utf-8"
            ).replace("%", "%%")
        )
        connection.exec_driver_sql(
            CONTROLLER_AUTHORITY_MIGRATION.read_text(encoding="utf-8").replace("%", "%%")
        )


def _run_postgres(
    sandbox: Any,
    *,
    source_control: Any,
    restored_control: Any,
    source_objects: Any,
    restored_objects: Any,
) -> tuple[CrossStoreRecoveryAdmission, dict[str, bool], Any]:
    if sandbox.runtime_engine is None:
        raise RuntimeError("PostgreSQL runtime engine is not ready")
    authorities = {
        tenant: PostgresCrossStoreRecoveryBindingAuthority(
            tenant, sandbox.runtime_engine
        )
        for tenant in TENANT_PREFIXES
    }
    admission = admit_cross_store_recovery(
        source_control_manifest=source_control,
        restored_control_manifest=restored_control,
        source_object_manifest=source_objects,
        restored_object_manifest=restored_objects,
        source_resource_version_ref="gda://tenant-a/data_product/source/v1",
        source_content_sha256=sha256_bytes(b"source-resource-version-v1"),
        authorities=authorities,
        allow_object_version_id_remap=True,
    )
    binding = admission.binding
    controller_ledger = PostgresCrossStoreRecoveryControllerLedger(
        binding.tenant_ids, sandbox.runtime_engine
    )
    controller = CrossStoreRecoveryController(
        "cross-store-recovery-certification-run",
        ledger=controller_ledger,
    )
    controller.admit(admission)
    completed_controller = controller.complete(admission)
    restarted_controller = CrossStoreRecoveryController(
        "cross-store-recovery-certification-run",
        ledger=PostgresCrossStoreRecoveryControllerLedger(
            binding.tenant_ids, sandbox.runtime_engine
        ),
    )
    replay = {tenant: authority.append(binding) for tenant, authority in authorities.items()}
    restarted = {
        tenant: PostgresCrossStoreRecoveryBindingAuthority(
            tenant, sandbox.runtime_engine
        ).current(binding.binding_sha256)
        for tenant in TENANT_PREFIXES
    }
    isolated = PostgresCrossStoreRecoveryBindingAuthority(
        "tenant-c", sandbox.runtime_engine
    ).current(binding.binding_sha256)
    isolated_controller = PostgresCrossStoreRecoveryControllerLedger(
        ("tenant-c",), sandbox.runtime_engine
    ).current(completed_controller.run_id)
    drifted = build_cross_store_recovery_binding(
        source_control,
        source_objects,
        source_resource_version_ref=binding.source_resource_version_ref,
        source_content_sha256="b" * 64,
    )
    drift_rejected = False
    try:
        authorities["tenant-a"].append(drifted)
    except CrossStoreRecoveryAuthorityValidationError:
        drift_rejected = True
    with sandbox.admin_connection() as connection:
        row_count = connection.execute(
            text(
                "SELECT count(*) FROM gda_control.cross_store_recovery_binding_history"
            )
        ).scalar_one()
        controller_row_count = connection.execute(
            text(
                "SELECT count(*) FROM "
                "gda_control.cross_store_recovery_controller_history"
            )
        ).scalar_one()
        controller_copy_count = connection.execute(
            text(
                """
                SELECT count(DISTINCT snapshot_document)
                FROM gda_control.cross_store_recovery_controller_history
                WHERE run_id = :run_id
                """
            ),
            {"run_id": completed_controller.run_id},
        ).scalar_one()
    checks = {
        "two_tenant_authority_rows": row_count == 2,
        "admission_persisted_source_identity": admission.binding == binding,
        "controller_completed": completed_controller.state is CrossStoreRecoveryRunState.COMPLETED,
        "controller_restart_readback": restarted_controller.snapshot == completed_controller,
        "controller_history_durable": len(
            restarted_controller.ledger.history(completed_controller.run_id)
        ) == 3,
        "controller_two_tenant_copies": controller_row_count == 6
        and controller_copy_count == 3,
        "idempotent_replay": all(value == binding for value in replay.values()),
        "restart_readback": all(value == binding for value in restarted.values()),
        "cross_tenant_current_hidden": isolated is None,
        "cross_tenant_controller_hidden": isolated_controller is None,
        "same_source_drift_rejected": drift_rejected,
    }
    return admission, checks, completed_controller


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minio-image", default=DEFAULT_MINIO_IMAGE)
    parser.add_argument("--mc-image", default=DEFAULT_MC_IMAGE)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")

    report: dict[str, Any]
    minio = _TemporaryMinio(args.minio_image, args.mc_image)
    try:
        minio.start()
        source_manifest, object_manifest = _run_minio(minio)
        control_manifest = _control_manifest()
        with _temporary_postgres(args.database_url) as postgres:
            _install_binding_authority(postgres)
            admission, checks, completed_controller = _run_postgres(
                postgres,
                source_control=control_manifest,
                restored_control=control_manifest,
                source_objects=source_manifest,
                restored_objects=object_manifest,
            )
        binding = admission.binding
        report = {
            "schema": "gda.cross_store_recovery_binding.acceptance.v1",
            "status": "passed" if all(checks.values()) else "failed",
            "database_scope": "temporary_database_only",
            "provider": {"name": "minio", "persistent": False},
            "tenant_ids": list(binding.tenant_ids),
            "source_resource_version_ref": binding.source_resource_version_ref,
            "source_manifest_sha256": source_manifest.manifest_sha256,
            "control_manifest_sha256": control_manifest.manifest_sha256,
            "object_manifest_sha256": object_manifest.manifest_sha256,
            "binding_sha256": binding.binding_sha256,
            "controller_state": completed_controller.as_dict(),
            "controller_ledger_scope": "temporary_postgresql_database",
            "checks": checks,
            "not_claimed": [
                "cross-store atomic commit or distributed transaction",
                "production PostGIS/MinIO HA, replication, PITR, RPO or RTO",
            ],
        }
    except Exception as exc:
        report = {
            "schema": "gda.cross_store_recovery_binding.acceptance.v1",
            "status": "failed",
            "error": str(exc)[:1000],
        }
    finally:
        cleanup = minio.cleanup()
    report["cleanup"] = cleanup
    if not all(cleanup.values()):
        report["status"] = "failed"
    report["report_sha256"] = canonical_json_fingerprint(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(args.report),
                "report_sha256": report["report_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
