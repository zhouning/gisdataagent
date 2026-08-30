# ADR-141: Governed Approval Notification Dead-Letter Recovery

**Status**: Accepted  
**Date**: 2026-08-04  
**Related**: ADR-103, ADR-140

## Context

ADR-140 deliberately stops automatic delivery after a bounded number of attempts. Leaving a failed
notification in that state preserves evidence but gives operators no governed way to resume delivery
after repairing an Alertmanager route or receiver. Direct table updates would bypass tenant policy,
erase operational history and allow a browser or worker to replay stale expiry alerts.

Recovery is an operational action over delivery state. It must not change `ApprovalCase.status`, add
an ApprovalCase event, manufacture a verdict, or authorize the target resource action.

## Options Considered

| Option | Benefit | Cost | Decision |
|---|---|---|---|
| Unlimited automatic retries | No operator workflow | Permanent outage creates unbounded load | Rejected |
| Direct administrator SQL update | Small implementation | Bypasses API policy, CAS and immutable audit | Rejected |
| Retry every terminal delivery state | Flexible | Replays completed, suppressed or stale lifecycle facts | Rejected |
| Governed recovery function and audit event | Bounded, tenant-scoped and observable | Adds one function, event table and UI action | Chosen |

## Decision

Migration `119_approval_notification_governed_recovery` adds a recovery projection and immutable
`approval_case_notification_recovery_event` audit table.

- Only a notification in `failed` state can be recovered.
- The caller must be an authenticated human administrator in the notification tenant.
- The API supplies `expected_attempt_count`; a stale operator view fails with a conflict.
- Recovery requires a reason, records the previous attempt count and error, releases no active lease,
  resets the automatic attempt budget, and makes the same notification immediately claimable.
- Each notification has at most ten manual recoveries. The immutable event sequence preserves every
  recovery even though the outbox row is a mutable delivery projection.
- An `expired` notification cannot be replayed after its ApprovalCase becomes terminal.
- Direct gateway-role updates and event inserts remain denied; only the security-definer function may
  perform the atomic audit-and-reset operation.
- The Approval Inbox exposes recovery evidence to platform operators but exposes the retry command
  only to administrators. The browser cannot select a destination or mutate another delivery state.
- The worker exports low-cardinality Prometheus counters for claimed, delivered, retrying,
  dead-lettered and cycle-error outcomes plus cycle duration. Metrics are evidence, not authority.

## Trade-offs

- Resetting the automatic attempt count gives a repaired route a fresh bounded delivery window, while
  the separate recovery count prevents an infinite human retry loop.
- Recovery is per notification instead of bulk. This keeps the reason and stale-state check precise;
  a future bulk workflow must still evaluate and audit each notification independently.
- The case detail view is sufficient for this slice. A cross-case dead-letter queue, assignment,
  escalation and incident correlation remain separate operational capabilities.

## Consequences

- Operators can repair and resume a dead letter without database access or loss of evidence.
- Approval authority and delivery authority remain separate and independently auditable.
- Prometheus can alert on delivery outcomes once the worker endpoint is scraped.
- `scripts/certify_approval_notification_recovery.py` applies the relevant authority and notification
  migrations to disposable PostgreSQL 16. Its ten checks verify ten contiguous recoveries, the recovery
  limit, attempt CAS, stale-expiry rejection, forced-RLS tenant isolation, immutable audit and gateway
  least privilege. Real Alertmanager redelivery and Prometheus scrape remain acceptance gates.
