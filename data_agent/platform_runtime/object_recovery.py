"""Tenant-scoped object recovery contracts.

Object storage recovery has two independent invariants: the restored bytes must
match the source inventory, and a tenant credential must never operate outside
its assigned key prefix.  This module keeps those checks provider-neutral so a
MinIO/S3 rehearsal and a production adapter can share the same admission logic.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

OBJECT_RECOVERY_MANIFEST_SCHEMA = "gda.tenant_object_recovery_manifest.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class TenantObjectRecoveryContractError(ValueError):
    """The object inventory or scoped operation cannot be admitted."""


def sha256_bytes(payload: bytes) -> str:
    """Return the exact byte digest used by the recovery manifest."""

    return hashlib.sha256(payload).hexdigest()


def _require_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TenantObjectRecoveryContractError(f"{field} must be non-empty")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise TenantObjectRecoveryContractError(f"{field} contains a control character")
    return value


def validate_tenant_prefix(tenant_id: str, prefix: str) -> None:
    """Validate a canonical, tenant-owned S3 prefix."""

    _require_text(tenant_id, "tenant_id")
    prefix = _require_text(prefix, "prefix")
    if not prefix.endswith("/") or prefix.startswith("/"):
        raise TenantObjectRecoveryContractError("tenant prefix must be relative and end with '/'")
    prefix_parts = prefix.rstrip("/").split("/")
    if "//" in prefix or any(part in {"", ".", ".."} for part in prefix_parts):
        raise TenantObjectRecoveryContractError("tenant prefix contains an unsafe path segment")


def validate_tenant_prefixes(tenant_prefixes: Mapping[str, str]) -> dict[str, str]:
    """Normalize and reject duplicate or overlapping tenant prefixes."""

    if not isinstance(tenant_prefixes, Mapping) or not tenant_prefixes:
        raise TenantObjectRecoveryContractError("at least one tenant prefix is required")
    normalized = {
        _require_text(tenant, "tenant_id"): _require_text(prefix, "prefix")
        for tenant, prefix in tenant_prefixes.items()
    }
    if len(normalized) != len(tenant_prefixes):
        raise TenantObjectRecoveryContractError("tenant prefixes must have unique tenant ids")
    for tenant, prefix in normalized.items():
        validate_tenant_prefix(tenant, prefix)
    values = list(normalized.items())
    for left_tenant, left_prefix in values:
        for right_tenant, right_prefix in values:
            if left_tenant == right_tenant:
                continue
            if left_prefix == right_prefix or left_prefix.startswith(right_prefix):
                raise TenantObjectRecoveryContractError(
                    f"tenant prefixes overlap: {left_tenant} and {right_tenant}"
                )
    return dict(sorted(normalized.items()))


def validate_tenant_object_key(tenant_id: str, prefix: str, key: str) -> None:
    """Fail closed when an object key is outside its tenant prefix."""

    validate_tenant_prefix(tenant_id, prefix)
    key = _require_text(key, "key")
    if key.startswith("/") or "//" in key:
        raise TenantObjectRecoveryContractError("object key is not a canonical relative key")
    relative = key[len(prefix) :] if key.startswith(prefix) else None
    if relative is None or not relative:
        raise TenantObjectRecoveryContractError(
            f"object key is outside tenant prefix for {tenant_id}"
        )
    if any(part in {"", ".", ".."} for part in relative.split("/")):
        raise TenantObjectRecoveryContractError("object key contains an unsafe path segment")


@dataclass(frozen=True)
class TenantObjectDigest:
    tenant_id: str
    prefix: str
    key: str
    size_bytes: int
    etag: str
    version_id: str
    sha256: str

    def __post_init__(self) -> None:
        validate_tenant_object_key(self.tenant_id, self.prefix, self.key)
        if (
            not isinstance(self.size_bytes, int)
            or isinstance(self.size_bytes, bool)
            or self.size_bytes < 0
        ):
            raise TenantObjectRecoveryContractError("size_bytes must be a non-negative integer")
        etag = _require_text(self.etag, "etag").strip('"')
        version_id = _require_text(self.version_id, "version_id")
        if version_id.lower() == "null":
            raise TenantObjectRecoveryContractError("version_id must identify a version")
        digest = _require_text(self.sha256, "sha256").lower()
        if not _SHA256.fullmatch(digest):
            raise TenantObjectRecoveryContractError(
                "sha256 must be a lowercase 64-character hex digest"
            )
        object.__setattr__(self, "etag", etag)
        object.__setattr__(self, "sha256", digest)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "prefix": self.prefix,
            "key": self.key,
            "size_bytes": self.size_bytes,
            "etag": self.etag,
            "version_id": self.version_id,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class TenantObjectRecoveryManifest:
    schema: str
    tenant_prefixes: tuple[tuple[str, str], ...]
    objects: tuple[TenantObjectDigest, ...]
    manifest_sha256: str

    def payload(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "tenant_prefixes": [
                {"tenant_id": tenant_id, "prefix": prefix}
                for tenant_id, prefix in self.tenant_prefixes
            ],
            "objects": [item.as_dict() for item in self.objects],
        }

    def as_dict(self) -> dict[str, Any]:
        return {**self.payload(), "manifest_sha256": self.manifest_sha256}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def build_object_recovery_manifest(
    tenant_prefixes: Mapping[str, str], objects: Sequence[TenantObjectDigest]
) -> TenantObjectRecoveryManifest:
    """Build a deterministic source or restored object inventory."""

    normalized_prefixes = validate_tenant_prefixes(tenant_prefixes)
    unique: set[tuple[str, str]] = set()
    for item in objects:
        if item.tenant_id not in normalized_prefixes:
            raise TenantObjectRecoveryContractError("object belongs to an unregistered tenant")
        if item.prefix != normalized_prefixes[item.tenant_id]:
            raise TenantObjectRecoveryContractError("object prefix does not match tenant prefix")
        identity = (item.tenant_id, item.key)
        if identity in unique:
            raise TenantObjectRecoveryContractError("object inventory contains duplicate keys")
        unique.add(identity)
    ordered = tuple(sorted(objects, key=lambda item: (item.tenant_id, item.key)))
    prefix_items = tuple(sorted(normalized_prefixes.items()))
    payload = {
        "schema": OBJECT_RECOVERY_MANIFEST_SCHEMA,
        "tenant_prefixes": [
            {"tenant_id": tenant_id, "prefix": prefix}
            for tenant_id, prefix in prefix_items
        ],
        "objects": [item.as_dict() for item in ordered],
    }
    return TenantObjectRecoveryManifest(
        schema=OBJECT_RECOVERY_MANIFEST_SCHEMA,
        tenant_prefixes=prefix_items,
        objects=ordered,
        manifest_sha256=hashlib.sha256(_canonical_bytes(payload)).hexdigest(),
    )


def compare_object_recovery_manifests(
    source: TenantObjectRecoveryManifest,
    restored: TenantObjectRecoveryManifest,
    *,
    allow_version_id_remap: bool = False,
) -> None:
    """Require exact inventory, optionally allowing a destination version remap.

    A copy into a new versioned bucket receives a provider-generated VersionId.
    The default remains exact (including VersionId); the explicit remap mode is
    only for that copy boundary and still requires identical key, prefix, size,
    ETag and byte digest.
    """

    if (
        source.schema != OBJECT_RECOVERY_MANIFEST_SCHEMA
        or restored.schema != OBJECT_RECOVERY_MANIFEST_SCHEMA
    ):
        raise TenantObjectRecoveryContractError("unsupported object recovery manifest schema")
    for manifest in (source, restored):
        expected_hash = hashlib.sha256(_canonical_bytes(manifest.payload())).hexdigest()
        if manifest.manifest_sha256 != expected_hash:
            raise TenantObjectRecoveryContractError(
                "object recovery manifest fingerprint is invalid"
            )
    if source.as_dict() == restored.as_dict():
        return
    if allow_version_id_remap and source.tenant_prefixes == restored.tenant_prefixes:
        source_objects = tuple(
            (item.tenant_id, item.prefix, item.key, item.size_bytes, item.etag, item.sha256)
            for item in source.objects
        )
        restored_objects = tuple(
            (item.tenant_id, item.prefix, item.key, item.size_bytes, item.etag, item.sha256)
            for item in restored.objects
        )
        if source_objects == restored_objects and len(source.objects) == len(restored.objects):
            if any(
                source_item.version_id != restored_item.version_id
                for source_item, restored_item in zip(
                    source.objects, restored.objects, strict=True
                )
            ):
                return
    if source.as_dict() != restored.as_dict():
        raise TenantObjectRecoveryContractError("restored object recovery manifest differs")


@dataclass(frozen=True)
class TenantObjectScope:
    """Provider call guard for one tenant prefix."""

    tenant_id: str
    prefix: str

    def __post_init__(self) -> None:
        validate_tenant_prefix(self.tenant_id, self.prefix)

    def validate_key(self, key: str) -> str:
        validate_tenant_object_key(self.tenant_id, self.prefix, key)
        return key

    def head_object(self, client: Any, *, bucket: str, key: str) -> Any:
        return client.head_object(Bucket=bucket, Key=self.validate_key(key))

    def get_object(self, client: Any, *, bucket: str, key: str, **kwargs: Any) -> Any:
        return client.get_object(Bucket=bucket, Key=self.validate_key(key), **kwargs)

    def put_object(self, client: Any, *, bucket: str, key: str, **kwargs: Any) -> Any:
        return client.put_object(Bucket=bucket, Key=self.validate_key(key), **kwargs)

    def delete_object(self, client: Any, *, bucket: str, key: str, **kwargs: Any) -> Any:
        return client.delete_object(Bucket=bucket, Key=self.validate_key(key), **kwargs)

    def validate_listed_keys(self, keys: Sequence[str]) -> tuple[str, ...]:
        """Reject a provider listing that leaks an object outside this prefix."""

        normalized = tuple(sorted(keys))
        for key in normalized:
            self.validate_key(key)
        return normalized
