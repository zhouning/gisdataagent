# ADR-167: Active CDC Schema Evolution and Fail-Closed Promotion

**Status**: Accepted

**Date**: 2026-08-05

**Related**: ADR-102, ADR-103, ADR-106, ADR-160, ADR-166

**Extended by**: ADR-168, ADR-169

## Context

ADR-106 and ADR-166 proved PostgreSQL logical CDC, checkpoint recovery, dual Silver/quarantine
commits and bounded network recovery, but the source schema stayed fixed. A running connector could
therefore continue to process an incompatible schema revision without the platform distinguishing
projection continuity from permission to promote that revision.

Adding a schema registry, Kafka or another scheduler would create a second authority before the
existing `SchemaDriftEvent`, `SourceSchemaDriftLedger` and `ApprovalCase` lifecycle had been exercised
by active CDC. Letting the connector silently widen its target would make the physical runtime, not
the governed SourceSync definition, the model authority.

## Options Considered

| Option | Benefit | Cost and risk | Decision |
|---|---|---|---|
| Add a registry and event bus | Central compatibility API and durable fan-out | New services, offsets and operational ownership without a measured need | Deferred |
| Let the connector auto-promote every source change | Minimal orchestration work | Breaking revisions can bypass standards, quality and human approval | Rejected |
| Keep an explicit projection and reuse the drift/ApprovalCase ledgers | No new runtime service; one governance authority | Requires discovery checkpoints and an explicit admission decision | Adopted |

## Decision

Use a stable, explicitly declared CDC projection for `road_id`, `revision`, `road_name_base64` and
`geometry_sha256`. While the Flink job is running, discover the PostgreSQL table from
`information_schema.columns` before and after each DDL operation and derive deterministic
`DiscoverySnapshot` and `SchemaDriftEvent` evidence.

An additive nullable `observed_at TIMESTAMPTZ` column may be reconciled after the existing projection
continues to checkpoint a subsequent update. Tightening that column to `NOT NULL` is breaking. It
must enter `approval_required`, create a target- and fingerprint-bound pending `ApprovalCase`, and
remain ineligible for schema-successor promotion. Automation must neither synthesize a human verdict
nor treat a running old projection as approval of the new schema.

`data_agent/source_schema_promotion.py` is the reusable fail-closed admission policy. Additive drift
must be `reconciled`; breaking drift must additionally carry its bound approved ApprovalCase.
Pending, rejected, unbound or otherwise unreconciled evidence returns a structured denied decision;
`require_source_schema_promotion()` raises before a successor can be admitted. The decision, drift
IDs, ApprovalCase reference and running projection are embedded in `SourceSyncCommit.target_commit_ref`.

The existing four-field projection may complete its governed SourceSync commit after additive
continuity is reconciled. The breaking successor is a separate promotion candidate and remains
blocked.

The disposable PostgreSQL source is considered ready only after the image emits its completed-init
marker and the final server answers `pg_isready`; this excludes the entrypoint's temporary bootstrap
server. Drift `detected_at` and transition `updated_at` both use the control database clock so the
ledger's ordering constraint does not compare a Docker VM timestamp with a client timestamp.

## Verification

- PostgreSQL 16.14 starts with four fields. During the second of two same-slot network partitions,
  active DDL adds nullable `observed_at`; discovery records one non-breaking `added` change. Flink
  remains `RUNNING`, no partial output is visible during the outage, and the projected update advances
  committed Silver output from 10 to 12 records after recovery while quarantine remains exactly 2.
- Active DDL then changes `observed_at` from nullable to `NOT NULL`; discovery records one breaking
  `nullable_tightened` change. The old projection is still `RUNNING` and drains to a savepoint.
- The additive drift lifecycle is `observed -> reconciled`. The breaking lifecycle remains exactly
  `approval_required`; direct reconciliation is rejected. Its ApprovalCase remains `pending`, state
  version 0, with no `decided_by`, and the promotion reason is
  `breaking_schema_drift_pending_approval`.
- Flink's intentional failure occurs at checkpoint 28 and processed count 5; attempt 1 restores count
  3. Checkpoints 75 through 85 observe all 16 CDC changelog records. After ADR-169's projected update,
  the exact provider split is 14 accepted and 2 quarantined, with two final source rows.
- Schema DDL/mutation LSNs are `0/1954780`, `0/19548E0`, `0/1954A48` and `0/1998B08`. During the
  additive phase,
  the same slot stays at `0/1952778` while disconnected and then reaches the exact target
  `0/19548E0`; WAL lag moves `56 -> 8,552 -> 0` bytes.
- All 18 provider checks, 4 schema-governance checks and 16 top-level checks pass. SourceSync advances
  `0 -> 1` once, and same-ID/cross-Run replay preserves the bound evidence.
- Report: `.tmp/source-sync-certification/chongqing-osm-postgres-cdc-report.json`, SHA-256
  `f27bb9912626bfa594557df37d2007cab1037735d752feb9b266290ac2f840ea`.
- The random control database, pending certification ApprovalCase, PostgreSQL/Flink containers and
  work directory are removed. Persistent SourceSync tables remain empty. This certifies behavior; it
  does not create an operational approval backlog in a durable environment.

## Trade-offs and Consequences

- Active additive PostgreSQL evolution now has real projection-continuity evidence without adding a
  registry, broker, service or scheduler.
- Breaking schema promotion is demonstrably fail-closed and reuses the same drift and ApprovalCase
  authority as other providers.
- A stable projection can mask source fields from the target by design. Consumers receive the new
  field only through a separately governed model/definition revision.
- This proof covers one nullable column addition accumulated during a short network partition and one
  later nullability tightening on a disposable local runtime. It does not certify column
  rename/removal, selected-column type changes, generated columns, table recreation, concurrent DDL,
  registry interoperability, long outage/sustained flapping, production notification delivery or
  production SLO/HA.

## Revisit Triggers

- multiple producers or consumers require a shared compatibility API or durable schema event stream;
- selected-column evolution requires coordinated dual-read/dual-write or backfill;
- production DDL rate, approval latency or notification SLO requires persistent automation;
- PostgreSQL, Flink CDC connector or decoding behavior changes.
