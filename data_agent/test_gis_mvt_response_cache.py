from __future__ import annotations

import json

import pytest

from data_agent.gis_mvt_response_cache import (
    DisabledMVTResponseCache,
    MVTCachePurgeError,
    MVTCachePurgeResult,
    MVTResponseCacheEntry,
    RedisMVTResponseCache,
    mvt_response_cache_key,
    mvt_response_cache_namespace,
)


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.expiries = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, *, ex):
        self.values[key] = value
        self.expiries[key] = ex

    async def delete(self, key):
        self.values.pop(key, None)

    async def unlink(self, *keys):
        deleted = 0
        for key in keys:
            if key in self.values:
                deleted += 1
                self.values.pop(key, None)
        return deleted

    async def scan_iter(self, *, match, count):
        prefix = match[:-1]
        for key in tuple(self.values):
            comparable = key.decode("utf-8") if isinstance(key, bytes) else key
            if comparable.startswith(prefix):
                yield key


@pytest.mark.asyncio
async def test_redis_mvt_cache_round_trips_binary_content_and_ttl():
    redis = FakeRedis()
    cache = RedisMVTResponseCache(redis_url="redis://fixture", client=redis)
    entry = MVTResponseCacheEntry.from_response(
        b"\x00\x01mvt", "application/x-protobuf"
    )

    await cache.put("key", entry, ttl_seconds=60)
    loaded = await cache.get("key")

    assert loaded == entry
    assert redis.expiries["gda:mvt:response:v1:key"] == 60
    assert b"\x00\x01mvt" not in redis.values["gda:mvt:response:v1:key"]


@pytest.mark.asyncio
async def test_redis_mvt_cache_discards_corrupt_entry():
    redis = FakeRedis()
    cache = RedisMVTResponseCache(redis_url="redis://fixture", client=redis)
    redis.values["gda:mvt:response:v1:key"] = json.dumps(
        {
            "schema": cache.schema,
            "media_type": "application/x-protobuf",
            "content_sha256": "0" * 64,
            "content_b64": "Y29ycnVwdA==",
        }
    ).encode()

    assert await cache.get("key") is None
    assert "gda:mvt:response:v1:key" not in redis.values


@pytest.mark.asyncio
async def test_redis_mvt_cache_rejects_non_mvt_media_type():
    redis = FakeRedis()
    cache = RedisMVTResponseCache(redis_url="redis://fixture", client=redis)
    await cache.put(
        "key",
        MVTResponseCacheEntry.from_response(b"payload", "application/json"),
        ttl_seconds=60,
    )
    assert redis.values == {}


def test_mvt_cache_key_is_stable_and_credential_free():
    context = {
        "tenant_id": "planning",
        "principal": "human:analyst-01",
        "tile": {"z": 0, "x": 0, "y": 0},
    }
    assert mvt_response_cache_key(context) == mvt_response_cache_key(
        {"tile": {"y": 0, "x": 0, "z": 0}, "principal": "human:analyst-01", "tenant_id": "planning"}
    )
    assert "secret" not in mvt_response_cache_key({**context, "token": "secret"})


def test_redis_mvt_cache_rejects_prefix_with_scan_pattern_characters():
    with pytest.raises(ValueError, match="unsafe Redis pattern"):
        RedisMVTResponseCache(
            redis_url="redis://fixture", key_prefix="gda:mvt:*", client=FakeRedis()
        )


def test_mvt_cache_namespace_rolls_over_on_release_or_pointer_transition():
    context = {
        "tenant_id": "planning",
        "service_urn": "gda://planning/gis_service/district-features",
        "service_release_binding_id": "release-a",
        "service_release_sha256": "a" * 64,
        "cache_policy_version_id": "cache-a",
        "cache_policy_sha256": "b" * 64,
        "service_policy_binding_id": "policy-a",
        "service_policy_sha256": "c" * 64,
        "mvt_serving_projection_version_id": "projection-a",
        "mvt_serving_projection_sha256": "d" * 64,
        "endpoint_state_version": 4,
        "endpoint_revision_id": "endpoint-a",
        "endpoint_sha256": "e" * 64,
        "principal": "human:analyst-01",
        "service_consumer_binding_id": "binding-a",
        "service_consumer_binding_sha256": "f" * 64,
        "tile": {"z": 0, "x": 0, "y": 0},
    }
    release_rollover = {**context, "service_release_binding_id": "release-b"}
    pointer_rollover = {**context, "endpoint_state_version": 5}

    assert mvt_response_cache_namespace(context) != mvt_response_cache_namespace(
        release_rollover
    )
    assert mvt_response_cache_namespace(context) != mvt_response_cache_namespace(
        pointer_rollover
    )
    # Principal and tile are object dimensions, not a new release generation.
    assert mvt_response_cache_namespace(context) == mvt_response_cache_namespace(
        {**context, "principal": "human:analyst-02", "tile": {"z": 1, "x": 0, "y": 0}}
    )
    first_key = mvt_response_cache_key(context)
    other_tile_key = mvt_response_cache_key(
        {**context, "tile": {"z": 1, "x": 0, "y": 0}}
    )
    namespace = mvt_response_cache_namespace(context)
    assert first_key.startswith(f"{namespace}:")
    assert other_tile_key.startswith(f"{namespace}:")
    assert first_key != other_tile_key


@pytest.mark.asyncio
async def test_redis_mvt_cache_purges_only_one_exact_generation():
    redis = FakeRedis()
    cache = RedisMVTResponseCache(redis_url="redis://fixture", client=redis)
    namespace = "a" * 64
    other_namespace = "b" * 64
    await cache.put(
        f"{namespace}:object-a",
        MVTResponseCacheEntry.from_response(b"a", "application/x-protobuf"),
        ttl_seconds=60,
    )
    await cache.put(
        f"{namespace}:object-b",
        MVTResponseCacheEntry.from_response(b"b", "application/x-protobuf"),
        ttl_seconds=60,
    )
    await cache.put(
        f"{other_namespace}:object-a",
        MVTResponseCacheEntry.from_response(b"other", "application/x-protobuf"),
        ttl_seconds=60,
    )
    redis.values["gda:mvt:response:v1:unrelated"] = b"keep"

    result = await cache.purge_namespace(namespace)

    assert result == MVTCachePurgeResult(True, namespace, 2, 2, 0)
    assert set(redis.values) == {
        f"gda:mvt:response:v1:{other_namespace}:object-a",
        "gda:mvt:response:v1:unrelated",
    }


@pytest.mark.asyncio
async def test_redis_mvt_cache_purge_refuses_unbounded_generation():
    redis = FakeRedis()
    cache = RedisMVTResponseCache(redis_url="redis://fixture", client=redis)
    namespace = "c" * 64
    for index in range(2):
        await cache.put(
            f"{namespace}:object-{index}",
            MVTResponseCacheEntry.from_response(b"payload", "application/x-protobuf"),
            ttl_seconds=60,
        )

    with pytest.raises(MVTCachePurgeError):
        await cache.purge_namespace(namespace, max_keys=1)
    assert len(redis.values) == 2


@pytest.mark.asyncio
async def test_disabled_mvt_cache_purge_is_explicit_noop():
    result = await DisabledMVTResponseCache().purge_namespace("d" * 64)
    assert result == MVTCachePurgeResult(False, "d" * 64, 0, 0, 0)
