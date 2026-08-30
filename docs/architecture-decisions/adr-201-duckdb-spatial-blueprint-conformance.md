# ADR-201: DuckDB Spatial Blueprint Conformance

**Status:** Accepted (bounded local and disposable PostgreSQL acceptance)

**Date:** 2026-08-20

**Related:** ADR-197, ADR-198, ADR-199, ADR-200

## Context

The DuckDB Blueprint provider could declare `require_spatial`, but that only
attempted `LOAD spatial`. It did not prove a version-matched installed binary,
prevent runtime extension downloads, bind the extension identity to a receipt,
or require a portable geometry output. A successful boolean therefore could not
establish GIS provider conformance.

## Decision

The worker image pins DuckDB `1.5.5` and installs the official matching Spatial
extension during image build. The resulting extension binary is copied to
`/app/duckdb-extensions/spatial.duckdb_extension`, made read-only, and loaded
from that path at runtime. The provider disables DuckDB auto-install and
auto-load before `LOAD`; it never executes `INSTALL` during a Run. Bare-metal
workers must supply the equivalent immutable, version-matched file through
`GDA_BLUEPRINT_DUCKDB_SPATIAL_EXTENSION_PATH`.

A Spatial Blueprint must explicitly set `require_spatial: true` and
`spatial_output_srid`. Spatial SQL without that declaration is rejected. Its
result must expose `geometry_wkb`, `srid`, and `bbox`; every non-null geometry
is decoded and validated by DuckDB Spatial, every row must use the declared
SRID, and bbox coordinates must be finite and agree with the WKB envelope. The
provider writes GeoParquet 1.1 `geo` metadata with WKB encoding and a PROJJSON
CRS derived from the declared SRID.

The provider receipt records extension version, signed binary SHA-256, install
source/mode, disabled auto-install/auto-load settings, geometry types, spatial
extent, CRS hash and GeoParquet metadata hash. Migration 202 requires that
evidence in Artifacts and observations, and a terminal-event trigger checks it
against the admitted Blueprint definition before a Spatial Run may succeed.
Non-spatial provider receipts must not carry spatial evidence.

## Verification

- Real DuckDB `1.5.5` + Spatial extension `eb1e57c` performs EPSG:4326 to
  EPSG:3857 transform, validates WKB/SRID/bbox, writes GeoParquet 1.1 metadata,
  and proves deterministic replay with external access disabled.
- Provider conformance covers missing declaration, missing extension path and
  invalid SRID/bbox as fail-closed cases.
- A disposable PostgreSQL 16 acceptance applies migrations through 202, runs a
  spatial Blueprint through the managed command/outbox path, writes the
  receipt/Artifact/quality/lineage facts, exercises ACK-loss terminal
  reconciliation, and passes the live DataProductVersion release gate.
- `scripts/certify_duckdb_blueprint_spatial.py` emitted a passed report with
  file SHA-256 `9a5db90b605cb7e07f21256373f54f1933567800cfb22d94ad32a97d3839bd37`.

## Consequences

The lightweight provider now has a real bounded GIS execution contract, not a
best-effort extension load. Spatial data remains portable at the platform
boundary as WKB + SRID + bbox with GeoParquet metadata; DuckDB's native
`GEOMETRY` remains internal to execution.

This is not cross-engine production certification. Spark/Sedona, Flink,
PostGIS and DuckDB must still complete the shared geometry encoding, temporal
semantics and GeoParquet interoperability suite before any native geometry type
becomes a cross-engine authority. Nor does this decision prove real-cluster
NetworkPolicy enforcement, identity rotation, lease heartbeat, multi-replica
HA, capacity/SLO or staging/production rollout.

## Revisit Trigger

Re-certify on any DuckDB or Spatial extension upgrade, extension source/path
change, GeoParquet specification change, additional geometry encoding, or
before allowing a new engine to treat the lightweight provider output as a
cross-engine authoritative spatial product.
