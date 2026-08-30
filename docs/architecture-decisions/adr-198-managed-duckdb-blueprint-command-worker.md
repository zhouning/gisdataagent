# ADR-198: Managed DuckDB Blueprint Command Worker

**Status:** Accepted (local worker process contract)

## Context

ADR-197 proved real DuckDB/Parquet execution, but the public API process still
invoked the provider synchronously. That couples request lifetime and API
capacity to data processing, leaves no durable initial dispatch, and cannot
recover an acknowledgement lost after provider completion. The platform
already has a tenant-scoped transactional command outbox with lease and replay
semantics.

## Options Considered

1. Keep synchronous API execution. This preserves the smallest code path, but
   cannot isolate provider capacity or recover delivery independently.
2. Introduce a separate queue, scheduler or worker service authority. This can
   scale independently, but duplicates command and lifecycle state already
   owned by the platform ledger.
3. Extend the shared outbox vocabulary and run a managed worker from the same
   codebase. This adds a process boundary while preserving one command delivery
   mechanism and one `PlatformRun` authority.

## Decision

DuckDB Blueprint admission atomically creates the existing Run, execution-plan
Artifact and one `blueprint_provider.execute` command. The command binds the
Run, plan, definition hashes, engine and initial attempt, and is claimable only
by `workload:blueprint-duckdb-executor`. Migration 200 adds only that command
type to the existing outbox constraint.

The managed worker performs bounded DuckDB/PyArrow and output-root readiness
checks, claims commands with the existing database lease, executes outside API
and control-plane transactions, then completes the command after the existing
success authority commits. A redelivered command observes a terminal Run and
only completes delivery; it does not rerun the provider. Control-plane delivery
failures return the command to the outbox without persisting private error
details. The existing synchronous endpoint remains a compatibility path and
uses the same dedicated identity and idempotent result authority.

## Trade-offs Accepted

This is a managed local worker contract, not an HA deployment. Its admitted
Parquet inputs and deterministic output are still `file://` locations that the
API and worker must both mount. Conservative lease and health budgets cover a
bounded batch, but there is no mid-query lease heartbeat. One process is
configured for one tenant so command claims remain explicit and auditable.

## Consequences

Provider work no longer depends on an HTTP request and outbox redelivery can
reconcile completion after an acknowledgement failure. No scheduler, registry,
Run table or provider state store was added. Immutable object storage, lease
heartbeat for long executions, multi-replica deployment, NetworkPolicy,
capacity SLO and staging/production rollout remain required before HA claims.

## Revisit Triggers

Replace the local storage boundary before multiple hosts or replicas execute
Blueprints. Add heartbeat or external cancel/reconcile when admitted work can
outlive the conservative lease. A Spark provider must consume the same plan and
outbox contracts rather than introduce a separate Run lifecycle.
