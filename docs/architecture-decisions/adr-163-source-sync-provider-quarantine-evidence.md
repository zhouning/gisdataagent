# ADR-163: Atomic Provider Quarantine Evidence for Governed SourceSync

**Status**: Accepted

**Date**: 2026-08-05

**Related**: ADR-096, ADR-104, ADR-105, ADR-141, ADR-160, ADR-161

**Extended by**: ADR-164, ADR-165

## Context

ADR-160 froze a quarantine ResourceURN into every governed Silver/Gold SourceSync definition, and
ADR-161 required that Resource to exist before promotion. Neither decision proved that the provider
had physically written rejected records, nor bound their count, reasons and content to the exact
source slice and commit. A provider could therefore satisfy the promotion gate with an empty
quarantine Resource.

Adding mutable quarantine fields to `SourceSyncCommit` would invalidate its existing fingerprint and
historical rows. A separate quarantine service or queue would introduce a second transaction boundary
without evidence that independent scaling is required.

## Options Considered

| Option | Benefit | Cost and risk | Decision |
|---|---|---|---|
| Extend `SourceSyncCommit` | One row contains every fact | Rewrites an immutable contract and breaks historical compatibility | Rejected |
| Add a quarantine service and delivery queue | Independent scaling and retention | Cannot atomically advance the PostgreSQL checkpoint without distributed coordination | Deferred |
| Add an append-only evidence ledger in the existing transaction | Preserves contracts and gives one atomic authority boundary | Adds a deferred database invariant and one cross-ledger receipt | Adopted |

## Decision

Add immutable `SourceSyncQuarantineEvidence` without changing `SourceSyncCommit`. Its canonical
SHA-256 binds the tenant, exact commit, source-slice SHA-256, quarantine `ResourceVersion`, quarantine
`Artifact`, rejected-record count and reason-count map. `ArtifactRole.QUARANTINE` identifies the
physical rejection output rather than generic quality evidence.

Migration `143_source_sync_quarantine_evidence` adds an append-only, tenant-scoped ledger with forced
RLS. The gateway can read it but cannot insert, update or delete it. The only write path is
`bind_source_sync_quarantine_evidence()`, which validates:

- the evidence tenant, commit and source slice;
- a quarantine ResourceVersion owned by the definition's frozen quarantine ResourceURN;
- an Artifact with role `quarantine`, the same Run, ResourceVersion, actor and content SHA-256;
- an Artifact timestamp no later than the commit and non-empty content when records were rejected;
- manifest schema `gda.source_sync_quarantine.v1`, definition ID, source slice, target content,
  rejected content, rejected count and exact reason distribution;
- positive canonical reason counts whose sum equals `records_rejected`, including the valid zero/empty
  receipt;
- the evidence SHA-256 recomputed by PostgreSQL from the same canonical document as Python.

A deferred constraint trigger requires every newly inserted Silver/Gold commit to have quarantine
evidence before the outer transaction commits. `SourceSyncAuthority.commit()` calls the governed
commit wrapper and quarantine binder in that same transaction. A missing or invalid receipt rolls
back checkpoint, commit, governance evidence and quarantine evidence together. Landing and ODS retain
their existing path and reject quarantine evidence.

Same-ID replay must supply the identical governance and quarantine evidence. Cross-Run replay of the
same source slice supplies neither new evidence nor a second provider write; it returns the original
commit and both original receipts. A historical governed commit without a quarantine receipt fails
closed instead of fabricating evidence.

## Provider Proof

The Chongqing OSM Flink certification is promoted from ODS to governed Silver. Flink 1.19.3 processes
ten deterministic events derived from the published 50,366-road GeoParquet. After a completed
checkpoint it fails once and restores from offset 5. Eight unique events are accepted; duplicate
`cq-osm-e05` and late `cq-osm-e07` are physically committed to the rejected output.

The certifier hashes physical output, quality and quarantine manifests, registers source, target and
quarantine ResourceVersions, then records output/evidence/quarantine Artifacts, an independently
evaluated passing QualityResult, LineageEvent and automatic OpenMetadata outbox row. One transaction
binds those governance facts and the two rejected records to the Silver SourceSync commit. Same-ID
and cross-Run replay both recover the original dual evidence.

ADR-164 extracts that provider assembly into `SourceSyncQuarantineRecorder` and applies the same
canonical path to a second provider class. The real Spark/Iceberg Silver micro-batch certification
now writes explicit zero-rejection receipts for both its 50,366-row baseline and its three-mutation
incremental merge; each receipt is hashed, registered and atomically bound with the phase's target,
quality, lineage and metadata evidence.

## Verification

- Contract tests pass 37/37 for the focused SourceSync and platform-contract slice.
- `scripts/certify_source_sync_authority.py` applies migration 143 to a random disposable PostgreSQL
  database. All 40 behavior gates and 26 database controls pass.
- Negative cases cover missing quarantine evidence, forged ResourceVersion, wrong Artifact role,
  wrong Run, wrong rejected count and mismatched same-ID evidence. Every failed Silver promotion
  leaves checkpoint/commit/governance/quarantine at `0/0/0/0`.
- Successful Silver and Gold commits produce `1/1/1/1`; Gold also proves a zero-rejection receipt.
- `scripts/certify_chongqing_osm_flink_stream.py` passes 12 end-to-end and 11 Flink behavior checks,
  including physical hash verification and the two real rejected events.
- Authority report: `.tmp/source-sync-certification/authority-report.json`, SHA-256
  `48889777cb4ca2201cba8ab12d9e3ce3a6bd8323c650a391f3ef2ba01242aeb1`.
- Flink report: `.tmp/source-sync-certification/chongqing-osm-flink-report.json`, SHA-256
  `413561aff0b8608b44645b05679180816a5ea57cedbd919bf463cf63ffea70ed`.
- Spark report: `.tmp/source-sync-certification/chongqing-osm-report.json`, SHA-256
  `211ae24a532dd5060049ce2c139bfc50f6a43c76d42d7a5e54d4aeb908d5f2f5`; all 12 end-to-end checks
  pass, including two governed zero-rejection receipts and dual-evidence cross-Run replay.
- PostgreSQL CDC report: `.tmp/source-sync-certification/chongqing-osm-postgres-cdc-report.json`,
  SHA-256 `216f318c9e3cf29c75bf3342cd4c013c66c2aa582d45ee47d364ce80230731f8`; 10 accepted
  and 2 `invalid_geometry_sha256` changes are checkpoint-consistently separated across a bounded
  source-network partition and all 13 top-level checks pass.
- All random databases, object prefixes and work directories were removed; persistent SourceSync
  tables were unchanged.

## Consequences

- A new Silver/Gold SourceSync commit cannot advance on the existence of an empty quarantine Resource;
  it requires a provider receipt for rejected records or an explicit zero-rejection receipt.
- Quarantine remains a versioned data-plane product with an immutable control-plane binding. This
  decision does not create another scheduler, registry or mutable projection.
- The real proof covers Flink filesystem event-stream rejected records, Spark/Iceberg micro-batch
  zero-rejection receipts and PostgreSQL CDC invalid-record rejection. It does not prove document,
  imagery, video, point-cloud, time-series or other database CDC adapters write a conforming
  quarantine.
- The disposable PostgreSQL and local Docker evidence is not a persistent development, staging,
  Kubernetes, production or cloud rollout.

## Revisit Triggers

- A provider needs asynchronous quarantine finalization that cannot share the SourceSync transaction;
- object-lock retention or deletion policy requires an independently operated quarantine service;
- another data-kind adapter produces real rejected records and needs additional manifest facets while
  preserving the canonical core receipt.
