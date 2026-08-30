# ADR-349: Flink REST provider cancellation adapter

## Status

Accepted and verified for the Flink REST cancellation adapter contract;
live Flink activity integration and production readiness are not claimed.

## Context

ADR-346 established the provider-neutral cancellation boundary, and ADR-347
verified Temporal workflow cancellation transport. The next boundary must map
that contract to a real long-running provider without treating Temporal's
cancel request as proof that the provider stopped.

## Decision

`FlinkProviderCancellationAdapter` implements the specialist cancellation
contract for a pinned Flink REST deployment:

- the provider binding must use `provider:flink` and
  `flink.iceberg.reconciliation.v1`;
- the immutable execution parameters must contain a lowercase 32-hex Flink
  `job_id`;
- the provider receipt must be exactly `flink://job/<job_id>`, preventing a
  stale worker from cancelling a different job;
- cancellation uses Flink `PATCH /jobs/{job_id}?mode=cancel`;
- HTTP `202`/`200`/`204` is only an `accepted` request, followed by a state
  observation;
- only `GET /jobs/{job_id}` with `state=CANCELED` produces `confirmed` and the
  `FlinkJobCancelled` failure type;
- transport failures, missing jobs, malformed responses, non-terminal states,
  and non-success HTTP responses remain `unknown`.

The adapter is injected through the existing
`SpecialistProviderCancellationAdapter` boundary. Provider receipt derivation
now uses the same job-bound reference in the specialist executor, Temporal
unknown envelope, and history reconciler; MMFE/GWM retain the historical
generic reference. The adapter itself does not write Temporal history or
mutate the specialist receipt authority; those components remain responsible
for durable reconciliation and terminal state transitions.

## Verification

`data_agent/test_agentops_flink_provider.py` passes 7 tests covering accepted
versus confirmed state, already-canceled observation, transport failure ->
`unknown`, provider/job/receipt identity drift, and executor integration. The
module also passes Ruff checks and compileall. The combined AgentOps/Temporal
regression passes `57 passed`.

## Limits and next evidence

The current evidence uses an HTTP contract transport, not a live Flink job. It
does not claim that an AgentOps activity can submit and observe a Flink job,
that Temporal cancellation reaches this adapter in a deployed worker, or that
PostgreSQL receipt/history reconciliation is end to end. The next evidence is
a real long-running Flink activity using this adapter, with provider terminal
state, Temporal history, durable receipt authority, authorization, retry budget,
and cleanup captured in one report. HA, fencing, multi-cluster recovery,
NetworkPolicy, and RPO/RTO remain separate gates.
