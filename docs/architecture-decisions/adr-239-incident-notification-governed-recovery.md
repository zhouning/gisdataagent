# ADR-239: Governed Recovery for DataIncident Notification Dead Letters

**Status**: Accepted  
**Date**: 2026-08-22  
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-4

## Context

ADR-236/237 make an external provider receipt part of notification terminal authority, and
ADR-238 adds worker observability and an HA deployment contract. A notification that exhausts
its attempts still remains `failed`, however. Operators previously had no authorized way to
replay it after repairing Alertmanager or its receiver. Directly changing the outbox row would
discard the failure evidence and bypass its mutation guard.

## Decision

Migration 228 adds one recovery operation to the existing notification outbox:

- only a `failed` notification whose attempt count reached `max_attempts` may be recovered;
- the caller must be `human:*`; the REST boundary additionally requires the `admin` role;
- the caller supplies the expected attempt count and exact failed `receipt_sha256`; both are
  checked while the notification row is locked;
- a 1-512 character reason is mandatory and each notification may be recovered at most 10 times;
- the transaction first appends `data_incident_notification_recovery_event`, retaining the prior
  failure error, attempt limit, terminal worker, completion time and receipt hash;
- the same transaction returns the existing notification to `pending`, resets its attempt count,
  clears terminal evidence and exposes the latest recovery projection;
- recovery events use tenant RLS/FORCE RLS and UPDATE/DELETE rejection. A separate INSERT guard
  also prevents the table owner from forging events outside the recovery function;
- `gda_control_gateway` receives only recovery-event SELECT and recovery-function EXECUTE. It has
  no outbox UPDATE or recovery-event INSERT privilege.

The HTTP boundary adds notification listing, recovery-history listing and recovery submission
under `/api/platform/v1/incidents/{incident_id}/notifications`.

## Alternatives considered

- A second dead-letter queue was rejected because the existing outbox already owns delivery state
  and a second queue would create reconciliation and ordering problems.
- Automatically changing `failed` back to `pending` was rejected because repair readiness and
  replay intent require an accountable operator decision.
- Reusing the existing failed receipt hash as a new acceptance receipt was rejected because a
  failure fingerprint is comparison evidence, not external delivery acceptance.

## Evidence

- Focused contract/Gateway/REST/static tests: `99 passed` together with the existing Platform
  Gateway suite.
- `scripts/certify_incident_notification_recovery.py` passed on disposable PostgreSQL `16.15`.
  Its 17 checks cover ten recovery cycles, contiguous audit sequence, pending/done rejection,
  stale attempt and receipt-hash CAS, non-human rejection, recovery limit, tenant isolation,
  direct event/outbox mutation denial, owner INSERT/UPDATE/DELETE guards and Gateway privileges.
- The development database is `228/228 in_sync`; catalog and database fingerprint are both
  `4864556af67959c2a1d32b9c1541dc55ce77cc898f64d43a587f18e932e1fb1c`.

## Consequences and limits

Operators now have an auditable and race-safe way to replay a repaired notification without
changing DataIncident lifecycle state or losing the original failure evidence. Delivery remains
at least once. This authority is not automatic remediation, exactly-once delivery, production
Alertmanager/on-call validation, production rollout evidence, or a DR/RPO/RTO claim. AR-4 remains
`in_progress`.
