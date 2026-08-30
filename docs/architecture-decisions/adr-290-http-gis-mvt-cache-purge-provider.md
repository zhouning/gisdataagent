# ADR-290: HTTP GIS MVT Cache Purge Provider

**Status**: Accepted and implemented as a bounded AR-4.4 provider slice (2026-08-25)  
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-4.4  
**Predecessor**: [ADR-289](adr-289-provider-neutral-gis-mvt-cache-purge-execution.md)

## Context

ADR-289 removed the worker's direct dependency on Redis, but only the Redis
adapter had an executable implementation. CDN and GeoWebCache integrations
need an external invalidation boundary with credentials, transport failures
and a provider receipt that can be checked before the existing outbox marks a
task done.

## Decision

Add `HTTPGISMVTCachePurgeProvider` using the versioned
`gda.gis_mvt_cache_purge.v1` JSON contract:

- request: `generation_token`, bounded `max_keys`, bounded `scan_count` and
  the schema identifier;
- optional Bearer authentication is read from a validated absolute token file,
  never from the URL or request body;
- only credential-free HTTP(S) endpoint URLs are accepted; redirects are not
  followed;
- a successful response must echo the exact generation token, return
  `status=succeeded`, integer matched/deleted/remaining counts and
  `remaining_keys=0`;
- 5xx, transport errors, malformed JSON, schema drift, generation mismatch or
  non-zero residue become provider errors for the existing outbox retry/failure
  path. The adapter does not change PostgreSQL authority or perform hidden
  retries.

The adapter is opt-in. The default purge worker continues to use the Redis
response-cache adapter; [ADR-291](adr-291-gis-mvt-purge-provider-selection.md)
adds the explicit process configuration needed to select this HTTP adapter.

## Verification

- HTTP provider contract tests: `11 passed`.
- Combined purge/response-cache/provider regression: `26 passed`.
- Loopback `ThreadingHTTPServer` certification passed 9 checks: 503 was
  surfaced for outbox retry, a valid receipt completed with zero residue,
  generation mismatch was rejected, the fixed path and bounds were preserved,
  the bearer token was sent only in the header, and the server was cleaned up.
  Report SHA-256:
  `69f858ceb93dad18ba56771fb0d2aee8f2a10bcd918bac6619719ddc8901a43d`.

## Boundary

The loopback result proves the HTTP transport and receipt contract only. It
does not certify a real CDN, GeoWebCache, cache purge latency SLO, provider
HA/DR, production identity rotation, or production rollout. AR-4 remains
`in_progress`.
