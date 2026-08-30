# AR-2 PostgreSQL CDC Failover Handoff

**Date**: 2026-08-07

**Branch**: `feat/windows-standalone-offline-bundle`

**Roadmap state**: AR-2 `in_progress`

## Authoritative State

- The detailed completion ledger and current phase table are in `docs/roadmap.md`.
- AR-0, AR-1 and AR-2 remain `in_progress`. AR-3 through AR-8 remain `planned`; completed
  component certifications inside those phases do not change their exit-gate state.
- ADR-106 is the PostgreSQL CDC certification boundary. ADRs 164 through 175 extend its recovery,
  quarantine, schema, slot-incarnation, WAL-capacity, physical-failover and fencing evidence.

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
- Added a typed `stop_and_detach` fencing witness: the stopped old primary is network-detached and
  a post-fence write probe is rejected before promotion. A companion split-brain certification keeps
  the old primary live, proves divergent writes on both timelines, and rejects admission before any
  alias transfer; the standalone provider does not invoke SourceSync.
- Added migration `147_postgresql_cdc_recovery_observation`, an append-only forced-RLS ledger keyed by
  the controller evidence Artifact. `PlatformGateway` now writes the Artifact and ledger projection
  atomically through a SECURITY DEFINER function; direct gateway table writes are denied.
- Added `GET /api/platform/v1/recovery-observations/{artifact_id}` as the tenant-scoped, read-only
  consumption surface for that ledger. Tenant identity comes only from the authenticated platform
  principal; the endpoint does not accept a tenant override or mutate checkpoint/recovery state.
- Advanced the promoted source with a revision-3 probe and observed zero FileSink growth for 2.0
  seconds. SourceSync checkpoint stayed at version 0; commit, successful output Artifact,
  QualityResult, LineageEvent, target ResourceVersion and successful provider-admission counts stayed
  at zero. The rejected Run has one separate, idempotent recovery evidence Artifact.
- Added `PostgresqlCdcFailoverRecoveryPlan`, an immutable recovery boundary that fingerprints the
  rejected admission evidence and last safe checkpoint. It requires a new governed Run, records
  `resnapshot_and_reconcile`, and explicitly sets `cursor_disposition=do_not_advance`; it does not
  execute a resnapshot, recreate a logical slot or create a second cursor authority.
- Added `PostgresqlCdcFailoverResnapshotAdmission`, which registers a new SourceSync definition
  identity/version with `mode=full`, `write_disposition=overwrite`, `cursor_kind=none`,
  `delete_mode=ignore` and batch governance. A real promoted-standby full read then materializes
  three rows through the governed output/quality/quarantine Artifact, LineageEvent and metadata
  outbox path. The new definition commits one snapshot checkpoint (`0 -> 1`) and an idempotent
  commit replay; the old CDC definition remains at checkpoint `0`.
- Completed the real DataOps dispatch boundary: the immutable workflow definition was compiled and
  deployed to DolphinScheduler 3.4.2, the command outbox was claimed and completed exactly once,
  and the executor observed workflow instance `28` in `SUCCESS`.
- Replaced the human `DataOpsManualTriggerSpec` with an automatic `DataOpsScheduleWindowSpec` whose
  immutable `schedule_ref` and window identity bind the recovery-plan fingerprint. The recovery
  workload atomically created the invocation, Run, policy Artifact and dispatch command without a
  human delegation or a second scheduler.
- Finalized the resnapshot Run from `reconciling` to `succeeded` only from the persisted
  `RunSuccessEvidence` and DolphinScheduler success observation. The finalization actor and all
  provider/lineage/commit actors derive from the immutable Run subject; no provider status shortcut
  can move the Run to a terminal success state.
- Added ADR-174 and updated ADR-106, ADR-172, ADR-173 and the AR-2 roadmap ledger without claiming
  automatic recovery, CDC resume or production HA.

## Evidence

- Report: `.tmp/source-sync-certification/chongqing-osm-postgres-cdc-failover-report.json`
- Report SHA-256: `0b484dfe466b75a07099fff3ce12701d58a012a47182e0aaecf4efecb3ee654c`
- Split-brain report: `.tmp/source-sync-certification/chongqing-osm-postgres-cdc-split-brain-report.json`
- Split-brain report SHA-256: `5f922455708c4d31f19b1d482804d827ec59ae178affd0e8f19e0d8f5629b364`
- Provider gates: `13/13`; top-level certification checks: `20/20`; cleanup gates: `11/11`
- Scoped static/unit regression: `72 passed` (Ruff, Python compilation and diff check also passed)
- Recovery plan: `authority.recovery_plan.plan_sha256=`
  `7e687270e2a494b3dcae8b90108281e18e2d0a28903cc59291bfd555e5dff4c2`, with checkpoint state
  `0` and reason `logical_replication_slot_missing_after_promotion`.
