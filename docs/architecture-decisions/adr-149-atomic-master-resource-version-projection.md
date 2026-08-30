# ADR-149: Atomic Master Activation to ResourceVersion Projection

**Status**: Accepted

**Date**: 2026-08-04

**Related**: ADR-006, ADR-131, ADR-133, ADR-148

## Context

ADR-148 made the master-data ledger authoritative for source evidence, entity versions and the
active golden pointer. An activated master entity still lacked a generic `Resource` and
`ResourceVersion`, so Metadata Fabric bindings, lineage and other platform consumers could not
reference it through the platform's common identity contract.

OpenMetadata and Gravitino must not become activation authorities. OpenMetadata is an external
governance catalog, while a Gravitino binding is valid only after a real technical object exists.
Network calls to either provider also cannot be made part of a PostgreSQL activation transaction.

## Options Considered

| Option | Benefits | Costs and risks | Decision |
|---|---|---|---|
| Call OpenMetadata synchronously during master activation | Provider appears current immediately | Couples database commit to network/provider availability; timeout creates an uncertain distributed commit; provider identity can become a second authority | Rejected |
| Commit activation, then create generic identity and provider bindings on a best-effort path | Simple activation transaction | A committed golden pointer can remain permanently undiscoverable; retry may derive a different identity or lose predecessor evidence | Rejected |
| Atomically create a generic `ResourceVersion` and immutable activation projection, then project to providers asynchronously through explicit crosswalks | Commits the golden pointer and platform identity together; external delivery remains retryable and reconcilable | Adds a projection ledger and requires provider workers | Chosen |

## Decision

Migration 125 installs an `AFTER INSERT OR UPDATE` trigger on `master_entity_activation`. In the same
database transaction it:

- verifies the exact activated master version and fingerprint;
- registers the master entity as a generic `Resource` with authority
  `gda_control.master_data`;
- derives a stable UUID from tenant, entity-version ResourceURN and fingerprint, then inserts an
  immutable generic `ResourceVersion` with the previous projected version as predecessor;
- appends `master_resource_projection`, binding activation version, ApprovalCase, master version,
  generic version and projection time;
- rejects any pre-existing Resource, ResourceVersion or projection with different evidence, causing
  the complete activation statement and event write to roll back.

The projection table has forced tenant RLS, an immutable update/delete trigger and gateway SELECT
only. `GET /api/platform/v1/master-data/entities/{entity_id}/resource-projections` exposes bounded,
typed history without accepting tenant or ResourceURN from the client.

Provider integration occurs only after this transaction. An OpenMetadata governance binding may
reference the master `ResourceURN` through `MetadataFabricBinding`; this records a crosswalk and does
not claim that a provider entity exists. A Gravitino binding must wait for a real PostGIS/Iceberg
technical object. EA, OpenMetadata and Gravitino consume the common identity but do not control the
master active pointer.

For repository upgrades, migration 125 projects only each current active pointer. It does not
fabricate historical projection rows from activation events that predate this contract.

## Verification

- Focused authority, API and gateway tests pass with 88 tests; migration-runner tests pass with 22.
- `scripts/certify_master_data_lifecycle.py` applies the chain through migrations 112, 124 and 125 to
  disposable PostgreSQL 16.14. All 28 checks pass, including v1/v2 predecessor linkage,
  deterministic identity replay, exact content/authority evidence, forced RLS, immutability,
  gateway least privilege, OpenMetadata crosswalk registration and atomic rollback on Resource
  identity conflict.
- The optional report path is `/tmp/gda-master-data-lifecycle.json`; the disposable container is
  removed before certification succeeds.

## Consequences

- Master activation and platform-wide identity can no longer diverge after a successful commit.
- Metadata and lineage consumers can resolve a master entity through the same `ResourceVersion`
  contract used by the rest of the platform.
- Provider availability does not block activation, but provider projection freshness must be
  monitored and reconciled separately.
- This decision alone does not complete real OpenMetadata provider acceptance, a Gravitino technical
  binding, EA round-trip, golden-record distribution, or staging/production acceptance. The bounded
  delivery worker is specified separately by ADR-150.

## Revisit Trigger

Revisit when an external provider supports a proven transactional protocol with the control ledger,
when historical projection reconstruction can be backed by complete immutable evidence, or when a
real technical master-data product requires version-bound Gravitino objects and distribution SLOs.
