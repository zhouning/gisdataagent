# ADR-155: Managed PostGIS Metric Query Command Worker

**Status**: Accepted

**Date**: 2026-08-05

**Related**: ADR-095, ADR-151, ADR-152, ADR-153, ADR-154

## Context

ADR-154 made PostGIS metric execution recoverable through the unified `PlatformCommand` outbox,
but the consumer was still only a library. Running it in the API process would couple query
availability to web replicas and request deployment. Treating each synchronous query as a
DolphinScheduler workflow would add submission latency and reconciliation before a measured SLO
requires that path. A production process also needs explicit secret handling, dependency probes,
health semantics and bounded shutdown behavior.

The provider performs two SQL statements: one for replayable logical scan evidence and one for the
bounded result. A command lease sized for only one statement can expire while a valid execution is
still running and permit another worker to reclaim it.

## Options Considered

| Option | Benefits | Costs and risks | Decision |
|---|---|---|---|
| Embed polling in the API process | No separate process | Web rollout and autoscaling change query ownership; weak shutdown boundary | Rejected |
| Submit every synchronous query to DolphinScheduler | Existing external scheduler operations | Extra latency and async reconciliation for interactive PostGIS work | Rejected |
| Create a metric-specific queue or scheduler | Custom lifecycle | Duplicates `PlatformCommand` truth and recovery | Rejected |
| Run the existing consumer as a tenant-scoped managed worker | Reuses command authority and provider code | Requires one process profile per tenant/provider identity | Chosen |

## Decision

`data_agent.metric_query_command_worker` is the managed process for the first PostGIS execution
profile. It is tenant-scoped and uses the fixed `workload:metric-query-postgis` identity; it cannot
claim DuckDB or Iceberg/Spark commands.

The process has two database boundaries:

- The platform control ledger uses the existing `POSTGRES_*` runtime connection and
  `gda_control_gateway` role transition.
- The PostGIS serving provider uses a separately scoped database URL read from an absolute,
  owner-only secret file. Its URL user must match the declared governed database role; the live
  probe rejects a superuser or any member of `gda_control_gateway`. The URL and password are never
  included in configuration summaries, status files or logs. The configured relation authority is
  the logical authority in governed `postgis://authority/schema.table` references, not a
  credential-bearing database endpoint.

Before claiming a command, each cycle opens a connection with a bounded connect timeout, starts a
read-only transaction and requires `PostGIS_Version()` to succeed. A failed provider probe leaves
the command unclaimed and moves the worker to `degraded`. A platform claim or receipt dependency
failure also degrades the process. A governed command-level query failure or exhausted retry is a
valid delivery outcome and increments counters without making the process unhealthy.

Configuration fails closed unless all secret, result and status paths are absolute and distinct,
the result root is not a filesystem root, and the lease exceeds one provider reconnect timeout plus
both execution statement timeouts. The health window covers the probe connection and bounded probe
statement, a possible execution reconnect, both execution statements and two polling intervals.
This reflects the actual synchronous path rather than only the longest individual SQL statement.

The worker writes an atomic mode-`0600` status document with `starting`, `ready`, `degraded` and
`stopped` states. Readiness requires a fresh successful cycle. Liveness accepts a fresh degraded
process so orchestration does not restart it during a recoverable database outage, but fails for a
missing, malformed, stale or stopped status. `SIGINT` and `SIGTERM` stop polling after the current
batch. Unexpected programming errors terminate the process instead of entering an infinite retry
loop.

The package exposes `gda-metric-query-worker` and the equivalent
`python -m data_agent.metric_query_command_worker` commands:

- `validate` checks configuration plus live platform and PostGIS dependencies;
- `run` starts polling, while `run --once` executes one operational cycle;
- `health` and `liveness` evaluate the local status document without database credentials.

## Rationale and Trade-offs

This is the smallest deployable boundary that preserves the unified outbox and avoids a second
scheduler. A provider probe on every polling cycle adds one short read-only round trip, accepted so
an idle worker cannot report ready while its serving database is unavailable. The health document
is local process evidence, not a replacement for command queue, query latency or database SLO
telemetry.

One process handles one tenant and PostGIS profile. This increases deployment instances for many
tenants, but keeps tenant identity and provider credentials explicit. Multi-tenant pooling should
only replace it after isolation and capacity evidence proves that the operational cost is material.

## Verification

- Worker unit tests pass 12/12 and cover configuration budgets, owner-only provider URL files,
  redaction, environment parsing, provider-before-claim ordering, successful counters, provider and
  gateway degradation, command-level failure, fail-closed probes, graceful stop and unexpected
  process failure. A real filesystem negative test proves Artifact write failures become redacted,
  retryable provider errors instead of process crashes. The complete focused metric suite passes
  50/50.
- The disposable PostgreSQL 16.4 + PostGIS command certification passes 18/18. It builds the
  provider engine from the secret-file profile, executes the real EPSG:4490 metric query through the
  managed worker, and proves fresh readiness/liveness plus a redacted mode-`0600` status file while
  retaining command replay, retry, terminal recovery, forged-command rejection and cross-tenant
  RLS. The real provider role has source-table `SELECT`, but no `INSERT`, superuser, database-create,
  role-create or platform-gateway membership.
- The packaged `gda-metric-query-worker` help path, Python compilation, Ruff and diff checks pass.

## Consequences

- The PostGIS command consumer now has a deployable, observable process boundary independent of the
  API lifetime.
- Provider outages are detected before command ownership, reducing avoidable lease churn.
- Platform and serving database credentials can be independently rotated and scoped.
- This does not claim staging or production deployment, horizontal capacity, distributed cache,
  cancellation, business `MetricObservation`, attribution analysis, DuckDB or Spark execution.

## Revisit Trigger

Add an orchestrator-specific deployment manifest only when its secret volume can preserve the
owner-only file contract. Add provider probe backoff or a lower-frequency probe only if measured
idle probe load is material. Move synchronous work to an external scheduler when representative
queries cannot fit the 3600-second command lease or an approved concurrency/latency SLO fails.
