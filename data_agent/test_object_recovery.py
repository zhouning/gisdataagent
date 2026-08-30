from dataclasses import replace

import pytest

from data_agent.platform_runtime.object_recovery import (
    TenantObjectDigest,
    TenantObjectRecoveryContractError,
    TenantObjectScope,
    build_object_recovery_manifest,
    compare_object_recovery_manifests,
    sha256_bytes,
    validate_tenant_prefixes,
)

TENANTS = {"tenant-a": "tenants/tenant-a/", "tenant-b": "tenants/tenant-b/"}


def _object(tenant_id: str, name: str, payload: bytes = b"payload") -> TenantObjectDigest:
    prefix = TENANTS[tenant_id]
    return TenantObjectDigest(
        tenant_id=tenant_id,
        prefix=prefix,
        key=f"{prefix}{name}",
        size_bytes=len(payload),
        etag="etag-" + tenant_id,
        version_id="version-" + tenant_id,
        sha256=sha256_bytes(payload),
    )


def _manifest(objects: tuple[TenantObjectDigest, ...]):
    return build_object_recovery_manifest(TENANTS, objects)


def test_manifest_is_stable_across_inventory_order_and_key_order() -> None:
    source = _manifest((_object("tenant-b", "roads.json"), _object("tenant-a", "roads.json")))
    restored = _manifest((_object("tenant-a", "roads.json"), _object("tenant-b", "roads.json")))
    compare_object_recovery_manifests(source, restored)
    assert source.manifest_sha256 == restored.manifest_sha256


@pytest.mark.parametrize(
    "changed",
    [
        lambda item: replace(item, etag="different-etag"),
        lambda item: replace(item, version_id="different-version"),
        lambda item: replace(item, sha256=sha256_bytes(b"different-bytes")),
        lambda item: replace(item, size_bytes=item.size_bytes + 1),
    ],
)
def test_provider_revision_and_bytes_mismatch_fail_closed(changed) -> None:
    source_item = _object("tenant-a", "roads.json")
    source = _manifest((source_item, _object("tenant-b", "roads.json")))
    restored = _manifest((changed(source_item), _object("tenant-b", "roads.json")))
    with pytest.raises(TenantObjectRecoveryContractError, match="differs"):
        compare_object_recovery_manifests(source, restored)


def test_missing_and_extra_objects_fail_closed() -> None:
    source = _manifest((_object("tenant-a", "roads.json"), _object("tenant-b", "roads.json")))
    missing = _manifest((_object("tenant-a", "roads.json"),))
    extra = _manifest(
        (
            _object("tenant-a", "roads.json"),
            _object("tenant-b", "roads.json"),
            _object("tenant-b", "buildings.json"),
        )
    )
    for candidate in (missing, extra):
        with pytest.raises(TenantObjectRecoveryContractError, match="differs"):
            compare_object_recovery_manifests(source, candidate)


def test_manifest_hash_tamper_fails_closed() -> None:
    source = _manifest((_object("tenant-a", "roads.json"), _object("tenant-b", "roads.json")))
    tampered = replace(source, manifest_sha256="0" * 64)
    with pytest.raises(TenantObjectRecoveryContractError, match="fingerprint is invalid"):
        compare_object_recovery_manifests(source, tampered)


def test_new_bucket_restore_can_explicitly_remap_provider_version_ids() -> None:
    source_item = _object("tenant-a", "roads.json")
    source = _manifest((source_item, _object("tenant-b", "roads.json")))
    restored = _manifest(
        (
            replace(source_item, version_id="destination-version-a"),
            replace(source.objects[1], version_id="destination-version-b"),
        )
    )
    with pytest.raises(TenantObjectRecoveryContractError, match="differs"):
        compare_object_recovery_manifests(source, restored)
    compare_object_recovery_manifests(source, restored, allow_version_id_remap=True)


def test_version_remap_does_not_allow_etag_or_byte_drift() -> None:
    source_item = _object("tenant-a", "roads.json")
    source = _manifest((source_item, _object("tenant-b", "roads.json")))
    restored = _manifest(
        (
            replace(source_item, version_id="destination-version-a", etag="wrong-etag"),
            replace(source.objects[1], version_id="destination-version-b"),
        )
    )
    with pytest.raises(TenantObjectRecoveryContractError, match="differs"):
        compare_object_recovery_manifests(source, restored, allow_version_id_remap=True)


def test_prefixes_must_be_disjoint_and_objects_must_use_registered_prefix() -> None:
    with pytest.raises(TenantObjectRecoveryContractError, match="overlap"):
        validate_tenant_prefixes({"tenant-a": "tenants/", "tenant-b": "tenants/tenant-b/"})
    with pytest.raises(TenantObjectRecoveryContractError, match="outside"):
        TenantObjectDigest(
            tenant_id="tenant-a",
            prefix=TENANTS["tenant-a"],
            key="tenants/tenant-b/leak.json",
            size_bytes=1,
            etag="etag",
            version_id="version",
            sha256=sha256_bytes(b"x"),
        )


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def _call(self, method: str, key: str):
        self.calls.append((method, key))
        return {"Key": key}

    def head_object(self, *, Bucket: str, Key: str):
        return self._call("head", Key)

    def get_object(self, *, Bucket: str, Key: str, **kwargs):
        return self._call("get", Key)

    def put_object(self, *, Bucket: str, Key: str, **kwargs):
        return self._call("put", Key)

    def delete_object(self, *, Bucket: str, Key: str, **kwargs):
        return self._call("delete", Key)


@pytest.mark.parametrize("operation", ("head_object", "get_object", "put_object", "delete_object"))
def test_scope_rejects_cross_tenant_read_write_delete_before_provider_call(operation: str) -> None:
    client = _RecordingClient()
    scope = TenantObjectScope("tenant-a", TENANTS["tenant-a"])
    with pytest.raises(TenantObjectRecoveryContractError, match="outside"):
        getattr(scope, operation)(client, bucket="bucket", key="tenants/tenant-b/leak.json")
    assert client.calls == []


def test_scope_allows_own_prefix_and_rejects_leaking_listing() -> None:
    client = _RecordingClient()
    scope = TenantObjectScope("tenant-a", TENANTS["tenant-a"])
    scope.put_object(client, bucket="bucket", key="tenants/tenant-a/roads.json", Body=b"x")
    assert client.calls == [("put", "tenants/tenant-a/roads.json")]
    assert scope.validate_listed_keys(
        ["tenants/tenant-a/z.json", "tenants/tenant-a/a.json"]
    ) == ("tenants/tenant-a/a.json", "tenants/tenant-a/z.json")
    with pytest.raises(TenantObjectRecoveryContractError, match="outside"):
        scope.validate_listed_keys(["tenants/tenant-a/a.json", "tenants/tenant-b/b.json"])
