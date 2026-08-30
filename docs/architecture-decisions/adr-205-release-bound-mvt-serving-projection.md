# ADR-205: Release-Bound MVT Serving Projection

## Decision

Every governed vector-tile `ServiceReleaseBinding` now carries an exact,
immutable `MVTServingProjectionVersion`. The projection is the data-plane
contract consumed by the Martin/PostGIS MVT function. It records:

- source `ResourceVersion` and its SHA-256;
- source schema/table, geometry column/SRID, and feature ID column;
- declared property allowlist, source-CRS extent, and per-tile feature limit;
- immutable projection SHA-256 and predecessor lineage.

The release recorder rejects a vector-tile release without this projection.
The projection recorder verifies that the source output and geometry column are
the exact layer inputs, that the source content hash still matches the output
`ResourceVersion`, and that the feature ID and property allowlist are declared
by the layer schema contract.

```mermaid
flowchart LR
    A[Active EndpointRevision] --> B[ServiceReleaseBinding]
    B --> C[MVTServingProjectionVersion]
    A --> D[provider_layer_ref + provider_query]
    D -->|same projection UUID| E[Platform Gateway]
    C --> E
    E --> F[Martin gda_mvt_serving_projection]
    F --> G[PostGIS gda_mvt_serving_projection_mvt]
    C --> G
    G --> H[versioned source table]
    H --> I[MVT bytes]
    I --> E
```

The endpoint contract is fixed to
`provider_layer_ref=gda_mvt_serving_projection` and a one-field
`provider_query` containing `serving_projection_version_id`. Before Martin is
called, the Gateway checks that this ID matches the active release projection.
An invalid or stale contract produces `409 invalid_mvt_endpoint_contract`.

`map_serving.gda_mvt_serving_projection_mvt(z, x, y, query)` resolves only the
projection UUID. It constructs the MVT query from stored identifiers, clips to
the declared source-CRS extent and requested tile, applies the fixed attribute
allowlist, repairs invalid geometry for tile generation, and enforces the
stored feature limit. Martin exposes that function as
`gda_mvt_serving_projection`; the legacy `map_publication` function remains a
separate compatibility path.

The projection ID and SHA-256 are part of the private tile cache identity, so
changing a projection creates a distinct cache namespace and ETag.

## Operating Boundary

The enforceable data-plane guarantee is a release-bound static projection:
fixed source version, fields, spatial extent, and tile cardinality. It is not a
claim of subject-specific row, column, spatial, temporal, or purpose filtering.
Martin therefore remains an internal-only provider behind the Gateway; it must
not be exposed as a client data endpoint. Provider-direct access, general ABAC,
and dynamic per-subject spatial filtering require their own provider-side
enforcement and conformance evidence.

## Verification

- Focused contracts cover projection fingerprinting, release fingerprint and
  cache identity changes, provider-context matching, and endpoint-contract
  rejection.
- Disposable PostgreSQL certification applies migrations 205 and 206, proves
  recorder idempotency and RLS, rejects a mismatched source content hash and a
  vector-tile release without a serving projection, and confirms the active
  endpoint projection is the one bound to the release.

Run:

```bash
uv run pytest data_agent/test_gis_service_control_plane.py \
  data_agent/test_gis_provider_runtime.py \
  data_agent/test_platform_gis_mvt_route.py \
  data_agent/test_gis_service_control_plane_postgres.py

uv run python scripts/certify_gis_service_control_plane.py \
  --database-url postgresql://postgres:postgres@127.0.0.1:5433/gis_agent
```
