# ADR-191: Bounded OpenMetadata provider search

## Status

Accepted

## Context

The Metadata Fabric read bridge can verify an OpenMetadata entity by its
explicit UUID, while the first provider-search slice only covered Gravitino.
Governance users need a bounded way to discover OpenMetadata tables without
turning GDA into a second catalog or allowing cross-tenant provider search.

OpenMetadata search results are provider-index projections and do not, by
themselves, prove the current entity revision. Any candidate must still be
verified through the explicit-UUID provider-read bridge before a binding is
created or changed.

## Decision

1. Keep the provider-neutral `gda.metadata_provider_search.v1` contract and
   bind each candidate fingerprint to tenant, provider system, namespace,
   object id and object type.
2. Add an OpenMetadata adapter for `table` candidates only. It calls the
   version-pinned `/api/v1/search/query` table index with a required bounded
   query, rejects redirects and oversized responses, and returns only UUID,
   name, fully-qualified name and service namespace evidence.
3. Require an exact same-tenant GDA binding whose OpenMetadata namespace is
   `service:<name>`. Returned hits must resolve to that service and to a
   canonical UUID; cross-service, malformed and duplicate hits are discarded.
4. Expose the existing authenticated provider-search route for
   `system=openmetadata`. Empty queries, unbound services and unsupported
   object types fail closed. Provider search remains read-only and does not
   write the GDA ledger.

## Evidence

- `data_agent/metadata_provider_search.py` implements the OpenMetadata adapter
  and service dispatch alongside the existing Gravitino adapter.
- `data_agent/test_metadata_provider_search.py` covers service isolation,
  bounded identity projection, authentication, pagination parameters,
  malformed candidates, configuration and no-Gravitino dispatch.
- `data_agent/test_metadata_fabric.py` covers authenticated route behavior,
  same-tenant binding enforcement and required-query validation.
- `scripts/accept_openmetadata_provider_search.py` runs against the fixed
  OpenMetadata 1.13.1 acceptance topology, discovers a real table, verifies
  the bounded candidate and performs explicit UUID read-after-search.
- Real report: `.tmp/metadata-fabric/openmetadata-provider-search-acceptance-report.json`
  (`0600`, SHA-256
`af678ea2f2c832057a8fb18908edf76875a7b5425119e3dbb35e26eb7787f759`). The
  latest run exercised the provider bridges through
  `GDA_OPENMETADATA_BEARER_TOKEN_SOURCE` only.

## Consequences

OpenMetadata governance discovery now has parity with the bounded Gravitino
entry point for one object type, while the provider remains authoritative.
Search result ordering and `has_more` still depend on the pinned OpenMetadata
search index response; the adapter does not claim global stable cursors.

This slice does not establish OpenMetadata production foundation, OIDC or
workload identity, provider-wide/unbound search, cross-tenant federation or
search SLOs. UUID read-after-search is still required for authority
verification.

## Revisit triggers

- OpenMetadata search API version or index contract changes.
- A production cursor/filter contract allows exact service scoping without
  relying on bounded local evidence filtering.
- A dual-provider search conformance and tenant-isolation failure-injection
  suite is available.
