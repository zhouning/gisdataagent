# ADR-171: Sustained High-Frequency CDC Network Flapping

**Status**: Accepted

**Date**: 2026-08-05

**Related**: ADR-106, ADR-165, ADR-166, ADR-168, ADR-169, ADR-170

**Extended by**: ADR-172, ADR-173

## Context

ADR-169 proved three rapid disconnect/reconnect cycles and ADR-170 proved one 20-second outage with
a combined sink-and-slot recovery budget. Neither exercised a longer train of repeated physical
network transitions. The remaining risk was that reconnect state, replication feedback or
checkpoint visibility would diverge after many short cycles even though one long outage recovers.

At a 0.1-second interval, sampling `confirmed_flush_lsn` before invoking Docker network disconnect is
racy. Replication feedback already in the TCP path can reach PostgreSQL between that sample and the
moment physical detachment completes. The authoritative stalled cursor is therefore the slot sample
taken after Docker confirms detachment, not the earlier pre-command observation.

Exact business-mutation recovery and total current-WAL catch-up are also different. PostgreSQL may
generate unrelated WAL after the projected transaction, while this Debezium configuration has no
heartbeat action query that creates source transactions. The platform must require the exact target
LSN and separately bound residual WAL; it must not fabricate a failed business recovery merely
because idle internal WAL remains after the target.

## Options Considered

| Option | Benefit | Cost and risk | Decision |
|---|---|---|---|
| Add Kafka before testing repeated reconnects | Durable buffer and independent retry boundary | Adds a service and second offset authority before proving current limits | Deferred |
| Compare only pre-command and end-of-cycle slot LSN | Small report | Misclassifies feedback delivered before physical detachment | Rejected |
| Use post-detachment LSN plus exact target and bounded residual WAL | Separates physical stall, business recovery and capacity risk | Requires more samples and explicit budgets | Adopted |

## Decision

After ADR-170's long outage has fully recovered, keep the same PostgreSQL source, Flink job,
publication, `pgoutput` slot and SourceSync Run. Update the projected road revision from 5 to 6 in
the first disconnected cycle, then execute 20 physical Docker disconnect/reconnect cycles with a
configured 0.1-second interval.

For every cycle record accepted/quarantined output, Flink job state, slot identity, confirmed LSN and
WAL lag at pre-command, confirmed-disconnected and end-of-disconnected-period boundaries. Admission
requires:

- all 20 disconnects and reconnects are physically confirmed in order;
- every end-of-disconnected-period LSN equals its post-detachment baseline;
- the Flink job remains `RUNNING` during every disconnected sample and after recovery;
- the first disconnected cycle keeps output at `16/2` and its mutation increases WAL lag;
- later sink visibility may advance while a cycle is disconnected only when its post-detachment slot
  LSN remains stalled, because already delivered records can finish a checkpoint;
- from the final reconnect, sink output and the exact target LSN recover within 60 seconds;
- residual slot WAL lag is at most 1 MiB, and final output is exactly `18/2`;
- drain leaves the same slot inactive.

Bind the full cycle list, sub-gate results, recovery duration and WAL budget into
`SourceSyncCommit.target_commit_ref`. Do not add another slot, broker, service or scheduler.

## Verification

- Twenty physical cycles with a configured 0.1-second interval complete in 16.007 seconds. Docker
  command and observation overhead means this is not a claim of 10 complete cycles per second.
- In cycle 1, output remains `16/2`; pre-command, confirmed-disconnected and end-of-disconnected-period
  LSN all remain `0/1998AB8`. WAL lag grows from 56 to 416 bytes after detachment and mutation.
- By cycle 3 output is `18/2` while its post-detachment and disconnected-period slot LSN remains
  `0/1998AF0`. All 20 cycles keep those two physical-outage samples equal, and every job-state
  observation is `RUNNING`. A rejected development run had already shown that pre-command feedback
  can differ from the post-detachment baseline; only the latter participates in the accepted gate.
- From the final reconnect, combined sink and slot recovery takes 0.107 seconds against the 60-second
  budget. Confirmed LSN reaches `0/1998C90`, beyond the exact projected target `0/1998C58`; residual
  WAL lag is 0 bytes against the 1 MiB safety budget.
- The complete changelog contains 18 unique accepted and 2 unique quarantined records. Final-state
  SHA-256 is `b93fe1b834d68bb016e03b574d6dc00df91f6a6e3b28ade445a573c5d5a3bdc7`.
- Flink fails intentionally at checkpoint 26/count 5, restores attempt 1 from count 3, and checkpoints
  165 through 214 observe all 20 accepted-plus-quarantined records.
- All 20 provider checks, 4 schema-governance checks and 18 top-level checks pass. SourceSync advances
  `0 -> 1` once; provider write count remains one and replay preserves the admitted evidence.
- Report: `.tmp/source-sync-certification/chongqing-osm-postgres-cdc-report.json`, SHA-256
  `abd4a89b66cff55a866eeab3187de4e989d69e7127565a0c31936c0ff6b4bb26`.
- The random control database, PostgreSQL/Flink containers and work directory are removed; persistent
  SourceSync tables remain empty.

## Trade-offs and Consequences

- The default profile now has a real 20-cycle local reconnect train in addition to short partitions
  and one 20-second outage.
- Pre-command observation remains useful for feedback timing, but only the post-detachment sample is
  used to prove a physically disconnected LSN stall.
- Exact mutation LSN and residual WAL capacity are independent gates. The 1 MiB local safety budget
  is evidence configuration, not a production retention or disk-capacity claim.
- ADR-172 separately proves fail-closed admission after physical slot absence and same-name
  recreation. ADR-173 proves bounded `max_slot_wal_keep_size` loss with a preserved filesystem safety
  floor. None certifies automatic slot repair/resume, reconnect-backoff exhaustion, physical disk
  exhaustion, PostgreSQL failover, production RPO/RTO, multi-cluster HA or Kubernetes recovery.

## Revisit Triggers

- measured production flap rate or duration exceeds this local envelope;
- connector retry/backoff reaches a terminal state;
- residual WAL approaches the configured source retention or disk budget;
- source failover changes publication or slot ownership;
- production RPO/RTO justifies a durable event boundary or externalized state backend.
