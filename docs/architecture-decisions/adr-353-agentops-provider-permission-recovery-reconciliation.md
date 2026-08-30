# ADR-353: Managed reconciliation after provider permission recovery

## Status

Accepted and verified for the bounded live Temporal/Flink/PostgreSQL rehearsal.
Production worker rollout and provider permission operations are not claimed.

## Context

ADR-352 made a denied Flink cancellation durable and diagnosable, but a denied
request can be followed by an operator restoring permissions and the provider
reaching a terminal state. The next reconciliation cycle must converge that
receipt without submitting a second operation or treating the original Temporal
cancellation as provider evidence.

## Decision

The managed specialist reconciler accepts an optional provider cancellation
adapter. For a receipt that is already `unknown` and
`cancellation_requested=true`, it asks the adapter for the provider's current
native state:

- `confirmed` appends the one allowed terminal `cancelled` receipt;
- `accepted`, `unknown`, adapter errors, and permission denial keep the receipt
  non-terminal and preserve the most specific uncertainty reason;
- no provider submission is made by reconciliation, and a terminal receipt is
  never rewritten.

The adapter is injected by provider reference, so a worker cannot infer a
provider endpoint from an unbound request. Existing receipt and reconciliation
fingerprints remain the authority.

## Verification

The live negative rehearsal first sends Flink cancellation through a proxy that
returns HTTP 403. Temporal records a cancelled activity while the real Flink job
remains `RUNNING`; PostgreSQL stores
`FlinkCancellationPermissionDenied` and specialist reconciliation remains
`unknown_pending`. After bypassing the proxy, the next reconciliation observes
the same job-bound `flink://job/<job_id>` receipt at `CANCELED`, appends one
terminal receipt, and produces `definitive_failed` without a second submission.
The rehearsal history replays successfully and all checks pass. The report file
SHA-256 is `a6d707f99646b4089dd72f6e94770a14bc8c90211bdb407073750d5162e1d505`;
the history file SHA-256 is
`e7fe8bc24d7a9424fde3c8735b684119ca62f195f94731a2504282cead7bfda6`. See
`docs/reports/agentops_temporal_flink_cancellation_permission_denied_2026-08-29.json`.

## Limits

This bounded evidence does not prove a crashed managed worker reconnecting to a
production cluster, retry-budget policy across workers, automatic alert/remediation
routing, NetworkPolicy enforcement, HA/DR, or production RPO/RTO.
