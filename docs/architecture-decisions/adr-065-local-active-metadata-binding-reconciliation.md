# ADR-065: Local Active Metadata binding reconciliation

**Status**: Accepted

**Date**: 2026-07-30

**Decision owners**: Data Platform, Metadata Platform, Data Governance, Security, Platform Architecture

**Related decisions**: [ADR-049](adr-049-tenant-scoped-metadata-fabric-binding-ledger.md) · [ADR-054](adr-054-local-gravitino-jdbc-catalog-restart-continuity.md) · [ADR-064](adr-064-local-scheduler-triggered-active-metadata-projection-execution.md)

## Context

M3-18 retained an exact OpenMetadata and Gravitino projection for the real Chongqing cultural-district ResourceVersion, but deliberately did not persist its provider binding in GDA Control. A later read-only probe found the OpenMetadata UUID, FQN, version, governance, content and snapshot unchanged while the Gravitino table was absent.

The Gravitino target used an Iceberg `memory` catalog. After provider restart, the connector reported no visible schemas, while Gravitino's PostgreSQL entity index still retained the old schema row. A normal schema create therefore failed with a duplicate-key conflict. Treating this as a generic create, directly deleting provider database rows, or accepting the M3-18 evidence without a current read-back would all weaken the binding contract.

## Decision

### 1. M3-18 evidence and OpenMetadata state are immutable prerequisites

M3-19 validates the checked M3-18 evidence and its dependency fingerprints before database or provider writes. It reconstructs the exact ResourceVersion, provider targets, binding candidate and independent `metadata_fabric.apply` authorization. The retained OpenMetadata UUID, FQN, version, GDA identity, owner, domain, tags and canonical snapshot must all match M3-18 before any repair.

Missing or drifted OpenMetadata blocks. A Gravitino-present/OpenMetadata-missing state also blocks. OpenMetadata is never mutated by this reconciliation.

### 2. Only an exact, visibly empty M3-18 memory catalog may be reset

If the target table is absent, M3-19 reads the dedicated M3-18 catalog configuration. Name, type, provider, `memory` backend, URI and warehouse must match the authorized target. The target schema must be absent and the complete visible schema inventory must be empty.

Only that state permits a provider-native forced catalog reset followed by recreation of the exact catalog, schema and table. Every recorded mutation must begin with `gravitino.`. A non-empty inventory, configuration drift, another backend, unexpected response or non-Gravitino mutation blocks before binding commit. Gravitino's PostgreSQL is never edited directly.

### 3. Repair is accepted only after zero-mutation replay

The repaired table must read back the M3-18 ResourceURN, ResourceVersion UUID, content SHA, provider revision and binding SHA. An immediate exact replay must be `no_op` with zero mutations and identical OpenMetadata/Gravitino observations. Only then is provider evidence materialized.

### 4. PlatformGateway owns the immutable binding fact

The same scheduler Run, dispatch authorization, provider-apply plan, PolicyDecision, Approval and provider evidence are registered on a fresh PostgreSQL database. `PlatformGateway.commit_metadata_fabric_binding` creates exactly one tenant-scoped row; exact replay returns `created=false`. FORCE RLS, cross-tenant invisibility, append-only grants and direct UPDATE/DELETE rejection remain mandatory.

### 5. Provider and scheduler success do not bypass terminal evidence

The PlatformRun remains `reconciling`. M3-19 does not produce the output Artifact, QualityResult, LineageEvent and RunSuccessEvidence required for `succeeded`. The callback, provider port-forwards, standalone scheduler container and temporary database are removed after the rehearsal.

## Verification

The local rehearsal recorded:

- Chongqing content SHA `fd474fd65c8e4a71da241eb3fd07748ca3b972fbd2d3c32833376dbe71104007`;
- exact retained OpenMetadata UUID `9d043410-02b5-487d-bb70-da5f3969a978` and snapshot SHA `a3ed5e2195c2f5847b5f5b59d78c8ba547c1f7170b3396cdd56b45f8559b0077`;
- four Gravitino-only mutations: stale empty memory-catalog reset, catalog create, schema create and table create;
- immediate replay `no_op/0 mutations` with binding SHA `7de24cee9dd50dfeefcc886cf43024f4d92b7650767d71d064fdce19ffccb16b`;
- first binding commit `created=true`, replay `created=false`, one ledger row, binding ID `ff669a52-1271-55f0-a1b6-ee6f57ddb1ea`;
- DolphinScheduler `SUCCESS`, two attempt observations, one external correlation and PlatformRun `reconciling`;
- callback, two port-forwards, standalone container and temporary database cleanup;
- contract SHA `012a7c86ba9fe53217e721ff7286b8f2a246b9394efd2999abbcd025e13ac7f5` and evidence SHA `e6d0e3ac4e052029dad0c18d0804626a8af61554a54081c37d8cc9a80c55cd33`.

## Claim Boundary

Allowed now:

- the retained M3-18 OpenMetadata projection was verified before mutation;
- the exact absent Gravitino projection was repaired under a content-bound local authorization;
- repair replay was mutation-free and the resulting binding was persisted idempotently through PlatformGateway;
- the checked real-data binding is tenant-scoped, append-only and cross-tenant invisible in the recorded local PostgreSQL rehearsal.

Fixed false now:

- durable Gravitino catalog continuity, Gravitino authentication and provider-wide minimum privilege;
- protected workload identity, OIDC, TLS and a deployed durable executor;
- production scheduler/provider submission, production binding deployment and production ingestion;
- terminal PlatformRun success and `production_ready`.

## Consequences

**Positive**: M3-19 connects a real scheduler/provider execution to the authoritative GDA binding ledger without trusting stale evidence or mutating retained governance state.

**Negative**: the repair exposes why a `memory` catalog cannot support a production durability claim. The local reset is intentionally limited to a dedicated, visibly empty catalog and is not a general recovery mechanism.

**Revisit trigger**: replace this repair path with authenticated durable-catalog reconciliation when a protected executor, persistent provider identity, durable Gravitino backend, production PlatformGateway deployment and complete terminal evidence chain are available.
