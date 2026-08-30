# ADR-190: Bound Gravitino provider search

## Status

Accepted

## Context

The provider-read bridge can verify one bound provider object, but users also
need discovery inside a technical namespace. A generic provider catalog search
would expose unbound namespaces, mix tenants when one provider serves several
customers and tempt the control plane to copy external catalog records.

Gravitino's namespace table-list response is sufficient for a first bounded
discovery slice. It returns identifiers, not a stable cross-provider search
contract, and it does not by itself prove the object revision. Revision proof
continues through the provider-read bridge.

## Decision

1. Add `gda.metadata_provider_search.v1` with a deterministic page of
   provider candidates. Each item contains tenant-scoped namespace/object/type,
   candidate fingerprint and only identity evidence (`name` and namespace).
   Full provider documents and object revisions are excluded.
2. Implement Gravitino namespace-scoped discovery for table/view/fileset/topic
   collections. The adapter bounds the response to 512 KiB and 5,000
   identifiers, filters to the exact requested namespace, validates canonical
   names, applies bounded local query/pagination and sorts deterministically.
3. Expose
   `GET /api/platform/v1/metadata-fabric/provider-search` with explicit
   `system=gravitino`, `provider_namespace`, bounded `q/limit/offset` and
   `object_type`. Before calling Gravitino, the gateway requires an existing
   same-tenant GDA Gravitino binding whose `external_namespace` exactly equals
   the requested namespace. Fuzzy GDA crosswalk pages are walked only up to
   the existing 10,000-row platform bound; a single first page is never
   treated as proof of absence.
4. OpenMetadata provider search, arbitrary unbound namespace discovery, bulk
   harvesting, cross-tenant federation and provider search cursors remain out
   of scope until separate provider contracts and isolation tests exist.

## Evidence

- `data_agent/metadata_provider_search.py` implements the contract and
  Gravitino adapter.
- `data_agent/test_metadata_provider_search.py` covers exact namespace
  filtering, deterministic pagination, response bounds, invalid query and
  missing configuration.
- `data_agent/test_metadata_fabric.py` covers the authenticated bound-namespace
  route; the OpenAPI route registry is updated and tested.
- The fixed-image Gravitino acceptance script verifies discovery of the bound
  `gda_acceptance/iceberg/transportation/parcels` table and records the page in
  `.tmp/metadata-fabric/gravitino-metadata-bridge-acceptance-report.json`.

## Consequences

GDA now has a safe first discovery path for technical metadata without becoming
the technical catalog. Search results are candidates only; consumers must use
the read bridge to verify provider state before creating or changing a GDA
binding. The namespace binding requirement means newly created but unbound
provider objects are intentionally invisible to this API.

The slice does not establish production search SLOs, external tenant isolation,
OIDC/workload identity, HA, restore/PITR, OpenMetadata search parity or broad
provider conformance.

## Revisit triggers

- Gravitino exposes a stable server-side pagination/cursor and revision
  contract.
- OpenMetadata search/query semantics are pinned and a dual-provider parity
  test is available.
- A production federation design proves credential, namespace and tenant
  isolation under failure injection.
