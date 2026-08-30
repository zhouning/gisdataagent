#!/usr/bin/env python3
"""Purge one exact Gateway MVT cache generation.

The Redis URL is read from ``GDA_GIS_MVT_CACHE_REDIS_URL`` rather than the
process command line.  This is an operator action, not an authorization or
release-state transition; callers must supply the already-derived 64-char
generation token from the Gateway ``X-GDA-Cache-Generation`` response header.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from data_agent.gis_mvt_response_cache import (
    MVTCachePurgeError,
    RedisMVTResponseCache,
)


async def _purge(namespace: str, *, max_keys: int, scan_count: int) -> int:
    redis_url = os.getenv("GDA_GIS_MVT_CACHE_REDIS_URL", "").strip()
    if not redis_url:
        raise RuntimeError("GDA_GIS_MVT_CACHE_REDIS_URL is required")
    cache = RedisMVTResponseCache(
        redis_url=redis_url,
        key_prefix=os.getenv("GDA_GIS_MVT_CACHE_KEY_PREFIX", "gda:mvt:response:v1"),
        max_object_bytes=int(os.getenv("GDA_GIS_MVT_CACHE_MAX_OBJECT_BYTES", "1048576")),
        socket_timeout_seconds=float(os.getenv("GDA_GIS_MVT_CACHE_TIMEOUT_SECONDS", "0.5")),
    )
    result = await cache.purge_namespace(
        namespace, max_keys=max_keys, scan_count=scan_count
    )
    print(json.dumps(result.__dict__, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("namespace", help="64-character generation token")
    parser.add_argument("--max-keys", type=int, default=10_000)
    parser.add_argument("--scan-count", type=int, default=100)
    args = parser.parse_args()
    try:
        return asyncio.run(
            _purge(args.namespace, max_keys=args.max_keys, scan_count=args.scan_count)
        )
    except (MVTCachePurgeError, RuntimeError, ValueError) as exc:
        print(f"purge_failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
