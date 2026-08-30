# ADR-343: Provider-bound Temporal activity failures remain unknown

## Status

Accepted and verified by contract tests; real Temporal server execution is not claimed.

## Context

The task-graph workflow schedules MMFE/GWM through a Temporal activity. Temporal can
report timeout, cancellation, transport loss, or an activity failure after the provider
has accepted the operation but before the activity response reaches the workflow. The
Temporal history event therefore proves only that Temporal did not accept a result; it
does not prove that the provider side effect failed.

The previous runtime projection converted every SDK exception into `FAILED`. That could
cause a retry or a failed ToolCall projection while a provider write was already
committed.

## Decision

When `TemporalActivitySchedulePlan.request.provider_spec` is present, `_execute_schedule`
projects an SDK exception to `TemporalActivityOutcome.UNKNOWN` with deterministic:

- `provider_operation_ref = <operation_ref>://<activity_id>`
- `provider_receipt_ref = provider://specialist/<activity_id>/<attempt_no>`

The workflow records the unknown evidence and stops the wave. A specialist receipt
reconciler must later inspect the provider operation authority and output Artifact before
settling success, definitive failure, or cancellation. No second provider submission is
made from the workflow path.

Activities without a provider binding retain the existing definitive `FAILED` projection,
because there is no external operation whose outcome needs reconciliation.

## Verification

`data_agent/test_agentops_temporal_task_graph_runtime.py` covers Temporal timeout,
cancellation, generic activity failure, deterministic receipt identity, and the unbound
activity regression. The specialist/provider reconciliation suite remains green.

## Consequences and limits

This closes the workflow-side misclassification gap for the bounded MMFE/GWM slice. It
does not by itself provide a provider-native cancellation API, PostgreSQL receipt
durability, a live Temporal history observer, lease fencing, HA/DR, or production SLOs.
Those remain explicit integration and readiness gates.
