# ADR-146: Versioned SLO Definition and Approval Authority

**Status**: Accepted

**Date**: 2026-08-04

**Related**: ADR-093, ADR-103, ADR-140, ADR-145

## Context

The platform can now observe ApprovalCase notification delivery and provision an operating dashboard.
Those SLI facts do not authorize a production objective. ADR-093 explicitly separates observations
from approved RPO, RTO and SLO commitments, while the roadmap requires every active data product,
service and agent deployment to bind an owner, on-call policy, SLO and incident path.

Hard-coding a plausible objective into PrometheusRule would bypass the service owner. Keeping an SLO
only in YAML would also permit an unreviewed edit to change paging behavior without a tenant-scoped,
immutable approval record.

## Decision

- Migration 122 creates a generic `SLODefinitionVersion` authority. A version binds one service
  ResourceURN, typed SLI configuration, objective in basis points, objective window, owner, on-call
  reference and one to four traffic-guarded burn-rate windows.
- Definition versions and events are immutable and tenant scoped with forced RLS. PostgreSQL computes
  the SHA-256 fingerprint over its normalized JSONB document; clients cannot nominate their own
  fingerprint.
- Staging a semantically equivalent version is idempotent even when an HTTP retry receives a later
  server timestamp. The first `created_at` and its fingerprint remain authoritative; changing any
  definition content, creator or reason fails with a conflict and cannot append a misleading event.
- Activation is a separate CAS-protected pointer. It requires an unexpired, approved ApprovalCase
  whose tenant, action `slo_definition.activate`, target version ResourceURN and target fingerprint
  exactly match the immutable definition. Pending, rejected, wrong-action and wrong-fingerprint
  cases fail closed.
- Activation may be performed by a typed controller after the independent human verdict. The event
  records both the ApprovalCase reference and human decision evidence. An exact replay is idempotent,
  while changing the active version requires the current activation version and another exact
  ApprovalCase.
- The gateway role receives SELECT on the three authority tables and EXECUTE on the stage/activate
  functions. It receives no direct INSERT, UPDATE or event-write privileges.
- The initial compiler supports `event_success_ratio`. It validates metric names, labels and disjoint
  outcomes, then produces multi-window error-ratio, traffic-count and burn-rate rules. Compilation
  requires the exact active version and fingerprint; a valid candidate alone is insufficient.
- The authenticated platform API derives tenant, typed actor, timestamps, version ResourceURN and
  fingerprint bindings at the server boundary. It exposes bounded version listing, exact activation
  approval creation, admin-only CAS activation, active state, active-only rule preview and immutable
  events. Clients cannot nominate authority-owned identity or fingerprint fields.

## Verification

- Contract tests cover tenant/version identity, immutable models, typed ownership, safe PromQL input,
  ordered windows, candidate refusal, activation mismatch and traffic-guarded rule generation.
- Gateway contract tests cover identity injection, bounded tenant version queries, exact ApprovalCase
  construction, admin-only activation, fail-closed candidate preview, active rule compilation, stable
  error mapping and registration of all seven lifecycle operations in OpenAPI.
- `scripts/certify_slo_definition_authority.py` applies migrations through 122 to disposable
  PostgreSQL 16, uses the real ApprovalCase principal and verdict path, and evaluates 21 authority,
  isolation, immutability, CAS, idempotency and least-privilege checks.
- The certification compiles one explicitly approved disposable 99% test objective into ten rules
  and validates them with Prometheus 3.5.0 `promtool`. That number is test data only and is not stored
  as a repository production objective.
- The first live certification found and fixed PostgreSQL's null `RETURNING INTO` behavior on
  `ON CONFLICT DO NOTHING`; explicit `COALESCE` now prevents duplicate staged events.
- Certification now replays the same version with a different server timestamp and proves that the
  original fingerprint and single staged event are preserved.

## Consequences

- Observations, candidates and active objectives are distinct machine-readable states. Dashboards may
  display SLI without implying an SLO exists.
- Prometheus deployment automation must resolve active authority state before publishing generated
  rules. Committed static candidates must not bypass this gate.
- This slice establishes the authority and compiler, not a production ApprovalCase notification SLO.
  No customer/staging/production objective was approved or deployed.
- SLO-to-Incident creation is completed by ADR-147. UI lifecycle management, retirement, External
  Secrets/on-call synchronization, rule rollout/rollback and multi-cluster reconciliation remain
  follow-up work.
