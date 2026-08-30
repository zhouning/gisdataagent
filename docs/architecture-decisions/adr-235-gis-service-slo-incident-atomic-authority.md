# ADR-235: GIS ServiceSLO Alert Uses Atomic Incident Authority

## Status

Accepted and implemented as a bounded AR-4 slice.

## Context

The generic SLO authority owns definition versions, ApprovalCase-gated activation,
and activation versioning. Migration 223 records which exact activation a GIS
service consumes, while the shared `data_incident`, `data_incident_event`, and
incident notification outbox tables own incident lifecycle and delivery evidence.

Before migration 225, a GIS SLO alert could validate the exact ServiceSLO binding
and create a DataIncident in separate transactions. An activation change between
those operations could leave an incident tied to an authority that was no longer
the active GIS projection.

## Decision

Migration `225_gis_service_slo_incident_authority.sql` adds one
`SECURITY DEFINER` assertion function:

`gda_control.assert_gis_service_slo_incident_authority(tenant, service, slo,
active_version, fingerprint, approval_case, activation_version)`.

The function validates tenant and GIS service identity, exact generic SLO
activation, SLO version fingerprint, ApprovalCase, and exact immutable GIS
ServiceSLO binding. It locks the active SLO row, exact SLO version, and exact GIS
binding with `FOR SHARE` until the caller transaction commits.

`PlatformGateway.open_gis_service_slo_incident` calls that assertion and inserts
the existing resource-bound `DataIncident` in the same PostgreSQL transaction.
The gateway role can execute the authority function and insert into the shared
incident table, but cannot write the GIS ServiceSLO binding table directly.

## Options Considered

| Option | Decision | Reason |
| --- | --- | --- |
| Validate binding, then open incident in a second transaction | Rejected | Activation can change between the two commits. |
| Add a separate GIS SLO incident table and notification queue | Rejected | Duplicates the existing incident lifecycle and splits operational queries. |
| Let Alertmanager become the incident state authority | Rejected | Alertmanager is evidence transport; the platform needs tenant-scoped, auditable lifecycle and outbox semantics. |
| Assert and lock exact authorities, then reuse DataIncident transaction | Chosen | Closes the race without creating a second incident system. |

## Consequences

- A firing or resolved GIS ServiceSLO alert must carry exact activation evidence
  and an immutable 223 binding.
- A stale fingerprint, ApprovalCase, activation version, or missing binding is
  rejected before a new incident is committed.
- Incident events and notification outbox rows continue to be produced by the
  existing shared incident authority.
- `FOR SHARE` intentionally serializes activation changes with an incident
  admission transaction; this is a short control-plane lock, not a long-running
  provider operation.
- This decision does not implement automatic remediation, provider-neutral
  incident routing, worker HA/RTO, multi-provider conformance, or production DR.

## Evidence

- Migration runner replayed all 225 migrations on PostgreSQL 16.14 with the
  catalog and database fingerprints equal to
  `28be3c5eaa7c34a2dca02debcf0b8b00d343545a67383b12133d8f0da6c3a842`.
- `scripts/certify_gis_service_slo_incident_authority.py` verified exact GIS
  service/SLO/ApprovalCase setup, incident creation, replay idempotency, shared
  event/outbox rows, stale and missing authority rejection, cross-tenant denial,
  activation lock blocking, and gateway least privilege on PostgreSQL 16.

## Revisit Trigger

Revisit this boundary when incident routing needs provider-specific delivery
contracts, when automatic remediation is admitted, or when a production HA/RTO
design requires a different locking and worker ownership model.
