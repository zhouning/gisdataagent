# ADR-188: Metadata Fabric crosswalk search and read bridge

## Status

Accepted

## Context

The Metadata Fabric already exposed a tenant-scoped read by `ResourceURN`, but
there was no deterministic discovery surface for finding the GDA crosswalk
before resolving a governance or technical reference. A broad catalog search in
GDA would create a second metadata authority and would blur the boundary with
OpenMetadata and Gravitino.

## Decision

1. Add `GET /api/platform/v1/metadata-fabric/bindings/search` as a read-only
   discovery facade over `gda_control.metadata_fabric_binding`.
2. The facade accepts an optional bounded `q`, an enumerated `system`, and
   bounded `limit`/`offset`. `q` matches only the GDA-owned `ResourceURN` and
   stable external reference fields; ordering is deterministic and results are
   tenant scoped by the authenticated principal.
3. The existing `GET /metadata-fabric/bindings?resource_urn=...` remains the
   authoritative read-by-resource operation. Search results are references,
   not provider metadata documents.
4. OpenMetadata remains authoritative for governance search and entity reads;
   Gravitino remains authoritative for technical catalog search and object
   reads. A future provider-backed bridge may call those systems only after
   identity, policy, freshness, timeout and reconciliation contracts are
   separately accepted.

## Evidence

- Migration 186 adds the tenant/system/reference ordering index.
- The platform route and OpenAPI operation are registered as
  `platform_search_metadata_fabric_bindings`.
- Route tests verify authenticated tenant propagation, pagination, system
  filtering and bounded query rejection.
- The SQL gateway method uses the existing transaction-local tenant context and
  parameterized predicates; it does not accept a client-supplied tenant.

## Consequences

Consumers can discover a crosswalk before resolving a ResourceURN while the
control ledger remains the only GDA-owned reference index. The facade is safe to
use for catalog navigation and impact tooling, but it does not yet prove
provider search/read interoperability, freshness reconciliation, dual-tenant
isolation in external services, or production OpenMetadata/Gravitino readiness.

## Revisit triggers

- Provider-backed search is required for metadata fields not represented by a
  stable GDA reference.
- Search volume requires a dedicated index; any replacement must preserve the
  tenant predicate, deterministic replay and authority boundary.
- OpenMetadata or Gravitino introduces a supported federated search contract
  with identity, pagination and consistency guarantees.
