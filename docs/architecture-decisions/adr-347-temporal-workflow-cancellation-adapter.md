# ADR-347: Typed Temporal workflow cancellation adapter

## Status

Accepted and verified for the Temporal workflow cancellation transport slice;
provider operation cancellation is not claimed.

## Decision

`TemporalWorkflowAdapter` now exposes `cancel()` and `cancel_async()`. The
Temporal SDK bridge calls the bound workflow handle's native `cancel` API and
returns a hash-bound `TemporalProviderCancellationResult` with `accepted` or
`unknown`, including the normalized reason and a deterministic provider receipt
reference. Tenant, namespace, and workflow identity are checked before the
result is accepted. RPC failures remain `unknown` and are not projected as a
terminal business outcome.

This transport is separate from `SpecialistProviderCancellationAdapter`: a
Temporal workflow cancellation request can stop scheduling or waiting, but it
does not prove that an MMFE/GWM or remote compute operation stopped. Specialist
provider receipts still require provider-native `confirmed` evidence before a
terminal `cancelled` transition.

## Verification

`data_agent/test_agentops_temporalio_provider.py` verifies the SDK-shaped bridge
using a fake workflow handle, including reason, namespace, workflow ID, receipt
hashing, accepted status, and RPC failure -> `unknown`. The focused
Temporal/provider suite passes `35 passed, 1 skipped` with Ruff and compileall
clean.

The adapter was also exercised against the live sandbox Temporal server
(`1.29.7`) through a unique workflow ID. The start RPC returned `unknown`, but
history observation found the started workflow; `cancel_async()` returned
`accepted`, and the same history contained
`EVENT_TYPE_WORKFLOW_EXECUTION_CANCEL_REQUESTED` (3 events). Evidence:

- [report](../reports/agentops_temporal_workflow_cancel_transport_2026-08-29.json),
  `report_sha256=786ba3348c88d10ee2f769a0c0217f7dea7b50169f190cd9e096769e91393d05`,
  file SHA-256 `2b64044c4bf4f22904332930a0518f33e4596172e3fddc06a29b568c1e34f598`;
- [history](../reports/agentops_temporal_workflow_cancel_transport_history_2026-08-29.json),
  file SHA-256 `2b79f6a82a09b9e25d71fada4a56286d13d7f4afe58075faadb82c94a4221869`.

## Limits

The live rehearsal only proves Temporal transport/history observation. It does
not prove that an MMFE/GWM or remote compute operation stopped: the report sets
`provider_operation_cancellation_claimed=false` and
`production_readiness_claimed=false`. The current sandbox has no running Flink
or Spark long-task provider; a provider-native cancel/observe implementation,
durable provider receipt, and end-to-end Temporal-to-specialist reconciliation
remain required before production readiness or cancellation SLO claims.
