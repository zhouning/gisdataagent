# ADR-226: Martin Release-Bound Provider-Origin Warmup

**Status**: Accepted  
**Date**: 2026-08-21  
**Related roadmap**: [GIS Data Agent Roadmap](../roadmap.md), AR-4.2, AR-4.3, AR-4.4  
**Depends on**: [ADR-215](adr-215-martin-release-bound-conformance.md), [ADR-225](adr-225-run-bound-gis-endpoint-warmup-evidence.md)

## Context

Migration 220 introduced the authoritative, Run-bound warmup receipt but its
provider payload was a deterministic certification fixture. The existing
Martin adapter could prove one release-bound tile read; it did not execute or
fingerprint a bounded multi-tile sample set suitable for warmup evidence.

The consumer Gateway route currently serves only the active release. A target
release must be warmed before migration cutover, so that route cannot yet be
used to pre-populate a target Gateway or shared cache. Calling the private
Martin origin is still useful, but the resulting claim must be limited to
provider readiness and tile materialization.

## Decision

`MartinVectorTileProvider.warmup_mvt_tiles()` executes a typed, ordered set of
one to 100 unique MVT coordinates against the private Martin origin. Before
tile reads it requires:

- the exact ready Martin deployment, MVT endpoint, release binding, cache
  policy and governed serving projection;
- an endpoint contract that binds only `gda_mvt_serving_projection` and the
  exact serving-projection query;
- one successful health probe and a catalog that advertises that function.

Every sample must return a non-empty HTTP 200 MVT response. The receipt records
both the private provider origin and consumer endpoint identity, exact control
IDs, cache namespace, ordered sample-set hash, per-sample coordinate, media
type, byte count, content SHA-256, ETag and timestamp, plus a fingerprint over
the complete aggregate. Credentials and request authorization are not written
to the receipt.

The implementation extends the existing provider adapter. The managed
`GISServiceEndpointWarmupConsumer` claims the existing PlatformCommand outbox,
publishes the receipt bytes to a content-verified evidence store and invokes
the Gateway's atomic settlement. It does not add a provider-owned queue,
endpoint state machine or active-pointer authority.

## Verification

Unit and contract tests cover successful multi-zoom reads, control-identity
drift, duplicate coordinates, missing catalog advertisement and empty/204
responses. The focused provider, certifier and migration-receipt suite passes
19 tests.

`scripts/certify_martin_active_release.py` additionally creates a disposable
PostGIS database and least-privilege Martin login, starts
`ghcr.io/maplibre/martin:v0.18.0`, activates an exact release and reads three
known-data coordinates: `0/0/0`, `1/1/0` and `2/3/1`. All three returned
non-empty HTTP 200 `application/x-protobuf` responses. The receipt records:

- requested/successful samples: `3/3`;
- sample-set SHA-256:
  `e36a2d0e4bd6b31c34bf2e67181d938d51fa1931b4aee631623918554b95b25b`;
- provider receipt SHA-256:
  `ed2aaf329cd1ece300c7f83018a9e6d516decc74ce4b784be0e34faf1d6601da`.

The report is
`.tmp/martin-endpoint-warmup-certification/report.json`; its SHA-256 is
`b033dd20bcd99939a18ca99c64492052fd037887be87bffda715ed79067ceadd`.
The disposable container, database and logins are removed by the certification
cleanup path. Martin can execute only the governed MVT function and cannot read
the source table or control projection directly.

## Consequences

The Martin adapter and managed worker can now produce a real, exact-release
provider payload and settle it as migration 220 evidence through the migration
221 command contract. The complete path is documented in
[ADR-227](adr-227-managed-martin-warmup-command-and-atomic-settlement.md).

This ADR does not claim that the consumer Gateway, Redis, CDN or GeoWebCache was
warmed. Candidate Gateway routing, shared-cache purge/warmup, GeoServer and
ArcGIS adapters, production network isolation, worker HA and replicated
receipt storage remain open.
