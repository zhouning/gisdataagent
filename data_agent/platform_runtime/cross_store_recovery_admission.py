"""Admission coordinator for a control-ledger/object-store recovery pair.

The coordinator is deliberately provider-neutral.  It verifies both restored
manifests, builds one source recovery identity, persists that identity through
the tenant-bound authority, and reads it back before admitting the pair.  An
object provider may issue new VersionIds during a copy; that is allowed only
when the object contract explicitly permits the remap and the source binding
continues to use the source inventory identity.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from .cross_store_recovery import (
    CrossStoreRecoveryBinding,
    CrossStoreRecoveryContractError,
    build_cross_store_recovery_binding,
)
from .object_recovery import (
    TenantObjectRecoveryManifest,
    compare_object_recovery_manifests,
)
from .tenant_recovery import TenantRecoveryManifest, compare_recovery_manifests


class CrossStoreRecoveryAdmissionError(CrossStoreRecoveryContractError):
    """The restored stores cannot be admitted as one recovery unit."""


class CrossStoreRecoveryBindingAuthority(Protocol):
    tenant_id: str

    def append(self, binding: CrossStoreRecoveryBinding) -> CrossStoreRecoveryBinding: ...

    def current(self, binding_sha256: str) -> CrossStoreRecoveryBinding | None: ...


@dataclass(frozen=True)
class CrossStoreRecoveryAdmission:
    """Durable evidence returned after a recovery pair is admitted."""

    binding: CrossStoreRecoveryBinding
    persisted_tenant_ids: tuple[str, ...]
    object_version_id_remap_allowed: bool


def admit_cross_store_recovery(
    *,
    source_control_manifest: TenantRecoveryManifest,
    restored_control_manifest: TenantRecoveryManifest,
    source_object_manifest: TenantObjectRecoveryManifest,
    restored_object_manifest: TenantObjectRecoveryManifest,
    source_resource_version_ref: str,
    source_content_sha256: str,
    authorities: Mapping[str, CrossStoreRecoveryBindingAuthority],
    allow_object_version_id_remap: bool = False,
) -> CrossStoreRecoveryAdmission:
    """Validate, persist, and re-read one cross-store recovery identity.

    The source manifests define the recovery identity.  The restored control
    manifest must be byte-for-byte equivalent; the restored object manifest may
    explicitly remap provider VersionIds, but its keys, sizes, ETags and bytes
    must still match the source inventory.
    """

    try:
        compare_recovery_manifests(source_control_manifest, restored_control_manifest)
        compare_object_recovery_manifests(
            source_object_manifest,
            restored_object_manifest,
            allow_version_id_remap=allow_object_version_id_remap,
        )
        binding = build_cross_store_recovery_binding(
            source_control_manifest,
            source_object_manifest,
            source_resource_version_ref=source_resource_version_ref,
            source_content_sha256=source_content_sha256,
        )
        binding.validate()
    except ValueError as exc:
        raise CrossStoreRecoveryAdmissionError(str(exc)) from exc

    expected_tenants = set(binding.tenant_ids)
    if set(authorities) != expected_tenants:
        raise CrossStoreRecoveryAdmissionError(
            "recovery authority set does not exactly cover binding tenants"
        )
    persisted: list[str] = []
    for tenant_id in binding.tenant_ids:
        authority = authorities[tenant_id]
        if getattr(authority, "tenant_id", tenant_id) != tenant_id:
            raise CrossStoreRecoveryAdmissionError(
                "recovery authority tenant identity differs"
            )
        try:
            stored = authority.append(binding)
            current = authority.current(binding.binding_sha256)
        except Exception as exc:
            if isinstance(exc, CrossStoreRecoveryAdmissionError):
                raise
            raise CrossStoreRecoveryAdmissionError(
                f"durable recovery binding authority failed for {tenant_id}"
            ) from exc
        if stored.as_dict() != binding.as_dict() or current is None:
            raise CrossStoreRecoveryAdmissionError(
                f"durable recovery binding read-back failed for {tenant_id}"
            )
        if current.as_dict() != binding.as_dict():
            raise CrossStoreRecoveryAdmissionError(
                f"durable recovery binding drifted for {tenant_id}"
            )
        persisted.append(tenant_id)

    return CrossStoreRecoveryAdmission(
        binding=binding,
        persisted_tenant_ids=tuple(persisted),
        object_version_id_remap_allowed=allow_object_version_id_remap,
    )


__all__ = [
    "CrossStoreRecoveryAdmission",
    "CrossStoreRecoveryAdmissionError",
    "CrossStoreRecoveryBindingAuthority",
    "admit_cross_store_recovery",
]
