# ADR-140: Durable ApprovalCase SLA and Notification Outbox

**Status**: Accepted  
**Date**: 2026-08-04  
**Related**: ADR-100, ADR-103

## Context

ADR-103 makes `ApprovalCase` the single authority for governed human decisions. The authenticated
Inbox can query and decide cases, but polling alone cannot guarantee that a request or missed expiry
reaches operators. Calling IM, email, or Alertmanager inside the approval transaction would couple
authority commits to external networks. Reusing `DataIncident` is also invalid because its current
contract requires a `PlatformRun`, while an ApprovalCase may target any ResourceURN.

## Options Considered

| Option | Benefit | Cost | Decision |
|---|---|---|---|
| Poll the Inbox only | No new persistence | No durable reminder or SLA delivery | Rejected |
| Convert expiry to rejected/cancelled | Reuses case events | Forges a human decision and breaks ADR-103 | Rejected |
| Create a synthetic DataIncident/Run | Reuses incident delivery | Manufactures an unrelated Run binding | Rejected |
| ApprovalCase transactional outbox | Durable, tenant-scoped, preserves authority | One delivery projection and worker | Chosen |

## Decision

Migration `118_approval_case_sla_notification_outbox` adds a forced-RLS delivery projection:

- the initial case event atomically enqueues `requested` for immediate delivery and `expired` with
  `available_at = expires_at`;
- a terminal case event atomically suppresses the still-pending expiry delivery and enqueues
  `decided`;
- expiry remains a derived SLA fact. It does not update `ApprovalCase.status`, create an approval
  event, or authorize the target action;
- claim uses a lease, `FOR UPDATE SKIP LOCKED`, bounded attempts, per-case ordering and tenant RLS;
- the outbox stores only logical `destination_ref`. Endpoint URLs and bearer tokens remain in worker
  configuration;
- Alertmanager delivery is at-least-once with stable ApprovalCase labels. `decided` closes the same
  alert using `endsAt`; an expired pending case remains active;
- historical terminal cases are not replayed. Historical pending cases receive only their scheduled
  expiry delivery.

The authenticated API may expose delivery status for operations, but cannot directly mutate, retry,
complete, or suppress outbox rows.

## Trade-offs

- Approval and incident notifications have separate outbox tables because their immutable source
  events and lifecycle semantics differ. They share the same transport adapter and delivery pattern.
- Alertmanager is the first adapter and is not the notification authority. IM/email routing belongs
  behind Alertmanager receivers until another provider has a concrete requirement and acceptance
  evidence.
- A permanently expired case remains pending in ApprovalCase authority and active as an SLA alert.
  A replacement case is a new immutable request; timeout never invents a verdict for the old case.

## Consequences

- Approval request, expiry and decision delivery survive process failure and external outages.
- Decisions before expiry suppress the scheduled timeout in the same database transaction.
- The platform gains auditable delivery status without introducing a second approval state machine.
- Production Alertmanager routing, receivers, HA, metrics, dead-letter recovery and real PostgreSQL
  rehearsal remain separate acceptance gates; source-level tests do not satisfy them.
