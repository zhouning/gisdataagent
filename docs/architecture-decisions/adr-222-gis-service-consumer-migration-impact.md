# ADR-222: GIS Service Consumer Migration Impact Authority

**Status**: Accepted  
**Date**: 2026-08-21  
**Related roadmap**: [GIS Data Agent Roadmap](../roadmap.md), AR-4.1, AR-4.4  
**Depends on**: [ADR-179](adr-179-consumer-binding-migration-notification-outbox.md), [ADR-221](adr-221-approval-bound-gis-service-consumer-binding-renewal.md)

## Context

The product migration authority already records an exact `ConsumerBinding`
transition and delivers its notice through a durable Alertmanager outbox. A
GIS service consumer, however, is admitted to an exact service definition and
release. A product migration can therefore affect a service release without
being visible in the product-only notification payload.

Creating a second GIS notification queue would duplicate leases, retry,
receipt and dead-letter semantics. Keeping the association in application
memory would lose the source release and consumer evidence needed for an
operator to act on the notice.

## Decision

Migration `217` adds the append-only
`gda_control.gis_service_consumer_binding_migration_impact` authority. Each
row records:

- the exact source `ServiceConsumerBinding` and its checksum;
- source and target `GISServiceDefinitionVersion` and `ServiceReleaseBinding`;
- the product transition, migration state and existing notification IDs;
- the service URN, consumer subject, recorder and immutable impact checksum.

The recorder verifies the complete lineage before insertion: the source
binding matches the source release, source and target definitions point to the
same product URN and from/to versions, the product migration state belongs to
the existing notification, and the product and GIS consumer subjects agree.
RLS, immutable triggers and recorder-only Gateway privileges apply to the new
fact. Replays are idempotent only when the complete payload is identical.

The existing `ConsumerBindingMigrationNotificationEnvelope` now carries zero
or more impact facts. The existing notification worker emits exact GIS service
URN, source/target release, source binding ID/checksum and impact checksum as
Alertmanager labels/annotations. Provider delivery, retry and terminal
receipt remain owned by the product notification outbox.

## Trade-offs

| Option | Decision | Reason |
|---|---|---|
| Add a GIS-specific provider outbox | Rejected | duplicates delivery authority and creates receipt divergence |
| Store only service URN in notification JSON | Rejected | loses exact release lineage and cannot support deterministic remediation |
| Keep impact association in Gateway memory | Rejected | not durable, tenant-scoped or auditable |
| Append a release-bound impact fact and enrich the existing envelope | Chosen | preserves exact GIS evidence while reusing one delivery lifecycle |

This slice deliberately does not perform service cutover, automatic renewal,
cache invalidation, generic ABAC or provider migration orchestration.

## Verification

The Python contract, Gateway path and SQL migration are covered by focused
regression tests. `scripts/certify_gis_service_consumer_migration_impact.py`
also builds a disposable PostgreSQL source-to-target chain containing two
`DataProductVersion` records, two GIS definitions/releases, the product and
service consumer bindings, migration state and the existing notification.

The certification verifies Python/SQL fingerprint parity, first-write and
idempotent replay, forged target-release rejection, identity-drift rejection,
forced-RLS cross-tenant isolation, immutable-row enforcement and the Gateway
privilege tuple `SELECT=true`, direct `INSERT=false`, recorder `EXECUTE=true`.
The 2026-08-21 report is
`.tmp/gis-service-consumer-migration-impact-certification/report.json`; its
SHA-256 is
`5fae0c7ef1aff521599274f48ff8a605d7825ccbfc2bd74d318ae7a3f6a237ec`.
The disposable database and login role are removed after the run.

This certifies the migration-impact authority itself. Production service
cutover, provider migration, automatic renewal and cache invalidation remain
separate delivery work.
