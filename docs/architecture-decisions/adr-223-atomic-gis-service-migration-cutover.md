# ADR-223: Atomic GIS Service Migration Cutover

**Status**: Accepted  
**Date**: 2026-08-21  
**Related roadmap**: [GIS Data Agent Roadmap](../roadmap.md), AR-4.1, AR-4.2, AR-4.4  
**Depends on**: [ADR-214](adr-214-gis-service-endpoint-readiness-binding.md), [ADR-222](adr-222-gis-service-consumer-migration-impact.md)

## Context

Migration 217 connects a product migration notice to each affected exact GIS
service release. Before 218, the endpoint activation function could still move
the service pointer after checking only target deployment readiness. It did not
wait for all source-release consumers to receive the notice, acknowledge the
product transition and obtain an effective target-release grant.

Performing those checks in application code would leave a transaction gap
between the final read and the active-pointer update. A per-consumer cutover
would also be incorrect because one GIS service has one active endpoint shared
by all of its consumers.

## Decision

Migration `218` adds
`gda_control.gis_service_migration_cutover` and the controlled
`cutover_gis_service_migration(...)` function. One call locks the product
migration and service-consumer scopes, then validates the complete source
consumer set:

- the current endpoint still names the requested source definition, release
  and product version, and the target endpoint belongs to the requested ready
  target deployment;
- every effective, non-revoked and non-superseded source
  `ServiceConsumerBinding` has exactly one migration-impact fact;
- every impact points to a `done` provider notification and the latest product
  migration state is `delivered` with a consumer acknowledgement;
- every source consumer has exactly one effective, non-revoked and
  non-superseded target `ServiceConsumerBinding` for the target release.

The function fingerprints the impact, acknowledgement and target-binding sets,
calls the existing endpoint activation implementation with CAS, verifies the
resulting activation event and appends the cutover receipt in the same database
transaction. The receipt records both release lineages, set counts and hashes,
pointer versions, activation event, actor, reason, idempotency identity and
time. Replay returns the original row only for identical request content.

The public `activate_gis_service_endpoint(...)` name remains available for
initial activation and deployment changes that stay on the same product
version. Its former implementation is private after 218. Cross-product
activation with effective source consumers is rejected there and by a pointer
update trigger; the cutover function is the Gateway-executable path that can
invoke the private implementation. Grant, revocation, renewal and impact
inserts share a service advisory lock with cutover so their effective set
cannot change between validation and pointer update.

MVT cache identity already contains the release. The cutover receipt therefore
records `release_namespace_rollover`. It does not claim that Redis, CDN,
GeoWebCache or another shared cache was purged.

## Trade-offs

| Option | Decision | Reason |
|---|---|---|
| Check each consumer in Python, then activate | Rejected | leaves a race between validation and pointer CAS |
| Switch the endpoint when the first consumer is ready | Rejected | one shared pointer would strand the remaining consumers |
| Add a second active endpoint authority for migration | Rejected | creates competing service truth and rollback ambiguity |
| Gate the existing pointer with one all-consumer SQL transaction | Chosen | preserves one authority and produces deterministic cutover evidence |

The gate currently requires one unambiguous active source binding and one
active target binding per consumer subject. Duplicate active grants for the
same subject fail closed and require lifecycle reconciliation before cutover.

## Verification

`scripts/certify_gis_service_consumer_migration_impact.py` now applies migration
218 to a disposable PostgreSQL database and creates two product versions, two
GIS definitions/releases, ready endpoint fixtures, product and service consumer
authorities, the existing notification and its impact fact. The deployment
readiness rows in this script are fixtures; provider lifecycle/readiness has a
separate certification and is not re-certified here.

The 2026-08-21 run verified pending-acknowledgement rejection, missing-target-
binding rejection, direct generic-activation bypass rejection, stale CAS,
source-pointer preservation after every failed gate, real notification
claim/completion, consumer acknowledgement, atomic source-to-target cutover,
idempotent replay, identity-drift rejection, Python/SQL fingerprint parity,
forced-RLS isolation, immutable ledgers and the Gateway privilege tuple
`cutover SELECT=true`, direct `INSERT=false`, controlled function
`EXECUTE=true`, private activation `EXECUTE=false`.

The report is
`.tmp/gis-service-migration-cutover-certification/report.json`; its SHA-256 is
`f309dac26cf6764b2e9338e6ea5e3a60003c1cb298b996d645e1530b9ce66ff8`.
The catalog contains 218 migrations with fingerprint
`be09c4928697887a092141bcbcdc3980021225176b7f72c3ad1a1afaf3913d88`.
The disposable database and login role are removed after every run.

Provider build, cache warmup/shared purge, automatic target-binding renewal,
rollback orchestration, provider migration, production HA/SLO and multi-
protocol consumer migration remain in AR-4.
