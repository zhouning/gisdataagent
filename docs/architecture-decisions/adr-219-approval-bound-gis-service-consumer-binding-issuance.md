# ADR-219: Approval-Bound GIS Service Consumer Binding Issuance

**Status**: Accepted  
**Date**: 2026-08-21  
**Related roadmap**: [GIS Data Agent Roadmap](../roadmap.md), AR-4.4  
**Depends on**: [ADR-218](adr-218-exact-release-gis-service-consumer-binding.md)

## Context

ADR-218 made the exact GIS release binding a real online MVT admission fact.
The remaining gap was issuance: a technically valid recorder call could create
that fact without an independent review. The platform already has a tenant-
scoped `ApprovalCase` authority with immutable request context and a terminal
human decision, so a second grant registry would create competing truth.

## Decision

Every new `ServiceConsumerBinding` is issued from one immutable
`ServiceConsumerBindingGrantPlan`. The plan fingerprints the complete binding
payload and creates a deterministic `ApprovalCase` with action
`gis_service_consumer_binding.grant`:

```text
requester -> immutable grant plan -> ApprovalCase pending
                                     -> independent eligible human approval
                                     -> controlled recorder -> binding
```

Migration 213 adds `approval_case_ref` and `grant_plan_sha256` to the binding
projection and replaces the Gateway recorder signature. The database recorder
requires all of the following in one transaction:

- the case belongs to the tenant and has the deterministic binding-specific ref;
- the case is approved, unexpired and uses the grant action;
- the case target service URN and target fingerprint match the call;
- the case request context contains the complete binding payload and matching
  plan fingerprint;
- the target is still a vector-tile release.

The old 212 recorder remains in the database only for historical compatibility,
but the Gateway role loses its `EXECUTE` privilege. Existing 212 rows remain
readable; no new row may be created through the old signature. Renewal,
revocation and consumer migration are separate lifecycle decisions and are not
implicitly solved by issuance.

## Trade-offs

| Option | Decision | Reason |
|---|---|---|
| Add a GIS-specific approval table | Rejected | duplicates `ApprovalCase` state and reviewer eligibility |
| Validate approval only in Python | Rejected | a direct caller could bypass the service facade |
| Bind approval case and full payload in SQL | Chosen | keeps the database as the final write boundary and makes tampering fail closed |

The accepted cost is a longer recorder signature and duplicated JSON comparison
between the typed plan and SQL. That duplication is intentional: it protects
the authority boundary if an application path is bypassed or regresses.

## Verification

The disposable PostgreSQL control-plane certificate passed with:

- unapproved grant rejected;
- pending grant rejected;
- approved grant created once and replayed idempotently;
- changed compatibility evidence rejected against the approved case;
- RLS/FORCE RLS enabled, Gateway table `INSERT` denied, old recorder execution
  denied, new recorder execution allowed.

The real Martin/PostGIS/FastAPI certificate then passed the normal route:

- no cookie: `401`;
- signed but unbound subject: `403 service_consumer_binding_required`;
- approved exact binding: `200`, 122-byte MVT;
- audit phases: `denied -> admitted -> outcome`, one provider call after admission.

## Boundaries

This ADR does not claim renewal, revocation, migration notification,
cross-protocol authorization, dynamic ABAC obligations, quota/rate counters,
production OIDC/API Gateway integration, shared cache invalidation, HA or
ServiceSLO completion.
