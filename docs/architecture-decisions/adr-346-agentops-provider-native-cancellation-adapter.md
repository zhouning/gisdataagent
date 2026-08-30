# ADR-346: Provider-native cancellation adapter boundary

## Status

Accepted and verified for the provider cancellation contract slice; production
provider cancellation is not claimed.

## Context

Temporal can cancel an activity after a specialist provider has accepted a
side effect. A Temporal `CANCELLED` history event is therefore not proof that
MMFE, GWM, or a future remote compute provider stopped its operation. The
previous bounded runtime had a receipt authority and history observer, but no
typed boundary for sending cancellation to the provider itself.

## Decision

1. Add `SpecialistProviderCancellationAdapter` with two operations:
   `request_cancellation()` sends the provider-native abort/cancel request, and
   `observe_cancellation()` reads the provider's own cancellation state.
2. The adapter returns a hash-bound
   `SpecialistProviderCancellationObservation` with one of `accepted`,
   `confirmed`, `unknown`, or `unsupported`.
3. `BoundSpecialistExecutor` invokes the adapter when the Temporal activity is
   cancelled. `accepted`, `unknown`, and `unsupported` only update the receipt
   to cancellation-requested/`unknown`; only `confirmed` may transition the
   PostgreSQL receipt authority to terminal `cancelled`.
4. Replaying an activity observes the adapter before attempting any provider
   work. A confirmed cancellation is projected as a failed activity with the
   provider failure type; a pending cancellation remains unknown and cannot
   publish an Artifact.
5. `UnsupportedSpecialistCancellationAdapter` is the explicit default for a
   provider without a native API. `InMemorySpecialistCancellationAdapter` is
   limited to contract tests and rehearsals.

## Verification

`data_agent/test_agentops_specialist_providers.py` verifies:

- hash-bound accepted/confirmed/unsupported observations;
- idempotent cancellation request and request/operation identity binding;
- Temporal-style task cancellation sending an adapter request;
- pending provider cancellation remaining `unknown`;
- provider confirmation converging on replay to terminal `cancelled`/failed.

The focused suite passes (`15 passed`) together with the existing specialist
provider and authority suite (`18 passed, 1 skipped`). Ruff and compileall pass.

## Limits and next evidence

The adapter is an integration boundary, not a provider implementation. MMFE and
GWM currently use the explicit unsupported adapter because their bounded local
runtimes expose no provider-native cancellation endpoint. Production requires
at least one real long-running provider with cancel and observe APIs, durable
provider receipts, timeout/retry budgets, authorization, and a live Temporal
history reconciliation rehearsal. MinIO/Iceberg/PostGIS conformance, CNI
NetworkPolicy enforcement, HA/DR, identity rotation, and production rollout
remain separate AR-5 exit gates.
