#!/usr/bin/env python3
"""Certify exact Redis generation purge with disposable Redis 7."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import socket
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from data_agent.gis_mvt_cache_purge import (
    GIS_MVT_CACHE_PURGE_WORKLOAD,
    GISMVTCachePurgeStatus,
    GISMVTCachePurgeTask,
)
from data_agent.gis_mvt_cache_purge_worker import (
    GISMVTCachePurgeWorker,
    GISMVTCachePurgeWorkerConfig,
)
from data_agent.gis_mvt_response_cache import (
    MVTCachePurgeError,
    MVTResponseCacheEntry,
    RedisMVTResponseCache,
    mvt_response_cache_namespace,
)

REDIS_IMAGE = "redis:7-alpine"


def _reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _start_redis() -> tuple[str, str]:
    name = f"gda-mvt-purge-cert-{uuid4().hex[:10]}"
    port = _reserve_port()
    result = subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            name,
            "--publish",
            f"127.0.0.1:{port}:6379",
            REDIS_IMAGE,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip())
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        probe = subprocess.run(
            ["docker", "exec", name, "redis-cli", "ping"],
            check=False,
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0 and probe.stdout.strip() == "PONG":
            return name, f"redis://127.0.0.1:{port}/0"
        time.sleep(0.2)
    subprocess.run(["docker", "rm", "--force", name], check=False)
    raise RuntimeError("Redis fixture did not become ready")


def _stop_redis(name: str) -> None:
    subprocess.run(["docker", "rm", "--force", name], check=False, capture_output=True)


async def _certify(redis_url: str) -> dict[str, object]:
    cache = RedisMVTResponseCache(
        redis_url=redis_url,
        key_prefix="gda:mvt:purge-cert:v1",
        client=None,
    )
    target = "a" * 64
    adjacent = "b" * 64
    await cache.put(
        f"{target}:tile-1",
        MVTResponseCacheEntry.from_response(b"target-1", "application/x-protobuf"),
        ttl_seconds=300,
    )
    await cache.put(
        f"{target}:tile-2",
        MVTResponseCacheEntry.from_response(b"target-2", "application/x-protobuf"),
        ttl_seconds=300,
    )
    await cache.put(
        f"{adjacent}:tile-1",
        MVTResponseCacheEntry.from_response(b"adjacent", "application/x-protobuf"),
        ttl_seconds=300,
    )
    redis = await cache._get_client()
    await redis.set("gda:mvt:purge-cert:v1:unrelated", b"keep")
    purge = await cache.purge_namespace(target, max_keys=10, scan_count=1)
    target_entries = [
        key
        async for key in redis.scan_iter(
            match=f"gda:mvt:purge-cert:v1:{target}:*", count=1
        )
    ]
    adjacent_entries = [
        key
        async for key in redis.scan_iter(
            match=f"gda:mvt:purge-cert:v1:{adjacent}:*", count=1
        )
    ]
    unrelated = await redis.get("gda:mvt:purge-cert:v1:unrelated")
    overflow = "c" * 64
    for index in range(2):
        await cache.put(
            f"{overflow}:tile-{index}",
            MVTResponseCacheEntry.from_response(b"overflow", "application/x-protobuf"),
            ttl_seconds=300,
        )
    overflow_rejected = False
    try:
        await cache.purge_namespace(overflow, max_keys=1, scan_count=1)
    except MVTCachePurgeError:
        overflow_rejected = True
    overflow_entries = [
        key
        async for key in redis.scan_iter(
            match=f"gda:mvt:purge-cert:v1:{overflow}:*", count=1
        )
    ]
    if not overflow_rejected or len(overflow_entries) != 2:
        raise RuntimeError("purge bound did not fail closed")
    if target_entries:
        raise RuntimeError("target generation still contains keys after purge")
    if len(adjacent_entries) != 1 or unrelated != b"keep":
        raise RuntimeError("purge crossed the exact generation boundary")
    await cache.aclose()
    return {
        "schema": "gda.gis_mvt_cache_namespace_purge_certification.v1",
        "status": "passed",
        "target_namespace": target,
        "purge": purge.__dict__,
        "target_remaining": len(target_entries),
        "adjacent_remaining": len(adjacent_entries),
        "unrelated_key_preserved": unrelated == b"keep",
        "overflow_rejected": overflow_rejected,
        "overflow_entries_preserved": len(overflow_entries),
    }


class _WorkerGateway:
    def __init__(self, task: GISMVTCachePurgeTask) -> None:
        self.task = task
        self.claimed = False
        self.completion: dict[str, object] | None = None

    def claim_gis_mvt_cache_purges(self, *_args, **kwargs):
        if kwargs["actor_subject"] != GIS_MVT_CACHE_PURGE_WORKLOAD:
            raise RuntimeError("worker used the wrong claim authority")
        if self.claimed:
            return ()
        self.claimed = True
        return (self.task,)

    def complete_gis_mvt_cache_purge(self, *_args, **kwargs):
        self.completion = kwargs
        return SimpleNamespace(status=GISMVTCachePurgeStatus.DONE)

    def fail_gis_mvt_cache_purge(self, *_args, **kwargs):
        raise RuntimeError(f"real Redis worker unexpectedly failed: {kwargs}")


async def _matching_keys(cache: RedisMVTResponseCache, generation: str) -> int:
    redis = await cache._get_client()
    return len(
        [
            key
            async for key in redis.scan_iter(
                match=f"{cache.key_prefix}:{generation}:*", count=1
            )
        ]
    )


def _certify_worker(redis_url: str) -> dict[str, object]:
    now = datetime.now(UTC)
    release_id = uuid4()
    endpoint_id = uuid4()
    context = {
        "schema": "gda.gis_mvt_cache_namespace.v1",
        "namespace": "district-features-v1",
        "tenant_id": "planning",
        "service_urn": "gda://planning/gis_service/district-features",
        "service_release_binding_id": str(release_id),
        "service_release_sha256": "1" * 64,
        "cache_policy_version_id": str(uuid4()),
        "cache_policy_sha256": "2" * 64,
        "service_policy_binding_id": str(uuid4()),
        "service_policy_sha256": "3" * 64,
        "mvt_serving_projection_version_id": str(uuid4()),
        "mvt_serving_projection_sha256": "4" * 64,
        "endpoint_state_version": 7,
        "endpoint_revision_id": str(endpoint_id),
        "endpoint_sha256": "5" * 64,
    }
    generation = mvt_response_cache_namespace(context)
    adjacent = "f" * 64
    task = GISMVTCachePurgeTask(
        tenant_id="planning",
        purge_task_id=uuid4(),
        source_kind="cutover",
        source_receipt_id=uuid4(),
        source_receipt_sha256="6" * 64,
        service_urn=context["service_urn"],
        endpoint_revision_id=endpoint_id,
        service_definition_version_id=uuid4(),
        service_release_binding_id=release_id,
        endpoint_state_version=7,
        cache_namespace=context["namespace"],
        cache_context=context,
        generation_token=generation,
        status="in_flight",
        attempt_count=1,
        max_attempts=5,
        available_at=now,
        claimed_by="worker:redis-cert",
        claimed_until=now + timedelta(minutes=5),
        created_at=now,
    )
    cache = RedisMVTResponseCache(
        redis_url=redis_url,
        key_prefix="gda:mvt:purge-worker-cert:v1",
    )
    gateway = _WorkerGateway(task)
    worker = GISMVTCachePurgeWorker(
        GISMVTCachePurgeWorkerConfig(
            tenant_id="planning",
            worker_id="worker:redis-cert",
            scan_count=1,
        ),
        gateway=gateway,
        cache=cache,
    )
    try:
        for suffix in ("tile-1", "tile-2"):
            worker._runner.run(
                cache.put(
                    f"{generation}:{suffix}",
                    MVTResponseCacheEntry.from_response(
                        suffix.encode(), "application/x-protobuf"
                    ),
                    ttl_seconds=300,
                )
            )
        worker._runner.run(
            cache.put(
                f"{adjacent}:tile-1",
                MVTResponseCacheEntry.from_response(
                    b"adjacent", "application/x-protobuf"
                ),
                ttl_seconds=300,
            )
        )
        cycle = worker.run_once()
        target_remaining = worker._runner.run(_matching_keys(cache, generation))
        adjacent_remaining = worker._runner.run(_matching_keys(cache, adjacent))
    finally:
        worker.close()
    completion = gateway.completion or {}
    if (
        cycle.claimed != 1
        or cycle.completed != 1
        or target_remaining != 0
        or adjacent_remaining != 1
        or completion.get("matched_keys") != 2
        or completion.get("deleted_keys") != 2
        or completion.get("remaining_keys") != 0
    ):
        raise RuntimeError("managed worker did not certify exact Redis cleanup")
    return {
        "cycle": cycle.__dict__,
        "generation": generation,
        "target_remaining": target_remaining,
        "adjacent_remaining": adjacent_remaining,
        "completion": completion,
        "redis_client_closed": cache._client is None,
    }


def certify(report_path: Path | None = None) -> dict[str, object]:
    container, redis_url = _start_redis()
    try:
        report = asyncio.run(_certify(redis_url))
        report["managed_worker"] = _certify_worker(redis_url)
    finally:
        _stop_redis(container)
    report["fixture"] = {"redis_image": REDIS_IMAGE, "cleanup": "completed"}
    if report_path is not None:
        payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(payload, encoding="utf-8")
        report["report_sha256"] = hashlib.sha256(payload.encode()).hexdigest()
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    print(json.dumps(certify(args.report), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
