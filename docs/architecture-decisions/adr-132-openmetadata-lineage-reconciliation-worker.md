# ADR-132: OpenMetadata lineage projection requires provider confirmation

- Status: accepted
- Date: 2026-08-03

## Context

ADR-131 added a transactional outbox but deliberately stopped before provider
delivery. A network timeout after OpenMetadata commits is ambiguous: blindly
retrying is safe only if the provider edge is idempotent, while acknowledging
the HTTP attempt without reading provider state can lose lineage.

The OpenMetadata `1.13.1-release` source contract confirms these operations:

- `PUT /api/v1/lineage` with an `AddLineageRequest` containing one
  `edge.fromEntity` and `edge.toEntity` reference;
- `GET /api/v1/lineage/{entityType}/{entityId}` with bounded upstream and
  downstream depth;
- response edges identify endpoints as `downstreamEdges[].fromEntity` and
  `downstreamEdges[].toEntity` UUIDs.

OpenMetadata stores generic lineage by entity endpoint pair. Multiple causal
GDA `LineageEvent` records can therefore project to one provider edge.

## Decision

`data_agent.openmetadata_lineage_worker` claims tenant-scoped Metadata Fabric
outbox rows and resolves only explicit OpenMetadata bindings. OpenMetadata
binding object IDs must be canonical UUID text. Missing bindings are retryable;
the worker never derives an entity ID or FQN from a ResourceURN or dataset name.

For every change, the adapter:

1. queries the source entity at upstream depth zero and downstream depth one;
2. completes immediately if the exact source-to-target UUID edge exists;
3. otherwise sends the minimal `PUT /api/v1/lineage` request;
4. queries again and completes the outbox row only if the exact edge exists.

A PUT timeout, transport failure, conflict or other response is reconciled by
the same provider query. An HTTP success without a confirmed edge remains a
failed attempt. The gateway's existing fail procedure schedules retry and
eventually marks the row failed after its attempt limit.

The provider URL is fixed by server configuration, redirects are disabled, and
credentials are accepted only from an absolute bearer-token file. The token is
read per request to allow file-based rotation and is never stored in the
outbox, logs or binding table. The lease must exceed the configured batch's
worst-case HTTP timeout budget.

## Consequences

Projection remains at least once and eventually consistent. OpenMetadata is
the authority for the generic edge; the GDA ledger remains the authority for
causal events, versions, runs, evidence and retry history. Provider writes do
not run inside a GDA lineage transaction.

The implementation is contract-tested with `httpx.MockTransport`, including
existing edges, confirmed writes, timeout reconciliation, missing mappings,
provider failures and dead-letter transitions. It is available through the
optional Docker Compose `metadata-fabric` profile.

## Real-provider verification

The repository provides a disposable, version-pinned acceptance topology in
`deploy/openmetadata-acceptance/compose.yml`. It runs OpenMetadata 1.13.1 with a
dedicated PostgreSQL database and OpenSearch 3.4.0, plus a separate PostgreSQL
control ledger. Only loopback API, admin and control-database ports are
published; the project uses unique Compose names and destroys its containers,
volumes and token directory after each run.

`scripts/metadata-fabric-openmetadata-acceptance.sh` now verifies against the
real provider that:

- Basic login returns the JWT used by the worker while an unauthenticated
  lineage PUT is rejected with HTTP 401;
- the worker creates a lineage edge through `GET, PUT, GET` when the provider
  commits but the client loses the successful response;
- reconciliation completes the outbox exactly once with `attempt_count = 1`;
- replay issues only `GET`, and the provider contains exactly one matching
  source-to-target edge.

Successful runs retain a secret-free report at
`.tmp/metadata-fabric/openmetadata-lineage-acceptance-report.json`. The bearer
token remains in a mode-0600 temporary directory and is deleted by the shell
trap. The 2026-08-03 acceptance passed all assertions against OpenMetadata
1.13.1.

## Operational boundary

The authenticated OpenMetadata generic-lineage projection slice is therefore
classified as operational. This classification does not promote the optional
Compose profile to a production OpenMetadata foundation and does not complete
the broader Metadata Fabric. OIDC/workload identity, HA, backup/restore,
metrics, upgrade rehearsal, multi-tenant provider isolation, full governance
ingestion and Gravitino projection remain separate acceptance gates.
