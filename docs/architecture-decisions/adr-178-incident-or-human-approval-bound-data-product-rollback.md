# ADR-178: Incident or Human Approval Bound DataProduct Rollback

**Status**: Accepted

**Date**: 2026-08-07

**Related**: ADR-103, ADR-122, ADR-147, ADR-177

## Context

DataProduct rollback already enforces an immutable predecessor chain and a
product-level transaction lock, but the rollback event itself did not identify
why an operator was allowed to move the active pointer. A reason string and an
actor identity are insufficient evidence for an emergency remediation or a
planned human change.

## Decision

- Migration 151 adds immutable rollback authority fields to
  `gda_control.data_product_event`: `incident` or `approval_case`, the authority
  reference, and its SHA-256 evidence.
- A rollback must provide exactly one authority. An active resource-bound
  `DataIncident` (`open` or `acknowledged`) may authorize emergency rollback;
  otherwise an unexpired, independently approved human `ApprovalCase` with
  action `data_product.rollback` must bind the exact product, current version,
  target ancestor and operation fingerprint.
- The registry validates authority while holding the existing product advisory
  lock, writes the authority evidence into the append-only event, and flips the
  pointer in the same transaction. Exact idempotent replay must use the same
  authority reference.
- The database trigger requires the governed recorder session marker and
  rechecks tenant, Incident subject/status/fingerprint or ApprovalCase action,
  status and request context. Direct SQL rollback inserts fail closed.

## Verification

- Contract tests cover deterministic operation fingerprints, API authority
  forwarding and migration guard markers.
- `scripts/certify_data_product_rollback_authority.py` applies migrations
  through 151 to disposable PostgreSQL, opens a resource-bound critical
  Incident, performs an Incident rollback, performs a second rollback with a
  human-approved exact ApprovalCase, and proves a direct SQL event insert is
  rejected.
- PostgreSQL 16 certification passed. The report is
  `.tmp/data-product-rollback-certification/report.json`; its SHA-256 is
  `5cc2d817ca3ef93e16ac5e5f5cadc54a2631851a1d49bc4a9bf2c005fdfb81ae`.

## Consequences

Rollback is now auditable as a governed operation and cannot be triggered by a
free-form actor/reason pair. Production incident routing, approval notification
delivery and service-level rollback remain separate follow-up work; this slice
does not make the GIS Service Control Plane production-ready.
