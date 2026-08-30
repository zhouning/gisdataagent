# ADR-131: Metadata Fabric projection starts with a crosswalk and transactional outbox

- Status: accepted
- Date: 2026-08-03

## Context

ADR-130 introduced authenticated OpenLineage ingestion into the GDA control
ledger. Projecting those edges to OpenMetadata requires stable source and target
entity identities. The repository did not yet contain the ResourceURN crosswalk
required by ADR-006, so deriving an entity FQN from dataset names would create
implicit and potentially incorrect mappings.

Calling OpenMetadata inside the lineage database transaction would also couple
ledger availability to an external service and leave ambiguous outcomes when a
request times out after the provider commits.

## Options considered

| Option | Benefit | Cost |
|---|---|---|
| Derive OpenMetadata identities from dataset names | Minimal schema | Renames and namespace collisions silently corrupt lineage |
| Call OpenMetadata synchronously during lineage writes | Immediate projection | External failures block the ledger; timeout outcomes are uncertain |
| Add typed crosswalk plus transactional outbox | Stable identity and recoverable delivery | Projection is eventually consistent and needs a worker |

## Decision

Migration 112 adds an immutable, tenant-scoped
`gda_control.metadata_fabric_binding` crosswalk. One ResourceURN may bind one
OpenMetadata governance entity and multiple Gravitino technical objects. The
binding stores only stable external references, version reference and a
canonical SHA-256; governance and technical metadata remain in their authority
systems.

The same migration adds `gda_control.metadata_change_outbox`. An `AFTER INSERT`
trigger on `lineage_event` enqueues one idempotent `lineage_upsert` change for
`openmetadata:default` in the lineage transaction. Existing lineage is
backfilled as pending, not marked delivered.

Gateway workers use lease-based claim, complete and fail procedures under the
transaction-local tenant and least-privilege gateway role. Delivery is at least
once. A claimed envelope resolves the current OpenMetadata source and target
bindings but permits either to be absent, so the future provider worker can
record a retryable mapping dependency instead of inventing identity.

## Verification

Contract and API tests verify authority-compatible binding kinds, fingerprints,
actor binding, tenant isolation and projection correlation. PostgreSQL 16 tests
verify mapping idempotency, conflicting governance identity rejection,
OpenMetadata plus Gravitino resolution, automatic lineage enqueue,
claim/fail/reclaim/complete and rollback of both lineage and outbox rows when a
later batch edge conflicts.

## Trade-offs and boundary

OpenMetadata projection is eventually consistent. No provider endpoint,
credential or full metadata document is stored in the outbox. This increment
does not claim that OpenMetadata accepted an edge, does not write Gravitino
relationships and does not implement binding retirement or replacement.

The next increment may add an OpenMetadata adapter only after it can render a
provider request from two resolved bindings, use provider-side idempotency or
read-after-write reconciliation, and leave missing mappings retryable. A real
provider acceptance and replay test is required before Metadata Fabric
projection can be called operational.
