# ADR-165: Checkpoint-Consistent CDC Quarantine Routing

**Status**: Accepted

**Date**: 2026-08-05

**Related**: ADR-104, ADR-106, ADR-160, ADR-161, ADR-163, ADR-164

**Extended by**: ADR-166

## Context

ADR-106 proved PostgreSQL WAL ingestion and Flink checkpoint recovery, but every decoded row was
written to an ODS changelog. ADR-164 then established a provider-neutral quarantine recorder without
proving that a CDC adapter could physically reject invalid changes under failure and recovery.

A Silver CDC stream cannot silently accept malformed spatial identity, but failing the entire job on
one invalid row would pin the replication slot and prevent unrelated valid changes from advancing.
Writing rejected rows through a second uncheckpointed client would create duplicate or missing
quarantine records after restart.

## Options Considered

| Option | Benefit | Cost and risk | Decision |
|---|---|---|---|
| Fail the CDC job on the first invalid row | No invalid row reaches Silver | One poison change can indefinitely block the slot and source checkpoint | Rejected |
| Drop invalid rows and increment a metric | Keeps the stream moving | No replayable rejected-record evidence and no exact reconciliation | Rejected |
| Route accepted and rejected rows from one checkpointed operator to two FileSinks | Preserves progress and gives exactly-once provider outputs under restart | Still requires later cross-system SourceSync reconciliation | Adopted |

## Decision

Upgrade the PostgreSQL CDC definition from ODS to governed Silver. The Flink job uses one stateful
`CheckpointFailureRouter` for every initial-snapshot and WAL change. It validates the frozen spatial
identity rule that `geometry_sha256` is 64 lowercase hexadecimal characters. Valid changelog rows go
to the versioned Silver FileSink; invalid rows go to a separate quarantine FileSink with reason
`invalid_geometry_sha256`.

Both sinks use checkpoint rolling policy and the same Flink checkpoint domain. Processing count and
the intentional failure are stateful, so restart cannot create a second committed accepted or
rejected row. The provider must verify both sets of committed part files before it may construct a
SourceSync commit.

The certification change set contains the original ten valid changelog rows plus an invalid insert
and delete for real OSM road `102262026`. The two invalid changes are absent from Silver and present
exactly once in quarantine. The source ends with the same two valid roads as before.

After provider verification, the adapter registers the Silver target ResourceVersion, output and
quality Artifacts, independent passed QualityResult, LineageEvent and OpenMetadata outbox. It then
passes a physical two-record receipt to `SourceSyncQuarantineRecorder`. `SourceSyncAuthority` is the
only component that atomically binds governance evidence, quarantine evidence, commit and checkpoint.
Flink checkpoints, LSNs and the replication slot remain provider evidence, not platform authority.

## Verification

- The real source is PostgreSQL 16.14 with `wal_level=logical`, `REPLICA IDENTITY FULL`, a dedicated
  publication and `pgoutput` slot; Flink is 1.19.3 with the verified PostgreSQL CDC connector 3.3.0.
- Ten accepted and two rejected changelog rows are committed. The quarantine reason distribution is
  exactly `{"invalid_geometry_sha256": 2}`.
- Attempt 0 fails after completed checkpoint `27` at processed count 5. Attempt 1 restores count 3;
  checkpoints `32` and `33` each observe all 12 processed changes after a bounded source-network
  partition.
- All 12 provider checks and 13 top-level checks pass. Same-ID and cross-Run replay preserve the
  original governance and quarantine evidence, with only one provider invocation and checkpoint
  state `0 -> 1`.
- Focused CDC, SourceSync, quarantine-recorder and platform-contract tests pass 49/49; Ruff, Python
  compilation and whitespace checks pass.
- Report: `.tmp/source-sync-certification/chongqing-osm-postgres-cdc-report.json`, SHA-256
  `216f318c9e3cf29c75bf3342cd4c013c66c2aa582d45ee47d364ce80230731f8`.
- The random control database, isolated PostgreSQL and Flink containers, checkpoint/savepoint/output
  directory and compilation directory are removed. Persistent SourceSync tables remain empty.

## Trade-offs and Consequences

- PostgreSQL CDC is now the third provider class using the common quarantine recorder and the second
  provider with real nonzero rejected records.
- A quarantined delete for a row that was never admitted remains in the rejection audit; it does not
  create a Silver tombstone. This preserves complete source-change accountability.
- Flink gives exactly-once commit behavior within its two FileSinks, not a distributed transaction
  with PostgreSQL or the SourceSync control database. Provider files may exist before authority
  admission, but the platform checkpoint cannot advance without both immutable receipts.
- The validated rule is intentionally narrow. ADR-166 adds one bounded network partition, but the
  proof does not cover active CDC schema evolution, repeated or long partitions, slot invalidation,
  WAL capacity, production throughput/freshness SLO, multi-cluster HA, Kubernetes or a
  Flink-to-Iceberg CDC sink.
- The short-lived local Docker and disposable PostgreSQL evidence is not a persistent development,
  staging, production or cloud rollout.

## Revisit Triggers

- rejected records must be retained under object lock, legal hold or independent access policy;
- schema changes introduce versioned validation rules that cannot be evaluated from one decoded row;
- production slot/WAL SLO requires Kafka or another durable event boundary between source and Flink;
- a transactional Iceberg sink replaces the bounded filesystem evidence adapter.
