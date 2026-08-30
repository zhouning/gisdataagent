# ADR-196: DolphinScheduler Cancel Terminal Evidence Timing and Replay

**Status:** Accepted (bounded control-plane slice)

## Context

The governed cancel path can receive a provider terminal state while the
external STOP request is still being delivered. DolphinScheduler 3.4 also
returns instance timestamps with whole-second precision. Requiring provider
evidence to be later than the outbox command's `completed_at` therefore rejects
valid `FAILURE` evidence produced by the STOP call itself. Retrying the
reconcile command can additionally change the outbox delivery attempt count
without changing the provider observation, which must remain immutable and
idempotent.

## Decision

Cancellation terminal mismatch validation is anchored to the immutable
`PlatformRun -> cancelling` event carrying
`gda.dataops_cancel_admission.v1`, not to outbox completion time. For the
DolphinScheduler 3.4 profile, a one-second bounded tolerance covers the
provider's timestamp truncation; evidence older than the admission event minus
that tolerance is rejected.

Outbox delivery retries are not provider execution attempts. The current
DolphinScheduler workflow-instance observation uses provider attempt `1` on
dispatch and reconcile replay, while command `attempt_count` remains delivery
state only. This keeps the same provider evidence idempotent across retries and
prevents duplicate observation payload conflicts.

## Consequences

Real sandbox evidence now proves the control-plane mismatch path: provider
instance `35` reached `FAILURE`, the platform Run became `failed`, one
`provider_cancel_terminal_mismatch` incident was opened, and cancel replay
created no new command or policy artifact. The provider capability remains
`conformance_probe`/`probe_only`; this ADR does not certify provider `STOP`.
