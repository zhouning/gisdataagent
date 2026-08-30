# ADR-130: OpenLineage ingestion is authenticated, bounded and atomic

- Status: accepted
- Date: 2026-08-03

## Context

The platform control ledger can record immutable version-to-version lineage and
query downstream impact, but producers previously had to construct GDA
`LineageEvent` records directly. That does not provide a standard collection
boundary for DolphinScheduler, Spark, Flink or other execution providers.

OpenLineage is the interoperability protocol, while OpenMetadata remains the
governance metadata authority and Gravitino remains the technical catalog
authority. Copying arbitrary OpenLineage metadata into `gda_control` would turn
the evidence ledger into a competing general-purpose catalog.

## Options considered

| Option | Benefit | Cost |
|---|---|---|
| Keep direct GDA lineage writes | No new protocol boundary | Every provider needs proprietary event construction |
| Store complete OpenLineage payloads | Maximum source fidelity | Unbounded payload and sensitive metadata risk; duplicates catalog authority |
| Convert a bounded OpenLineage envelope | Standard provider boundary with a small ledger surface | Unsupported facets remain available only in their authority systems |

## Decision

`POST /api/platform/v1/openlineage/events` accepts only authenticated workload
identities with a platform role. The first contract accepts only `COMPLETE`
RunEvents with at least one input and output. A required `gda_platform` Run
facet binds tenant, PlatformRun, definition, artifact and operation. Every
dataset requires a `gda_resource.resourceVersionId` facet.

Input/output counts, facet counts, serialized event size and the generated
Cartesian edge count are bounded. Duplicate resource versions, input/output
overlap, missing GDA facets and unsupported event types fail closed.

One OpenLineage event becomes `N x M` deterministic `LineageEvent` edges. UUIDv5
identities and canonical JSON SHA-256 fingerprints make delivery replayable.
The authenticated workload, not a client-supplied identity, is stored as the
ledger producer. OpenLineage run/job/dataset identifiers are retained, but
arbitrary facets are represented only by SHA-256 fingerprints.

The gateway validates in one tenant transaction that:

- the PlatformRun belongs to the authenticated workload;
- the definition matches the immutable run;
- every input is an admitted run binding;
- the artifact belongs to the run and any artifact resource is an output;
- every referenced ResourceVersion exists in the tenant.

All edges are then inserted in that same transaction. A conflict on any edge
rolls back the entire batch. Exact replay returns one result per edge with
`created=false`.

## Verification

Contract and API tests cover deterministic conversion, facet redaction,
unsupported events, missing correlation facets, edge explosion, workload-only
admission and tenant mismatch. Gateway tests cover immutable run ownership and
artifact binding. PostgreSQL 16 integration verifies first ingestion, complete
replay and rollback of an earlier insert when a later edge conflicts.

## Trade-offs and boundary

This increment does not ingest `START`, `RUNNING`, `FAIL`, job lifecycle or
column-level lineage. It does not persist the complete OpenLineage document and
is not an OpenLineage archive. Providers that need full protocol retention must
send the same event to the designated metadata authority or event archive.

The endpoint records lineage only in the tenant-scoped `gda_control` ledger. It
does not yet project lineage into OpenMetadata or Gravitino, add resource-level
read authorization, certify every execution provider or complete the Metadata
Fabric and next-generation Data Platform.
