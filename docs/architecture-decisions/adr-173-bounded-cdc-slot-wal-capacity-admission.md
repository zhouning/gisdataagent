# ADR-173: Bounded CDC Slot WAL Capacity Admission

**Status**: Accepted

**Date**: 2026-08-05

**Related**: ADR-106, ADR-165, ADR-166, ADR-168, ADR-169, ADR-170, ADR-171, ADR-172

**Extended by**: ADR-174

## Context

ADR-171 separates exact target-LSN recovery from a small residual-WAL lag budget. ADR-172 proves
that physical slot absence and same-name recreation fail closed. A third failure mode remains: the
same slot can stay present while PostgreSQL removes WAL needed by that slot after
`max_slot_wal_keep_size` is exceeded at checkpoint. Slot name, `active` state and a nominally
`RUNNING` Flink job are insufficient in this state.

PostgreSQL exposes the capacity boundary through `wal_status`, `safe_wal_size` and `restart_lsn`.
`reserved` means required files remain retained within the configured limit. `extended` is already
outside the normal reserved boundary; `unreserved` can lose files at the next checkpoint; `lost`
means required WAL has been removed and the slot is unusable. A production admission gate must act
before governed target advancement and must also fail closed when these observations are missing.

Actual disk exhaustion is unsafe and unnecessary for this certification. The test needs bounded WAL
generation, physical `pg_wal` and filesystem measurements, a hard pressure ceiling and a free-space
safety floor.

## Options Considered

| Option | Benefit | Cost and risk | Decision |
|---|---|---|---|
| Leave slot WAL retention unlimited | Avoids configured slot loss | An unavailable consumer can fill the source disk without a bounded platform policy | Rejected |
| Add Kafka or automatically resnapshot on loss | May provide a new recovery boundary | Adds another cursor/write path before production RPO/RTO and reconciliation semantics are proven | Deferred |
| Bind finite capacity policy and reject unsafe slot states | Keeps one SourceSync cursor authority and makes loss observable | Requires operator reconciliation and a new Run after rejection | Adopted |

## Decision

Bind a versioned `slot_wal_capacity_policy` into the SourceSyncDefinition configuration. It contains:

- finite `max_slot_wal_keep_size_bytes`;
- `minimum_safe_wal_bytes` for admission before loss;
- `filesystem_safety_floor_bytes` for bounded diagnostics;
- `on_unsafe_or_lost = reject_fail_closed`.

For a finite-capacity profile, provider admission requires the same continuously present slot to
have `wal_status=reserved`, a non-empty `restart_lsn` and integer `safe_wal_size` greater than or
equal to the policy margin. `extended`, `unreserved`, `lost`, a missing slot, missing policy or
incomplete observations all reject fail closed. This gate is independent from slot-incarnation
continuity in ADR-172; both must pass before a successful provider commit.

The isolated negative certification commits the three-row initial checkpoint, physically
disconnects PostgreSQL, terminates the exact active replication backend and keeps the original slot
inactive. It then emits deterministic transactional logical WAL in bounded batches, switches WAL
and forces a checkpoint after every batch. Each cycle records payload size, start/emitted/checkpoint
LSNs, observed WAL distance, slot status, `safe_wal_size`, `restart_lsn`, `pg_wal` bytes and source
filesystem capacity. Pressure stops immediately when the slot reaches `lost` or the configured cycle
ceiling is reached.

The controller evaluates capacity before source reconnection, rejects the Run, cancels Flink and
reconnects only for final observation. Physical FileSink output must not grow after the fault;
SourceSync checkpoint and provider-success ledgers must remain at their initial state.

## Verification

- PostgreSQL 16 uses `max_slot_wal_keep_size=1MB` and 16 MiB WAL segments. The capacity policy is
  fingerprint-bound to the SourceSyncDefinition with a 64 KiB minimum slot margin and 512 MiB source
  filesystem safety floor. The configured run caps payload at 32 MiB and the segment-aware physical
  WAL budget at 160 MiB.
- Before pressure, the same inactive slot is `reserved`, has restart LSN `0/19520D0` and
  `safe_wal_size=7,003,648`. `pg_wal` occupies 16,785,408 bytes and the measured data path has
  1,344,166,965,248 bytes available.
- One bounded cycle requests 16 messages of 524,288 bytes, or 8,388,608 payload bytes. WAL advances
  23,781,080 bytes from `0/1952200` through emitted LSN `0/21586D8` to checkpoint LSN `0/30000D8`.
- After that checkpoint, the continuously present same-name slot is `lost`; `restart_lsn` is empty
  and `safe_wal_size` is null. `pg_wal` is 50,339,840 bytes and the data path still has
  1,344,133,394,432 bytes available, far above the 512 MiB safety floor.
- Admission is `rejected_fail_closed` with `replication_slot_wal_status_lost`,
  `replication_slot_restart_lsn_missing` and `replication_slot_safe_wal_size_exhausted`. Flink is
  `RUNNING` at decision time and then becomes `CANCELED` by controller action; connector exception
  and backoff exhaustion remain separate, unclaimed evidence.
- Physical sink counts remain exactly `3/0`. SourceSync checkpoint remains version 0 with no commit;
  Artifact, QualityResult, LineageEvent, target ResourceVersion and successful provider-admission
  counts are all zero. PlatformRun terminates `failed`.
- All 11 provider gates and 10 top-level gates pass. Random PostgreSQL/Flink containers, control
  database and work directory are removed; persistent SourceSync tables remain empty.
- Report: `.tmp/source-sync-certification/chongqing-osm-postgres-cdc-wal-capacity-report.json`,
  SHA-256 `412aacd1a90c1c165332510649d28c32a4128268f0c7a0aef13e6fddf769c919`.

## Trade-offs and Consequences

- The platform now distinguishes recoverable WAL lag, slot-incarnation loss and same-incarnation WAL
  loss. Each has a separate evidence contract and admission outcome.
- A finite-capacity profile rejects `extended` before PostgreSQL reaches `lost`. This favors data
  integrity over availability and requires an operator to reconcile the source boundary.
- The local 1 MiB limit deliberately creates loss within one bounded cycle. It is evidence
  configuration, not a recommended production retention value.
- The test measures physical storage and enforces headroom but does not fill the filesystem. It does
  not certify disk-exhaustion recovery, automatic slot repair/resnapshot, connector retry exhaustion,
  production WAL rate, RPO/RTO, throughput, freshness or high availability. ADR-174 separately
  certifies PostgreSQL 16 physical promotion with fail-closed missing-slot admission, not automatic
  CDC resume.
- No broker, second slot, service or scheduler is added. SourceSyncCheckpoint remains the only
  platform cursor authority.

## Revisit Triggers

- measured production WAL rate and maximum outage define a retention budget;
- `safe_wal_size` approaches alert or rejection thresholds under real load;
- source disk growth requires predictive SLO/Incident automation;
- operator recovery needs an approved resnapshot or point-in-time reconciliation workflow;
- PostgreSQL failover changes system identifier, timeline, publication or slot ownership;
- production RPO/RTO or fan-out justifies an external durable event boundary.
