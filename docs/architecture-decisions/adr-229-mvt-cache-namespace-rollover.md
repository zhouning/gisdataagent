# ADR-229: MVT Cache Namespace Rollover on Release Pointer Changes

## Status

Accepted and implemented as the release-transition follow-up to ADR-228.

## Context

The Gateway already binds an MVT response cache object to the active release,
cache and service policies, serving projection, endpoint revision and pointer
state.  Migration cutover and rollback receipts record
`release_namespace_rollover`, but the distinction between a cache generation
and one principal/tile object was implicit.  Without that distinction an
operator could not reason about whether a pointer transition creates a fresh
generation, especially when a rollback returns to an older release.

## Decision

1. Derive a deterministic namespace token from tenant, service, release,
   cache/service policy, serving projection, endpoint revision and endpoint
   state-version identities.
2. Derive the object token from that namespace plus principal, exact
   `ServiceConsumerBinding` identity and tile coordinates.  No credential,
   cookie, access-decision hash or response bytes enter either token.
3. Expose the full generation token in `X-GDA-Cache-Generation`; retain
   `X-GDA-Cache-Namespace` as a human-readable policy namespace plus short
   token.  Keep the Redis key opaque.  A release cutover or rollback changes
   the release and/or pointer state and therefore changes both the generation
   and object token.
4. Retain old generations until their normal TTL expiry by default.  No
   `FLUSHDB`, broad scan, or database migration is part of this slice.  An
   explicit Redis generation cleanup adapter is documented in ADR-230; it is
   an operator action and does not participate in the PostgreSQL pointer
   transaction.

## Alternatives considered

| Option | Decision | Reason |
|---|---|---|
| Redis `FLUSHDB` after activation | Rejected | It can delete unrelated tenants, services and Redis workloads. |
| Scan and delete all keys for a service | Deferred | The generation prefix now makes exact deletion possible, but broad Redis scans still need a bounded, observable adapter and operational receipt. |
| Keep one hash with all dimensions | Rejected | It hides the release generation boundary and cannot support an exact future purge without changing the key contract. |
| Generation token plus natural expiry | Chosen | It is immediately safe, provider-neutral and requires no control-plane write or migration. |

## Consequences

- A cutover to a new release and a rollback to a prior release both miss the
  old generation, even if the human release key is reused.
- Existing authorized requests remain fail-closed at admission; a stale cache
  entry never bypasses binding revocation or policy evaluation.
- Old Redis entries consume memory until their bounded TTL expires.  The
  configured TTL remains capped by `CachePolicyVersion` and 300 seconds.
- CDN/GeoWebCache purge, explicit warmup and HA/DR remain separate slices.

## Verification

Unit and Gateway route tests prove that release and endpoint state changes roll
the namespace and ETag, while principal/tile changes stay in the same
generation.  The real disposable PostgreSQL/PostGIS + Martin + Redis HTTP
certification was rerun after this change and passed miss, hit, Redis-outage
fallback, revoked-binding denial and security-ledger validation.  Report:
`.tmp/gis-mvt-redis-gateway-certification/report.json`; SHA-256:
`6d26f8e343bc3a1cd6c233fece668ff2d999a1c2681d0de6b7611267129c7293`.
