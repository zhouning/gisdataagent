# ADR-352: Preserve provider cancellation denial as durable uncertainty

## Status

Accepted and verified for the bounded Temporal/Flink/PostgreSQL rehearsal. This
decision does not claim production readiness or authorize a production worker
rollout.

## Context

The Flink cancellation adapter previously mapped permission denial, transport
loss, missing jobs, malformed responses, and observation timeout to the same
`unknown` result. The fail-closed outcome was correct, but the receipt did not
tell an operator whether to grant permission, restore connectivity, inspect an
identity mismatch, or terminate the provider job manually.

## Decision

Add an optional `uncertainty_type` to provider cancellation observations and
specialist operation receipts. It is allowed only while the operation receipt is
`unknown`; terminal success, failure, and cancellation clear it. Flink maps REST
and provider observations to stable reason codes, including
`FlinkCancellationPermissionDenied`, while only provider state `CANCELED` can
produce a confirmed cancellation.

Migration 247 exposes the reason from the immutable JSON receipt as a generated,
indexed PostgreSQL column and constrains it to the admitted reason set. Old
receipts omit a null `uncertainty_type` from their canonical fingerprint, so
migration does not invalidate existing hashes.

The rejected alternatives were:

- putting the reason in `failure_type`, because a 403 does not prove provider
  failure or cancellation;
- deriving the reason only from worker logs, because logs are not the durable,
  tenant-scoped operation authority;
- treating Temporal activity cancellation as provider cancellation, because the
  provider job can continue running after the worker is cancelled.

## Verification

The disposable PostgreSQL 16 migration rehearsal applied migrations 246 and 247
and passed 7/7 checks, including cross-instance recovery of
`FlinkCancellationPermissionDenied`, append-only transitions, terminal CAS, and
tenant RLS. Evidence:

- `docs/reports/agentops_specialist_operation_uncertainty_postgres_2026-08-29.json`
- file SHA-256
  `aed5771ee411808c4237e6f60b8e6947bb8da9fe661d9a2e4627dc98af3b6764`

The live negative rehearsal placed a policy proxy in front of a real Flink
1.19.3 job. GET requests reached Flink and PATCH cancellation returned 403. The
result was:

- Temporal activity `cancelled`;
- Flink job still `RUNNING` at the evidence boundary;
- PostgreSQL receipt `unknown`, `cancellation_requested=true`,
  `uncertainty_type=FlinkCancellationPermissionDenied`;
- specialist reconciliation `unknown_pending` and resulting activity outcome
  `unknown`;
- 18 Temporal history events replayed successfully;
- 8/8 checks passed.

The rehearsal then bypassed the denial proxy, confirmed Flink state `CANCELED`,
and removed the disposable runtime. Evidence:

- `docs/reports/agentops_temporal_flink_cancellation_permission_denied_2026-08-29.json`
  with file SHA-256
  `740a58aabeebbeca4de86e8d14d90101a505f8774c892fe4a5d5e3ab25dd8f94`;
- `docs/reports/agentops_temporal_flink_cancellation_permission_denied_history_2026-08-29.json`
  with file SHA-256
  `d9c616465a3bdeae60b23ac05285648921d344b976e64cfeabf01cf247edce10`.

## Consequences and remaining work

Operators can now distinguish permission denial from transport and provider-state
uncertainty without promoting an uncertain operation to a false terminal state.
The remaining gates include production identity and permission rollout, alert and
remediation routing by reason code, worker restart/retry-budget evidence,
NetworkPolicy, HA/fencing, backup/recovery, and production RPO/RTO.
