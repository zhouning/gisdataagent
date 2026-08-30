# ADR-176: PostgreSQL CDC Recovery-Controller Slot-Continuity Contract

**Status**: Accepted

**Date**: 2026-08-07

**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2

**Related**: ADR-166, ADR-172, ADR-173, ADR-174, ADR-175

## Context

The failover and slot-loss certifications already prove that SourceSync must stop
when a logical replication slot disappears or changes incarnation. The previous
decision logic lived in certification scripts, which made it easy for a future
controller to reimplement the gate and accidentally advance the old cursor.

The platform needs one reusable, checkpoint-bound contract for the controller's
observation and next-action decision. The contract must distinguish a continuous
slot, a physically witnessed loss that can schedule a governed resnapshot, and
insufficient evidence that must remain stopped.

## Decision

Add `data_agent.postgresql_cdc_recovery_controller` as the deterministic control
contract. It defines:

- `PostgresqlCdcSlotIncarnation`, an immutable identity and fingerprint for one
  slot incarnation;
- `PostgresqlCdcSlotContinuityObservation`, bound to a tenant, sync-definition
  version and the exact last checkpoint cursor; and
- `PostgresqlCdcRecoveryDecision`, whose action is `resume_cdc`,
  `schedule_resnapshot`, or `rejected_fail_closed`.

The controller rules are:

1. A matching, continuously observed incarnation returns `resume_cdc` and keeps
   the checkpoint as the only cursor authority.
2. A witnessed slot absence or same-name recreation returns
   `schedule_resnapshot`, preserves the old checkpoint and requires a new
   governed Run. The evidence Artifact builder is part of the controller
   module, so certification code only submits the typed artifact through the
   existing PlatformGateway.
3. Missing or un-witnessed continuity evidence returns
   `rejected_fail_closed`; it cannot create a Run or advance SourceSync.

The decision is workload-authored and fingerprinted. The module does not execute
provider work, create a scheduler, recreate a slot, or mutate the checkpoint.
The existing slot-invalidation certifier now uses the same incarnation builder
and continuity assessor. `PostgresqlCdcRecoveryControllerRuntime` provides the
gateway-injected evaluation and evidence-write facade used by the failover
certification.

Expose the durable observation projection through the versioned platform API as
`GET /api/platform/v1/recovery-observations/{artifact_id}`. The handler derives
the tenant exclusively from the authenticated `admin` or `platform_operator`
principal and calls the existing `PlatformGateway` read method. The request has
no tenant parameter and the endpoint cannot write controller evidence, advance
a checkpoint or schedule recovery.

## Verification

- `data_agent/test_postgresql_cdc_recovery_controller.py`: eight contract tests
  cover resume, witnessed recreation, un-witnessed absence, checkpoint binding,
  tamper rejection and compatibility with the negative certifier.
- `data_agent/test_chongqing_osm_postgres_cdc_slot_invalidation.py`: existing
  five slot-loss tests still pass through the shared production module.
- Ruff passes for the module, tests and certifier integration.
- Real isolated backend certification passed with PostgreSQL `16.14` and
  Flink `1.19.3`: the original slot was physically absent, a same-name slot
  was recreated as a new incarnation, and the controller rejected admission
  before runtime termination. Provider checks were `9/9`, top-level checks
  `9/9`, cleanup checks `7/7`; SourceSync checkpoint and commit history stayed
  at `0`/empty. Report:
  `.tmp/source-sync-certification/chongqing-osm-postgres-cdc-slot-invalidation-controller-report.json`
  (SHA-256 `b81d996f5588fc1c9608db72d80d1647be2122d844e0c98a6d83df4e79f35413`).
