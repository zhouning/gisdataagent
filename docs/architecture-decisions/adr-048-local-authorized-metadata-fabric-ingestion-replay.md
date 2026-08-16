# ADR-048: Local Authorized Metadata Fabric Ingestion Replay

**Status**: Accepted

**Date**: 2026-07-28

**Decision owners**: Data Platform, Metadata Platform, Data Governance, Security, Platform Architecture

**Related decisions**: [ADR-006](adr-006-openmetadata-governance-and-active-metadata-platform.md) · [ADR-020](adr-020-platform-resource-run-and-evidence-contracts.md) · [ADR-024](adr-024-dispatch-authorization-evidence.md) · [ADR-036](adr-036-read-only-metadata-fabric-bridge-contract.md) · [ADR-037](adr-037-local-metadata-fabric-foundation-sandbox.md) · [ADR-047](adr-047-deterministic-metadata-fabric-ingestion-projection.md)

## Context

M3-1 established a deterministic projection plan from terminal GDA evidence, but deliberately exposed no provider mutation client. M3-2 must test the next boundary: whether one exact plan can be authorized, materialized into the local OpenMetadata and Gravitino providers, read back using provider-assigned identity, and replayed without a second mutation.

The available environment is the Docker Desktop sandbox. OpenMetadata uses its local bootstrap administrator, Gravitino authentication is disabled, and the Gravitino Iceberg catalog uses the memory backend. The source ResourceVersion and authorization records are deterministic local fixtures. These facts permit a bounded integration rehearsal, not a production-ingestion claim.

## Options Considered

| Option | Benefit | Cost/risk | Decision |
|---|---|---|---|
| Reuse M3-1's synthetic OpenMetadata UUID as a write identity | Minimal adapter work | Provider identity would be fabricated and could collide with real state | Rejected |
| Upsert each provider independently and repair later | Tolerates partial availability | Creates an ambiguous half-projection and weakens replay semantics | Rejected |
| Persist a new binding into GDA Control immediately | Completes the apparent round trip | Adds a second write authority before gateway and protected authorization are available | Rejected |
| Create by natural key, read back provider identity, compensate partial failure, and retain a binding candidate only in evidence | Exercises the provider APIs while preserving authority boundaries | Does not establish production identity, durable catalog behavior, or GDA persistence | Adopted |

## Decision

### 1. Authorization is exact and precedes every provider read/write decision

`metadata_fabric_ingestion_replay` derives an execution-plan Artifact from the immutable M3-1 plan. A content-bound `PolicyDecision` must allow the exact action, tenant, run, definition version, source/target versions, plan fingerprint and Artifact. A separate `ApprovalRecord` must bind that policy Artifact and be active at execution time. Executor, evaluator and approver subjects must be distinct, and any missing, expired, denied, obligated or scope-drifted record fails before mutation.

These are checked-in local contract artifacts. They do not prove protected-environment policy evaluation, human review, workload identity or production authorization.

### 2. Providers are addressed by natural key and read back after creation

OpenMetadata objects are created by service/database/schema/table names. The table is then read back to obtain its real UUID, version, owner, domain, glossary/classification tags and GDA reference extensions. Gravitino is created and read back by metalake/catalog/schema/table identity and GDA properties.

The two observations form a deterministic binding-candidate fingerprint. M3-2 does not persist this candidate into GDA Control and never writes legacy tables.

### 3. Partial inventory blocks and failed creation compensates

Preflight checks both target tables. If only one provider contains the target, apply stops without mutation. If neither contains it, OpenMetadata and Gravitino are materialized in order. A provider failure triggers reverse-order deletion of only the objects created by the current attempt. Existing governance objects and unrelated provider state are not deleted.

Gravitino lookup checks metalake, catalog and schema before the table because Gravitino 1.3.0 can return HTTP 500 for a deep lookup whose parent metadata is absent. The rehearsal therefore treats parent absence as target absence without suppressing other provider errors.

### 4. Successful projections are retained for a zero-mutation replay

