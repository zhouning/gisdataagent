# ADR-174: PostgreSQL CDC Physical Failover Timeline Admission

**Status**: Accepted

**Date**: 2026-08-05

**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2

**Related**: ADR-106, ADR-166, ADR-171, ADR-172, ADR-173

## Context

ADR-172 proves that slot absence and same-name recreation are not continuity. ADR-173 proves that a
continuously present slot can still lose required WAL. Both operate on one PostgreSQL primary. A
physical failover has a different boundary: the promoted server may preserve the database cluster,
tables, publication and exact source mutation while starting a new WAL timeline without the logical
replication slot used by Flink.

PostgreSQL `system_identifier` identifies the physical cluster, not a logical slot incarnation.
Likewise, a reachable table and publication prove data-plane availability but not the decoder cursor
needed for CDC. Admitting only from those signals could make a physically valid failover look like a
logically continuous stream and silently skip WAL.

This is a negative certification for PostgreSQL 16. A passed report means the platform rejects the
missing slot before governed advancement. It does not mean Flink automatically resumes, that a
logical slot is synchronized to the standby, or that production high availability is complete.

## Options Considered

| Option | Benefit | Cost and risk | Decision |
|---|---|---|---|
| Admit when the cluster identifier and table match | Fast cutover | Ignores WAL timeline and logical decoder cursor; can skip changes | Rejected |
| Recreate the same slot name automatically after promotion | Simple apparent recovery | Creates a new cursor boundary and can lose changes between the old and new consistent LSN | Rejected |
| Add Kafka or another durable event boundary | Can decouple source failover from consumers | Adds a second cursor/write path before RPO/RTO and reconciliation semantics are proven | Deferred |
| Require cluster, timeline, replay and slot-continuity evidence | Preserves one SourceSync cursor authority and fails closed on ambiguity | Requires operator recovery or a separately certified failover-slot mechanism | Adopted |

## Decision

Bind `gda.postgres_cdc_failover_admission_policy.v1` into the SourceSyncDefinition. Admission
requires all of the following before a successful provider commit:

- primary, standby and promoted source have the same PostgreSQL `system_identifier`;
- the standby is observed in recovery and replays the exact mutation target LSN and row before
  promotion;
- the old primary is stopped before promotion;
- the promoted source is not in recovery and its timeline increments exactly once;
- the publication and replayed row are present after promotion;
- the original logical slot remains present with the same database, name, plugin, type and cluster
  identity.

Missing or inconsistent observations reject fail closed. Timeline identity, source replay and slot
continuity are independent gates: a valid physical promotion does not compensate for a missing
logical slot. `SourceSyncCheckpoint` remains the only governed cursor authority.

The isolated certification uses PostgreSQL 16.14 primary and a real asynchronous physical standby
built with `pg_basebackup -R -X stream`. Its temporary HBA rule allows only the `replication`
database, the isolated replication role, Docker `samenet` and SCRAM authentication. Flink connects
through a stable source alias. The alias moves to the promoted server only after the old primary is
stopped and detached.

After the initial three-row snapshot, one projected update is committed, replayed on the standby and
checkpointed into the physical FileSink. The primary is then stopped and the standby promoted. The
controller evaluates continuity before a post-promotion probe, rejects because the slot is absent,
and later cancels Flink. A second source update on the promoted server must advance PostgreSQL but
must not advance either accepted or quarantine FileSink output.

## Verification

- PostgreSQL 16.14 uses `system_identifier=7670536130765070376`. Primary and recovering standby are
  on timeline 1; after promotion and checkpoint, the source is out of recovery on timeline 2.
- `pg_stat_replication` observes the standby as asynchronous `streaming`. The projected revision-2
  mutation commits at `0/3000390`; standby receive and replay LSN both reach exactly `0/3000390`, and
  the complete four-field row matches before primary shutdown.
- The pre-failover Flink FileSink contains `5/0` accepted/quarantine records and completed checkpoint
  count 5. The original `pgoutput` slot is active on the primary.
- After promotion, the same table row and publication are present, but PostgreSQL 16 reports the
  original logical slot absent. Admission is `rejected_fail_closed` with the sole reason
  `logical_replication_slot_missing_after_promotion`.
- The stable source alias is attached to the promoted server only after the stopped primary is
  detached, and Docker network metadata confirms that exact alias. A revision-3 probe advances the
  promoted source to `0/3000920`; over the following 2.0-second observation, FileSink counts remain
  exactly `5/0`, with zero accepted and quarantine delta.
- Flink is still `RUNNING` when the controller decision is observed and becomes `CANCELED` by
  controller action. Connector exception and retry exhaustion are separate, unclaimed evidence.
- SourceSync checkpoint remains version 0 with no commit. Artifact, QualityResult, LineageEvent,
  target ResourceVersion and successful provider-admission counts are all zero; PlatformRun ends
  `failed`.
- All 12 provider gates and 9 top-level gates pass. The primary, standby, Flink, random control
  database, named standby volume and work directory are removed; persistent SourceSync tables remain
  empty.
- Report: `.tmp/source-sync-certification/chongqing-osm-postgres-cdc-failover-report.json`, SHA-256
  `f28ac7763c3f7e24c48f36adc965b3e271ec0accf359e5d548125fae8847f223`.

## Trade-offs and Consequences

- The platform now distinguishes physical-cluster continuity from logical-decoder continuity. A
  fully replayed, writable promoted database can still be rejected as an unsafe CDC continuation.
- Failing closed favors data integrity over availability. Recovery needs an approved resnapshot,
  point-in-time reconciliation or a separately certified slot synchronization mechanism and a new
  Run.
- PostgreSQL 16 behavior is not evidence for PostgreSQL 17+ failover slots. Any native failover-slot
  adoption requires version-specific synchronization, promotion, lag, loss and replay certification.
- The test proves ordered stop/promotion, exact replay and zero post-failover sink growth. It does not
  measure production RPO/RTO, automatic reconnect/backoff exhaustion, fencing under split brain,
  multi-cluster HA, Kubernetes recovery or CDC-to-Iceberg exactly-once behavior.
- No broker, second slot, service or scheduler is added. The temporary physical standby and SCRAM
  credential exist only inside the isolated certification and are destroyed during cleanup.

## Revisit Triggers

- production PostgreSQL adopts native failover slots or another synchronized logical-slot mechanism;
- recovery policy defines an approved resnapshot or point-in-time cursor reconciliation workflow;
- measured failover RPO/RTO and workload fan-out justify an external durable event boundary;
- DNS/service discovery, fencing, split-brain prevention or multi-zone promotion enter scope;
- the CDC target changes from the provisional FileSink to direct Iceberg streaming commits.
