# ADR-150: Leased Master Metadata Projection to Bound Glossary Terms

**Status**: Accepted

**Date**: 2026-08-04

**Related**: ADR-006, ADR-131, ADR-132, ADR-148, ADR-149

## Context

ADR-149 gives every successful master activation a generic `ResourceVersion`, but it deliberately
does not call metadata providers. The existing `metadata_change_outbox` is structurally owned by
`LineageEvent`: its aggregate has a foreign key to lineage and its payload represents an edge.
Making that table polymorphic would weaken referential integrity and increase the blast radius of an
already operational lineage worker.

OpenMetadata glossary terms also have provider-owned identity, hierarchy, owner, approval status and
tags. GDA may project its master-data evidence into an explicitly bound term, but it must not infer a
term from a name/FQN or silently create a second governance identity.

## Options Considered

| Option | Benefits | Costs and risks | Decision |
|---|---|---|---|
| Extend the lineage outbox with polymorphic aggregates | One delivery table | Drops or emulates the LineageEvent foreign key; couples unrelated workers and recovery policies | Rejected |
| Call OpenMetadata during activation | Immediate provider state | Network availability and uncertain commits enter the golden-record transaction | Rejected |
| Add a typed master projection outbox and reconcile only an explicit glossary-term UUID binding | Exact database evidence, independent scaling and recoverable delivery | Separate worker and provider provisioning are required | Chosen |

## Decision

Migration 126 adds `master_metadata_projection_outbox`. An `AFTER INSERT` trigger on
`master_resource_projection` enqueues exactly one `openmetadata:default` delivery in the activation
transaction. The row binds tenant, entity, activation version, generic ResourceVersion and master
fingerprint through a composite foreign key. Existing repositories backfill only proven projection
rows. Forced RLS and gateway SELECT-only privileges apply; claim, complete and fail are available only
through tenant- and lease-bound security-definer functions.

`PlatformGateway.claim_master_metadata_projections` resolves an exact envelope containing the outbox
row, authoritative `MasterEntityVersion`, generic `ResourceVersion` and current OpenMetadata binding.
It never derives provider identity.

`openmetadata_master_data_worker` accepts only an explicit OpenMetadata binding whose object type is
`glossaryTerm`, whose object ID is a canonical UUID and whose namespace matches the glossary returned
by the provider. It performs:

1. `GET /api/v1/glossaryTerms/{id}`;
2. no write when `displayName` and `description` already match;
3. otherwise a minimal JSON Patch affecting only those two GDA-owned projection fields;
4. a second GET, acknowledging the outbox only after exact state is observed.

The projected description is provider-stable plain text. OpenMetadata 1.13.1 HTML-encodes Markdown
backticks on persistence, so markup-bearing input cannot satisfy exact read-after-write comparison.
Business key, domain, ResourceURN, master version and fingerprint remain explicit fields in the text.

PATCH timeouts and transport failures are reconciled with the same GET. Missing, stale, deleted,
wrong-type or wrong-namespace bindings remain retryable and eventually dead-letter through the
bounded attempt policy. Programming errors are not acknowledged. Provider URL and token are
server-owned; redirects are disabled and the token is read from an absolute file for rotation.

The optional Compose `metadata-fabric` profile runs lineage and master-metadata workers separately,
with independent worker, batch, lease, retry and polling configuration.

## Verification

- Contract tests cover exact envelope correlation, minimal rendering, existing-state idempotency,
  `GET -> PATCH -> GET`, timeout reconciliation, stale/wrong binding rejection, namespace checking,
  retry/dead-letter transitions and programming-error fail-closed behavior.
- Focused metadata, master authority, API, gateway and migration tests pass with 139 tests, and the static gateway
  report is `valid` with migration 126 and the worker source included.
- `scripts/certify_master_data_lifecycle.py` applies migrations through 126 to disposable PostgreSQL
  16.14. All 32 checks pass, including atomic v1/v2 enqueue, exact envelope resolution, lease-owner
  rejection, fail/reclaim/complete, exhausted replay, forced RLS, least privilege and rollback of
  activation, Resource projection and metadata outbox on Resource identity conflict.
- `scripts/metadata-fabric-openmetadata-acceptance.sh` now runs lineage and master-data acceptance in
  one version-pinned OpenMetadata 1.13.1 topology. The master slice creates a disposable glossary and
  term, binds the provider-returned UUID, observes `GET -> PATCH -> GET`, masks the committed PATCH
  response, reconciles by GET, proves replay is GET-only, confirms one exact term and
  `done/attempt_count=1`, then hard-deletes the term and glossary and confirms both return 404.
  Unauthenticated PATCH returns 401. The secret-free report is
  `.tmp/metadata-fabric/openmetadata-master-data-acceptance-report.json`.

## Consequences

- A committed active master version always has durable metadata-delivery work.
- Lineage and master projection retain independent relational types and operational queues.
- OpenMetadata remains authoritative for glossary identity, hierarchy and governance fields; GDA
  owns only its deterministic display/description projection.
- Real OpenMetadata 1.13.1 delivery is proven only for an already bound glossary term's
  `displayName` and `description`. The acceptance harness provisions disposable provider entities;
  the production worker does not create terms or bindings.
- This increment does not automate glossary provisioning, move term hierarchy, project owner/tag/
  status, deliver to Gravitino, complete EA round-trip, or prove staging/production deployment,
  identity, backup/restore or multi-tenant operations.

## Revisit Trigger

Revisit when a steward-approved create-and-bind protocol is implemented as a product capability,
when projection volume requires shared queue infrastructure with equally strong typed foreign keys,
or when provider custom properties can carry a version-bound ResourceURN/fingerprint without
weakening provider governance authority.
