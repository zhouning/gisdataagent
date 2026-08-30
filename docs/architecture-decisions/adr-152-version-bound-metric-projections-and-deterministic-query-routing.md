# ADR-152: Version-Bound Metric Projections and Deterministic Query Routing

**Status**: Accepted

**Date**: 2026-08-05

**Related**: ADR-002, ADR-006, ADR-103, ADR-133, ADR-151

## Context

ADR-151 established the canonical metric meaning, but an active definition alone cannot answer a
query efficiently. The platform needs to select between PostGIS Serving, DuckDB interactive and
Iceberg/Spark batch data without changing aggregation semantics, querying a stale snapshot or
sharing cached results across metric versions and security contexts.

Allowing an LLM to choose a table and generate SQL directly would bypass active-version,
DataProductVersion, spatial CRS, non-additive grain and freshness controls. Adding another OLAP
engine before measuring the existing profiles would also increase operational responsibility
without evidence that it solves a current SLO gap.

## Options Considered

| Option | Benefits | Costs and risks | Decision |
|---|---|---|---|
| Let NL2SQL select relations and generate physical SQL | Short path to a demo | Non-deterministic semantics, injection surface, no exact snapshot or cache evidence | Rejected |
| Resolve only the metric and let each engine choose its own source | Thin control plane | Different consumers can calculate the same metric from different data or grains | Rejected |
| Register immutable version-bound projections and compile a structured query plan | Replayable routing, fail-closed aggregation and cache isolation | Materializers must register every refreshed projection version | Chosen |
| Add a dedicated OLAP engine now | Potentially lower latency at scale | New deployment, security, backup and skill burden before a benchmark proves need | Deferred |

## Decision

Migration 136 establishes immutable `MetricProjectionVersion`, a CAS active pointer and append-only
events. A projection version binds all of the following evidence:

- exact active MetricDefinitionVersion ResourceURN and fingerprint;
- exact passed DataProductVersion, output ResourceVersion and manifest SHA-256;
- immutable source snapshot reference and refresh timestamp;
- PostGIS, DuckDB or Iceberg/Spark engine profile and Serving/Interactive/Gold/Batch tier;
- credential-free physical relation reference, metric value column, dimension mapping and grain;
- optional time column/grain and geometry column/SRID/CRS;
- estimated rows and observed p95 latency used by deterministic routing.

Staging verifies the exact metric and passed DataProductVersion evidence. Activation does not require
a second human approval because it does not change metric meaning, but it rechecks that the bound
metric is currently active at the exact version and that the DataProductVersion evidence still
matches. Activation uses CAS. Tables use forced tenant RLS and immutable triggers; the gateway can
read them and invoke security-definer lifecycle functions but cannot write them directly.

`MetricQueryPlanner` resolves an active metric, loads only projections bound to that exact active
version and applies the following rules:

- additive metrics may roll a finer projection up to a requested dimension subset;
- semi-additive metrics may not remove a non-additive dimension unless an exact equality filter
  preserves it; non-additive metrics require an exact preserved grain;
- time coarsening is allowed only for additive metrics; spatial filters require the governed
  geometry binding and exact CRS;
- stale or latency-incompatible projections are rejected;
- bounded PostGIS Serving and DuckDB interactive scans are synchronous; scans beyond the configured
  bound require an eligible Iceberg/Spark projection and become asynchronous;
- Serving wins over Interactive, Gold and Batch among otherwise eligible plans.

The planner returns `gda.metric_query_plan.v1`, a structured physical intent rather than SQL. Its
cache key includes exact metric, projection, DataProductVersion, output ResourceVersion, manifest,
snapshot, filters, grouping, time/spatial constraints, tenant, subject, roles and purpose. No
eligible projection is a conflict response, not permission to fall back to arbitrary SQL.

The API adds projection stage/list/activate/events, active projections for a metric, and
`POST /api/platform/v1/metric-query-plans`. Projection lifecycle remains a platform-operator
surface; authenticated tenant consumers may request plans under their own security context.

## Verification

- Sixteen focused metric tests pass. The new planner coverage includes engine/tier identity,
  additive rollup, semi/non-additive rejection, exact-date preservation, freshness, spatial binding,
  Serving preference, large-scan Spark routing and cache-key isolation.
- `scripts/certify_metric_projection_query_planning.py` applies migration 136 after the metric
  authority migrations in disposable PostgreSQL 16.14. All 17 checks pass, including exact
  DataProductVersion manifest binding, inactive-metric activation rejection, CAS, active resolution,
  planner routing, append-only evidence, direct-write denial and cross-tenant RLS.
- The disposable certification container is removed after the run.

## Consequences

- Humans, agents and APIs can receive the same replayable metric execution decision without letting
  an LLM author physical SQL.
- A refreshed table or lakehouse snapshot is a new immutable projection version; it cannot silently
  replace evidence behind a cached result.
- The control plane now chooses an execution profile but does not yet submit SQL/Spark jobs, persist
  query plans as Artifacts, materialize Gold tables, execute a distributed cache or record
  MetricObservations.
- Estimated rows and p95 latency are registration evidence in this slice. Production routing still
  needs provider observations, capacity benchmarks and SLO feedback before it can claim sustained
  high-throughput performance.

## Revisit Trigger

Revisit the engine set only when representative PostGIS/DuckDB/Iceberg+Spark benchmarks fail an
approved latency, concurrency, freshness or cost SLO. Revisit query-plan persistence when execution
is connected to PlatformRun/Artifact, and revisit grain rules when the semantic expression authority
can prove decomposable algebra beyond additive `sum` rollups.
