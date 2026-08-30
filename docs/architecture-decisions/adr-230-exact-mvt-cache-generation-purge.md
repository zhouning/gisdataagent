# ADR-230: Exact MVT Cache Generation Purge

## Status

Accepted and implemented as the operational follow-up to ADR-229.

## Context

ADR-229 made release transitions safe by giving each MVT response cache
generation an opaque prefix.  Natural TTL expiry is sufficient for correctness,
but old generations can occupy Redis memory after a cutover or rollback.  An
operator needs a bounded cleanup action that cannot delete another tenant,
service, generation or Redis workload.

## Decision

1. Expose `RedisMVTResponseCache.purge_namespace()` and an operator CLI that
   accepts only the 64-character generation token from
   `X-GDA-Cache-Generation`.  The Redis URL is read from
   `GDA_GIS_MVT_CACHE_REDIS_URL`, never from command-line arguments.
2. Match exactly `key_prefix:<generation>:` using incremental `SCAN`; collect
   all keys before deletion so the configured bound fails closed without a
   partial purge.
3. Delete with Redis `UNLINK`, then perform a second exact-prefix scan.  A
   purge is successful only when the second scan finds zero keys.  Redis
   failures and residual keys return a terminal error rather than a success
   receipt.
4. Bound each operation by `max_keys` (default 10,000, maximum 100,000) and
   `scan_count` (default 100, maximum 10,000).  The action is deliberately
   outside the PostgreSQL pointer transaction; namespace rollover remains the
   correctness mechanism when Redis is unavailable.

## Alternatives considered

| Option | Decision | Reason |
|---|---|---|
| `FLUSHDB` or `KEYS *` | Rejected | Can block Redis or delete unrelated workloads. |
| Delete while scanning | Rejected | A bound failure could leave an unreported partial purge. |
| Natural TTL only | Retained as fallback | It remains correct when Redis or the operator action is unavailable. |
| Exact `SCAN` + `UNLINK` + residual scan | Chosen | Bounded, non-blocking and auditable for the generation key contract. |

## Consequences

- Operators can reclaim one old generation without changing release truth or
  authorization state.
- A large generation must be purged in a later bounded operation or left to
  TTL; the adapter does not silently continue past its safety limit.
- This is a Redis-specific adapter. CDN/GeoWebCache purge and automatic
  cutover-triggered dispatch still require their own provider-neutral contract.

## Verification

The disposable `redis:7-alpine` certification proved target `2/2` deletion,
adjacent-generation preservation, unrelated-key preservation and fail-closed
overflow with both original keys retained. Report:
`.tmp/gis-mvt-cache-namespace-purge-certification/report.json`; SHA-256:
`d83540959783b6e3dc67ad7b67d4ef722de328594b6573fab3e20bf3905c89db`.
