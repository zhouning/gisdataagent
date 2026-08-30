"""Tenant-scoped recovery evidence and visibility checks.

Recovery must preserve the logical ownership boundary as well as row counts.  This
module deliberately contains no database driver code: callers provide canonical
row projections from the source and restored stores, then use the resulting
manifest as an immutable comparison and admission artifact.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

RECOVERY_MANIFEST_SCHEMA = "gda.tenant_recovery_manifest.v1"


class TenantRecoveryContractError(ValueError):
    """The recovery evidence cannot prove tenant-preserving restoration."""


@dataclass(frozen=True)
class TenantTableDigest:
    tenant_id: str
    table_name: str
    row_count: int
    rows_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "table_name": self.table_name,
            "row_count": self.row_count,
            "rows_sha256": self.rows_sha256,
        }


@dataclass(frozen=True)
class TenantRecoveryManifest:
    schema: str
    tenant_ids: tuple[str, ...]
    tables: tuple[TenantTableDigest, ...]
    manifest_sha256: str

    def payload(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "tenant_ids": list(self.tenant_ids),
            "tables": [item.as_dict() for item in self.tables],
        }

    def as_dict(self) -> dict[str, Any]:
        return {**self.payload(), "manifest_sha256": self.manifest_sha256}


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (UUID,)):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, set):
        return sorted(_json_value(item) for item in value)
    return value


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _json_value(value), ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def fingerprint_tenant_rows(
    tenant_id: str, table_name: str, rows: Sequence[Mapping[str, Any]]
) -> TenantTableDigest:
    """Hash a stable, tenant-filtered row projection.

    Rows are sorted by their canonical encoding so SQL planner order and restore
    insertion order cannot change the identity.  The projection must not contain
    secrets; callers should select only the control/evidence columns needed for
    recovery comparison.
    """

    if not tenant_id or not table_name:
        raise TenantRecoveryContractError("tenant and table names are required")
    canonical_rows = sorted(_canonical_bytes(row) for row in rows)
    digest = hashlib.sha256()
    for row in canonical_rows:
        digest.update(row)
        digest.update(b"\n")
    return TenantTableDigest(
        tenant_id=tenant_id,
        table_name=table_name,
        row_count=len(canonical_rows),
        rows_sha256=digest.hexdigest(),
    )


def build_recovery_manifest(
    tenant_ids: Sequence[str], table_digests: Sequence[TenantTableDigest]
) -> TenantRecoveryManifest:
    """Build the immutable source/restored comparison manifest."""

    normalized_tenants = tuple(sorted(set(tenant_ids)))
    if not normalized_tenants or any(not item for item in normalized_tenants):
        raise TenantRecoveryContractError("at least one non-empty tenant is required")
    expected_keys = {
        (tenant, table)
        for tenant in normalized_tenants
        for table in {item.table_name for item in table_digests}
    }
    actual_keys = {(item.tenant_id, item.table_name) for item in table_digests}
    if actual_keys != expected_keys:
        raise TenantRecoveryContractError("every tenant must have every table digest")
    if len(actual_keys) != len(table_digests):
        raise TenantRecoveryContractError("table digests must be unique")
    tables = tuple(sorted(table_digests, key=lambda item: (item.tenant_id, item.table_name)))
    payload = {
        "schema": RECOVERY_MANIFEST_SCHEMA,
        "tenant_ids": list(normalized_tenants),
        "tables": [item.as_dict() for item in tables],
    }
    return TenantRecoveryManifest(
        schema=RECOVERY_MANIFEST_SCHEMA,
        tenant_ids=normalized_tenants,
        tables=tables,
        manifest_sha256=_sha256(_canonical_bytes(payload)),
    )


def compare_recovery_manifests(
    source: TenantRecoveryManifest, restored: TenantRecoveryManifest
) -> None:
    """Fail closed unless source and restored logical tenant inventories match."""

    if source.schema != RECOVERY_MANIFEST_SCHEMA or restored.schema != RECOVERY_MANIFEST_SCHEMA:
        raise TenantRecoveryContractError("unsupported recovery manifest schema")
    if source.as_dict() != restored.as_dict():
        raise TenantRecoveryContractError("restored tenant recovery manifest differs")


def validate_tenant_visibility(
    manifest: TenantRecoveryManifest,
    visible_rows_by_tenant: Mapping[str, Mapping[str, int]],
) -> None:
    """Check gateway-visible rows: own tenant may be visible, other tenants may not."""

    expected_tables = {item.table_name for item in manifest.tables}
    if set(visible_rows_by_tenant) != set(manifest.tenant_ids):
        raise TenantRecoveryContractError("visibility probe must cover every tenant")
    for tenant_id in manifest.tenant_ids:
        visible = visible_rows_by_tenant[tenant_id]
        if set(visible) != expected_tables:
            raise TenantRecoveryContractError("visibility probe table set is incomplete")
        for table_name, count in visible.items():
            if not isinstance(count, int) or count < 0:
                raise TenantRecoveryContractError("visibility counts must be non-negative integers")
            expected = next(
                item.row_count
                for item in manifest.tables
                if item.tenant_id == tenant_id and item.table_name == table_name
            )
            if count != expected:
                raise TenantRecoveryContractError(
                    f"tenant {tenant_id} visibility mismatch for {table_name}"
                )
