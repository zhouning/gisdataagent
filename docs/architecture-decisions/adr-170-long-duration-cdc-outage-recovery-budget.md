# ADR-170: Long-Duration CDC Outage and Recovery Budget

**Status**: Accepted

**Date**: 2026-08-05

**Related**: ADR-106, ADR-165, ADR-166, ADR-167, ADR-168, ADR-169

**Extended by**: ADR-171

## Context

ADR-169 proved three rapid PostgreSQL CDC disconnect/reconnect cycles while one projected update was
outstanding. Its disconnected intervals were only 0.5 seconds and the complete flap train lasted
about four seconds. It did not establish whether the same Flink job and replication slot remain
usable when the source is unavailable longer than the job's 15-second checkpoint timeout, or whether
sink visibility and slot catch-up satisfy an explicit recovery budget.

A connector that stays nominally `RUNNING` is insufficient evidence. Recovery must include the exact
accepted/quarantined output boundary and the source slot's exact mutation LSN. Increasing retry
timeouts without measuring that boundary would only hide an unbounded outage.

## Options Considered

| Option | Benefit | Cost and risk | Decision |
|---|---|---|---|
| Add Kafka before measuring the current path | Durable buffering and independent replay | Adds a cluster and second offset authority without a production RPO/RTO requirement | Deferred |
| Declare recovery when the Flink job is `RUNNING` | Smallest health check | Can admit stale sink output or an unadvanced slot | Rejected |
| Keep one job and slot, then enforce a sink-plus-slot recovery budget | Measures the current authority model end to end | Local duration and WAL volume do not establish production capacity | Adopted |

## Decision

After the two bounded partitions and rapid flap train have fully recovered, physically disconnect the
same PostgreSQL source container for at least 20 seconds. This exceeds the Flink job's configured
15-second checkpoint timeout. While disconnected, update the projected road revision from 4 to 5.

The outage phase records its objective, actual duration, accepted/quarantined counts, Flink job
state, slot identity, confirmed LSN and WAL lag. Admission requires:

- Silver/quarantine remains exactly `14/2` throughout the disconnected interval;
- the Flink job is `RUNNING` during the outage and immediately after physical reconnection;
- the same `pgoutput` slot exists and its confirmed LSN remains unchanged while disconnected;
- WAL lag grows after the projected mutation commits;
- from physical reconnection, Silver/quarantine reaches exactly `16/2` and the slot reaches the
  mutation's exact target LSN within a 60-second combined recovery budget;
- recovered WAL lag is below the disconnected sample and drain leaves the same slot inactive.

Bind the complete `long_duration_outage` record into `SourceSyncCommit.target_commit_ref`. Keep the
earlier bounded partitions and rapid flapping as separate ordered evidence. Represent each phase's
expected count as an explicit event-plan milestone so adding a later event cannot silently change an
earlier phase's wait target.

Do not add another slot, broker, service or scheduler until a measured production RPO/RTO or fan-out
requirement justifies it.

## Verification

- The physical outage lasts 20.259 seconds against a 20-second objective and the 15-second Flink
  checkpoint timeout. Silver/quarantine remains `14/2`; the job is `RUNNING` during and immediately
  after the outage.
- The same slot `gda_slot_737442c7bc` remains at confirmed LSN `0/1998950` while disconnected. WAL
  lag grows from 0 to 416 bytes.
- Combined sink and slot recovery completes in 5.157 seconds against the 60-second budget. Output
  reaches exactly `16/2`, confirmed LSN reaches the exact target `0/1998AB8`, WAL lag falls to 56
  bytes, and the final drained slot is inactive.
- The complete changelog contains 16 unique accepted and 2 unique quarantined records. The two-row
  final state SHA-256 is
  `037068d5c34f3caa47c588020b8824c6f088726579426896cd2c14c463d3c86c`.
- Flink still fails intentionally at checkpoint 28/count 5, restores attempt 1 from count 3, and
  checkpoints 209 through 216 observe all 18 accepted-plus-quarantined records.
- All 19 provider checks, 4 schema-governance checks and 17 top-level checks pass. SourceSync advances
  `0 -> 1` once; the provider writes once and replay preserves the admitted evidence.
- Report: `.tmp/source-sync-certification/chongqing-osm-postgres-cdc-report.json`, SHA-256
  `05511af8fd663757e09c2e308911e454d449ee2ea7b7fc4fa6776b0beaff29fe`.
- The random control database, PostgreSQL/Flink containers and work directory are removed; persistent
  SourceSync tables remain empty.

## Trade-offs and Consequences

- The default profile now has a measured local outage and recovery objective rather than an
  unbounded reconnect claim.
- Job liveness, checkpointed sink visibility and source cursor recovery are separate gates. A
  `RUNNING` job cannot admit stale results.
- The first development run failed closed before this outage because the rapid-flapping phase waited
  for the later final count. Explicit event-plan milestones now prevent that phase-contamination bug.
- This is one 20-second local outage with only 416 bytes of measured disconnected WAL growth.
  ADR-171 separately adds a 20-cycle local flap train, but neither establishes production RPO/RTO,
  throughput/freshness SLO, `max_slot_wal_keep_size`, disk exhaustion, slot invalidation,
  reconnect-backoff exhaustion, PostgreSQL failover,
  multi-cluster HA or Kubernetes recovery.

## Revisit Triggers

- production outage or recovery objectives exceed the certified local envelope;
- measured WAL generation approaches slot retention or disk capacity;
- sustained flapping exhausts connector retry/backoff policy;
- PostgreSQL failover changes publication or slot ownership;
- a production RPO/RTO or multi-consumer requirement justifies a durable event boundary.
