# ADR-133: ResourceVersion architecture uses references and fingerprints, not a third catalog

- Status: accepted
- Date: 2026-08-03

## Context

The control ledger already identifies immutable `ResourceVersion` objects, but
could not authoritatively answer which technical schema, governance contract or
provider snapshot applied to one version. The existing schema-drift ledger
records change observations and reconciliation; it is not the current
architecture binding for a resource version.

OpenMetadata remains the authority for governance metadata and contracts.
Gravitino and execution/storage providers remain the authorities for technical
schema, catalog objects, snapshots and physical facts. Copying their complete
documents into GDA would create another catalog and an unresolved multi-writer
problem.

## Options considered

| Option | Benefit | Cost |
|---|---|---|
| Store complete schema, contract and location JSON in GDA | Self-contained reads | Duplicates authority documents, increases secret/drift risk and creates a third catalog |
| Keep only independent external references | Small schema | A caller can combine schema, contract and location records from different resource versions |
| Store typed references plus an immutable composite binding | Small authority-safe surface with database-enforced version consistency | Requires explicit harvesters and one extra readiness step |

## Decision

Migration 113 adds tenant-scoped, append-only `SchemaVersion`,
`DataContractVersion`, `PhysicalLocation` and
`ResourceVersionArchitectureBinding` records. Each fact references an existing
`ResourceVersion`, carries a canonical SHA-256 and stores only normalized
external identity:

- schema references identify a Gravitino or provider object and version;
- contract references identify an OpenMetadata or provider contract and
  enforcement mode;
- location references identify provider, namespace, locator,
  snapshot/revision and content checksum.

Composite foreign keys require every component in an architecture binding to
belong to the same tenant and `ResourceVersion`. A binding is all-or-nothing;
an incomplete set of component records is reported as not architecture-ready.
The first slice permits one bound schema, contract and primary physical
location per resource version. Replicas and placement history remain future
`StorageBinding` and `PlacementDecision` work.

All four tables force row-level security and reject update/delete. The existing
least-privilege gateway role receives only `SELECT` and `INSERT`. Typed gateway
transactions provide independent component registration, atomic complete
registration, idempotent replay, immutable conflict detection and a fail-closed
readiness projection.

An Agent or LLM may propose a schema, contract or placement change, but it
cannot become the authority by writing a free-form document. A provider or
governance harvester must resolve an immutable external version before the
controller can create the binding.

## Verification

Contract tests verify canonical fingerprints, required provider revision and
same-resource registration. A disposable PostgreSQL 16.14 acceptance verifies
idempotent registration, conflicting payload rejection, incomplete readiness,
same-resource composite foreign keys, cross-tenant denial, direct update/delete
denial and a complete ready projection.

The acceptance recorded two complete resource versions. All four tables had
forced RLS and immutable triggers; the gateway had `SELECT/INSERT` and no
`UPDATE/DELETE`. The random container and port were removed after the run. The
repeatable script is
`scripts/certify_data_architecture_version_authority.py`; the secret-free report
is `.tmp/data-architecture-version-authority/acceptance-report.json`, SHA-256
`fd3121b6f4051aa737fbf6bec19bbaf90004df180481fb628db02c1bb9e81109`.

## Consequences and boundary

This closes the missing architecture identity chain for a `ResourceVersion`.
It does not harvest real OpenMetadata/Gravitino objects, reconcile provider
deletion, model schema compatibility, manage replicas, execute architecture
changes, or provide search and lifecycle UX. It therefore does not complete
the Metadata Fabric, AR-1 data architecture scope or the next-generation Data
Platform.

## Revisit triggers

Revisit the one-primary-location binding when a resource version must expose
multiple active replicas or placement history. Revisit the authority enums when
an approved contract/schema authority is added, and revisit append-only binding
semantics only after provider tombstone and replacement reconciliation has a
tested lifecycle model.
