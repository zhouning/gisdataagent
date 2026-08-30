# ADR-215: Martin Release-Bound Conformance and Internal Provider Origin

**Status**: Accepted  
**Date**: 2026-08-21  
**Related roadmap**: [GIS Data Agent Roadmap](../roadmap.md), AR-4.3 and AR-4.4  
**Related decisions**: [ADR-182](adr-182-martin-mvt-provider-adapter-boundary.md), [ADR-205](adr-205-release-bound-mvt-serving-projection.md), [ADR-212](adr-212-gis-service-deployment-readiness-evidence.md), [ADR-214](adr-214-gis-service-endpoint-readiness-binding.md)

## Context

The first Martin certification proved that a disposable `map_publication` fixture
could produce an MVT response. That function remains useful for a legacy
compatibility API, but it is not the data-plane contract of a current GIS
release. A current MVT release binds an immutable
`MVTServingProjectionVersion`, and Martin must read only through
`map_serving.gda_mvt_serving_projection_mvt` with the exact projection UUID.

There are also two distinct network identities in a production release:

- `EndpointRevision.endpoint_uri` is the stable, credential-free HTTPS address
  registered for a consumer.
- Martin is a private provider reached by the Gateway through a trusted internal
  origin (`MARTIN_URL`).

Using the public endpoint as the Gateway's Martin upstream can recurse through
the Gateway or escape its private provider boundary. A health-only result cannot
show that the projection function, catalog contract and tile response work for
the actual release.

## Decision

### 1. One release-bound Martin receipt

`MartinVectorTileProvider.conform_mvt_read()` now produces
`gda.gis_martin_mvt_conformance.v1`. The receipt records:

```text
ready health
+ catalog SHA-256 advertising gda_mvt_serving_projection
+ exact ServiceReleaseBinding and MVTServingProjectionVersion IDs
+ one fixed provider query: serving_projection_version_id=<projection UUID>
+ a valid TMS coordinate and non-empty HTTP 200 MVT response
+ media type, byte count, content SHA-256 and provider ETag
```

The receipt is immutable and self-hashed. A readiness controller can turn it
into the existing `gda.gis_service_deployment_observation.v2` and submit it to
the existing atomic terminal-settlement endpoint. The existing Gateway still
owns deployment identity, Run, placement, state-version CAS and the terminal
transition.

The known-data coordinate is deliberate. It is the readiness witness that the
actual release can return a tile. Empty-tile behavior remains an independent
data-plane conformance case; it does not prove a release can serve data.

### 2. Internal Martin upstream for Gateway reads

The governed MVT route retains `EndpointRevision.endpoint_uri` as the
consumer-visible address and resolves Martin from `MARTIN_URL` for its upstream
read. `MARTIN_URL` must be a credential-free HTTP(S) origin and is checked
before provider construction. The release-bound endpoint contract still controls
the only admitted layer reference and query.

```text
Consumer -- HTTPS --> Gateway -- MARTIN_URL --> Martin
                         |                    |
                         +-- release/TMS ------+-- PostGIS projection function
```

### 3. Certification reads the active authority

`scripts/certify_martin_provider.py` has two modes:

- discovery mode checks a live provider health and catalog surface;
- active-release mode loads `GISServiceControlProjection` through
  `PlatformGateway`, requires an active ready Martin deployment and exact MVT
  endpoint contract, then invokes the release-bound conformance read.

Active-release mode requires `--database-url`, `--tenant` and `--service-urn`
together. It does not construct a synthetic release context and does not create
or mutate provider data. Its report binds the result to active endpoint state,
deployment, release and serving-projection IDs.

## Consequences

The platform can now distinguish three facts that previously blurred together:

| Fact | Evidence |
|---|---|
| Martin process is reachable | health and catalog discovery |
| A current release is physically serveable | release-bound conformance receipt |
| A deployment becomes ready | receipt admitted through existing terminal settlement |

This ADR adds no deployment worker, provider lifecycle store, queue, registry,
or scheduler. The certificate is a repeatable integration fixture, not a claim
that a customer or production release has been accepted. Production acceptance
must still use its own registered release, provider origin, data, SLO, and
network controls.

### 4. Disposable active-release fixture

`scripts/certify_martin_active_release.py` closes the integration gap without
writing a sample service into the development database. Each run:

