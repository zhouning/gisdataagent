# ADR-342: PostgreSQL authority for specialist provider operation receipts

## Status

Accepted and verified for the bounded PostgreSQL authority slice; production readiness
is not claimed.

## Context

MMFE/GWM activities can submit a provider operation successfully and then lose the
Temporal activity response.  A retry based only on activity history can submit the
same side effect twice.  The in-memory receipt authority already defines the
provider-neutral contract, but it is not durable across worker processes or restarts.

## Decision

Persist `SpecialistOperationReceipt` as an append-only PostgreSQL history in
`gda_control.agentops_specialist_operation_receipt_history` (migration 246), expose a
current-state view, and allow writes only through the security-definer function
`record_agentops_specialist_operation_receipt`.

The database contract is deliberately separate from Temporal checkpoint/evidence
history:

- one `operation_ref` identifies one provider side effect;
- the first row must be `submitted`;
- `submitted`/`unknown` may converge to `succeeded`, `failed`, or `cancelled`;
- a cancellation request is represented as `unknown`; a provider-confirmed
  cancellation uses the separate `cancel` transition and is terminal;
- terminal rows cannot be overwritten or moved to another terminal state;
- every row carries the complete request/provider identity and a hash-bound receipt
  document;
- a successful row must reference an existing tenant-scoped output Artifact;
- tenant RLS and the gateway role provide visibility and write isolation.

`PostgresSpecialistOperationAuthority` implements the existing
`SpecialistOperationAuthority` protocol.  The executor remains provider-neutral: it
receives this authority by dependency injection and does not open database connections
itself.

## Alternatives considered

| Option | Benefit | Cost / risk | Decision |
|---|---|---|---|
| Keep only in-memory receipts | Minimal code | Lost on restart; duplicate side effects remain possible | Rejected |
| Store receipts in Temporal history | Same system as activity | Temporal is not the provider-operation authority; provider receipt may outlive an activity | Rejected |
| Add receipt columns to checkpoint/evidence tables | Fewer tables | Couples workflow snapshots to provider side effects and makes terminal CAS ambiguous | Rejected |
| Dedicated append-only PostgreSQL receipt history | Durable, tenant-isolated, auditable, explicit state machine | Requires migration, role grants and cross-store rehearsal | Chosen |

## Consequences

Positive:

- a new worker instance can discover the submitted/unknown operation without resubmitting it;
- terminal state transitions are serialized per tenant/operation with advisory locking;
- output Artifact authority remains the source of truth for bytes and lineage;
- cancellation remains `unknown` until the provider supplies a definitive terminal result.

Accepted limitations:

- the current evidence is a disposable PostgreSQL rehearsal and contract tests;
- provider-native cancellation APIs and real Temporal cancellation/history observation
  are not implemented by this ADR;
- HA/DR, cross-region replication, connection-pool failure and production identity
  rotation remain separate exit gates.

## Verification

- migration contract tests cover RLS, append-only triggers, controlled writes and
  terminal payload constraints;
- repository tests cover PostgreSQL-only configuration, tenant/actor validation and
  receipt tamper rejection;
- the disposable PostgreSQL rehearsal passed all six authority-boundary checks:
  submit replay idempotency, new-repository recovery, terminal success CAS, stale
  failure rejection, cancellation-to-unknown, and cross-tenant invisibility. The
  report is [agentops_specialist_operation_authority_postgres_2026-08-28.json](../reports/agentops_specialist_operation_authority_postgres_2026-08-28.json),
  with `report_sha256=5ef38ebb9b6cf838d7fd776b2ec704e6fdf187fc8a1a37254eb10442c211f466`.

The rehearsal uses migration `246` in a temporary PostgreSQL database. It proves the
receipt state machine and tenant boundary under this bounded runtime; it does not prove
HA, cross-region recovery, provider-native cancellation, or production operations.

The Temporal bridge now also exposes `reconcile_specialist_activity_history`.  It
joins a decoded Temporal timeout/cancel/failure observation to the provider receipt
and emits a hash-bound `TemporalSpecialistHistoryReconciliation`.  A Temporal timeout
therefore remains `unknown_pending` when the provider receipt is still pending; it is
not converted into a failed provider operation merely because the worker stopped
responding.
