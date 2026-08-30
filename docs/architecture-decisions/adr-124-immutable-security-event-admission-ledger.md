# ADR-124: Sensitive spatial operations require immutable admission evidence

- Status: accepted
- Date: 2026-08-03

## Context

ADR-123 made spatial anonymization and re-identification verification fail closed
on identity, role, governed asset access and safe table identifiers. Their only
operation record was still `agent_audit_log`. That log is intentionally
best-effort, retention-based and mutable, so a sensitive operation could execute
even when no durable security evidence was recorded.

The platform already has a tenant-scoped `gda_control` control plane, a
least-privilege `gda_control_gateway` role, forced RLS and immutable-ledger
triggers. Adding an unrelated audit database or a second control plane would
split tenant context and operating authority.

## Options considered

| Option | Benefit | Cost |
|---|---|---|
| Keep only `agent_audit_log` | No new schema | Sensitive work can run without durable evidence; records can expire or be deleted |
| Build a separate security control plane | Independent storage boundary | Duplicates tenant, identity, migration, backup and operating authority |
| Extend `gda_control` | Reuses tenant RLS, gateway role and migration authority | The ledger shares the PostgreSQL administrative trust boundary |

## Decision

Migration 110 adds `gda_control.security_event` as a tenant-scoped append-only
SHA-256 chain. Each tenant has a contiguous sequence and each event includes the
previous event hash. `(tenant_id, attempt_id, phase)` is the idempotency key, and
a tenant-scoped advisory transaction lock serializes sequence assignment.

Only `gda_control.append_security_event(...)` may be used by the runtime gateway
role. The role can read events through forced RLS and execute append/verify
functions, but cannot directly insert, update or delete rows. A database trigger
rejects update and delete even for the table owner. The verification function
recomputes sequence, previous-hash and event-hash integrity.

Sensitive classification operations use three event forms:

- `denied/denied` for authorization, asset access and request-validation denial;
- `admitted/admitted` after all checks pass and before the spatial operation starts;
- `outcome/success|failure` after execution returns or raises an exception.

An admitted event is mandatory. If it cannot be appended, the API returns 503
and does not call the spatial operation. If execution finishes but the outcome
event cannot be appended, the API returns `security_evidence_incomplete` with an
attempt ID for reconciliation. Denials remain fail closed even if their
best-effort security-event append fails. `agent_audit_log` remains the operational
query log and links attempt, admission and outcome IDs where available; it is no
longer the only security evidence.

## Verification

`scripts/certify_immutable_security_event_ledger.py` applies migrations 092, 094
and 110 in an automatically removed PostgreSQL 16 container. It verifies tenant
RLS isolation, contiguous sequence and previous hashes, idempotent replay,
conflict rejection, gateway direct-write denial, immutable-trigger enforcement,
least-privilege grants, chain verification and detection of a deliberately
privileged mutation. API and client tests also prove that admission failure
prevents anonymization and verification from starting.

## Trade-offs and boundary

The outcome event and PostGIS anonymization DDL are not committed by one database
transaction. An operation can therefore complete while its outcome evidence is
temporarily incomplete; the attempt ID is the reconciliation handle. Moving the
spatial work behind a durable command/outbox boundary is the revisit trigger for
atomic execution evidence.

The hash chain detects privileged mutation but is not an external trust anchor.
A PostgreSQL superuser can disable triggers or replace both data and hashes.
Production compliance still requires periodic external hash anchoring or WORM
export, separate retention authority, backup/restore verification and alerting.

The gateway login can set the transaction-local tenant setting; application
authentication remains responsible for binding an authenticated subject to that
tenant. Full asset tenant ownership, purpose, column, row, spatial and temporal
policy, encryption/key rotation, release security gates and security-event
reconciliation are not delivered here. This decision does not complete AR-3,
AR-4, the full data-security lifecycle or the next-generation Data Platform.

Migration 110 may only be applied by the migration authority in an explicitly
selected environment. This decision does not authorize migration of the shared
development database.
