# ADR-289: Provider-Neutral GIS MVT Cache Purge Execution Boundary

**Status**: Accepted and implemented as a bounded AR-4.4 follow-up (2026-08-25)  
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-4.4  
**Predecessor**: [ADR-231](adr-231-gis-mvt-cache-purge-outbox.md)

## Context

ADR-231 made cache reclamation durable, but its worker accepted the Redis
response-cache object directly. That kept the control-plane task contract
correct, yet coupled the execution boundary to one cache implementation and
made a future CDN or GeoWebCache adapter likely to copy the worker lifecycle.

## Decision

Introduce `GISMVTCachePurgeProvider` as the worker's only purge execution
contract. A provider receives one immutable generation token plus bounded
`max_keys` and `scan_count` values, returns the existing
`MVTCachePurgeResult`, exposes a provider kind for diagnostics, and owns its
async close hook. `MVTResponseCachePurgeProvider` adapts the current Redis
response cache without changing PostgreSQL task authority, leases, retry
semantics or zero-residue requirements.

The worker rejects ambiguous construction with both a legacy cache and an
explicit provider. The default process configuration still selects the Redis
adapter, so this change does not silently activate a CDN, GeoWebCache or
another cache. Provider replacement remains an explicit deployment decision.

## Verification

- Focused purge and response-cache regression: `15 passed`.
- Ruff check passed for the provider contract, worker and tests.
- A replacement provider double completed the same leased task and received
  the exact generation token and safety bounds.
- Disposable `redis:7-alpine` certification passed after the adapter change:
  one task claimed and completed, target generation `2/2` deleted, adjacent
  generation retained, zero residual keys, overflow rejected without partial
  deletion, and client closed. Report SHA-256:
  `d553e3b732954f3898b4a9ed4bd00e53180397e08b42e87c2a0b48b20946561d`.

## Boundary

This ADR establishes an interchangeable execution boundary; it does not
certify CDN/GeoWebCache behavior, Redis HA, cross-region DR, provider-neutral
protocol conformance, purge latency SLO, or production rollout. AR-4 remains
`in_progress`.
