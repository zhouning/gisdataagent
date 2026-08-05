# ADR-166: Bounded CDC Network Partition and Slot Recovery

**Status**: Accepted

**Date**: 2026-08-05

**Related**: ADR-104, ADR-106, ADR-160, ADR-161, ADR-163, ADR-164, ADR-165

**Extended by**: ADR-167, ADR-168, ADR-169, ADR-170, ADR-171

## Context

ADR-165 proved checkpoint-consistent Silver and quarantine outputs for PostgreSQL CDC, but the
source remained continuously reachable. It did not prove whether a network interruption would lose
the replication slot, partially commit one sink, duplicate rejected rows or incorrectly advance the
platform checkpoint.

Adding Kafka or another durable event boundary before measuring the existing connector would expand
the default runtime and create another offset authority. Creating a new replication slot after every
disconnect would avoid reconnection work but could replay an initial snapshot and violate the frozen
source-slice identity.

## Options Considered

| Option | Benefit | Cost and risk | Decision |
|---|---|---|---|
| Add Kafka between PostgreSQL and Flink | Long-lived buffering and independent consumers | New cluster, offset authority and operational surface without a measured SLO need | Deferred |
| Recreate the slot and restart from a new snapshot | Simple recovery procedure | Can duplicate history and lose exact cursor continuity | Rejected |
| Retain the same slot and let the certified connector catch up | Preserves WAL ordering and current authority model | Bounded by PostgreSQL WAL retention and connector recovery behavior | Adopted |

## Decision

Extend the existing isolated PostgreSQL/Flink certification with a real Docker network partition.
After the three-row initial snapshot is checkpoint-committed, detach the PostgreSQL source container
from the Flink network. While detached, apply the complete source mutation set that produces ten
valid and two invalid changelog rows.

During the partition the certifier must prove:

- the source container is physically absent from the configured Docker network;
- committed Silver output remains exactly three rows and quarantine remains empty;
- the same `pgoutput` slot still exists;
- `confirmed_flush_lsn` does not advance while the consumer is disconnected;
- current WAL lag grows after the source transaction commits.

Reconnect the same source container without changing slot, publication, SourceSync definition or
Run. The provider must then checkpoint all 12 changes, preserve the exact 10/2 Silver/quarantine
split, advance the same slot's confirmed LSN and reduce WAL lag. The drain savepoint must leave the
slot inactive before evidence admission.

Network, slot and WAL observations are embedded in `SourceSyncCommit.target_commit_ref`, not stored
only in an external report. The SourceSync checkpoint remains at version 0 until accepted output,
quarantine output, quality, lineage, metadata outbox and both cross-ledger receipts are complete.

## Verification

- The PostgreSQL source is detached for 3.33 seconds. Silver stays at 3 committed records and
  quarantine at 0 while all source mutations are already present in WAL.
- The same slot `gda_slot_5f6b8623d8` is observed before, during and after the partition. Its
  `confirmed_flush_lsn` stays at `0/1952108` during disconnection, then advances to `0/19526D8`.
- Measured WAL lag grows from 248 bytes to 1,648 bytes during the partition and falls to 216 bytes
  after catch-up.
- The intentional checkpoint failure still occurs at checkpoint `27`, processed count 5. Attempt 1
  restores count 3, and checkpoints `32` and `33` observe all 12 changes.
- All 12 provider checks and 13 top-level checks pass. SourceSync advances `0 -> 1` once; same-ID and
  cross-Run replay preserve the original governance and quarantine evidence.
- Focused CDC, SourceSync, quarantine-recorder and platform-contract tests pass 49/49; Ruff, Python
  compilation and whitespace checks pass.
- Report: `.tmp/source-sync-certification/chongqing-osm-postgres-cdc-report.json`, SHA-256
  `216f318c9e3cf29c75bf3342cd4c013c66c2aa582d45ee47d364ce80230731f8`.
- The random control database, isolated PostgreSQL and Flink containers, network attachment,
  checkpoint/savepoint/output directory and compilation directory are removed. Persistent
  SourceSync tables remain empty.

## Trade-offs and Consequences

- The default profile now has real evidence for a bounded single PostgreSQL-to-Flink network
  interruption without introducing a broker or second checkpoint authority.
- No accepted or rejected sink files become visible during the partition; catch-up preserves the
  original provider and platform replay contracts.
- This is one 3.33-second partition with a small WAL backlog. It does not establish maximum outage,
  WAL disk capacity, `max_slot_wal_keep_size`, repeated flap behavior, slot invalidation, source
  failover, production RPO/RTO, throughput/freshness SLO, multi-cluster HA or Kubernetes recovery.
- The disposable local Docker evidence is not a persistent development, staging, production or
  cloud rollout.

ADR-167 reruns this same-slot partition boundary and adds active additive and breaking schema changes.
ADR-168 then runs two partitions in one job, accumulates additive DDL/DML during the second outage and
requires exact per-phase target-LSN recovery. Those extensions do not alter this ADR's original
historical measurements.

ADR-169 further applies one projected update and three rapid disconnect/reconnect cycles before exact
target-LSN recovery. It distinguishes source-slot progress from checkpoint visibility for records
already delivered into Flink.

ADR-170 adds one 20-second outage that exceeds the Flink checkpoint timeout and enforces a 60-second
combined sink-and-slot recovery budget. It does not change this ADR's historical measurements.

ADR-171 adds 20 physical disconnect/reconnect cycles with post-detachment LSN sampling, an exact
target-LSN gate and a separate residual-WAL budget. It does not change this ADR's historical
measurements.

## Revisit Triggers

- measured outage or WAL volume approaches the source's slot retention capacity;
- repeated network flaps cause job-level restarts or exceed the connector retry policy;
- production RPO/RTO requires source failover, external checkpoint storage or a durable event bus;
- selected-column evolution, concurrent DDL or repeated schema changes must be reconciled while the
  slot is accumulating WAL.
