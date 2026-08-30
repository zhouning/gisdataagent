# ADR-160: SourceSync Governance Contract for Lakehouse Ingestion

**Status**: Accepted

**Date**: 2026-08-05

**Related**: ADR-101, ADR-102, ADR-103, ADR-104, ADR-105, ADR-106, ADR-130, ADR-131

## Context

The platform already has real batch, micro-batch, event-stream and PostgreSQL WAL CDC slices, native
vector and raster materialization, schema-drift approval, quality results, OpenLineage ingestion and
metadata-fabric reconciliation. Those capabilities did not form one ingestion admission contract.
`SourceSyncDefinitionVersion` froze cursor and write semantics, but standard, model, quality,
classification, retention, schema evolution, quarantine and promotion bindings could remain in
free-form executor config or be omitted.

Adding a second ingestion registry or service would create competing authority for source-to-target
state. Rewriting old immutable definitions to invent governance facts would invalidate fingerprints
and manufacture evidence that never existed.

## Decision

`SourceSyncDefinitionVersion` remains the sole provider-independent ingestion authority and now owns
an optional, immutable `gda.source_sync_governance.v1` contract. The contract is optional only so
historical definitions remain readable with their original fingerprint. The application authority
and PostgreSQL insert trigger both reject every new definition without it.

The governance contract freezes:

- target layer (`landing`, `ods`, `silver`, `gold`), data kind (`tabular`, `vector`, `raster`,
  `document`, `image`, `video`, `point_cloud`, `timeseries`) and capture kind (`batch`,
  `micro_batch`, `cdc`, `event_stream`);
- exact source-adapter ID, version and SHA-256 fingerprint;
- standard-mapping contract, standard version and data-model version bindings;
- one or more unique quality-rule version refs, classification and retention policy versions;
- schema-change policy, promotion mode, quarantine ResourceURN and event-time/watermark semantics.

Landing and ODS writes cannot declare promotion and must remain `blocked`. Silver and Gold require
standard, model and same-tenant quarantine bindings and a promotion gate; Gold requires an approval
gate. Event streams require event time and watermark. CDC and event streams require provider-token
or offset cursors. Full loads are batch-only, while non-batch captures are incremental. Raster and
object-shaped data cannot use row merge or event-stream semantics.

The canonical contract document is part of `definition_sha256`. When the contract is absent, the old
fingerprint document is retained byte for byte. The full contract is projected into the canonical
Resource governance reference, while ResourceVersion records layer, kind, capture and a contract
fingerprint. This makes ingestion policy discoverable without introducing another catalog.

Migration `141_source_sync_governance_contract` adds one nullable JSONB column for historical rows,
a structural and cross-field CHECK, a unique non-empty quality-ref validator, and a replacement
insert guard. PostgreSQL independently rejects missing contracts, malformed adapters, inconsistent
standard bindings, invalid layer promotion, missing stream time semantics, wrong capture/cursor
combinations, unsupported merge combinations and cross-tenant quarantine references.

Existing Spark/Iceberg bounded merge definitions are classified as `micro_batch`; the bounded
Flink/Iceberg reconciliation slice is also `micro_batch`; the event-time Flink job is
`event_stream`; and PostgreSQL WAL ingestion is `cdc`. These existing ODS certifications bind an
integrity quality rule, classification and retention policy and explicitly block promotion.

## Verification

- SourceSync contract tests pass 14/14, including ODS admission, missing Silver bindings, missing
  event-time/watermark, invalid CDC cursor, cross-tenant quarantine, contract fingerprinting,
  historical hash compatibility and application-level rejection of new legacy definitions.
- Platform-contract, SourceSync, Spark incremental, Flink stream, PostgreSQL CDC, Flink/Iceberg
  reconciliation and migration regressions pass 69/69.
- `scripts/certify_source_sync_authority.py` applies migrations 092, 094, 104 and 141 to a random
  disposable PostgreSQL database. All 17 authority behavior gates and 15 database controls pass,
  including direct gateway rejection of a missing contract and duplicate quality refs. The random
  database is confirmed removed. Report:
  `.tmp/source-sync-certification/authority-report.json`, SHA-256
  `2339671f2c4eb82efac63dfdc26d745d687701ca1a8ab0d8a157fa3b1b8b0905`.
- Python compilation and diff whitespace checks pass. Ruff reports only the pre-existing
  whole-file modernization findings in `platform_contracts.py`.

## Consequences

- An ingestion definition can no longer be newly admitted with only connectivity and cursor
  semantics. Governance versions become part of its immutable identity and replay comparison.
- Historical definitions are not backfilled with invented policy references. They can be read and
  replayed, but the Authority cannot create another contract-less definition.
- The contract describes all required data shapes and capture modes, but this milestone does not
  certify a working adapter for every enumerated shape. Existing real vector adapters are the only
  data-plane paths regressed here; prior raster evidence remains separate.
- ADR-161 now prevents Silver/Gold checkpoint advancement without exact quality, approval, lineage
  and metadata-outbox evidence and an existing quarantine Resource. Physical rejected-record writes
  by each provider adapter remain a separate data-plane certification gate.
- The disposable PostgreSQL certification is not a persistent development, staging, Kubernetes,
  production or cloud rollout. Migration deployment and environment reconciliation remain governed
  operational actions.

## Revisit Trigger

Add data-kind-specific contracts only when a real document, imagery, video, point-cloud or
time-series adapter reaches the same replay, isolation, quarantine-write and recovery gates. See
ADR-161 for the completed Silver/Gold commit-evidence authority.
