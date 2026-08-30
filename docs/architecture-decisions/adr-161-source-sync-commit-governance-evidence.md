# ADR-161: Atomic SourceSync Commit Governance Evidence

**Status**: Accepted

**Date**: 2026-08-05

**Related**: ADR-096, ADR-103, ADR-104, ADR-112, ADR-130, ADR-160, ADR-163, ADR-164, ADR-165

## Context

ADR-160 made standards, models, quality rules, classification, retention, schema evolution,
quarantine and promotion policy part of each immutable `SourceSyncDefinitionVersion`. That admission
contract did not prove that a Silver or Gold provider commit had actually consumed passing quality
results, an independent approval, exact lineage or a metadata projection event. The migration-104
`commit_source_sync` function could still advance a checkpoint using provider evidence alone.

Creating a second promotion service or mutable projection would split authority from the existing
PostgreSQL SourceSync ledger. Adding governance fields to `SourceSyncCommit` would also rewrite its
immutable fingerprint contract and make historical evidence incompatible.

## Decision

Keep `SourceSyncCommit` unchanged and add the immutable
`SourceSyncCommitGovernanceEvidence` contract. Its fingerprint binds:

- the exact SourceSync commit and target `ResourceVersion`;
- the output `Artifact`;
- a non-empty, unique and canonically sorted set of `QualityResult` IDs;
- the `LineageEvent` and its OpenMetadata `metadata_change_outbox` row;
- an optional `ApprovalCase` reference, required by approval-gated and Gold definitions.

Migration `142_source_sync_commit_governance_evidence` stores that contract in an append-only,
tenant-scoped table. The gateway has read access but cannot insert, update or delete rows directly.
Migration 104's original CAS implementation is renamed to the private
`commit_source_sync_v104` primitive. Only a new governed `commit_source_sync` wrapper is executable by
the gateway.

The wrapper preserves historical, Landing and ODS behavior and rejects promotion evidence on those
paths. Before a new Silver or Gold commit can call the CAS primitive, PostgreSQL verifies all of the
following:

- the definition's same-tenant quarantine Resource exists;
- the target ResourceVersion belongs to the definition target and has the provider commit content
  SHA-256;
- the output Artifact belongs to the same Run and target version, has role `output`, and has the
  same content SHA-256;
- quality IDs exactly cover every frozen rule ref, all verdicts are `passed`, all results bind the
  same Run and target version, each evidence Artifact has role `evidence`, and the evaluator is not
  the committing workload;
- lineage binds the same Run, platform definition, output Artifact and target version, resolves its
  source version to the definition source ResourceURN, and names the committing workload as
  producer;
- the outbox row is the automatic `lineage_upsert` for that event, targets
  `openmetadata:default`, and carries the lineage event SHA-256;
- the evidence SHA-256 equals PostgreSQL's recomputation of the same canonical JSON document used
  by the Python contract;
- when approval is supplied, the case targets the definition target and content fingerprint, uses
  action `source_sync.promote`, is `approved`, and was decided before the commit. Gold and
  approval-gated promotion cannot omit it.

The wrapper calls the old CAS primitive and inserts governance evidence in one database transaction.
Any validation or insert failure rolls back the commit, evidence row and checkpoint advance.
Quality failure therefore cannot advance the authoritative target checkpoint.

Same-ID replay requires the exact stored governance evidence. Cross-Run recovery of the same source
slice returns the original commit and original evidence and cannot create a second promotion record.
The old CAS primitive is no longer executable by the gateway.

## Verification

- SourceSync contract and migration tests pass 16/16, including canonical quality IDs, evidence
  fingerprinting, tenant-safe approval references, migration controls and application-level
  commit/evidence identity validation.
- `scripts/certify_source_sync_authority.py` applies migrations 092, 094, 096, 102, 103, 104, 112,
  130, 141 and 142 to a random disposable PostgreSQL database.
- All 35 behavior gates pass. Negative cases cover missing evidence, incomplete rule coverage,
  failed quality, same-actor quality, wrong target/artifact/lineage/outbox, missing/pending/wrong
  fingerprint/wrong action approval, and mismatched same-ID replay. Each failed Silver/Gold
  promotion leaves checkpoint/commit/governance counts at `0/0/0`.
- Successful Silver and Gold paths atomically produce `1/1/1`; same-ID replay is idempotent and a
  second legal Run reuses the original Silver commit and evidence.
- All 20 database controls pass, including forced RLS, append-only guards, gateway denial of direct
  evidence insertion, the commit foreign key, public wrapper access and denial of the private v104
  primitive. The random database is confirmed removed.
- Report: `.tmp/source-sync-certification/authority-report.json`, SHA-256
  `97e2435d088b622ce3f0f180c3cbf0ef09db433b59dbdca257c6eae3334cd31f` at ADR-161
  acceptance. The cumulative ADR-163 certification now applies migration 143 and passes 40 behavior
  gates plus 26 database controls; its report SHA-256 is
  `48889777cb4ca2201cba8ab12d9e3ce3a6bd8323c650a391f3ef2ba01242aeb1`.

## Consequences

- A declared Silver/Gold promotion gate can no longer be bypassed through the SourceSync checkpoint
  authority.
- Quality, approval, lineage and metadata projection evidence remain owned by their existing
  ledgers; this decision adds only an immutable cross-ledger binding, not duplicate state.
- A quarantine Resource is required before governed promotion. ADR-163 additionally requires an
  atomic physical quarantine receipt; ADR-164/165 now prove the shared path for Flink event-stream,
  Spark/Iceberg micro-batch and PostgreSQL CDC, without extending that claim to every provider or
  data kind.
- The disposable PostgreSQL certification is not a persistent development, staging, Kubernetes,
  production or cloud rollout. Migration deployment and environment reconciliation remain governed
  operational actions.

## Revisit Trigger

Extend ADR-164's shared quarantine recorder only when document, imagery, video, point-cloud,
time-series or additional database CDC adapters have real data-plane certification rather than
contract-only enumeration.
