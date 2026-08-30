# ADR-234: Automatic GIS ServiceSLO Activation Reconciliation

## Status

Accepted

## Context

ADR-233 established `gis_service_slo_binding` as the GIS projection of one
exact generic SLO activation. Requiring a human to perform a second binding
operation after every approved activation leaves an avoidable gap: an active
GIS service can temporarily have no projection task, while putting GIS binding
logic directly inside generic activation would make the generic SLO authority
implicitly own GIS lifecycle semantics.

## Decision

Migration 224 adds a tenant-scoped reconciliation outbox. The generic SLO
activation transaction emits one idempotent task containing service URN,
definition/version, fingerprint, ApprovalCase and activation CAS evidence. A
separate lease-controlled worker claims the task and calls the migration 223
binding authority in the same database transaction.

The worker rechecks the current activation before binding. If a newer activation
has replaced the task evidence, the task becomes `superseded` and cannot bind
the stale version. Existing exact manual bindings are reused. Claim performs a
compensation scan for active GIS SLOs created before migration 224 or while a
trigger was unavailable. Expired leases are redelivered with bounded attempts;
terminal failures remain visible in the outbox.

## Trade-offs

The outbox and worker add an asynchronous convergence window and an operational
worker to the deployment. That cost preserves generic SLO authority, avoids a
cross-domain transaction, supports replay/backfill, and makes stale activation
handling explicit. This decision does not claim worker HA/RTO, full Incident
automation, or multi-provider conformance.

## Consequences

- Every GIS ServiceSLO activation has a durable, auditable reconciliation task.
- Exact binding remains append-only and is still created only by migration 223.
- Activation replacement cannot accidentally create a stale binding.
- Compose deployments can enable the worker with the `gis-slo` profile and a
  tenant-scoped workload identity.

## Validation

`scripts/certify_gis_service_slo_reconciliation.py` passed against PostgreSQL
16 after applying all 224 migrations. It verified activation replay,
automatic task creation, manual binding reuse, superseded tasks, trigger-gap
backfill, lease redelivery/max-attempt handling, forced RLS, direct-write
denial, cross-tenant isolation, and least-privilege trigger execution.
