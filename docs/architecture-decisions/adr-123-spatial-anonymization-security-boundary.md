# ADR-123: Spatial anonymization must resolve governed assets before execution

- Status: accepted
- Date: 2026-08-03

## Context

The classification API previously accepted physical PostGIS table names directly.
An authenticated caller could therefore request anonymization or verification for
a table that was not visible through the asset catalog. The implementation also
used caller-provided identifiers in generated SQL and replaced an existing output
table with `DROP TABLE IF EXISTS`.

Migration 032 is older than the unified `agent_data_assets` table. In a normally
ordered migration history it can apply policies to the legacy catalog without
ever protecting the later backing table. Its shared predicate was also part of a
single policy, which could make a shared asset writable instead of read-only.

## Decision

1. Classification routes establish the authenticated user context before every
   catalog query and retain an explicit owner/shared/admin predicate in the query.
2. Anonymization and verification resolve source and output tables through
   governed PostGIS catalog assets. Missing or inaccessible assets fail closed.
3. Only simple PostgreSQL identifiers are accepted. Schema, table and column
   identifiers are validated both at the API boundary and in the core spatial
   anonymization functions.
4. Anonymization creates a new output table and never drops an existing table.
5. Analysts and administrators may execute anonymization and verification;
   viewers are denied. Authenticated success, failure and denial outcomes are
   written to the existing operational audit log.
6. Migration 109 enables and forces RLS on `agent_data_assets`, removes the legacy
   policy, and installs separate SELECT, INSERT, UPDATE and DELETE policies.
   Shared assets are readable but only their owner or an administrator can change
   them.

## Boundary

The current operational audit log is best-effort and retention-based; it is not
an immutable compliance ledger. The asset catalog also does not yet carry the
full tenant, purpose, spatial, temporal and action policy model described by AR-3
and AR-4. Field encryption remains outside this slice. Therefore this decision
does not complete the platform security lifecycle, AR-3, AR-4, or the next-
generation Data Platform objective.

Migration 109 may only be applied by the migration authority in an explicitly
selected environment. This decision does not authorize migration of the shared
development database.
