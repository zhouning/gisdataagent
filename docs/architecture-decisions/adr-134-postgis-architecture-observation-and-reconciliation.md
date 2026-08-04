# ADR-134: PostGIS architecture changes are observed before they are adopted

- Status: accepted
- Date: 2026-08-03

## Context

ADR-133 created immutable schema, contract and physical-location bindings for a
`ResourceVersion`, but a binding alone cannot prove that the provider object
still exists or still has the same structure and physical identity. Treating a
connector exception as deletion would create false tombstones. Automatically
rewriting the binding after every successful scan would make the harvester a
new architecture authority and allow unreviewed DDL to become accepted state.

The first provider slice must be real and small enough to verify end to end.
The repository already operates PostGIS and PostgreSQL 16; it does not yet have
a version-pinned Gravitino sandbox or certified Spark/Flink Gravitino path.

## Options considered

| Option | Benefit | Cost |
|---|---|---|
| Reuse generic connector discovery JSON as architecture truth | Minimal implementation | Unbounded provider payload, weak physical identity and no immutable observation lifecycle |
| Copy complete PostgreSQL catalogs into the control ledger | Rich diagnostics | Builds another technical catalog and may retain defaults or other sensitive expressions |
| Hash bounded system-catalog facts and append observations | Deterministic drift evidence without duplicating provider metadata | Detailed differences require a fresh provider query or separate governed evidence |
| Auto-rebind whenever a scan differs | No manual reconciliation step | Makes provider drift authoritative and bypasses impact/approval gates |

## Decision

Migration 114 adds append-only, tenant-scoped
`ArchitectureProviderObservation`. A successful observation records provider
identity, object state, source revision, schema-content hash, candidate
`SchemaVersion` and `PhysicalLocation` hashes, `observed_at`, `fresh_until` and
a canonical observation SHA-256. It stores no schema document, row data,
endpoint, credential or connection string.

The PostGIS harvester runs one PostgreSQL transaction as `READ ONLY` with a
bounded statement timeout. It resolves the table through parameterized system
catalog queries and hashes ordered columns, constraints and non-primary
indexes. PostGIS geometry type and SRID are represented through PostgreSQL's
canonical `format_type` result. The physical revision binds relation OID and
filenode; the immutable content checksum and snapshot reference still come
from the admitted `ResourceVersion` rather than an estimated table count.

Only a successful catalog query that finds no matching table emits
`tombstoned`. Authentication, timeout, transport and SQL errors propagate and
produce no observation. Present observations return deterministic schema and
location candidates, but never register or bind them automatically.

The gateway compares the latest successful observation with the immutable
binding and returns one of:

- `unobserved` or `unbound`;
- `in_sync`;
- `stale` when `fresh_until` has passed;
- `schema_drift`, `location_drift` or both;
- `tombstoned`.

Every non-synchronized status carries an explicit required action. Agent or LLM
automation may explain the difference or prepare a proposal, but a later
impact/approval flow must create a new `ResourceVersion` and architecture
binding. It cannot mutate the current binding.

## Verification

A disposable `postgis/postgis:16-3.4` acceptance used PostgreSQL 16.4 and
PostGIS 3.4.3. It created a real polygon table with SRID 4326 and GiST index,
then verified:

1. initial harvest, unbound status, explicit binding and `in_sync`;
2. freshness expiry produces `stale`;
3. `ALTER TABLE ADD COLUMN` produces `schema_drift` only;
4. drop and same-schema recreation produces `location_drift` through a new
   relation identity;
5. final drop produces a real tombstone;
6. replay is idempotent, conflicting observation payloads fail, cross-tenant
   reads fail, and direct update/delete is rejected.

The ledger retained three present observations and one tombstone while the
accepted schema, contract, location and binding each remained exactly one row.
RLS was enabled and forced, the immutable trigger was active, and the gateway
had `SELECT/INSERT` without `UPDATE/DELETE`. The temporary container was
removed. The repeatable script is
`scripts/certify_postgis_architecture_reconciliation.py`; the secret-free report
is `.tmp/data-architecture-provider-reconciliation/acceptance-report.json`,
SHA-256
`bc160bdc7d9e2807db8b851992f4af3edd0727f9b126bd85496051e21c425778`.

## Consequences and boundary

This makes PostGIS architecture freshness, structural drift, physical
replacement and deletion observable without changing authority. It does not
provide field-level diff storage, compatibility classification, impact
analysis, approval, automatic new-version creation, scheduling or alerting.
It does not validate Gravitino, Iceberg, object storage, STAC or DuckDB
harvesters and does not complete AR-1 or the Metadata Fabric.

## Revisit triggers

Revisit the bounded hash projection when an approved diagnostic store is needed
for field-level diffs. Revisit relation OID/filenode identity when logical
replication, partition exchange or managed PostGIS providers require a stronger
revision. Add a provider adapter only after its native object identity,
revision, error and tombstone semantics have a real conformance test.