- The physical-failover recovery certification now constructs this observation
  from the real primary/promoted slot evidence before creating the recovery
  plan. It refuses to schedule unless the decision is
  `schedule_resnapshot`; the observation and decision are included in the
  immutable recovery evidence. The PostgreSQL 16/Flink/DolphinScheduler rerun
  passed `21/21` top-level and `11/11` cleanup checks. Recovery plan SHA-256 was
  `28a481c46b02d08ee2bdd18223a538dffda6c227bf23b7a09470747794d8237e`, decision
  SHA-256 was `01573bcf722d9ea00c34fd7300d552fc7172c2b7212bc46052b1595d4b280c70`,
  and report SHA-256 was
  `e1308ea1e8ad489b04ba436352150845651a3ee7dd7e0cbf7809a0296920c1c1`.
- The follow-up rerun also persisted a dedicated
  `gda.postgresql_cdc_recovery_controller_evidence.v1` Artifact through
  `PlatformGateway`: first write `created=true`, idempotent replay
  `created=false`, with the Artifact manifest bound to recovery plan SHA
  `b6d81338d2019d43eac4205385df7f0782d1db2bc6aec8364419bd2d1ec0174c` and
  decision SHA `8a3c9d06a7a78d6850ae3aa10853fc041f4909ad7861c8fb28dbe9780b05584f`.
  This rerun passed `22/22` top-level and `11/11` cleanup checks; report
  SHA-256:
  `132be7a774462aa434329a15e0b5b2bc36b9a2e4ba8e554aa05f5de0f3c99a3e`.
- The runtime facade rerun passed with the same `22/22` top-level and `11/11`
  cleanup gates after moving controller evidence persistence out of the
  certification script. Decision remained `schedule_resnapshot`; Artifact
  first write/replay remained `created=true/false`. Report SHA-256:
  `41706da28f937c572a16d6d9545e90c1b282aef906b2ac1e77e42ce5281ef049`.
- Migration `147_postgresql_cdc_recovery_observation` now projects the same
  evidence into an append-only, forced-RLS control table keyed by the
  recovery-controller Artifact. `PlatformGateway` writes the Artifact and
  ledger row in one transaction; the gateway role has `SELECT` plus function
  `EXECUTE` only, with direct table `INSERT/UPDATE/DELETE` denied. The
  projection stores the checkpoint cursor/state, observation and decision
  documents, reason codes, recovery-plan SHA and Run/definition bindings.
- The real PostgreSQL 16.4 + Flink 1.19.3 + DolphinScheduler 3.4.2 rerun with
  the ledger passed `23/23` top-level, `13/13` provider and `11/11` cleanup
  checks. Ledger first write/replay were `created=true/false`, the queried
  projection matched observation/decision/checkpoint/recovery-plan fingerprints,
  and the old SourceSync checkpoint remained `0`. Report SHA-256:
  `7d4a731ecb97e21e8b9a4b9f42e048261f3e31253dc5ad08823b31a09fb36cc1`.
- Durable projection fingerprints from that run were observation
  `874c4302450a6443598ed26335dc4e4359b4da9e9f830c45de099ae0945a749c`,
  decision `a32bb9dd97cbd97bb2d70da9251c8853355e783aea71942086c1ce309a805dad`,
  and recovery plan
  `793e8cd28a4f44d14681a6cb6c34271976e21c017717b201bc6c992a195c6d1e`.
- The platform API route, tenant derivation, ignored client tenant override,
  invalid UUID rejection, authentication/role gates, gateway 403/404 mapping,
  route registration and OpenAPI security declaration pass in the 77-test
  `data_agent/test_platform_gateway.py` suite. A read against the current shared
  development database returned 404 for the isolated certification Artifact,
  so this evidence does not claim a deployed live 200 response.

## Boundary

This is the deterministic decision kernel, now wired through the certified
SourceSync/PlatformRun recovery plan and schedule-window path and backed by a
durable queryable observation ledger. It is not a production HA deployment:
slot repair or native failover-slot configuration, CDC resume,
fencing/lease acquisition, failover RPO/RTO and freshness SLO remain AR-2 exit
gates. The ledger is an observation/evidence authority only; it does not create
a second cursor or scheduler and does not authorize production promotion by
itself. The read API is a consumption surface for that same authority, not a
second recovery-controller or a production deployment claim.