- Resnapshot admission: `admission_sha256=`
  `e56ede9622f674d8250e6ccaa3dcbdecbeaa955e3010617f9f284f76a9b000eb`; replay is idempotent
  (`artifact_replay_created=false`). New definition version is
  `334e0c3d-8a53-4937-90d1-fd8e5e626159`, new Run is
  `9e7026ab-86d5-55ca-9876-08bd68d4ddcd`, and its checkpoint advances to `1` with target
  content SHA-256 `29fda3d9cf9a36f40957a0001210bea4d73f5d077ba741dbfa38926e12bf6936`.
- Resnapshot execution: `postgresql-full-resnapshot`, `3` rows read/output, commit
  `365b65c9-98a0-5560-8163-4ad70112b853`, first write `created=true`, replay `created=false`;
  DolphinScheduler workflow `180820130339392` / instance `28` observed `SUCCESS`, and final Run
  status is `succeeded` with persisted success evidence.
- Automatic trigger: `trigger_kind=schedule`, `run_created=true`, `command_created=true`, and window
  SHA-256 `1b2aa81d650d23e73d828e6b74a68e5665bea21319c75c1e2f49881199feeb5c`.
- Ruff, Python compilation, structured report assertions and scoped `git diff --check` passed.
- Durable recovery-controller ledger rerun: `.tmp/source-sync-certification/chongqing-osm-postgres-cdc-recovery-ledger-report.json`,
  SHA-256 `7d4a731ecb97e21e8b9a4b9f42e048261f3e31253dc5ad08823b31a09fb36cc1`;
  provider/top-level/cleanup gates `13/13`, `23/23`, `11/11`; ledger first write/replay
  `created=true/false`; queried projection matched the checkpoint, observation, decision and
  recovery-plan fingerprints; migration catalog/database was `148/148` with fingerprint
  `6ffffe01e1f337ddbcb9cf6500b93757eb43a86aba693c4334b680f2c995b71f`.
- Platform API suite: `77 passed`; Ruff, Python compilation and scoped diff check passed. The tests
  cover tenant derivation, ignored tenant override, invalid UUID, 401/403/404, route registration and
  OpenAPI security. The isolated certification Artifact was absent from the current shared
  development database, so no deployed live 200 response is claimed.
- No random CDC primary, standby or Flink container and no standby named volume remained.
- Full-worktree `git diff --check` still reports only the unrelated pre-existing blank line at EOF in
  `data_agent/migrations/131_platform_branding_settings.sql:33`.

## Do Not Claim

- automatic logical replication slot synchronization, repair or recreation;
- automatic Flink CDC resume after promotion;
- production recovery-controller deployment or automatic slot-loss detection;
- production failover RPO/RTO or freshness SLO;
- automatic fencing, lease expiry or split-brain prevention;
- multi-zone, multi-cluster or Kubernetes HA;
- direct CDC-to-Iceberg distributed exactly-once behavior.

## Next AR-2 Work

The slot-loss decision kernel is now shared by the certification path and the
controller contract in [ADR-176](../architecture-decisions/adr-176-postgresql-cdc-recovery-controller-slot-continuity.md).
The physical-failover certification now constructs the checkpoint-bound
observation and refuses to create the recovery schedule unless the controller
returns `schedule_resnapshot`. The follow-up rerun also writes a dedicated
controller evidence Artifact through PlatformGateway, with idempotent replay;
it passed `22/22` top-level and `11/11` cleanup checks. The runtime-service
rerun kept the same gates and Artifact `created=true/false` behavior. The
follow-up durable-ledger rerun also proves an atomic Artifact + observation
projection and query round-trip; its report SHA-256 is
`7d4a731ecb97e21e8b9a4b9f42e048261f3e31253dc5ad08823b31a09fb36cc1`.
The ledger now has a versioned, tenant-scoped read API for platform operations,
without introducing another cursor or scheduler authority.
The slot-loss-only rerun remains independently recorded with SHA-256
`b81d996f5588fc1c9608db72d80d1647be2122d844e0c98a6d83df4e79f35413`; both
paths stop before advancing the old SourceSync checkpoint.

1. Select and certify a production slot-continuity mechanism: PostgreSQL-version-specific failover
   slots, an approved resnapshot/reconciliation workflow, or an externally justified durable event
   boundary.
2. Measure end-to-end failover RPO/RTO, connector reconnect/backoff exhaustion and freshness under a
   bounded workload.
3. Continue the remaining AR-2 exit gaps recorded in `docs/roadmap.md`: selected-column/concurrent-DDL
   evolution, physical-disk and predictive-capacity SLOs, Flink/Iceberg kill/network uncertainty,
   REST/Gravitino catalog, DriveTransfer, multi-tenant recovery and provider-profile parity.

Do not add Kafka, a second cursor authority, a permanent service or a scheduler until measured
fan-out and RPO/RTO requirements justify that architecture.
