from __future__ import annotations

from dataclasses import replace

import pytest

from data_agent.platform_runtime.cross_store_recovery import (
    CrossStoreRecoveryBinding,
)
from data_agent.platform_runtime.cross_store_recovery_admission import (
    CrossStoreRecoveryAdmissionError,
    admit_cross_store_recovery,
)
from data_agent.platform_runtime.object_recovery import (
    TenantObjectDigest,
    build_object_recovery_manifest,
    sha256_bytes,
)
from data_agent.platform_runtime.tenant_recovery import (
    build_recovery_manifest,
    fingerprint_tenant_rows,
)

TENANTS = {"tenant-a": "tenants/tenant-a/", "tenant-b": "tenants/tenant-b/"}


class MemoryAuthority:
    def __init__(self, tenant_id: str, *, drift: bool = False):
        self.tenant_id = tenant_id
        self._binding: CrossStoreRecoveryBinding | None = None
        self.drift = drift

    def append(self, binding: CrossStoreRecoveryBinding) -> CrossStoreRecoveryBinding:
        self._binding = binding
        return binding

    def current(self, binding_sha256: str) -> CrossStoreRecoveryBinding | None:
        if self._binding is None or self._binding.binding_sha256 != binding_sha256:
            return None
        if self.drift:
            return replace(self._binding, binding_sha256="0" * 64)
        return self._binding


def _manifests():
    control = build_recovery_manifest(
        tuple(TENANTS),
        tuple(
            fingerprint_tenant_rows(tenant, "resource_version", [{"tenant": tenant}])
            for tenant in TENANTS
        ),
    )
    objects = build_object_recovery_manifest(
        TENANTS,
        tuple(
            TenantObjectDigest(
                tenant_id=tenant,
                prefix=prefix,
                key=f"{prefix}roads.json",
                size_bytes=1,
                etag=f"etag-{tenant}",
                version_id=f"source-version-{tenant}",
                sha256=sha256_bytes(b"x"),
            )
            for tenant, prefix in TENANTS.items()
        ),
    )
    return control, objects


def _admit(
    *,
    restored_control=None,
    restored_objects=None,
    authorities=None,
    allow_remap=False,
):
    control, objects = _manifests()
    return admit_cross_store_recovery(
        source_control_manifest=control,
        restored_control_manifest=restored_control or control,
        source_object_manifest=objects,
        restored_object_manifest=restored_objects or objects,
        source_resource_version_ref="gda://tenant-a/data_product/source/v1",
        source_content_sha256="a" * 64,
        authorities=authorities
        or {tenant: MemoryAuthority(tenant) for tenant in TENANTS},
        allow_object_version_id_remap=allow_remap,
    )


def test_admission_persists_and_reads_one_source_identity_for_each_tenant():
    authorities = {tenant: MemoryAuthority(tenant) for tenant in TENANTS}
    result = _admit(authorities=authorities)

    assert result.persisted_tenant_ids == tuple(TENANTS)
    assert result.binding.tenant_ids == tuple(TENANTS)
    assert all(
        authority.current(result.binding.binding_sha256) == result.binding
        for authority in authorities.values()
    )


def test_admission_allows_explicit_object_version_remap_without_changing_source_identity():
    control, objects = _manifests()
    restored_objects = build_object_recovery_manifest(
        TENANTS,
        tuple(
            replace(item, version_id=f"restored-{item.version_id}")
            for item in objects.objects
        ),
    )
    result = _admit(
        restored_objects=restored_objects,
        allow_remap=True,
    )

    assert result.object_version_id_remap_allowed is True
    assert result.binding.object_manifest_sha256 == objects.manifest_sha256


def test_admission_rejects_object_remap_without_explicit_opt_in():
    _, objects = _manifests()
    restored_objects = build_object_recovery_manifest(
        TENANTS,
        tuple(replace(item, version_id=f"restored-{item.version_id}") for item in objects.objects),
    )
    with pytest.raises(CrossStoreRecoveryAdmissionError, match="differs"):
        _admit(restored_objects=restored_objects)


def test_admission_rejects_control_drift_and_authority_set_drift():
    control, _ = _manifests()
    changed_control = build_recovery_manifest(
        tuple(TENANTS),
        tuple(
            fingerprint_tenant_rows(tenant, "resource_version", [{"tenant": "changed"}])
            for tenant in TENANTS
        ),
    )
    with pytest.raises(CrossStoreRecoveryAdmissionError, match="differs"):
        _admit(restored_control=changed_control)
    with pytest.raises(CrossStoreRecoveryAdmissionError, match="exactly cover"):
        _admit(authorities={"tenant-a": MemoryAuthority("tenant-a")})


def test_admission_rejects_durable_readback_drift():
    with pytest.raises(CrossStoreRecoveryAdmissionError, match="drifted"):
        _admit(
            authorities={
                "tenant-a": MemoryAuthority("tenant-a", drift=True),
                "tenant-b": MemoryAuthority("tenant-b"),
            }
        )
