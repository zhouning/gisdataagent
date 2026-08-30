# ADR-189: Metadata provider read bridge

## Status

Accepted

## Context

The GDA Metadata Fabric crosswalk is now searchable and can resolve a stable
`ResourceURN -> provider object` binding. That lookup is not a provider catalog:
OpenMetadata and Gravitino still own object state, revisions and catalog
semantics. A platform consumer nevertheless needs an authenticated,
read-after-write observation path that can prove whether a bound provider
object is present and which revision was observed.

Copying complete provider documents into the GDA control ledger would create a
second metadata authority, leak provider-owned fields and make replay and
retention ambiguous. Provider search, tenant federation and provider recovery
also require capabilities beyond this first read slice.

## Decision

1. Add the provider-neutral `gda.metadata_provider_read.v1` result contract.
   It carries tenant/resource/binding identity, `present` or `not_found` state,
   provider revision, a bounded selected-evidence projection, observation time
   and a deterministic provider fingerprint. Transport, HTTP, identity and
   configuration failures are typed and remain retryable only when the failure
   is plausibly transient.
2. Implement a Gravitino adapter using the crosswalk's exact
   `metalake/catalog/namespace/object` path. Its fingerprint removes only the
   provider-managed `audit` field, which Gravitino reconstructs after restart;
   all technical identity, schema, properties and location facts remain bound.
   A `metadata-sha256:<fingerprint>` binding is rejected when the live stable
   fingerprint differs.
3. Implement an OpenMetadata adapter for the explicitly supported entity
   types. It reuses the existing `/api/v1` URL validation, bearer-token file,
   no-redirect and timeout rules and reads by external UUID only. It returns
   selected identity/version fields and never guesses by name or FQN.
4. Expose the read through authenticated
   `GET /api/platform/v1/metadata-fabric/provider-read?resource_urn=...&system=...`.
   The gateway resolves exactly one tenant-scoped GDA binding and returns the
   typed observation. The endpoint performs no ledger mutation and does not
   return the provider document.

## Evidence

- `data_agent/metadata_provider_read.py` implements both adapters and the
  neutral contract.
- `data_agent/test_metadata_provider_read.py` covers namespace/UUID binding,
  auth headers, bounded evidence, not-found state, identity mismatch and
  Gravitino revision drift.
- `data_agent/test_metadata_fabric.py` covers the authenticated route and
  tenant-scoped binding resolution; the route is visible in OpenAPI.
- The real fixed-image Gravitino acceptance report
  `.tmp/metadata-fabric/gravitino-metadata-bridge-acceptance-report.json`
  (`gda.gravitino_metadata_bridge_acceptance.v3`) proves provider `present`
  fingerprint/evidence and post-delete `not_found` after a container restart.

## Consequences

Consumers can perform an auditable provider read without treating GDA as a
catalog. Provider-specific adapters are isolated behind one contract, and
Gravitino's restart-volatile audit field is no longer mistaken for technical
version drift. The endpoint remains operator/authentication scoped until a
separate consumer policy is certified.

This does not provide provider-backed search, bulk harvesting, dual-tenant
external isolation, OIDC/workload identity, HA, backup/restore/PITR, metrics or
Spark/Sedona/Flink conformance. Those remain AR-1 work.

## Revisit triggers

- A provider adds a supported bulk search or pagination contract.
- Production identity, tenant federation or recovery requirements require
  provider-specific credentials, workload identity or endpoint routing.
- A provider changes its revision semantics or the stable Gravitino object
  projection needs fields beyond the bounded evidence contract.
