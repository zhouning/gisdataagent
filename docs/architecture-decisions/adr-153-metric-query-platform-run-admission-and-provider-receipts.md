# ADR-153: Metric Query PlatformRun Admission and Provider Receipts

**Status**: Accepted

**Date**: 2026-08-05

**Related**: ADR-003, ADR-096, ADR-133, ADR-151, ADR-152

## Context

ADR-152 produces a deterministic, version-bound `MetricQueryPlan`, but a returned plan is not an
execution record. The platform still needs an atomic boundary that proves which definition,
security context, metric version, projection version and source snapshot a provider was authorized
to execute, followed by immutable start and terminal receipts.

Creating a separate query-job ledger would duplicate `PlatformDefinitionVersion`, `PlatformRun`,
`FrameworkAttemptObservation` and `Artifact`. Executing SQL or waiting for Spark inside the API
process would also create a second scheduler and make retries, cancellation and recovery dependent
on process lifetime.

## Options Considered

| Option | Benefits | Costs and risks | Decision |
|---|---|---|---|
| Execute SQL/Spark directly in the metric API | Short synchronous path | Process-bound work, hidden retries, no common Run evidence | Rejected |
| Add a dedicated metric query run and status subsystem | Query-specific schema | Duplicates platform identity, state, artifact and observation authorities | Rejected |
| Reuse generic DataProduct success finalization | Existing quality and lineage gate | A read-only query result is not a released ResourceVersion or DataProduct | Rejected |
| Admit into PlatformRun and require query-specific provider receipts | One run identity and state machine with evidence appropriate to queries | Providers must implement the receipt protocol | Chosen |

## Decision

Migrations 137 and 138 plus `MetricQueryExecutionAuthority` establish the following control-plane
protocol. Migration 137 introduces the evidence model; migration 138 tightens provider replay
without rewriting the historical migration:

1. The server replans the submitted semantic query under the authenticated tenant, subject, role
   and purpose. The run API never accepts a client-authored physical plan.
2. A deterministic, tenant-local metric query executor `PlatformDefinitionVersion` is registered
   idempotently. Synchronous PostGIS/DuckDB uses orchestration class `synchronous`; asynchronous
   Iceberg/Spark uses `dataops`.
3. One security-definer database function atomically creates the `PlatformRun`, exact metric-source
   input binding, execution-plan `Artifact` and immutable query admission. Failure leaves none of
   those four records. Definition registration is a preceding idempotent transaction, so an
   admission failure may leave only a reusable definition.
4. Admission rechecks that the metric and projection are active at the exact planned versions and
   fingerprints and still bind the exact output ResourceVersion, manifest and source snapshot.
5. A workload provider submits a separate start receipt. The database writes a provider-specific
   `FrameworkAttemptObservation` and moves the Run through `accepted -> dispatching -> running`.
6. A workload provider submits one terminal receipt containing cache hit/miss/bypass, returned and
   scanned rows, scanned bytes, duration, and exactly one successful result or failure error.
7. Success requires a credential-free, content-hashed result `Artifact`; failure forbids one. The
   query receipt and terminal attempt observation are immutable, and only then may the database move
   the Run to `succeeded` or `failed` through the private transition primitive.

Start and terminal receipt replay must match the first immutable evidence, including provider
identity, timestamp, counters, result metadata and error details. A changed replay is a conflict.
Provider result manifests may add fields but cannot override platform-reserved plan, cache or scan
evidence. Forced tenant RLS applies to both new ledgers; the gateway has SELECT and function EXECUTE
only, with no direct INSERT, UPDATE or DELETE rights.

The API adds:

- `POST /api/platform/v1/metric-query-runs` for server-side plan plus admission;
- `GET /api/platform/v1/metric-query-runs/{run_id}` for the submitter or a platform operator;
- `POST /api/platform/v1/metric-query-runs/{run_id}/start` for platform workload identities;
- `POST /api/platform/v1/metric-query-runs/{run_id}/complete` for platform workload identities.

## Rationale and Trade-offs

Reusing `PlatformRun` keeps query execution visible to the same audit, state and artifact model as
other platform work. A dedicated success gate is necessary because a transient query result does
not have the independent quality and input-to-output lineage evidence required to release a new
DataProduct ResourceVersion. The accepted trade-off is that query success proves execution and
result integrity, not business-data quality or product publication.

The admission function and the Run/plan Artifact share one transaction, while executor definition
registration does not. This avoids half-created Runs without forcing every query to rewrite the
same immutable definition. The protocol supports both synchronous and asynchronous providers, but
it deliberately does not add an in-process queue, scheduler or result cache.

## Verification

- The focused execution and planning contract suite passes 23/23 tests. Coverage includes
  deterministic definitions, security fingerprint mismatch, exact admission/run/artifact binding,
  success/error exclusivity, unsafe result URI rejection, server-side replanning, run ownership,
  workload-only provider receipts, route inventory, RLS and least privilege.
- `scripts/certify_metric_query_execution.py` applies migrations 096, 136, 137 and 138 after the existing
  metric bootstrap in disposable PostgreSQL 16.14. All 17 checks pass for atomic admission,
  idempotent and conflicting replay, start CAS, exact start binding, successful PostGIS evidence,
  failed asynchronous Spark evidence, result Artifact rules, reserved manifest fields, superseded
  projection rejection, append-only mutation denial, direct-write denial and cross-tenant RLS.
- The disposable certification container is removed after the run.

## Consequences

- A deterministic metric plan now has a durable Run identity, execution-plan Artifact and immutable
  provider evidence instead of ending at an API response.
- Consumers can distinguish admission, provider start and evidence-gated terminal outcome and can
  inspect cache and scan statistics without interpreting provider logs.
- This slice does not execute SQL, submit Spark applications, dispatch work, implement cancellation,
  materialize Gold data, operate a distributed result cache or publish `MetricObservation` business
  values. It also does not implement intelligent attribution or production capacity SLOs.
- Persistent development and production databases are not migrated by the certification.

## Revisit Trigger

Add provider adapters only through the existing orchestration gateway when a real PostGIS/DuckDB or
Iceberg/Spark execution profile is selected. Revisit the query success gate if query results become
durable governed products; at that point they must use ResourceVersion, quality and lineage release
evidence instead of treating the query receipt as product certification.
