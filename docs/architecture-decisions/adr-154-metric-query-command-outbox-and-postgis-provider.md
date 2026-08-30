# ADR-154: Metric Query Command Outbox and PostGIS Provider

**Status**: Accepted

**Date**: 2026-08-05

**Related**: ADR-095, ADR-096, ADR-151, ADR-152, ADR-153

## Context

ADR-153 made metric-query admission and provider receipts durable, but an accepted Run still had no
reliable path to an executor. Executing PostGIS or Spark in the API process would couple query
completion to request lifetime. Adding a metric-specific queue would duplicate the existing
`PlatformCommand` lease, retry, dedupe and recovery authority.

Migration 138 preserves migration 137 as immutable history while tightening provider identity,
timestamp, counter, result metadata and reserved-manifest replay checks. The next migration must
carry command admission and provider binding without modifying either historical file.

## Options Considered

| Option | Benefits | Costs and risks | Decision |
|---|---|---|---|
| Execute queries in the metric API | Low initial latency | Process-bound execution, hidden retries, no lease recovery | Rejected |
| Add `metric_query_dispatch_outbox` | Query-specific schema | Duplicates command state, workers and operational tooling | Rejected |
| Submit every query to a new scheduler | One external execution path | Adds infrastructure and latency before an SLO proves need | Rejected |
| Extend unified `PlatformCommand` and add provider consumers | Reuses transactional delivery and Run evidence | Consumers must implement idempotent receipt recovery | Chosen |

## Decision

Migration 139 adds `metric_query.execute` to the unified command vocabulary. The public admission
function delegates to the preserved v138 implementation and then enqueues the command in the same
database transaction. Admission replay recreates a missing command but cannot create a second one.
The dedupe key binds tenant, Run, execution-plan Artifact and plan fingerprint; a SHA-256-derived
UUID gives the command a stable identity across replay and rollback.

The immutable command payload binds Run ID, plan Artifact ID and fingerprint, cache key, engine and
execution mode. Engine identity selects one workload:

- PostGIS: `workload:metric-query-postgis`;
- DuckDB: `workload:metric-query-duckdb`;
- Iceberg/Spark: `workload:metric-query-spark`.

Start and completion receipts must resolve the canonical command identity and exact payload. A
second command with copied payload but a non-canonical dedupe key or UUID cannot authorize a Run.
Start requires an in-flight claim. Completion accepts the same claimed command or an already
terminal delivery state so exact receipt replay remains possible.

`MetricQueryCommandConsumer` reuses `claim_commands`, `complete_command` and `fail_command`. Outbox
delivery attempt count is not a query attempt number: provider evidence remains attempt 1 and uses
command-derived external identity and start time. A temporary provider failure returns the command
to the outbox. When retries are exhausted, the consumer first writes a failed query receipt and
only then marks the command failed. If the worker stops after terminal Run evidence but before
command acknowledgement, lease recovery sees the terminal Run and completes the command without
executing the query again.

The first real provider is PostGIS. It accepts only `MetricQueryPlan`, never SQL. Relation, schema,
table and column identifiers are validated and quoted; `eq`, `in`, `between`, half-open time ranges
and the governed `intersects`, `within`, `contains` and `centroid_within` predicates are compiled
with bound values. Each database transaction is read-only and has a statement timeout. Result rows
are bounded and written by atomic rename as canonical JSON. The content hash, logical source row
count, `pg_column_size` byte count and read-only transaction evidence become the result Artifact.

## Rationale and Trade-offs

The unified outbox is the smallest pattern that solves the missing failure boundary. It avoids a
second scheduler while retaining at-least-once delivery and exact-once evidence through immutable
receipts. A local canonical JSON result is intentionally simpler than adding distributed cache or
object-store coordination in this slice.

Counting logical source rows and bytes adds a second bounded SQL statement. This is accepted for
auditable scan evidence and can be replaced by trustworthy engine-native statistics after measured
capacity shows the extra scan is material. Query leases must exceed the provider statement timeout;
long-running Spark work will require its own adapter and reconciliation protocol rather than using
this synchronous PostGIS process unchanged.

## Verification

- Focused metric planning, execution and command-consumer tests pass 29/29. They cover exact command
  payload validation, successful delivery, terminal recovery, retry exhaustion, safe identifier
  compilation and dangerous identifier rejection.
- `scripts/certify_metric_query_command_execution.py` applies migrations 095, 096, 097 and 136
  through 139 in disposable PostgreSQL 16.4 with PostGIS. All 15 checks pass for atomic admission,
  stable replay, exact payload, engine-specific claim, real spatial query results, read-only scan
  evidence, changed-request rejection, lease ownership, transient retry, terminal recovery, retry
  exhaustion, forged-command rejection, unsafe identifier rejection and cross-tenant RLS.
- The real query executes `centroid_within` against EPSG:4490 geometry, returns the expected two
  rows, and records two logical source rows. The disposable container is removed after the run.

## Consequences

- An admitted PostGIS metric query now moves from durable plan to recoverable execution and a
  content-hashed result Artifact without depending on the API process lifetime.
- Command delivery and provider evidence have separate identities and counters, so transport retry
  does not invent a second query attempt.
- DuckDB and Iceberg/Spark commands are admitted under their own workload identities but no provider
  implementation is claimed here. They remain pending until a deployed adapter exists.
- This slice does not implement distributed result cache, cancellation/reconciliation, worker
  deployment and health operations, `MetricObservation`, automatic Gold materialization, intelligent
  attribution, production capacity SLOs or staging/production acceptance.

## Revisit Trigger

Add DuckDB only when an interactive projection profile needs local-file execution. Add the
Iceberg/Spark adapter with external application identity, cancellation and reconciliation before
claiming asynchronous execution. Replace logical scan counting only after engine metrics provide
equally replayable row and byte evidence, and introduce another serving engine only after an
approved concurrency, latency or cost SLO fails on representative PostGIS workloads.
