# ADR-358: ApprovalCase SLA escalation projection

## Status

Verified as a bounded PostgreSQL slice. The companion bounded bulk-escalation
orchestration is recorded in ADR-359. Production paging, enterprise on-call
synchronization and batch approval remain open.

## Context

ApprovalCase already has an authoritative terminal verdict, assignment checks and
a durable Alertmanager outbox. That outbox only represented request, expiry and
decision notifications, so an unattended case could not be routed to a standby
team before expiry. Adding escalation to the verdict state machine would make an
operational reminder look like an approval decision and would weaken the existing
CAS boundary.

## Decision

1. Store each pre-expiry escalation as an immutable `approval_case_sla_escalation`
   row bound to tenant, case reference, pending state version, action, target
   fingerprint, stage, due time, team and on-call reference.
2. Derive a SHA-256 idempotency key from that complete scope. The database
   recomputes the key and permits one row per case/stage; a replay returns the
   original row.
3. A due escalation is materialized into the existing notification outbox by a
   `SKIP LOCKED` function. Migration 250 makes `escalation_stage` part of the
   outbox delivery identity, so stage 1 and stage 2 can coexist for one case.
   The outbox carries the routing evidence and uses the existing worker
   delivery/retry/dead-letter path.
4. A terminal ApprovalCase event suppresses scheduled and materialized-but-
   pending escalation projections. A materialized projection retains its
   `materialized_at` evidence while recording `suppressed_at`; it never changes
   the case verdict and never sends an automatic approval or rejection.
5. Scheduling and materialization are exposed only through `SECURITY DEFINER`
   gateway functions; the gateway has SELECT-only table access and cannot mutate
   escalation rows directly.

## Verification

`certify_agentops_approval_sla_escalation.py` ran against disposable PostgreSQL
16 and verified:

- schedule replay is idempotent;
- both due escalation stages materialize exactly once, and a replay creates no
  duplicate notification;
- a human decision suppresses both pending materialized stages;
- stale state version is rejected;
- tenant RLS isolation holds;
- gateway direct mutation is not granted;
- the ApprovalCase verdict remains `approved` after escalation processing.

Report: [`agentops_approval_sla_escalation_2026-08-30.json`](../reports/agentops_approval_sla_escalation_2026-08-30.json)

- `report_sha256=5e8baee73736f8c05947300059a491c6aa5fc9838e4fa550c3c27d9116687f40`
- file SHA-256: `c97dd1f5c62776133b326ea4c2e005060e309ee4c8ce14a80b7c9bb84e0b70b9`
- migration 250 SHA-256: `20a1d7ed5e339c30d652dcd9070b5b37fb25b7f122230ba91384952ab0930033`

## Limits and next gate

This slice does not provide batch approval, bulk escalation, production paging,
enterprise on-call API synchronization, UI inboxes, or production HA/RPO/RTO.
Those must preserve per-case authority checks and return per-case outcomes rather
than claiming an all-or-nothing batch transaction.
