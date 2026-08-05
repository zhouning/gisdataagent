# ADR-169: Rapid CDC Network Flapping and Exact Slot Recovery

**Status**: Accepted

**Date**: 2026-08-05

**Related**: ADR-106, ADR-165, ADR-166, ADR-167, ADR-168

**Extended by**: ADR-170, ADR-171

## Context

ADR-168 proved two bounded PostgreSQL-to-Flink network partitions in one job, including additive
schema DDL/DML accumulated in WAL. Each phase was allowed to recover fully before the next outage.
It did not prove that the connector, one publication and one replication slot survive rapid repeated
disconnect/reconnect cycles while a projected mutation is outstanding.

Requiring every later disconnected interval to show an unchanged sink would also be incorrect.
Records already delivered into Flink before a disconnect may become visible when their checkpoint
completes even though the source slot cannot advance. Source cursor continuity and checkpointed sink
visibility must therefore be recorded separately.

## Options Considered

| Option | Benefit | Cost and risk | Decision |
|---|---|---|---|
| Add Kafka or another durable boundary | Buffers prolonged interruption and supports fan-out | Adds a cluster and second offset authority without measured SLO need | Deferred |
| Restart or recreate the slot after flapping | Simple reconnect procedure | Can re-snapshot, duplicate history or abandon exact cursor continuity | Rejected |
| Keep one slot and certify a bounded flap train | Exercises the current connector and authority model | Does not establish long-outage or retention capacity | Adopted |

## Decision

After ADR-168's additive-schema partition has recovered, update the projected road revision from 3
to 4 while the source is disconnected. Execute three physical Docker network disconnect/reconnect
cycles with a 0.5-second interval in the same PostgreSQL/Flink job and SourceSync Run.

For every cycle record accepted/rejected sink counts, network attachment, slot identity, confirmed
LSN and WAL lag before and during disconnection. Admission requires:

- all three disconnect and reconnect operations are physically observed;
- every sample and the final recovery use the same slot;
- the first disconnected interval keeps accepted/rejected output at `12/2`, keeps confirmed LSN
  unchanged and grows WAL lag;
- later sink visibility is allowed to advance only if the slot remains stalled, because already
  delivered records may checkpoint while the source is disconnected;
- final accepted/quarantine output is exactly `14/2`, with 16 unique total changelog records;
- final confirmed LSN is greater than or equal to the projected mutation's exact target LSN and WAL
  lag is below the observed flap-train peak;
- the job remains `RUNNING`, then drains to a savepoint and leaves the same slot inactive.

Bind the complete `rapid_network_flapping` evidence into
`SourceSyncCommit.target_commit_ref`. Keep the two ordered `network_partitions` from ADR-168 as
separate bounded-phase evidence. Do not add another slot, broker, service or scheduler.

## Verification

- Three cycles complete in 4.141 seconds with a configured 0.5-second interval. Every disconnect and
  reconnect is observed on slot `gda_slot_210042e6f6`.
- Cycle 1 keeps Silver/quarantine at `12/2`, confirmed LSN at `0/19548E0`, and increases WAL lag from
  0 to 360 bytes after the projected update is committed.
- Cycle 2 starts at `12/2` and observes `14/2` during disconnection while confirmed LSN remains
  `0/19548E0`. This is checkpoint visibility for records already delivered before that disconnect,
  not source cursor progress. Cycle 3 remains `14/2` with the same stalled LSN.
- Final recovery reaches the exact mutation target `0/1954A48`; WAL lag is 278,280 bytes versus the
  observed 278,640-byte peak. The later breaking DDL advances PostgreSQL to `0/1998B08` but is not
  treated as a projected DML catch-up target.
- Output contains 14 unique accepted and 2 unique quarantined changelog records. The final two-row
  source/Silver state has SHA-256
  `7a78fa535384c39253cd0397a0bc81a60b2d4115398f2628e038585d8f354015`.
- Flink fails intentionally at checkpoint 28/count 5, restores attempt 1 from count 3, and
  checkpoints 75 through 85 observe all 16 changelog records.
- All 18 provider checks, 4 schema-governance checks and 16 top-level checks pass. SourceSync advances
  `0 -> 1` once; replay preserves the original governance and quarantine evidence.
- Report: `.tmp/source-sync-certification/chongqing-osm-postgres-cdc-report.json`, SHA-256
  `f27bb9912626bfa594557df37d2007cab1037735d752feb9b266290ac2f840ea`.
- The random control database, PostgreSQL/Flink containers and work directory are removed; persistent
  SourceSync tables remain empty.

## Trade-offs and Consequences

- The default profile now has real evidence for bounded rapid connection flapping without a broker
  or second cursor authority.
- Provider admission distinguishes slot progress from checkpointed sink visibility, preventing a
  false failure when in-flight records commit during a later disconnected interval.
- This is only three local cycles at 0.5-second intervals with one projected update. It does not
  certify long outage, sustained flapping, reconnect backoff exhaustion, `max_slot_wal_keep_size`,
  disk exhaustion, slot invalidation, PostgreSQL failover, production RPO/RTO, throughput/freshness
  SLO, multi-cluster HA or Kubernetes recovery.

## Revisit Triggers

- measured flap frequency exceeds connector retry or checkpoint timeout budgets;
- outage duration or WAL generation approaches configured retention capacity;
- source failover changes slot/publication ownership;
- production SLO requires external checkpoint storage or a durable event bus.
