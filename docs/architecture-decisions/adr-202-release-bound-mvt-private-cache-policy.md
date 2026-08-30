# ADR-202: Release-Bound MVT Private Cache Policy

## Decision

`CachePolicyVersion` is an immutable control-plane record bound to one
`GISServiceDefinitionVersion`. A `ServiceReleaseBinding` stores the exact policy
version used by that release. New vector-tile releases require both a TMS and a
cache policy; historic releases remain readable as immutable facts but cannot
serve through the governed MVT route until replaced by a cache-governed release.

The current policy is deliberately narrow:

- `cache_max_age_seconds` is 1-300 seconds.
- The cache key must contain `tenant`, `service_release`, `principal`, and
  `tile` dimensions.
- Responses use `Cache-Control: private, max-age=N, must-revalidate` and vary
  on `Authorization`, `Cookie`, and `Accept-Encoding`.
- The gateway derives an opaque namespace and ETag from the policy fingerprint,
  release binding, active endpoint state, authenticated principal, ConsumerBinding
  identity when applicable, tile coordinates, and returned tile bytes.

`CachePolicyVersion` has tenant RLS, immutable-row protection, and a
`SECURITY DEFINER` recorder. The gateway has read access plus recorder execute;
it has no direct insert or update privilege.

## Consequences

An active release switch changes the cache namespace. A ConsumerBinding check
still runs before every provider request; cache policy does not provide row,
column, spatial, temporal, or purpose enforcement.

This change does not add Redis, CDN, GeoWebCache, cache warmup, purge workers,
shared/public caching, ServicePolicyBinding, or provider-side authorization
pushdown. Those require separate authority and conformance slices.
