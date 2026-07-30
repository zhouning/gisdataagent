# ADR-066: Runtime-bound durable Active Metadata promotion

**Status**: Accepted

**Date**: 2026-07-30

**Decision owners**: Data Platform, Metadata Platform, Data Governance, Security, Platform Architecture

**Related decisions**: [ADR-049](adr-049-tenant-scoped-metadata-fabric-binding-ledger.md) · [ADR-054](adr-054-local-gravitino-jdbc-catalog-restart-continuity.md) · [ADR-065](adr-065-local-active-metadata-binding-reconciliation.md)

## Context

M3-19 persisted the exact real Chongqing provider binding, but its Gravitino table used a `memory` catalog. That binding correctly identifies the logical provider object but does not contain provider runtime, service, StatefulSet, cluster or storage identity. Reusing the same natural target in another runtime would therefore not prove that the retained object came from a restart-continuous provider.

Changing the shared binding schema would invalidate the checked M3-19 contract and its source-bound evidence. Overwriting the M3-19 ledger row would also confuse a verified historical memory projection with a new durability claim. M3-20 therefore needs a separate promotion fact before any durable target can become authoritative.

## Decision

### 1. Preserve the M3-19 binding and add a promotion candidate

M3-20 does not modify `MetadataFabricBinding`, the binding ledger or the M3-19 evidence. It creates a new logical binding for `gda_chongqing_m3_20/lakehouse/cultural_heritage/cultural_districts` and combines it with an observed runtime binding. The resulting promotion candidate includes the source M3-19 binding SHA, immutable ResourceVersion, content SHA, OpenMetadata ref, durable Gravitino ref, logical binding SHA and runtime binding SHA.

The candidate is evidence only. `binding_schema_changed=false` and `durable_candidate_persisted_to_gda_control=false` remain fixed until a versioned runtime-aware ledger contract is accepted.

### 2. Bind the provider to stable runtime identity

The runtime binding includes Docker Desktop cluster UID, namespace UID, Gravitino Service UID, PostgreSQL and Gravitino StatefulSet UIDs, both PVC UIDs and volume names, pinned image IDs, JDBC URI and warehouse URI. Pod UIDs are intentionally excluded from the stable binding because they must rotate during restart.

Before and after restart, cluster, namespace, Service, StatefulSet, image and PVC identity must be unchanged. PostgreSQL and Gravitino pod UIDs must both change. Any stable identity drift blocks the promotion.

### 3. Separate bootstrap administration from provider apply

An ephemeral local service admin creates the isolated metalake, JDBC catalog, schema, Basic user and schema-bounded role. The role permits only `USE_CATALOG`, `USE_SCHEMA` and `CREATE_TABLE`; catalog creation is verified as `403` before and after restart.

The content-bound promotion plan, PolicyDecision and independent Approval authorize only the table projection. On a fresh isolated catalog the first provider action is a direct table create. It must record exactly one `gravitino.table.create` mutation. Retained OpenMetadata is read-only and must exactly match the M3-19 UUID, FQN, version, governance, content and snapshot.

### 4. Restart continuity requires zero repair

The exact apply immediately after create must be `no_op/0 mutations`. PostgreSQL is then restarted and made ready before Gravitino is restarted. The first post-restart apply must also be `no_op/0 mutations`, with identical table projection, Gravitino snapshot, logical binding and promotion candidate. A repair or recreate after restart is a failure, not continuity.

### 5. Local continuity is not production durability

The warehouse is a local RWO PVC and Gravitino identity uses its built-in Basic IdP. The namespace and volumes are deleted after the rehearsal. M3-20 therefore proves local JDBC/PVC restart continuity and runtime identity binding only. `durable_catalog_verified`, `production_object_store_verified`, protected workload identity, OIDC, TLS, production ingestion and `production_ready` remain false.

## Verification

The local rehearsal recorded:

- Chongqing ResourceVersion `a6000000-0000-4000-8000-000000000001` and content SHA `fd474fd65c8e4a71da241eb3fd07748ca3b972fbd2d3c32833376dbe71104007`;
- exact retained OpenMetadata UUID `9d043410-02b5-487d-bb70-da5f3969a978` with zero OpenMetadata writes;
- one bounded `gravitino.table.create`, then immediate `no_op/0` replay;
- ordered PostgreSQL/Gravitino pod replacement with stable cluster, namespace, Service, StatefulSet and PVC identities;
- first post-restart replay `no_op/0`, without repair;
- logical binding SHA `8c312db37bfe92e034bcdcb7a3c35847c81e862c74a3437970def1007af42750`;
- runtime binding SHA `a78975311fc34abd76fa41dea581594806b3d18ed364ba518cfc44c4204822f7`;
- promotion candidate SHA `bb6672cb7f98fa53305e17bbca2cb5b3756d4a335a94d79114fb4184273871d1`;
- contract SHA `307f2d4390028589c0f38be859c53826bd149d7f2a133b14488230d4f5ff6eb8` and evidence SHA `53773e9417668e03ad3ab2b5c3cdbd627fb3bc397d63c5860755ec5318eebe8b`;
- complete namespace, PVC and port-forward cleanup.

## Consequences

**Positive**: a real Active Metadata projection is now distinguishable by both logical provider identity and the exact restart-continuous runtime that served it. Historical binding evidence remains valid.

**Negative**: the candidate is not yet a first-class GDA Control ledger object, and the local file warehouse is not the target production storage architecture.

**Mitigation**: the next slice should combine this runtime-aware promotion contract with JDBC metadata plus S3-compatible object storage, then define the versioned ledger promotion transaction without weakening M3-19 history.

**Revisit trigger**: adopt a versioned runtime-aware binding/promotion ledger when protected provider identity, production object storage, backup/PITR, tenant isolation and production reconciliation evidence are available.