1. creates a temporary PostGIS database and inserts one known polygon;
2. creates a gateway login and a Martin login, then gives Martin only
   `USAGE` on `map_serving` and `EXECUTE` on the governed MVT function;
3. registers the definition, release components, successful `PlatformRun`,
   deployment, receipt, endpoint, and active pointer through `PlatformGateway`;
4. starts one Martin container with only `gda_mvt_serving_projection` in its
   catalog, reads a non-empty tile, settles the deployment, and invokes the
   normal active-release certifier; and
5. deletes the database, both logins, container, and temporary config before
   retaining the report.

The public HTTPS endpoint remains the endpoint authority. Martin is reached at
an ephemeral HTTP origin only inside the integration fixture. The report
contains no credentials and proves the two identities were not conflated.

The first fixture run also exercised the `SECURITY DEFINER` MVT function under
its real restricted search path. It exposed two PostGIS extension-resolution
bugs: unqualified `ST_*` functions and the geometry overlap operator `&&` do
not resolve when `public` is intentionally absent from `search_path`.
Migrations 210 and 211 explicitly bind them as `public.ST_*` and
`OPERATOR(public.&&)`. The function remains `SECURITY DEFINER` with
`pg_catalog, gda_control, map_serving`; adding `public` to the security context
was not accepted.

## Verification

Focused contract coverage verifies:

- receipt creation carries exact release/projection query, catalog and tile hash;
- missing catalog function or an empty readiness tile is rejected;
- Gateway calls the internal Martin origin instead of the public endpoint;
- missing internal provider configuration fails before a provider call;
- the certifier rejects partial parameters and a mismatched active endpoint
  contract.

The current Compose runtime has additionally been checked in place: Martin
`v0.18.0` is healthy and advertises `gda_mvt_serving_projection`. The business
development database still has no active GIS endpoint; that is intentional.
The isolated fixture now supplies the active release required to certify the
actual control-plane and data-plane path.

The same runtime check found a separate deployment defect: the migration ledger
was at 208, but the `gda_control_gateway` role had lost GIS control-plane table
grants. Migration 209 restores the narrow read/observation/controlled-function
ACL and the disposable control-plane certificate now verifies all 15 privileges
used to materialize an active service projection.

```bash
uv run pytest -q \
  data_agent/test_gis_provider_runtime.py \
  data_agent/test_platform_gis_mvt_route.py \
  data_agent/test_certify_martin_provider.py

uv run python scripts/certify_martin_provider.py \
  --endpoint http://martin:3000 \
  --database-url "$DATABASE_URL" \
  --tenant planning \
  --service-urn gda://planning/gis_service/district-features \
  --z 0 --x 0 --y 0 \
  --report .tmp/gis-martin-release-conformance/report.json

uv run python scripts/certify_martin_active_release.py \
  --report .tmp/gis-martin-release-conformance/active-release-fixture-report.json
```

Compose discovery report:
`.tmp/gis-martin-release-conformance/discovery-report.json`, SHA-256
`1b378edd1d53f59a7c3a0bd3559397f8f1ca669ccb6f5c89fa943b8e137e4885`.

Disposable PostgreSQL control-plane certificate v9:
`/private/tmp/gis-service-control-plane-209-report.json`, SHA-256
`4b67e63e50a0adb854ca04003cf68c619253e5a8e0be59f1ce38914dab0a71bb`.

Active-release fixture certificate:
`.tmp/gis-martin-release-conformance/active-release-fixture-report.json`,
SHA-256 `e4bb5ebe8dcf8552fb5ffe4435c134c93a18fcd86a77608bc77bb41c75951262`.
It records `active_release_read_certified`, a 122-byte MVT response, exact
release/projection IDs, a public HTTPS consumer endpoint, and a distinct
ephemeral internal Martin origin. The Martin principal has no `SELECT` on the
source table or control projection.

After migrations 210/211, the Compose ledger and catalog are both 211 with
fingerprint `792d267eac939a2874954bde6e10b4ff8a36a801252039facb71ddb8aff8d1a0`.
The fresh control-plane certificate is
`/private/tmp/gis-service-control-plane-211-report.json`, SHA-256
`fda5e5a355d9e71345452f4cf2a7824ee99e195f3ca879ae71ac4ddf7f6f5ad8`.
