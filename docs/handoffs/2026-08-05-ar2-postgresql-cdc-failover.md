# AR-2 PostgreSQL CDC Failover Handoff

**Date**: 2026-08-05

**Branch**: `feat/natural-resource-ontology-okf-v2`

**Roadmap state**: AR-2 `in_progress`

## Authoritative State

- The detailed completion ledger and current phase table are in `docs/roadmap.md`.
- AR-0, AR-1 and AR-2 remain `in_progress`. AR-3 through AR-9 remain `planned`; completed
  component certifications inside those phases do not change their exit-gate state.
- ADR-106 is the PostgreSQL CDC certification boundary. ADRs 164 through 174 extend its recovery,
  quarantine, schema, slot-incarnation, WAL-capacity and physical-failover evidence.

## Completed In This Slice

- Added a real PostgreSQL 16 primary/physical-standby certification using `pg_basebackup -R -X
  stream`, asynchronous replay, exact primary stop and standby promotion.
- Bound SourceSync failover admission to the same PostgreSQL system identifier, exact mutation replay,
  a one-step timeline increment, publication continuity and logical-slot continuity.
- Proved the projected revision-2 mutation at LSN `0/3000390` reached the standby at the exact replay
  LSN before promotion.
- Proved promotion changed timeline `1 -> 2` while preserving the cluster identifier, publication and
  projected row, but PostgreSQL 16 did not contain the original `pgoutput` logical slot.
- Rejected provider admission with the sole reason
  `logical_replication_slot_missing_after_promotion` before governed advancement.
- Moved the stable source alias only after the old primary stopped and detached, and verified the
  alias from Docker network metadata.
- Advanced the promoted source with a revision-3 probe and observed zero FileSink growth for 2.0
  seconds. SourceSync checkpoint stayed at version 0; commit, Artifact, QualityResult, LineageEvent,
  target ResourceVersion and successful provider-admission counts stayed at zero.
- Added ADR-174 and updated ADR-106, ADR-172, ADR-173 and the AR-2 roadmap ledger without claiming
  automatic CDC resume or production HA.

## Evidence

- Report: `.tmp/source-sync-certification/chongqing-osm-postgres-cdc-failover-report.json`
- Report SHA-256: `f28ac7763c3f7e24c48f36adc965b3e271ec0accf359e5d548125fae8847f223`
- Provider gates: `12/12`
- Top-level gates: `9/9`
- Related regression: `67 passed`
- Ruff, Python compilation, structured report assertions and scoped `git diff --check` passed.
- No random CDC primary, standby or Flink container and no standby named volume remained.
- Full-worktree `git diff --check` still reports only the unrelated pre-existing blank line at EOF in
  `data_agent/migrations/131_platform_branding_settings.sql:33`.

## Do Not Claim

- automatic logical replication slot synchronization, repair or recreation;
- automatic Flink CDC resume after promotion;
- production failover RPO/RTO or freshness SLO;
- fencing or split-brain safety;
- multi-zone, multi-cluster or Kubernetes HA;
- direct CDC-to-Iceberg distributed exactly-once behavior.

## Next AR-2 Work

1. Select and certify a production slot-continuity mechanism: PostgreSQL-version-specific failover
   slots, an approved resnapshot/reconciliation workflow, or an externally justified durable event
   boundary.
2. Measure end-to-end failover RPO/RTO, connector reconnect/backoff exhaustion and freshness under a
   bounded workload.
3. Add fencing and split-brain negative tests before any HA claim.
4. Continue the remaining AR-2 exit gaps recorded in `docs/roadmap.md`: selected-column/concurrent-DDL
   evolution, physical-disk and predictive-capacity SLOs, Flink/Iceberg kill/network uncertainty,
   REST/Gravitino catalog, DriveTransfer, multi-tenant recovery and provider-profile parity.

Do not add Kafka, a second cursor authority, a permanent service or a scheduler until measured
fan-out and RPO/RTO requirements justify that architecture.
