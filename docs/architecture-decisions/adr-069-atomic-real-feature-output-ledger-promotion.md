# ADR-069: Atomic real-feature output ledger promotion

**Status**: Accepted

**Date**: 2026-07-31

**Decision owners**: Data Platform, Metadata Platform, Data Governance, GIS Platform, Security, Platform Architecture

**Related decisions**: [ADR-047](adr-047-deterministic-metadata-fabric-ingestion-projection.md) · [ADR-068](adr-068-local-authorized-real-feature-iceberg-ingestion.md) · [ADR-022](adr-022-platform-control-gateway.md)

## Context

M3-22 produced a path-free output ResourceVersion, output Artifact, Iceberg metadata evidence Artifact, independently evaluated passed QualityResult and source-to-output LineageEvent for the real 20-feature Chongqing cultural-district slice. It deliberately kept every object outside GDA Control and left the PlatformRun non-terminal.

Calling the existing public `register_resource_version`, `record_artifact`, `record_quality_result` and `record_lineage` methods sequentially would commit one transaction per call. A process failure could therefore leave an authority-looking partial ledger. The promotion must also reject a missing or drifted output Resource authority record, exact replay must be a no-op, and the existing PlatformRun success function must remain the only terminal success authority.

The M3-22 runtime and object-store material were deleted after its local rehearsal. M3-23 can prove the control-ledger mechanism against the checked evidence, but it cannot turn the deleted local S3 location into retained production material.

## Options considered

| Option | Benefit | Cost or risk | Decision |
|---|---|---|---|
| Call existing public gateway writes in sequence | No gateway refactor | Partial commits are observable after failure | Rejected |
| Add a new `SECURITY DEFINER` database function | Strong database-owned entry point | Duplicates existing contract validation and adds migration/privilege surface without a current need | Deferred |
| Compose a dedicated promoter over one gateway transaction | Reuses current RLS, foreign keys, append-only triggers and grants without changing the evidence-bound gateway module | All callers must use the dedicated promoter for this bundle | Chosen |

## Decision

### 1. Promote one content-bound bundle

`RunOutputLedgerPromotion` binds exactly one pre-existing authority Resource to:

- one output ResourceVersion;
- one output Artifact with the same content SHA and Run;
- one distinct quality evidence Artifact;
- one passed QualityResult whose evaluator differs from the output creator and whose rule/metrics match the evidence Artifact;
- one LineageEvent from a Run input ResourceVersion to the output version and output Artifact.

Tenant, Run, DefinitionVersion, ResourceVersion, Artifact and content identities must match before any write.

### 2. Use one existing PostgreSQL transaction boundary

`RunOutputLedgerPromoter.promote` is isolated in the M3-23 module so adding this bundle does not invalidate the earlier gateway-bound evidence chain. It composes the existing `PlatformGateway` transaction, load and ResourceVersion-write primitives, validates the pre-existing Resource authority, source ResourceVersion, DefinitionVersion and accepted/reconciling PlatformRun, then writes in foreign-key order:

1. ResourceVersion;
2. output Artifact;
3. quality evidence Artifact;
4. QualityResult;
5. LineageEvent.

The promoter reuses the existing `_transaction` boundary with `SET LOCAL ROLE gda_control_gateway` and tenant context. Artifact, QualityResult and LineageEvent inserts remain private to that transaction coordinator; no public single-record gateway method is called mid-transaction. No legacy table is written and no new database privilege is granted.

All five writes must report the same creation state. `true` for all is the first commit; `false` for all is an exact replay. Mixed creation states mean partial pre-existing state and fail the entire new transaction. Existing conflicting identity/content also fails closed.

### 3. Keep authority and terminal success separate

The output Resource authority record is a prerequisite rather than an implicit side effect of candidate promotion. M3-23 records its local Gravitino/Iceberg identity and explicitly marks the material as not retained and not production-ready.

M3-22 did not retain complete PolicyDecision and Approval Artifact payloads. M3-23 therefore creates an accepted Run correlation with the checked M3-22 authorization fingerprint as `config_fingerprint`; it does not fabricate those missing Artifacts or claim that M3-22 authorization was persisted to GDA Control.

The promotion transaction never calls `finalize_platform_run_success`. The existing terminal gate still lacks a successful FrameworkAttemptObservation. In addition, the M3-22 Iceberg metadata evidence Artifact was created by the ingestion workload, not by the independent quality evaluator required by the success function. An explicit finalization attempt must fail and leave the Run at `accepted`, state version zero, with only its initial event.

### 4. Treat the result as local control-plane evidence

The real PostgreSQL rehearsal uses a fresh temporary database, proves rollback through an injected failure before QualityResult append, proves exact first/replay behavior, FORCE RLS, cross-tenant isolation, minimum grants and direct UPDATE/DELETE rejection, then deletes the database.

`promotion_persisted_to_gda_control=true` means the checked bundle committed to that real temporary GDA Control database. It does not mean the local Iceberg material, database or provider runtime was retained, deployed to staging or promoted to production.

## Verification

The M3-23 rehearsal recorded:

- source M3-22 evidence SHA `42abd82613eaf28cb53c64280258bc75dba6cf841f9a513a4c801a9f798b9899`;
- output content SHA `bdc06792e8b935176ee6df6f6f6d4be1535622d54d9b994a778cabfe5a574618`;
- promotion SHA `404b6e4e5d8194f092bd83ef99cbf2d1d727015b926cd438a79eb0210f969a22`;
- injected failure rollback counts of zero for all five candidate categories;
- first promotion `created=true`, exact replay `created=false`, with row counts `1 ResourceVersion + 2 Artifacts + 1 QualityResult + 1 LineageEvent`;
- missing authority, cross-tenant read/direct insert and eight direct mutation attempts rejected;
- PlatformRun `accepted@0`, one initial event and explicit success finalization rejection;
- contract SHA `bd21c81925f66acdfecca5cabd78651f31deab4165da2ccd6900c4e5796e5735` and evidence SHA `f6efea5000791dec1716a8354a8e39a8425b083ca4d409f4bcb61f0e7e03580d`.

## Consequences

**Positive**: a real GIS output can now cross from checked provider evidence into the version, Artifact, quality and lineage ledgers as one idempotent transaction without weakening RLS, append-only or terminal success authority.

**Negative**: M3-23 proves a local control-plane commit against historical evidence. Its target material and database are not retained. The correlated Run does not contain persisted M3-22 policy/approval Artifacts and cannot be finalized successfully.

**Mitigation**: the next retained staging slice must produce policy/approval, provider success observation, independently created quality evidence and output material in durable selected storage before calling the same promotion method and the existing success gate.

**Revisit trigger**: add a database-owned promotion function only if another trusted writer must perform the same bundle commit without the Python gateway, or if production concurrency shows that gateway transaction serialization is insufficient.
