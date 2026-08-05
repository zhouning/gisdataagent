# ADR-168: Repeated CDC Partition and Schema WAL Recovery

**Status**: Accepted

**Date**: 2026-08-05

**Related**: ADR-106, ADR-165, ADR-166, ADR-167

**Extended by**: ADR-169, ADR-170, ADR-171

## Context

ADR-166 proved recovery from one bounded PostgreSQL-to-Flink network partition. ADR-167 then proved
active additive schema continuity and fail-closed breaking-schema promotion, but both DDL operations
were applied after the first network recovery. The evidence did not establish that the same slot and
running projection could survive a second outage with schema DDL and DML already accumulating in
WAL.

The earlier certifier also sampled the first partition's recovered slot only after later schema work.
That made the final LSN valid for the whole Run but did not independently prove that each partition
had reached its own mutation boundary before the next phase began.

## Options Considered

| Option | Benefit | Cost and risk | Decision |
|---|---|---|---|
| Restart with a new slot after each outage | Simple phase isolation | Re-snapshot and duplicate/loss risk; abandons cursor continuity | Rejected |
| Keep one end-of-Run slot sample | Smallest report | Conflates recovery phases and can overstate catch-up | Rejected |
| Reuse one slot and gate every phase on its target LSN | Exact phase evidence without a new service | Adds bounded waiting and more provider evidence | Adopted |

## Decision

Run two physical Docker network partitions in the same PostgreSQL/Flink job, SourceSync Run,
publication and `pgoutput` slot:

1. `base_mutations`: disconnect after the three-row initial snapshot, apply the existing valid and
   invalid mutation set, and require Silver/quarantine to remain `3/0` during the outage.
2. `additive_schema_evolution`: after the first phase is fully recovered, disconnect again, add the
   nullable `observed_at TIMESTAMPTZ` column, discover its additive drift, and apply the projected
   revision update. Silver/quarantine must remain `10/2` during this outage.

Each phase records sink counts, slot identity, confirmed LSN and WAL lag at `before`, `during` and
`after`. Reconnection alone is not recovery. Admission to the next phase requires:

- the same slot name throughout;
- unchanged confirmed LSN while disconnected;
- WAL lag growth during the partition;
- recovered confirmed LSN greater than or equal to that phase's final DML target LSN;
- recovered WAL lag below the phase peak;
- the exact post-recovery Silver/quarantine counts.

After the second recovery, apply the breaking nullability tightening and reuse ADR-167's drift ledger,
pending ApprovalCase and fail-closed successor decision. Drain to a savepoint and separately prove
that the final slot is inactive. Preserve the original singular `network_partition` field for report
compatibility and bind the complete ordered `network_partitions` list into
`SourceSyncCommit.target_commit_ref`.

Do not add Kafka, a schema registry, another slot, service or scheduler.

## Verification

- Phase `base_mutations` is disconnected for 3.355 seconds. Silver/quarantine stays `3/0`, then
  becomes `10/2`. Confirmed LSN stays `0/1952108` during the outage and reaches the exact target
  `0/1952778`; WAL lag moves `248 -> 1,648 -> 56` bytes.
- Phase `additive_schema_evolution` is disconnected for 3.522 seconds. Silver/quarantine stays
  `10/2`, then becomes `12/2`. Confirmed LSN stays `0/1952778` during the outage and reaches the exact
  target `0/19548E0`; WAL lag moves `56 -> 8,552 -> 0` bytes.
- Both phases use the same slot. The second phase recovery sample reaches confirmed LSN `0/19548E0`;
  ADR-169 later proves the final drain inactive on that slot after its additional target LSN.
- The additive drift still reconciles; the breaking successor remains `approval_required` with a
  pending, correctly bound ApprovalCase and reason `breaking_schema_drift_pending_approval`.
- Flink fails intentionally at checkpoint 28/count 5, restores attempt 1 from count 3, and checkpoints
  75 through 85 observe all 16 CDC changelog records after ADR-169's additional projected update.
- All 18 provider checks, 4 schema-governance checks and 16 top-level checks pass. SourceSync advances
  `0 -> 1` once and replay preserves the original dual evidence.
- Report: `.tmp/source-sync-certification/chongqing-osm-postgres-cdc-report.json`, SHA-256
  `f27bb9912626bfa594557df37d2007cab1037735d752feb9b266290ac2f840ea`.
- The random control database, PostgreSQL/Flink containers and work directory are removed; persistent
  SourceSync tables remain empty.

## Trade-offs and Consequences

- Repeated outage evidence now has exact per-phase cursor boundaries rather than one end-of-Run
  observation.
- Active additive DDL/DML is proven while the slot is accumulating WAL and without partial sink
  visibility.
- Waiting for exact target LSN makes the certification stricter and may expose connector offset-flush
  latency; that latency is evidence, not bypassed with a looser "LSN moved" check.
- This remains two short local partitions with a small source slice. ADR-169 separately extends it
  with three rapid cycles, ADR-170 adds one measured 20-second outage, and ADR-171 adds a 20-cycle
  local flap train. None certifies reconnect-backoff exhaustion, `max_slot_wal_keep_size`, disk
  exhaustion, slot invalidation, PostgreSQL
  failover, multi-cluster HA, production RPO/RTO or throughput/freshness SLO.

## Revisit Triggers

- measured outage duration or WAL generation approaches configured retention capacity;
- repeated flaps exceed connector retry or checkpoint timeout budgets;
- source failover changes slot/publication ownership;
- production SLO requires an external state backend or durable event bus.
