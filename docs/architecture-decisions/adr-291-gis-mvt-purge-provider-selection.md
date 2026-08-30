# ADR-291: GIS MVT Purge Provider Process Selection

**Status**: Accepted and implemented as a deployment-contract slice (2026-08-25)  
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-4.4  
**Predecessor**: [ADR-290](adr-290-http-gis-mvt-cache-purge-provider.md)

## Context

The HTTP purge adapter was executable through dependency injection, but the
managed worker could only construct Redis from process environment. That made
the external provider contract difficult to deploy and encouraged ad hoc
worker images or entrypoints.

## Decision

`GISMVTCachePurgeWorkerConfig` now selects the purge provider explicitly with
`GDA_GIS_MVT_CACHE_PURGE_PROVIDER`:

- `redis` remains the default and constructs the existing response-cache
  adapter;
- `http` requires `GDA_GIS_MVT_CACHE_PURGE_HTTP_ENDPOINT_URL`, accepts an
  optional `GDA_GIS_MVT_CACHE_PURGE_HTTP_BEARER_TOKEN_FILE`, and validates the
  bounded timeout before worker construction;
- unknown providers, HTTP without an endpoint, or HTTP settings attached to
  the Redis selection fail before a task is claimed.

Compose and Kubernetes configuration expose the non-secret selection and
endpoint fields but default to Redis. No external provider is activated by
this change, and no token is placed in ConfigMap or command-line arguments.

## Verification

- Worker/provider selection and purge regression: `21 passed`.
- Ruff, compileall and `docker compose config --quiet` passed.
- Explicit HTTP configuration constructs `http_cache_purge`; default worker
  behavior remains the Redis adapter; missing/unknown selection fails closed.

## Boundary

This is a process configuration and deployment contract. It does not certify
an external cache service, CDN/GeoWebCache production identity, HA/DR, purge
latency SLO, or staging/production rollout. AR-4 remains `in_progress`.
