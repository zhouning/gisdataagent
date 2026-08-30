# ADR-126: Spatial output and completion receipt commit atomically

- Status: accepted
- Date: 2026-08-03

## Context

ADR-125 made a durable completion receipt sufficient for reconciling a missing
security outcome. The polygon and point implementations still committed the
output table, differential-privacy updates and GiST index in separate
transactions, then opened another connection to record the receipt. A receipt
failure could therefore leave a completed output table without durable
completion evidence.

The existing platform command outbox is intentionally a thin delivery mechanism
for DolphinScheduler provider commands. ADR-007 forbids its consumer from
executing long business logic. Adding a local security queue or background
worker would create another scheduler and would not make the current PostGIS
commit atomic.

## Options considered

| Option | Benefit | Cost | Decision |
|---|---|---|---|
| Keep intermediate commits and rely on reconciliation | No code change | Missing receipt cannot prove whether the output completed | Rejected |
| Add a local queue and worker | Durable request identity | Duplicates scheduler, lease and retry responsibilities | Rejected |
| Immediately model the operation as a full DolphinScheduler/Temporal run | Target architecture alignment | Requires provider definition, deployment and recovery acceptance beyond this bounded defect | Deferred |
| Commit PostGIS output and guarded receipt in one transaction | Removes the current orphan-output window with existing PostgreSQL authority | Longer transaction; outcome remains separate | Selected |

## Decision

`grid_anonymize_pg` and `poi_grid_aggregate_pg` now use one caller-owned
PostgreSQL transaction for:

1. output-table creation;
2. optional differential-privacy updates;
3. output statistics used by the receipt;
4. GiST index creation; and
5. `gda_control.record_security_operation_receipt(...)`.

`SecurityEventLedger.record_operation_receipt_in_transaction(...)` joins that
transaction without opening or committing another connection. It temporarily
assumes the least-privilege `gda_control_gateway` role, binds the tenant with a
transaction-local setting, calls the guarded database function and restores the
session role. The caller remains responsible for commit or rollback.

If receipt validation or persistence fails, the exception leaves the transaction
scope and PostgreSQL rolls back the output table, privacy updates, index and
receipt together. No successful result is returned. Catalog lineage and
sensitivity projection start only after this transaction commits and remain
best-effort projections rather than commit authority.

The API still writes the admitted event before execution and the outcome event
after the output-and-receipt transaction. If the outcome append fails, ADR-125's
deterministic reconciler uses the atomically committed receipt to append the
missing success outcome.

## Verification

The focused Python suite verifies that polygon and point implementations use
`engine.begin()`, pass the same connection to the ledger and perform no direct
commit.

`scripts/certify_security_event_reconciliation.py` runs 17 PostgreSQL 16 checks,
including output-and-receipt co-commit and a rejected-row-count receipt that
rolls back both the output table and receipt.

`scripts/certify_atomic_spatial_anonymization.py` runs 15 checks in an
automatically removed `postgis/postgis:16-3.4` container. It executes real polygon
and point `ST_SquareGrid` operations, creates valid GiST indexes, records receipts,
reconciles outcomes, verifies event/receipt integrity and proves that a
resource-binding rejection leaves no output table or receipt.

## Trade-offs and boundary

Large spatial transformations now keep one database transaction open through
index and receipt creation. This improves correctness but can increase lock time,
WAL retention and rollback cost. Production SLO and capacity acceptance must
bound input size and transaction duration.

This decision assumes the PostGIS output and `gda_control` receipt authority are
reachable in the same PostgreSQL transaction. Cross-database or cloud-provider
outputs still require a durable provider command, completion artifact and
reconciliation protocol. The target path remains DolphinScheduler for DataOps
and Temporal for durable actions; the PostgreSQL outbox must only deliver to
those providers.

The outcome append remains a separate transaction, but now has an atomic durable
receipt for deterministic recovery. API process restart before commit results in
a PostgreSQL rollback; this slice does not provide asynchronous request status,
automatic provider retry, cancellation or a durable workflow run.

This decision does not complete full classification policy, encryption/key
rotation, release security gates, AR-3, AR-4, the full data-security lifecycle or
the next-generation Data Platform.
