# ADR-225: Run-Bound GIS Endpoint Warmup Evidence

**Status**: Accepted  
**Date**: 2026-08-21  
**Related roadmap**: [GIS Data Agent Roadmap](../roadmap.md), AR-4.2, AR-4.4  
**Depends on**: [ADR-214](adr-214-gis-service-endpoint-readiness-binding.md), [ADR-223](adr-223-atomic-gis-service-migration-cutover.md), [ADR-224](adr-224-authority-bound-gis-service-migration-rollback.md)

## Context

Migrations 218 and 219 move the one authoritative GIS service endpoint pointer
only after validating release lineage, deployment readiness, consumer impact
and rollback authority. A `ready` deployment does not prove that the exact
endpoint, release and cache namespace were exercised recently. A migration
could therefore switch to a cold or stale destination while still satisfying
the database gates.

A boolean on `EndpointRevision` would not identify who performed the warmup,
which samples ran, which cache policy bounded its lifetime or whether a real
platform Run succeeded. Letting a provider update the active pointer would
also transfer control-plane authority to a replaceable runtime.

## Decision

Migration `220` adds the append-only
`gda_control.gis_service_endpoint_warmup` receipt and the controlled
`record_gis_service_endpoint_warmup(...)` function. One receipt binds:

- one successful `PlatformRun` whose capability is
  `gis-service-endpoint-warmup` and purpose is
  `gis_service.endpoint_warmup`;
- that Run's exact product-output input binding and evidence-gated
  `succeeded` event;
- an evidence Artifact containing the provider receipt hash and complete
  warmup manifest;
- one immutable endpoint, ready deployment, service definition, release,
  cache-policy version and cache namespace;
- the requested/successful sample counts, sample-set hash, provider-receipt
  hash and bounded evidence window.

Every requested sample must succeed. The receipt must still be live when it is
recorded, and its validity cannot exceed the exact release cache policy's
`cache_max_age_seconds`. Its Python and SQL fingerprints cover every immutable
field except the fingerprint itself.

A pointer trigger requires a current receipt for the destination endpoint when
the existing 218 cutover or 219 rollback transaction marker is present. It does
not change first activation or same-product endpoint revision activation. The
existing endpoint CAS, activation event, cutover receipt and rollback receipt
remain the only pointer history; 220 does not add another endpoint state
machine or provider queue.

## Trade-offs

| Option | Decision | Reason |
|---|---|---|
| Store `warmed=true` on the endpoint | Rejected | mutable and cannot prove release, cache, Run, samples or freshness |
| Let each provider own warmup state and pointer activation | Rejected | makes replaceable runtime state authoritative and weakens atomic cutover |
| Add a dedicated warmup queue and lifecycle | Rejected for now | duplicates existing PlatformRun and provider orchestration contracts |
| Reuse evidence-gated PlatformRun and append one release-bound receipt | Chosen | preserves current ownership and adds only the missing migration fact |

The receipt proves that accepted evidence was recorded. It cannot by itself
prove that a provider receipt is truthful. Production adapters and their
network/runtime isolation still require independent conformance certification.

## Verification

`scripts/certify_gis_service_consumer_migration_impact.py` applies migrations
through 220 in a disposable PostgreSQL database. It constructs two product and
GIS service releases and, for each warmup, runs the existing
`accepted -> dispatching -> running -> succeeded` state path with a
DolphinScheduler success observation, content-bound output Artifact,
independent passed QualityResult, lineage and RunSuccessEvidence.

The certification proves that target cutover and source rollback both fail
without a live destination receipt and preserve the previous pointer. After
recording the exact receipt, source-to-target cutover, approved rollback in a
reverted transaction and Incident-authorized committed rollback succeed. It
also verifies replay, identity-drift rejection, Python/SQL fingerprint parity,
forced-RLS isolation, append-only mutation rejection, direct-insert denial and
the Gateway privilege tuple `SELECT=true`, `INSERT=false`, recorder and
fingerprint `EXECUTE=true`.

The report is
`.tmp/gis-service-endpoint-warmup-certification/report.json`; its SHA-256 is
`2286eecc8a9c06d375050163ca07ba68c4cd8aece2a9559e8176e2b20f6b1fbf`.
The disposable catalog contains 220 migrations with fingerprint
`3f65e65fc1bee30d7eed2822f4f95c4e2b9516164b0565b03df58553c3637292`.
The database and login role are removed after the run.

The development database was read-only audited at 219 applied with 220 as the
only pending migration and no checksum, metadata, probe, duplicate-ID or
unknown-migration drift. The strict runner then applied 220 and a second audit
returned `220/220 in_sync`; catalog and database fingerprints are both
`3f65e65fc1bee30d7eed2822f4f95c4e2b9516164b0565b03df58553c3637292`.

The provider receipts used by this certification are deterministic fixtures;
the test certifies the control-plane contract and transaction gates, not a
real Martin, GeoServer, ArcGIS, CDN or cloud-provider warmup.

## Consequences

Cross-product cutover and its exact rollback destination can no longer move the
active pointer based only on older deployment readiness. Warmup evidence is
queryable through the Platform Gateway, tenant-isolated, immutable and bounded
by the release cache policy.

The managed Martin warmup worker and provider adapter are now implemented on
top of this receipt contract and certified separately by ADR-227. Shared
Redis/CDN/GeoWebCache purge or warmup, provider rebuild and health refresh for
other providers, automatic Incident routing, ServiceSLO, multi-provider
compensation and production HA/RTO remain open. AR-4 therefore stays
`in_progress`.
