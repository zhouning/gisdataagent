"""Best-effort shared response cache for governed MVT tiles.

The cache is a rebuildable performance projection. It never decides whether a
caller may read a tile; the Gateway performs that decision before looking here.
Redis failures therefore fall back to the Martin provider and are not allowed
to turn an authorized request into an outage.
"""

from __future__ import annotations

import base64
import inspect
import json
import os
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol

from .observability import get_logger
from .platform_contracts import canonical_json_fingerprint

logger = get_logger("gis_mvt_response_cache")
_MVT_MEDIA_TYPES = frozenset(
    {
        "application/vnd.mapbox-vector-tile",
        "application/x-protobuf",
        "application/octet-stream",
    }
)

# A release transition must produce a new cache generation even when the
# operator reuses the same human-facing cache namespace (for example when a
# service rolls back to an older release).  Keep the generation identity
# separate from the per-principal/tile object key so a future exact-prefix
# purge can remove one generation without touching another tenant or service.
MVT_CACHE_NAMESPACE_SCHEMA = "gda.gis_mvt_cache_namespace.v1"
_CACHE_NAMESPACE_RE = re.compile(r"^[0-9a-f]{64}$")
_CACHE_KEY_PREFIX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_-]{0,127}$")
_NAMESPACE_CONTEXT_KEYS = (
    "namespace",
    "tenant_id",
    "service_urn",
    "service_release_binding_id",
    "service_release_sha256",
    "cache_policy_version_id",
    "cache_policy_sha256",
    "service_policy_binding_id",
    "service_policy_sha256",
    "mvt_serving_projection_version_id",
    "mvt_serving_projection_sha256",
    "endpoint_state_version",
    "endpoint_revision_id",
    "endpoint_sha256",
)
_OBJECT_CONTEXT_KEYS = (
    "principal",
    "service_consumer_binding_id",
    "service_consumer_binding_sha256",
    "tile",
)

try:
    import redis.asyncio as redis_async

    HAS_REDIS = True
except ImportError:  # pragma: no cover - exercised in minimal installations.
    redis_async = None  # type: ignore[assignment]
    HAS_REDIS = False


@dataclass(frozen=True)
class MVTResponseCacheEntry:
    content: bytes
    media_type: str
    content_sha256: str

    @classmethod
    def from_response(cls, content: bytes, media_type: str) -> MVTResponseCacheEntry:
        return cls(content, media_type, sha256(content).hexdigest())

    def validate(self, *, max_object_bytes: int) -> bool:
        return (
            bool(self.content)
            and len(self.content) <= max_object_bytes
            and len(self.content_sha256) == 64
            and self.content_sha256 == sha256(self.content).hexdigest()
            and self.media_type in _MVT_MEDIA_TYPES
        )


class MVTCachePurgeError(RuntimeError):
    """Raised when an exact cache-generation purge cannot be certified."""


@dataclass(frozen=True)
class MVTCachePurgeResult:
    enabled: bool
    namespace: str
    matched_keys: int
    deleted_keys: int
    remaining_keys: int


class MVTResponseCache(Protocol):
    enabled: bool

    async def get(self, key: str) -> MVTResponseCacheEntry | None: ...

    async def put(
        self, key: str, entry: MVTResponseCacheEntry, *, ttl_seconds: int
    ) -> None: ...

    async def purge_namespace(
        self, namespace: str, *, max_keys: int = 10_000, scan_count: int = 100
    ) -> MVTCachePurgeResult: ...

    async def aclose(self) -> None: ...


class DisabledMVTResponseCache:
    enabled = False

    async def get(self, key: str) -> MVTResponseCacheEntry | None:
        return None

    async def put(
        self, key: str, entry: MVTResponseCacheEntry, *, ttl_seconds: int
    ) -> None:
        return None

    async def purge_namespace(
        self, namespace: str, *, max_keys: int = 10_000, scan_count: int = 100
    ) -> MVTCachePurgeResult:
        _validate_purge_parameters(namespace, max_keys=max_keys, scan_count=scan_count)
        return MVTCachePurgeResult(False, namespace, 0, 0, 0)

    async def aclose(self) -> None:
        return None


