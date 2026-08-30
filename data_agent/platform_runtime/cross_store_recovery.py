"""Cross-store recovery identity binding.

The control ledger and object store cannot be committed in one local database
transaction.  This contract therefore binds their recovery evidence to the
same source ResourceVersion and tenant set, then compares the complete pair as
one admission unit.  It does not claim atomic provider commits.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from .object_recovery import (
    OBJECT_RECOVERY_MANIFEST_SCHEMA,
    TenantObjectRecoveryManifest,
)
from .tenant_recovery import RECOVERY_MANIFEST_SCHEMA, TenantRecoveryManifest

CROSS_STORE_RECOVERY_SCHEMA = "gda.cross_store_recovery_binding.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CrossStoreRecoveryContractError(ValueError):
    """The control and object recovery evidence cannot be admitted together."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def _require_sha256(value: str, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise CrossStoreRecoveryContractError(f"{field} must be a lowercase 64-character SHA-256")
    return value


@dataclass(frozen=True)
class CrossStoreRecoveryBinding:
    """Immutable identity joining one control and one object recovery manifest."""

    schema: str
    tenant_ids: tuple[str, ...]
    source_resource_version_ref: str
    source_content_sha256: str
    control_manifest_sha256: str
    object_manifest_sha256: str
    binding_sha256: str

    def payload(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "tenant_ids": list(self.tenant_ids),
            "source_resource_version_ref": self.source_resource_version_ref,
            "source_content_sha256": self.source_content_sha256,
            "control_manifest_sha256": self.control_manifest_sha256,
            "object_manifest_sha256": self.object_manifest_sha256,
        }

    def as_dict(self) -> dict[str, Any]:
        return {**self.payload(), "binding_sha256": self.binding_sha256}

    def validate(self) -> None:
        if self.schema != CROSS_STORE_RECOVERY_SCHEMA:
            raise CrossStoreRecoveryContractError("unsupported cross-store recovery schema")
        if (
            not self.tenant_ids
            or any(not isinstance(tenant, str) or not tenant.strip() for tenant in self.tenant_ids)
            or tuple(sorted(set(self.tenant_ids))) != self.tenant_ids
        ):
            raise CrossStoreRecoveryContractError(
                "cross-store tenant ids must be sorted and unique"
            )
        if (
            not isinstance(self.source_resource_version_ref, str)
            or not self.source_resource_version_ref.strip()
        ):
            raise CrossStoreRecoveryContractError("source ResourceVersion reference is required")
        _require_sha256(self.source_content_sha256, "source_content_sha256")
        _require_sha256(self.control_manifest_sha256, "control_manifest_sha256")
        _require_sha256(self.object_manifest_sha256, "object_manifest_sha256")
        expected = hashlib.sha256(_canonical_bytes(self.payload())).hexdigest()
        if self.binding_sha256 != expected:
            raise CrossStoreRecoveryContractError(
                "cross-store recovery binding fingerprint is invalid"
            )


def build_cross_store_recovery_binding(
    control_manifest: TenantRecoveryManifest,
    object_manifest: TenantObjectRecoveryManifest,
    *,
    source_resource_version_ref: str,
    source_content_sha256: str,
) -> CrossStoreRecoveryBinding:
    """Bind manifests only when they cover the same tenant set and schemas."""

    if control_manifest.schema != RECOVERY_MANIFEST_SCHEMA:
        raise CrossStoreRecoveryContractError("unsupported control recovery manifest schema")
    if object_manifest.schema != OBJECT_RECOVERY_MANIFEST_SCHEMA:
        raise CrossStoreRecoveryContractError("unsupported object recovery manifest schema")
    if control_manifest.manifest_sha256 != hashlib.sha256(
        _canonical_bytes(control_manifest.payload())
    ).hexdigest():
        raise CrossStoreRecoveryContractError("control recovery manifest fingerprint is invalid")
    if object_manifest.manifest_sha256 != hashlib.sha256(
        _canonical_bytes(object_manifest.payload())
    ).hexdigest():
        raise CrossStoreRecoveryContractError("object recovery manifest fingerprint is invalid")
    control_tenants = tuple(sorted(control_manifest.tenant_ids))
    object_tenants = tuple(sorted(tenant for tenant, _ in object_manifest.tenant_prefixes))
    if control_tenants != object_tenants:
        raise CrossStoreRecoveryContractError(
            "control and object recovery manifests cover different tenants"
        )
    values = {
        "schema": CROSS_STORE_RECOVERY_SCHEMA,
        "tenant_ids": control_tenants,
        "source_resource_version_ref": source_resource_version_ref,
        "source_content_sha256": source_content_sha256,
        "control_manifest_sha256": control_manifest.manifest_sha256,
        "object_manifest_sha256": object_manifest.manifest_sha256,
    }
    binding = CrossStoreRecoveryBinding(
        **values,
        binding_sha256=hashlib.sha256(_canonical_bytes(values)).hexdigest(),
    )
    binding.validate()
    return binding


def compare_cross_store_recovery_bindings(
    source: CrossStoreRecoveryBinding,
    restored: CrossStoreRecoveryBinding,
) -> None:
    """Require the control/object pair to restore as one source identity."""

    source.validate()
    restored.validate()
    if source.as_dict() != restored.as_dict():
        raise CrossStoreRecoveryContractError("cross-store recovery binding differs")
