# ADR-049: Tenant-Scoped Metadata Fabric Binding Ledger

**Status**: Accepted

**Date**: 2026-07-28

**Decision owners**: Data Platform, Metadata Platform, Data Governance, Security, Platform Architecture

**Related decisions**: [ADR-006](adr-006-openmetadata-governance-and-active-metadata-platform.md) · [ADR-020](adr-020-platform-resource-run-and-evidence-contracts.md) · [ADR-022](adr-022-platform-control-gateway.md) · [ADR-024](adr-024-dispatch-authorization-evidence.md) · [ADR-036](adr-036-read-only-metadata-fabric-bridge-contract.md) · [ADR-048](adr-048-local-authorized-metadata-fabric-ingestion-replay.md)

## Context

M3-2 created the bounded local OpenMetadata and Gravitino projections, read the provider-assigned identities back and proved a zero-mutation replay. It intentionally retained only a binding candidate in sanitized evidence. M3-3 must close one narrower control-plane gap: persist that exact verified binding through `PlatformGateway` without mutating either provider, a legacy table or the immutable ResourceVersion.

The existing golden Resource contains a synthetic OpenMetadata UUID, while M3-2 observed the real local UUID `522fb32f-8613-4ff5-96cd-0306da155d00`. `Resource` is insert-only. Replacing the synthetic reference in an existing row would hide identity drift and violate the control ledger.

## Options Considered

| Option | Benefit | Cost/risk | Decision |
|---|---|---|---|
| Update the existing synthetic Resource in place | Minimal fixture work | Violates immutability and conceals provider identity replacement | Rejected |
| Store the binding as another generic Artifact only | Reuses an existing table | Does not enforce one binding per ResourceVersion or expose an explicit tenant-scoped lookup | Rejected |
| Let provider success insert a binding directly | Short path | Bypasses PlatformGateway, policy/approval verification and GDA authority boundaries | Rejected |
| Add an append-only binding ledger and require the exact four Artifacts through PlatformGateway | Explicit identity, provenance, RLS and replay semantics | Adds one narrow schema and gateway contract | Adopted |

## Decision

### 1. One immutable binding is allowed per ResourceVersion

Migration 097 adds `gda_control.metadata_fabric_binding`. Each row binds tenant, ResourceURN, ResourceVersion UUID and content SHA-256 to the complete `MetadataFabricBinding` document and its fingerprint. The binding UUID is deterministic from the target ResourceVersion. Unique constraints allow only one row per tenant and target version; a different replay conflicts instead of updating the row.

The table uses the existing immutable-mutation trigger, `FORCE ROW LEVEL SECURITY` and `gda_control.current_tenant()`. `gda_control_gateway` receives only `SELECT` and `INSERT`; `PUBLIC`, gateway `UPDATE` and gateway `DELETE` remain denied.

### 2. Four immutable Artifacts must authorize and prove the row

The record references the exact execution-plan, PolicyDecision, Approval and provider-evidence Artifact UUIDs. Before insert, `PlatformGateway` reloads all four under the transaction-local tenant and verifies:

- the Resource governance/technical refs exactly equal the provider-assigned binding refs;
- target, source and definition ResourceVersions exist and match the execution plan;
- the execution-plan Artifact, plan fingerprint and projection identities are content-bound;
- action is exactly `metadata_fabric.apply`, effect is `allow`, obligations are empty and the decision was active at provider observation time;
- approval binds the exact policy Artifact and SHA, was active at observation time and is independent from executor and evaluator;
- provider evidence contains the same binding, M3-2 evidence fingerprint, both snapshot hashes and a zero-mutation replay;
- recorder, plan creator and provider-evidence creator match the authorized workload.

Missing, cross-tenant, expired, denied, obligated, tampered or scope-drifted evidence fails before insert. Replaying the byte-equivalent record returns `created=false`; a different immutable record for the same target raises a conflict.

### 3. Live identity is registered only in a fresh local rehearsal database

The M3-3 rehearsal starts an empty temporary PostgreSQL 16 database. It reconstructs the target Resource with M3-2's real OpenMetadata UUID and verified Gravitino ref, registers the definition/source/target control chain, records the four Artifacts and commits the binding twice. It never overwrites the checked-in synthetic Resource and never calls OpenMetadata or Gravitino.

This proves the gateway and ledger behavior against retained M3-2 evidence. The temporary database is deleted after the rehearsal; it is not a production control database or a durability/backup claim.

## Verification

The local rehearsal records:

- source M3-2 evidence SHA `3d5fb07267680520d2f03bf27f354787b7253210eb93ab85aae83d5f5a714dbe`;
- provider-assigned OpenMetadata UUID `522fb32f-8613-4ff5-96cd-0306da155d00`;
- binding SHA `125d7197f05ff9c37999a94d090d123dcf905480b776da0738d9625ab5045598`;
- deterministic binding UUID `9580cd65-9fd9-5216-90a5-1fd6837e6cfb`;
- immutable record SHA `19bdbddedc27d2ed8a35119e8f065a47a02345f9bbd3a51075856cb9587f4176`;
- first commit `created=true`, exact replay `created=false`;
- FORCE RLS, no gateway UPDATE/DELETE privilege and cross-tenant read rejection;
- evidence SHA `518bfed363aba34e539ada19ea1dc708bacc9eba6578ccab165d11bccfc05223`.

Unit tests cover deterministic reconstruction, synthetic/live identity separation, execution/provider Artifact tampering and evidence integrity. PostgreSQL integration covers migrations, exact replay, missing Artifact rejection, immutable-record conflict, RLS visibility and UPDATE/DELETE rejection.

## Claim Boundary

Allowed now:

- the verified M3-2 binding can be persisted through `PlatformGateway` into a tenant-scoped append-only local GDA Control ledger;
- exact ledger replay performs no second insert;
- provider evidence, authorization and target identity are content-bound before insert;
- M3-3 performs no provider or legacy mutation.

Fixed false now:

- production GDA Control deployment, backup/recovery and concurrent-writer behavior;
- protected workload OIDC and real human approval provenance;
- OpenMetadata minimum privilege and Gravitino authentication;
- durable Gravitino catalog persistence and production conformance;
- live OpenLineage emission and production ingestion;
- production observability/NetworkPolicy gates and `production_ready`.

## Consequences

**Positive**: GDA now has an explicit immutable relation between one ResourceVersion and its verified governance/technical provider identities. A provider response cannot create it without the exact platform evidence chain.

**Negative**: the committed evidence still originates from bootstrap-admin OpenMetadata, unauthenticated Gravitino and an in-memory local catalog. The rehearsal database is ephemeral.

**Mitigation**: the next capability must be selected independently: protected workload identity and provider minimum privilege, authenticated durable catalog conformance, or live OpenLineage delivery. None may inherit a production claim from this local ledger result.

**Revisit trigger**: change this ledger only when multiple binding generations per immutable ResourceVersion, a protected approval lifecycle or provider identity rotation has an explicit migration and audit model.