class RedisMVTResponseCache:
    """Binary-safe Redis cache with fail-open network behavior."""

    schema = "gda.gis_mvt_response_cache_entry.v1"
    enabled = True

    def __init__(
        self,
        *,
        redis_url: str,
        key_prefix: str = "gda:mvt:response:v1",
        max_object_bytes: int = 1_048_576,
        socket_timeout_seconds: float = 0.5,
        client: Any | None = None,
    ) -> None:
        if not redis_url:
            raise ValueError("redis_url is required")
        if _CACHE_KEY_PREFIX_RE.fullmatch(key_prefix) is None:
            raise ValueError("key_prefix contains unsafe Redis pattern characters")
        if max_object_bytes < 1:
            raise ValueError("max_object_bytes must be positive")
        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self.max_object_bytes = max_object_bytes
        self.socket_timeout_seconds = socket_timeout_seconds
        self._client = client

    async def _get_client(self) -> Any:
        if self._client is None:
            if not HAS_REDIS or redis_async is None:
                raise RuntimeError("redis package is not installed")
            self._client = redis_async.from_url(
                self.redis_url,
                decode_responses=False,
                socket_connect_timeout=self.socket_timeout_seconds,
                socket_timeout=self.socket_timeout_seconds,
            )
        return self._client

    def _redis_key(self, key: str) -> str:
        return f"{self.key_prefix}:{key}"

    def _namespace_prefix(self, namespace: str) -> str:
        _validate_cache_namespace(namespace)
        return f"{self.key_prefix}:{namespace}:"

    async def get(self, key: str) -> MVTResponseCacheEntry | None:
        try:
            redis = await self._get_client()
            redis_key = self._redis_key(key)
            raw = await redis.get(redis_key)
            if raw is None:
                return None
        except Exception as exc:
            logger.debug("MVT Redis cache read failed; falling back to provider: %s", exc)
            return None
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            payload = json.loads(raw)
            if payload.get("schema") != self.schema:
                raise ValueError("cache schema mismatch")
            content = base64.b64decode(payload["content_b64"], validate=True)
            entry = MVTResponseCacheEntry(
                content=content,
                media_type=str(payload["media_type"]),
                content_sha256=str(payload["content_sha256"]),
            )
            if not entry.validate(max_object_bytes=self.max_object_bytes):
                raise ValueError("cache entry validation failed")
            return entry
        except Exception as exc:
            logger.debug("invalid MVT Redis cache entry discarded: %s", exc)
            try:
                await redis.delete(redis_key)
            except Exception:
                pass
            return None

    async def put(
        self, key: str, entry: MVTResponseCacheEntry, *, ttl_seconds: int
    ) -> None:
        if not entry.validate(max_object_bytes=self.max_object_bytes):
            return
        if ttl_seconds < 1:
            return
        payload = json.dumps(
            {
                "schema": self.schema,
                "media_type": entry.media_type,
                "content_sha256": entry.content_sha256,
                "content_b64": base64.b64encode(entry.content).decode("ascii"),
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        try:
            redis = await self._get_client()
            await redis.set(self._redis_key(key), payload, ex=int(ttl_seconds))
        except Exception as exc:
            logger.debug("MVT Redis cache write failed; provider response remains valid: %s", exc)

    async def purge_namespace(
        self,
        namespace: str,
        *,
        max_keys: int = 10_000,
        scan_count: int = 100,
    ) -> MVTCachePurgeResult:
        """Delete one exact generation without deleting unrelated Redis keys.

        Keys are collected before deletion so an operator cannot partially
        purge a generation merely because it exceeded the configured safety
        bound.  ``UNLINK`` keeps the deletion non-blocking for large MVT
        payloads; a final exact-prefix scan is required before reporting
        success.
        """

        _validate_purge_parameters(namespace, max_keys=max_keys, scan_count=scan_count)
        prefix = self._namespace_prefix(namespace)
        try:
            redis = await self._get_client()
            keys = await _scan_namespace_keys(
                redis, prefix, max_keys=max_keys, scan_count=scan_count
            )
            if keys:
                deleted = int(await redis.unlink(*keys))
            else:
                deleted = 0
            remaining = await _count_namespace_keys(
                redis, prefix, max_keys=max_keys, scan_count=scan_count
            )
            if remaining:
                raise MVTCachePurgeError(
                    f"MVT cache namespace purge left {remaining} keys"
                )
            result = MVTCachePurgeResult(
                True, namespace, len(keys), deleted, remaining
            )
            logger.info(
                "MVT cache namespace purged namespace=%s matched=%d deleted=%d",
                namespace,
                result.matched_keys,
                result.deleted_keys,
            )
            return result
        except MVTCachePurgeError:
            raise
        except Exception as exc:
            logger.warning(
                "MVT cache namespace purge failed namespace=%s: %s", namespace, exc
            )
            raise MVTCachePurgeError("MVT cache namespace purge failed") from exc

    async def aclose(self) -> None:
        client = self._client
        self._client = None
        if client is None:
            return
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result


_default_cache: MVTResponseCache | None = None


def get_mvt_response_cache() -> MVTResponseCache:
    """Return the process-local cache projection configured for this Gateway."""

    global _default_cache
    if _default_cache is not None:
        return _default_cache
    redis_url = os.getenv("GDA_GIS_MVT_CACHE_REDIS_URL")
    if not redis_url or not HAS_REDIS:
        _default_cache = DisabledMVTResponseCache()
        return _default_cache
    try:
        _default_cache = RedisMVTResponseCache(
            redis_url=redis_url,
            key_prefix=os.getenv("GDA_GIS_MVT_CACHE_KEY_PREFIX", "gda:mvt:response:v1"),
            max_object_bytes=int(
                os.getenv("GDA_GIS_MVT_CACHE_MAX_OBJECT_BYTES", "1048576")
            ),
            socket_timeout_seconds=float(
                os.getenv("GDA_GIS_MVT_CACHE_TIMEOUT_SECONDS", "0.5")
            ),
        )
    except (TypeError, ValueError):
        logger.warning("invalid GIS MVT cache configuration; shared cache disabled")
        _default_cache = DisabledMVTResponseCache()
    return _default_cache


def reset_mvt_response_cache() -> None:
    global _default_cache
    _default_cache = None


def _validate_cache_namespace(namespace: str) -> None:
    if _CACHE_NAMESPACE_RE.fullmatch(namespace) is None:
        raise ValueError("cache namespace must be a lowercase SHA-256 token")


def _validate_purge_parameters(
    namespace: str, *, max_keys: int, scan_count: int
) -> None:
    _validate_cache_namespace(namespace)
    if max_keys < 1 or max_keys > 100_000:
        raise ValueError("max_keys must be between 1 and 100000")
    if scan_count < 1 or scan_count > 10_000:
        raise ValueError("scan_count must be between 1 and 10000")


async def _scan_namespace_keys(
    redis: Any,
    prefix: str,
    *,
    max_keys: int,
    scan_count: int,
) -> list[str | bytes]:
    keys: list[str | bytes] = []
    seen: set[str | bytes] = set()
    async for key in redis.scan_iter(match=f"{prefix}*", count=scan_count):
        if key in seen:
            continue
        seen.add(key)
        keys.append(key)
        if len(keys) > max_keys:
            raise MVTCachePurgeError(
                f"MVT cache namespace exceeds purge bound of {max_keys} keys"
            )
    return keys


async def _count_namespace_keys(
    redis: Any,
    prefix: str,
    *,
    max_keys: int,
    scan_count: int,
) -> int:
    keys: set[str | bytes] = set()
    async for key in redis.scan_iter(match=f"{prefix}*", count=scan_count):
        keys.add(key)
        if len(keys) > max_keys:
            raise MVTCachePurgeError(
                f"MVT cache namespace exceeds purge bound of {max_keys} keys"
            )
    return len(keys)


def mvt_response_cache_key(cache_context: dict[str, Any]) -> str:
    """Build an opaque ``generation:object`` Redis key suffix."""

    namespace = mvt_response_cache_namespace(cache_context)
    object_context = {
        "schema": "gda.gis_mvt_response_cache_object.v1",
        "namespace": namespace,
        **{key: cache_context[key] for key in _OBJECT_CONTEXT_KEYS if key in cache_context},
    }
    object_token = canonical_json_fingerprint(object_context)
    return f"{namespace}:{object_token}"


def mvt_response_cache_namespace(cache_context: dict[str, Any]) -> str:
    """Return the generation token changed by release/policy/pointer transitions.

    The token intentionally excludes principal, binding and tile coordinates.
    Those dimensions remain in :func:`mvt_response_cache_key`; keeping them
    out of the generation makes an exact namespace rollover possible without
    ever deleting unrelated tenants, services or Redis keys.
    """

    namespace_context = {
        "schema": MVT_CACHE_NAMESPACE_SCHEMA,
        **{
            key: cache_context[key]
            for key in _NAMESPACE_CONTEXT_KEYS
            if key in cache_context
        },
    }
    return canonical_json_fingerprint(namespace_context)
