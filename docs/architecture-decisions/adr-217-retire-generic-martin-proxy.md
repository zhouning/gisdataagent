# ADR-217: Retire the Generic Martin Table Proxy

**Status**: Accepted  
**Date**: 2026-08-21  
**Related roadmap**: [GIS Data Agent Roadmap](../roadmap.md), AR-0 and AR-4.4  
**Related decisions**: [ADR-205](adr-205-release-bound-mvt-serving-projection.md), [ADR-215](adr-215-martin-release-bound-conformance.md), [ADR-216](adr-216-authenticated-gateway-mvt-access-evidence.md)

## Context

The older `/api/tiles/martin/{table}/{z}/{x}/{y}.pbf` endpoint accepted an
authenticated user's arbitrary Martin catalog name and proxied the response.
`/api/tiles/martin/catalog` exposed the provider catalog through the same
boundary. Neither endpoint reads the active `GISServiceControlProjection` or
binds a release, ConsumerBinding, service policy, serving projection, access
decision, or immutable security event.

Martin is private at the Compose network layer, but routing an arbitrary catalog
entry through the application turns it into a public data-plane bypass. Input
sanitization cannot make the endpoint governable because the missing authority
is the service/release binding, not SQL identifier validation.

The nearby `/api/tiles/{layer_id}/...` endpoints are different: they serve
short-lived, owner-scoped work layers. Authenticated map-publication tiles also
remain on their existing governed result-delivery path. Neither is promoted to
a DataProduct GIS service by this decision.

## Decision

1. Keep both legacy Martin URLs registered only to return a stable,
   authenticated `410 legacy_martin_proxy_retired` response. The handlers do
   not read `MARTIN_URL`, contact Martin, query the catalog, or parse a table
   identifier.
2. The replacement for a governed service tile is exclusively
   `GET /api/platform/v1/gis/tiles/{release_key}/{z}/{x}/{y}.pbf` with a
   tenant-scoped service URN. It resolves the active release and performs the
   ADR-216 access decision before reaching Martin.
3. Owner-scoped work-layer tiles, TileJSON, and deletion responses use
   `Cache-Control: private, no-store`, `Pragma: no-cache`, a cookie/authorization
   `Vary` header and `nosniff`. Their previous public cache directive and
   wildcard CORS response header are removed.
4. `mercantile==1.2.1`, already fixed in `requirements.txt`, is declared in
   the `full` `pyproject.toml` profile so the PostGIS user-layer tile runtime
   has the same dependency contract under `uv`.

## Trade-offs

Existing callers of the generic proxy must migrate; returning `410` rather than
silently removing the route makes that migration observable and gives clients a
machine-readable error code. Maintaining it behind a feature flag was rejected:
any enabled deployment would retain a provider bypass, and a generic table
parameter cannot be made release-bound by configuration alone.

Private no-store work-layer responses trade cache efficiency and cross-origin
embedding convenience for preventing a cookie-authorized work product from
being retained in a shared cache. A governed, release-bound service may use its
own separately approved private-cache contract.

## Verification

```bash
uv run --with mercantile==1.2.1 pytest -q data_agent/test_tile_server.py
uv run pytest -q data_agent/test_tile_routes_security.py
uv run pytest -q data_agent/test_platform_gis_mvt_route.py \
  data_agent/test_gis_mvt_access.py
```

The route tests assert that both retired URLs return `410` without provider
configuration and that unauthenticated callers still receive `401`. User-layer
tile and TileJSON tests assert the private no-store response contract.
The HTTP regression test mounts the registered Starlette routes, supplies a
configured-looking `MARTIN_URL`, and replaces `httpx.AsyncClient` with a
sentinel. It verifies that an authenticated request to either retired URL
returns the stable retirement response without initializing a provider client.

## Revisit Triggers

- all supported MVT consumers have migrated and the two `410` route shims can
  be removed in a versioned API retirement;
- a replacement needs cross-origin delivery, signed URLs, or reusable caching;
  it must first bind its consumer identity, release, policy and invalidation
  behavior into a governed service contract;
- a provider other than Martin needs a catalog or protocol facade; it must
  expose only typed, release-bound provider capability, never arbitrary tables.
