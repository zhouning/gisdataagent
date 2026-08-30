# ADR-147: Approved SLO Alert to Resource-Bound DataIncident

**Status**: Accepted

**Date**: 2026-08-04

**Related**: ADR-093, ADR-099, ADR-100, ADR-140, ADR-146

## Context

ADR-146 establishes an approved, versioned SLO authority and compiles only the exact active version
into Prometheus rules. A firing rule still does not create an operational incident. The existing
`DataIncident` contract was bound only to `PlatformRun`, so attaching a service reliability breach
to a fabricated Run would corrupt lineage and leave service SLO incidents outside the unified event,
notification and transition lifecycle.

Alertmanager webhooks may be retried, delivered after an active SLO changes, or contain a later alert
episode with the same Alertmanager fingerprint. The platform must reject forged or stale firing
signals, accept an authentic resolution for a previously approved version, and remain idempotent
without making Alertmanager the incident state authority.

## Alternatives Considered

- Create a separate SLO incident table. This preserves the Run-only schema but duplicates incident
  state, events, notifications and operator workflows.
- Create a synthetic PlatformRun for each service alert. This reuses the existing table but invents
  execution lineage and weakens the meaning of Run.
- Generalize DataIncident to exactly one governed subject. This changes a shared contract, but keeps
  one incident lifecycle and gives non-Run resources a canonical identity.

## Decision

- Migration 123 generalizes `DataIncident` so exactly one of `run_id` or `subject_resource_urn` is
  present. The ResourceURN must be canonical and match the tenant. Observation-derived incidents
  remain Run-bound, and existing Run incident fingerprint material is unchanged.
- Subject binding is immutable. Resource incidents reuse the existing status CAS, ordered
  `DataIncidentEvent` chain and transactional incident notification outbox.
- `POST /api/platform/v1/slo-alerts/alertmanager` accepts strict Alertmanager webhook v4 payloads
  only from an authenticated `WORKLOAD` principal whose actor exactly matches
  `GDA_SLO_ALERT_DETECTOR_SUBJECT`. Tenant always comes from the authenticated context.
- Reconciliation accepts only `GDASLOErrorBudgetBurn` and rejects truncated deliveries. SLO ID,
  version, database fingerprint, service, owner, on-call, burn window, severity and ApprovalCase
  reference must all match immutable authority data.
- A firing alert must match the exact current active pointer. A resolved alert may instead use its
  immutable activation event, allowing an old approved episode to close after a newer version is
  activated without authorizing a new incident from stale rules.
- Episode identity includes tenant, SLO version and fingerprint, Alertmanager fingerprint and
  timezone-normalized `startsAt`. Delivery replay reuses the same incident; a later episode creates a
  new incident even if Alertmanager reuses its fingerprint.
- Firing opens a resource-bound `slo_error_budget_burn` incident. Resolved performs an incident CAS
  transition; resolution replay is idempotent, while resolution without a prior incident does not
  manufacture one.
- Alertmanager is evidence transport, not the incident state store. A silence suppresses alert
  notification and does not acknowledge or resolve a DataIncident.

## Verification

- Contract and API tests cover strict webhook parsing, authority/fingerprint/active-pointer drift,
  replay, new episodes, resolution, resolution without firing and the workload identity boundary.
- Platform tests cover exactly-one incident subjects, tenant matching, immutable resource binding,
  existing Run incident compatibility, event ordering and notification outbox reuse.
- `scripts/certify_slo_incident_lifecycle.py` applies migrations through 123 to disposable PostgreSQL
  16, activates an approved test SLO through the real authority path, and verifies 11 firing,
  resolution, idempotency, RLS, constraint, immutability, evidence and cleanup checks.

## Trade-offs

- The shared incident schema is broader and every incident reader must tolerate one nullable subject
  column. The exactly-one database constraint and frozen Pydantic contract keep ambiguity out.
- Resolved delivery relies on immutable activation events after pointer movement. Retaining those
  events is therefore part of incident correctness, not optional audit cleanup.
- The initial integration is a synchronous webhook. A production ingress still needs enterprise TLS,
  workload authentication, replay/rate controls and availability validation at the gateway edge.

## Consequences

- Service SLO breaches now participate in the same auditable incident/event/notification lifecycle as
  Run incidents without inventing execution history.
- The same subject mechanism can support future governed resource incidents, but each new detector
  still needs a typed contract and authority validation; arbitrary generic incident creation remains
  out of scope.
- Local PostgreSQL certification proves the control-plane lifecycle, not staging or production
  Alertmanager routing, enterprise identity, TLS, paging escalation or multi-cluster delivery.
- Revisit asynchronous ingestion when measured webhook availability, burst volume or gateway retry
  behavior cannot meet an approved inbound reconciliation SLO.
