# ADR-233: GIS ServiceSLO as an Exact Activation Binding

## Status

Accepted

## Context

The platform already has one generic SLO authority: immutable definition
versions, ApprovalCase-gated activation, Prometheus rule compilation, and exact
Alertmanager-to-DataIncident reconciliation. GIS Service Control Plane also
needs a service-scoped `ServiceSLO` view. A string in an SLO definition is not
enough to prove that the named service exists or that the GIS control plane has
accepted the active objective.

## Decision

Migration 223 adds `gda_control.gis_service_slo_binding`, an immutable,
tenant-scoped projection. Its recorder accepts only an existing
`gda_control.gis_service`, the exact current SLO activation (version, fingerprint,
ApprovalCase and activation CAS version), and an SLO whose
`service_resource_urn` exactly equals the GIS service URN. Direct table writes,
updates and deletes are denied; the Gateway calls the `SECURITY DEFINER`
recorder. The Gateway exposes service-scoped read and bind operations, while
the generic SLO tables remain the lifecycle authority.

For `gis_service` subjects, SLO Alertmanager reconciliation requires the exact
binding to exist and still match the current activation. A later SLO activation
does not silently rewrite history or remain valid for the old GIS binding.

## Trade-offs

The binding is an explicit administrative action rather than being folded into
the generic SLO activation transaction. This preserves the existing generic
authority and gives GIS Service Operations its own auditable decision, at the
cost of one additional step in service onboarding. Historical bindings are
retained instead of overwritten, so the table grows with every service/SLO
activation association; the current read path joins the binding to the active
pointer.

## Consequences

- GIS service SLO ownership is database-verifiable and tenant-isolated.
- Alert-driven incidents cannot be opened for an unbound or stale GIS service.
- Existing non-GIS SLOs continue to use the generic authority unchanged.
- Service APIs can inspect and explicitly establish the exact SLO contract.

## Validation

`scripts/certify_gis_service_slo_binding.py` exercises migration 223 against a
disposable PostgreSQL 16 database. It verifies exact binding and idempotent
replay, service/SLO mismatch and stale activation rejection, least-privilege
direct-write denial, owner-level immutable-trigger enforcement, forced RLS and
cross-tenant invisibility, plus old-binding invalidation and explicit rebind
after the generic activation advances.
