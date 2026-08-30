# ADR-224: Authority-Bound GIS Service Migration Rollback

**Status**: Accepted  
**Date**: 2026-08-21  
**Related roadmap**: [GIS Data Agent Roadmap](../roadmap.md), AR-4.2, AR-4.4  
**Depends on**: [ADR-178](adr-178-incident-or-human-approval-bound-data-product-rollback.md), [ADR-223](adr-223-atomic-gis-service-migration-cutover.md)

## Context

Migration 218 can move a GIS service from one product-backed release to the
next only after every source consumer has acknowledged the migration and holds
an exact target-release grant. Once that pointer moves, the generic endpoint
activation path cannot safely move it back: it has no incident or human-change
authority, does not bind the requested direction to the completed cutover, and
does not prove that current consumers can read the old release.

A rollback also cannot overwrite the cutover receipt or create a second active
endpoint state. Either would make it unclear which pointer is authoritative and
would break the existing CAS and activation-event history.

## Decision

Migration `219` adds the append-only
`gda_control.gis_service_migration_rollback` receipt and the controlled
`rollback_gis_service_migration(...)` function. A request names an immutable
218 cutover ID and SHA, its exact target-to-source endpoint direction, the
current endpoint state version and one rollback authority.

The function uses the same product/service advisory-lock order as cutover and
the existing endpoint row lock. In one transaction it verifies:

- the current pointer and state version still equal the completed cutover's
  target endpoint and post-cutover version;
- the rollback endpoint is exactly that cutover's source endpoint, its
  definition/release/product lineage still matches the receipt, and its
  deployment remains `ready`;
- every effective current-target consumer has exactly one effective binding to
  the source exact release; duplicate or missing bindings fail closed;
- the authority is either an `open`/`acknowledged` `DataIncident` whose subject
  is this GIS ServiceURN, or an unexpired approved ApprovalCase with action
  `gis_service_migration.rollback` whose fingerprint and context bind the
  cutover SHA, endpoint direction and current state version.

It then calls the private endpoint CAS implementation, verifies the resulting
activation event and appends the rollback receipt in the same transaction. The
receipt stores the cutover evidence, both release lineages, complete consumer
counts and source-binding set hash, captured authority state/hash, pointer
versions, activation event, actor, reason and idempotency identity. Exact replay
returns the stored row; identity drift is rejected. The original cutover row is
never changed.

The pointer trigger now accepts a transaction-local rollback marker in addition
to the cutover marker. Neither marker can be set through the Gateway's generic
activation API, and the private endpoint implementation remains non-executable
by the Gateway role.

## Trade-offs

| Option | Decision | Reason |
|---|---|---|
| Treat product rollback as GIS service rollback | Rejected | product and service pointers have different consumers, releases and recovery timing |
| Let an operator call generic endpoint activation with a reason | Rejected | reason text is not authority and leaves consumer compatibility unproved |
| Add a second rollback pointer/state machine | Rejected | creates competing active-service truth and split-brain recovery semantics |
| Reuse the active pointer and bind rollback to cutover + authority + consumer set | Chosen | preserves one CAS authority and produces one auditable recovery fact |

The gate evaluates consumers currently effective on the failed target release.
It allows an empty current set, but any current consumer must have one and only
one effective source-release grant. Binding changes share the service advisory
lock installed by migration 218, so the derived set cannot change across the
pointer update.

## Verification

The disposable PostgreSQL certification applies migrations through 219 and
performs a real source-to-target cutover. It then adds a target-only consumer
and proves rollback fails without changing the target pointer, adds the missing
source grant, and proves missing authority, a product-bound Incident, generic
activation and stale CAS all fail.

An exact approved ApprovalCase executes a target-to-source rollback inside a
transaction that is deliberately reverted. A service-bound active Incident
then executes the committed rollback. The certification verifies a single
state-version advance, both-consumer set equality, idempotent replay,
identity-drift rejection, Python/SQL operation and receipt fingerprint parity,
forced-RLS isolation, immutable receipt, direct-insert denial and the Gateway
privilege tuple `SELECT=true`, `INSERT=false`, controlled `EXECUTE=true`,
private activation `EXECUTE=false`.

The report is
`.tmp/gis-service-migration-rollback-certification/report.json`; its SHA-256 is
`d002e9bb43f9a8eae9bbf2b73e23fd58af2582cd730eba166e0346b4ca9fa4cc`.
The catalog and development database contain 219 migrations with fingerprint
`b489a82988bed543e42e5628f017114726612545fff1567bde58e8b5985834b3`.
Provider
rebuild, cache warmup or shared purge, automated incident routing, ServiceSLO,
multi-provider compensation and production HA/RTO are not certified here.

## Consequences

GIS service migration now has a database-authoritative recovery path for the
active endpoint and exact-release consumer access. A provider failure can be
linked to an immutable Incident or independently approved change without
rewriting cutover history.

This does not rebuild an unavailable source provider or prove it healthy beyond
its existing `ready` deployment evidence. A production controller must still
coordinate provider observation, cache work, incident policy and recovery
timing before AR-4 can exit `in_progress`.
