# ADR-172: CDC Slot Incarnation Fail-Closed Admission

**Status**: Accepted

**Date**: 2026-08-05

**Related**: ADR-106, ADR-165, ADR-166, ADR-168, ADR-169, ADR-170, ADR-171

**Extended by**: ADR-173, ADR-174

## Context

ADRs 166 through 171 prove that one continuously existing PostgreSQL replication slot can retain
WAL and recover after bounded partitions, a 20-second outage and sustained physical network
flapping. They do not cover slot teardown. A PostgreSQL slot name is not a durable instance identity:
after the original slot is dropped, a new slot may be created with the same name, plugin and
database while starting from a different consistent LSN. Treating that name as continuity can skip
WAL generated while no slot retained it.

Docker network detachment and PostgreSQL backend termination are also separate events. A physical
disconnect removes network reachability, but an established replication backend can remain marked
`active` during the TCP timeout window. The platform must not infer that the slot is inactive merely
from the container network state, and PostgreSQL correctly refuses to drop an active slot.

This is a negative certification. A passed report means the expected business outcome was rejected
fail closed; it does not mean the invalidated stream resumed successfully.

## Options Considered

| Option | Benefit | Cost and risk | Decision |
|---|---|---|---|
| Automatically accept any slot with the configured name | Fast apparent recovery | Can silently admit a different WAL history and fabricate continuity | Rejected |
| Automatically repair the slot or add Kafka | May create a durable recovery boundary | Adds a write path or second cursor authority before RPO/RTO requirements and recovery semantics are frozen | Deferred |
| Bind slot incarnation, prove absence and reject before governed advancement | Preserves one SourceSync cursor authority and prevents silent data loss | Requires explicit operator recovery and a new certified Run | Adopted |

## Decision

Represent a replication slot incarnation with PostgreSQL system identifier, database identity, slot
name, plugin, slot type, a creation LSN anchor, an ordered incarnation number and the event that
established it. Canonically hash those fields. Slot name remains a locator, not identity.

Admission requires a continuously observed current incarnation with the same fingerprint. Missing
or incomplete continuity evidence fails closed. A physically witnessed absence always rejects the
Run, even if a slot later reappears with the same name. The rejection reason and both fingerprints
are written to the failed `PlatformRun`; no SourceSync commit or provider-success evidence is
created.

The isolated negative certification uses this ordered event chain:

1. Commit the three-row initial Flink snapshot and observe the original slot active.
2. Physically disconnect the PostgreSQL source container.
3. Terminate only the observed slot backend, then prove the original slot inactive.
4. Drop the slot and query `pg_replication_slots` to prove absence.
5. Commit one projected source mutation while no slot exists.
6. Recreate a `pgoutput` slot with the same name and bind it as incarnation 2.
7. Reject provider admission before runtime termination, cancel Flink, then reconnect only for a
   final inactive-slot and sink-stability observation.

The physical FileSink is provisional provider state. It may contain the three pre-fault snapshot
records, but it must not advance after invalidation. Only an admitted SourceSync commit can advance
the governed target checkpoint.

## Verification

- PostgreSQL returns the original creation anchor `0/19520D0`. After physical disconnect and
  targeted backend termination, the slot is inactive and is dropped at `0/1952200`; the following
  catalog observation proves it absent.
- The projected mutation commits at `0/1952340` while no slot exists. Same-name recreation returns
  consistent LSN `0/1952378`, establishing incarnation 2 after the mutation.
- Original and recreated fingerprints are respectively
  `a8956f5035fafb592bd8f5e2768b54895f5585f3fdf74b55b05784d8bff16b35` and
  `7b0d16866d49dac2c28f9c520ab7e1697a7723a903e176f9f749de06e93de4d5`.
- Admission is `rejected_fail_closed` with
  `replication_slot_absence_witnessed` and `replication_slot_incarnation_changed`. The Flink job is
  `RUNNING` when the decision is made, then reaches `CANCELED` by controller action. Connector
  exception evidence is recorded separately and is empty; connector retry exhaustion is not
  claimed.
- Physical sink counts remain exactly `3/0` before and after the fault. SourceSync checkpoint remains
  version 0 with no last commit or target reference, and commit history remains empty.
- Artifact, QualityResult, LineageEvent and target ResourceVersion counts for the Run are all zero.
  The PlatformRun terminates `failed`; successful provider admission count is zero.
- All 9 provider gates and 9 top-level gates pass. The random control database, PostgreSQL/Flink
  containers and work directory are removed; persistent SourceSync tables remain empty.
- Report:
  `.tmp/source-sync-certification/chongqing-osm-postgres-cdc-slot-invalidation-report.json`, SHA-256
  `057c83ed556975a57a241a4a7ff19749cc9c049275931eced3fa4ab27d6025e6`.

## Trade-offs and Consequences

- Same-name slot recreation can no longer be mistaken for recovery. Recovery requires an explicit
  operator decision, source reconciliation and a new certified Run from an approved cursor or
  snapshot boundary.
- The controller cancels before source reconnection, prioritizing zero post-fault sink advancement.
  This intentionally does not measure connector terminal failure or backoff exhaustion.
- PostgreSQL boolean evidence now accepts both wire-style `t/f` and explicit-cast `true/false`,
  preventing an active slot with an `active_pid` from being reported inactive.
- No broker, second slot, service or scheduler is added. The existing SourceSync checkpoint remains
  the only platform cursor authority.
- ADR-173 separately certifies bounded same-incarnation WAL loss under
  `max_slot_wal_keep_size`. ADR-174 separately certifies a real PostgreSQL 16 physical promotion and
  fail-closed admission when the promoted source lacks the original logical slot. None certifies
  automatic slot repair/synchronization, physical disk exhaustion, production RPO/RTO, throughput,
  freshness or high availability.

## Revisit Triggers

- production policy requires automated resnapshot or point-in-time slot recovery;
- connector retry/backoff must be measured independently without controller cancellation;
- WAL generation approaches configured retention or disk capacity;
- PostgreSQL failover changes system identifier, timeline, publication or slot ownership;
- measured RPO/RTO or fan-out justifies an external durable event boundary.
