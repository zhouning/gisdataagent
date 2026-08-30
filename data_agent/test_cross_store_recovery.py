import hashlib
import json
from dataclasses import replace

import pytest

from data_agent.platform_runtime.cross_store_recovery import (
    CrossStoreRecoveryContractError,
    build_cross_store_recovery_binding,
    compare_cross_store_recovery_bindings,
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


def _control(tenants: tuple[str, ...] = ("tenant-a", "tenant-b")):
    tables = tuple(
        fingerprint_tenant_rows(tenant, "resource", [{"source": tenant}])
        for tenant in tenants
    )
    return build_recovery_manifest(tenants, tables)


def _objects(tenants: dict[str, str] = TENANTS):
    objects = tuple(
        TenantObjectDigest(
            tenant_id=tenant,
            prefix=prefix,
            key=f"{prefix}roads.json",
            size_bytes=1,
            etag=f"etag-{tenant}",
            version_id=f"version-{tenant}",
            sha256=sha256_bytes(b"x"),
        )
        for tenant, prefix in tenants.items()
    )
    return build_object_recovery_manifest(tenants, objects)


def _binding(control=None, objects=None):
    return build_cross_store_recovery_binding(
        control or _control(),
        objects or _objects(),
        source_resource_version_ref="gda://tenant-a/data_product/source/v1",
        source_content_sha256="a" * 64,
    )


def test_binding_is_order_independent_and_restored_pair_matches():
    source = _binding()
    restored = _binding()
    compare_cross_store_recovery_bindings(source, restored)
    assert source.binding_sha256 == restored.binding_sha256


def test_different_tenant_set_is_rejected_before_binding():
    with pytest.raises(CrossStoreRecoveryContractError, match="different tenants"):
        _binding(control=_control(("tenant-a", "tenant-c")))


@pytest.mark.parametrize(
    "change",
    [
        lambda binding: replace(binding, source_resource_version_ref="gda://other/source/v1"),
        lambda binding: replace(binding, source_content_sha256="b" * 64),
        lambda binding: replace(binding, control_manifest_sha256="b" * 64),
        lambda binding: replace(binding, object_manifest_sha256="b" * 64),
    ],
)
def test_restored_pair_drift_is_rejected(change):
    source = _binding()
    changed = change(source)
    changed_payload = changed.payload()
    restored = replace(
        changed,
        binding_sha256=hashlib.sha256(
            json.dumps(
                changed_payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
    )
    with pytest.raises(CrossStoreRecoveryContractError, match="differs"):
        compare_cross_store_recovery_bindings(source, restored)


def test_binding_tamper_is_rejected_even_when_pair_values_are_unchanged():
    source = _binding()
    with pytest.raises(CrossStoreRecoveryContractError, match="fingerprint"):
        compare_cross_store_recovery_bindings(source, replace(source, binding_sha256="0" * 64))


@pytest.mark.parametrize("manifest_kind", ("control", "object"))
def test_manifest_tamper_is_rejected_before_cross_store_binding(manifest_kind):
    control = _control()
    objects = _objects()
    if manifest_kind == "control":
        control = replace(control, manifest_sha256="0" * 64)
    else:
        objects = replace(objects, manifest_sha256="0" * 64)
    with pytest.raises(CrossStoreRecoveryContractError, match="manifest fingerprint"):
        _binding(control=control, objects=objects)
