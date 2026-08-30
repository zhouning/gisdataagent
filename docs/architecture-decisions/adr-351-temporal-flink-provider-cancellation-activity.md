# ADR-351: Temporal activity to Flink provider cancellation settlement

## Status

Accepted and verified for the bounded live-worker rehearsal path. This ADR does
not authorize the AgentOps worker deployment or claim production readiness.

## Context

ADR-347 proved that a Temporal workflow cancellation request can reach the
Temporal server. ADR-350 proved that the Flink REST adapter can cancel a real
Flink job. Neither proof connected the two boundaries, and the PostgreSQL
specialist receipt authority had only been exercised with a synthetic activity
failure. A worker can lose its activity response after the provider has accepted
or completed cancellation, so the three authorities must remain separately
observable.

## Decision

Add `TemporalProviderCancellationProbeExecutor` as the reusable activity-side
binding for an externally submitted provider operation:

1. On the first activity attempt, register the deterministic
   `operation_ref = <operation_ref>://<activity_id>` and provider-native receipt.
   A replay reuses that receipt and never submits a second operation.
2. Keep the activity open until Temporal delivers cancellation. The activity
   definition emits periodic heartbeats for the full execution lifetime, and the
   cancellation handler calls the injected provider adapter in a worker thread.
3. Persist `unknown` with `cancellation_requested=true` for an accepted,
   unavailable, malformed, or observation-timeout response. After an accepted
   response, poll the provider within a bounded window. Persist `cancelled` only
   when the adapter observes a provider terminal cancellation.

The live rehearsal entry point is
`scripts/rehearse_agentops_temporal_flink_cancellation.py`. It starts a real
Temporal worker activity, uses `FlinkProviderCancellationAdapter` against a
caller-supplied Flink REST endpoint/job, and uses a disposable PostgreSQL
authority. It then observes Temporal history, runs the specialist history
reconciler, and replays the workflow history.

The workflow input envelope schema is explicitly admitted by
`TemporalioProviderClient` so history observation can validate the canonical
`TemporalWorkflowInput` without coupling the provider bridge to one rehearsal.

## Verification

The executor contract tests cover all settlement branches:

- provider `accepted` leaves the PostgreSQL receipt `unknown` and marked for
  cancellation;
- provider `accepted -> confirmed` produces a terminal `cancelled` receipt with
  the provider failure type;
- provider observation timeout remains `unknown` rather than inventing a
  terminal outcome.

The live rehearsal passed on 2026-08-29 with Temporal Server `1.29.7`, Python SDK
`1.32.0`, PostgreSQL `16.14`, and Flink `1.19.3`. Temporal recorded the activity
as `cancelled`, Flink reported the bound job as `CANCELED`, the PostgreSQL receipt
settled to `cancelled/FlinkJobCancelled`, specialist reconciliation returned
`definitive_failed`, and history replay passed. All seven checks passed across 16
Temporal history events.

Evidence:

- `docs/reports/agentops_temporal_flink_cancellation_2026-08-29.json`, file
  SHA-256 `4e01721abaa6d4cfb4fb442996532cc8e518478bc189ba64ca3269c25529121b`;
- `docs/reports/agentops_temporal_flink_cancellation_history_2026-08-29.json`,
  file SHA-256
  `c66e06ab1cc8613d9648ad8c5a8594703bf306fa022b8f0e5dd1b19e49eaeb0b`.

Focused provider/runtime tests: `15 passed`; Ruff and compileall pass. The live
script remains parameterized and requires a running Temporal frontend, an admin
PostgreSQL URL, and a running non-terminal Flink job.

## Limits and next evidence

The bounded cross-process path is verified. ADR-352 separately closes durable
diagnosis for provider permission denial; the remaining gates are retry budget
and worker restart, durable reconciliation worker settlement, NetworkPolicy,
HA/fencing, backup/restore, identity rotation, and production rollout. An
`accepted` Temporal cancel or Flink REST response is never a terminal business
result.
