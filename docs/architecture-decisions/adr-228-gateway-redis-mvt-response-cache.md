# ADR-228: Gateway Redis MVT Response Cache

## Status

Accepted and implemented as the first shared consumer-cache slice for AR-4.4.

## Context

The governed MVT route resolves an active release, service policy, serving
projection and exact consumer binding before it calls the private Martin
origin. Its HTTP cache headers were deterministic, but every authorized
request still went to Martin. A shared response cache is needed for repeated
tile reads and for more than one Gateway process.

The cache cannot become an authorization source. A tile must not remain
readable after a binding is revoked or a release is replaced.

## Decision

1. Put a binary-safe Redis response cache behind the Gateway. The route performs
   the full access admission and writes the admission audit before Redis is
   queried. A cache hit still writes an outcome audit with
   `delivery_source=redis_cache` and `provider_invocations=0`.
2. Cache only non-empty HTTP 200 MVT responses. The TTL is bounded by the
   release `CachePolicyVersion`; the entry is rejected if its content hash,
   media type, schema or maximum object size is invalid.
3. Keep the existing private Martin origin as the miss path. Redis get, set,
   connection and decode failures are fail-open to Martin. Access-audit
   failures remain fail-closed and prevent a provider or cache response from
   being returned.
4. Build the shared identity from stable, credential-free facts: tenant,
   service URN, release ID/hash, cache policy ID/hash, service policy ID/hash,
   serving projection ID/hash, endpoint revision ID/hash and state version,
   authenticated principal, exact consumer binding ID/hash, and tile
   coordinates. The per-request decision hash stays in the immutable audit
   record but is not part of the shared key.
5. Use a separate Redis URL/profile and key prefix from unrelated Redis stream
   data. Cache entries contain only response media type, content bytes and
   content SHA-256; credentials, cookies, tokens and policy decisions are not
   stored.

## Alternatives considered

| Option | Decision | Reason |
|---|---|---|
| Put Redis before authorization | Rejected | A stale entry could bypass binding revocation or policy evaluation. |
| Reuse the existing text Redis client | Rejected | `decode_responses=True` is not safe for arbitrary MVT bytes and mixes failure domains. |
| Add CDN/GeoWebCache and automatic purge dispatch in the same change | Deferred | Those require provider-neutral purge, namespace rollover, HA and operational contracts that are not yet certified. |
| Fail closed when Redis is unavailable | Rejected | Redis is a rebuildable performance projection; Martin remains the governed read path. |

## Verification

Focused contract tests pass: `39 passed` across the response-cache, access
service, Gateway route and certification wiring tests. The real certification
uses disposable PostgreSQL/PostGIS, Martin `v0.18.0`, Redis `7-alpine` and the
normal FastAPI signed-cookie route. It proves:

- first authorized read: Martin 200, cache miss, `provider_invocations=1`;
- same authorized binding replay: Redis hit, Martin not called,
  `provider_invocations=0`;
- Redis container stopped: authorized request falls back to Martin 200;
- binding revocation: request remains `403` even though a cached tile exists;
- security ledger chain and exact binding least-privilege checks remain valid.

Report: `.tmp/gis-mvt-redis-gateway-certification/report.json`.
Report SHA-256: `6d26f8e343bc3a1cd6c233fece668ff2d999a1c2681d0de6b7611267129c7293`.

## Scope boundary

This slice does not claim automatic cutover-triggered purge/warmup dispatch,
CDN or GeoWebCache adapters, Redis Sentinel/Cluster HA, cross-region DR,
provider-neutral cache conformance, quota/rate limiting, ServiceSLO or
incident automation. Explicit Redis generation purge is documented separately
in ADR-230. AR-4 remains `in_progress`.

## Revisit trigger

Revisit when a second provider or a production multi-region deployment needs a
provider-neutral purge protocol, cache replication, measured RTO, or a shared
edge-cache contract.