After the first read-back verifies exact GDA identity, governance and technical revision, the same authorized plan is applied again. Both target observations must already match, no mutation operation may be recorded, the status must be `no_op`, and the binding-candidate fingerprint must remain unchanged.

The replay proves idempotency only for the retained local provider objects in this bounded run. It does not prove concurrent writers, crash recovery, durable queue delivery or production retry behavior.

### 5. Local provider limitations remain explicit

The OpenMetadata login token is held only in memory and never enters evidence or exceptions, but the authenticated principal is the bootstrap administrator rather than a minimum-privilege workload. Gravitino has no authentication. Its `lakehouse-iceberg` catalog uses a memory backend; restart persistence and production Iceberg catalog conformance are not verified. A force-delete followed by same-process recreation can retain invalid backend cache and requires a Gravitino process restart in this sandbox.

No OpenLineage event is emitted, no binding is committed to GDA Control, and no production readiness gate changes state.

## Verification

The final local observation records:

- source plan fingerprint `a5c8ef636c03a38d0c6edaacff7d1edeba9c4b8a7f1491c493e9308257c5a94d`;
- local apply plan fingerprint `241cb2018c093f76378d265ab8fb617d161c1be7bd4effa6fad361e9db7522c4`;
- authorization fingerprint `7bc8f577cbdea8d9979b2606278a52176cc2d723a6159c4e1f35ada0f5bb6db0`;
- first apply `created` with eight target-hierarchy mutations; shared governance/custom-property objects already present were reused;
- replay `no_op` with zero mutations;
- provider-assigned OpenMetadata table UUID `522fb32f-8613-4ff5-96cd-0306da155d00`;
- binding-candidate fingerprint `125d7197f05ff9c37999a94d090d123dcf905480b776da0738d9625ab5045598`;
- sanitized evidence fingerprint `3d5fb07267680520d2f03bf27f354787b7253210eb93ab85aae83d5f5a714dbe`;
- both loopback port-forwards stopped and no credential-bearing field recorded.

Focused tests cover authorization scope and separation, natural-key identity, first apply/replay, partial inventory, state drift, compensation, credential sanitization, Gravitino parent lookup, evidence tampering and committed live-evidence boundaries.

## Claim Boundary

Allowed now:

- `local_live_provider_ingestion_verified=true` for the recorded Docker Desktop provider identities;
- `deterministic_live_replay_verified=true` for the retained local target objects;
- provider mutations were gated by exact local PolicyDecision/Approval artifacts;
- a real provider UUID was read back into a non-persisted binding candidate;
- the path does not write GDA Control or legacy authorities.

Fixed false now:

- provider minimum privilege and OIDC;
- Gravitino authentication and durable catalog persistence;
- binding persistence into GDA Control;
- live OpenLineage emission;
- production ingestion, production conformance and `production_ready`.

## Consequences

**Positive**: M3-2 proves the adapter boundary against both live local APIs, including provider-assigned identity, fail-closed authorization, compensation and deterministic replay. It also preserves the system-of-record split: providers receive projections, while GDA truth is untouched.

**Negative**: the rehearsal uses fixture evidence, bootstrap admin access, unauthenticated Gravitino and an in-memory catalog. Retained local projection objects are not a production deployment or durable binding.

The validator treats the checked live evidence as a historical observation. Its raw contract fingerprint must either match the current files or appear in the explicit historical allowlist, and the current code must still regenerate the exact source-plan, apply-plan and authorization fingerprints. This permits mainline-only formatting or enum modernization without rewriting live evidence, while any unknown historical contract or semantic fingerprint drift remains blocked. A compatibility verdict is not a new live provider rehearsal.

**Mitigation**: the next capability must use protected workload identity, minimum-privilege provider roles, a durable authenticated catalog, persisted binding through the GDA gateway, concurrency/failure injection and wire-level OpenLineage delivery. Each claim requires its own evidence and production gate.

**Revisit trigger**: change this adapter contract only when provider API behavior, protected authorization, durable catalog selection or gateway binding persistence requires a different identity, compensation or replay rule.
