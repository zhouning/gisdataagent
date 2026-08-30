# ADR-345: Observe Temporal specialist timeout before settling provider state

## Status

Accepted and verified for the bounded Temporal + PostgreSQL history-observer slice;
production readiness is not claimed.

## Context

For an MMFE or GWM activity, Temporal can record a timeout after the provider has
accepted an operation but before the worker returns a response. Treating that event as
a provider failure can cause a second data write. Treating it as success can publish an
Artifact that the provider never committed. The provider receipt and Temporal history
must therefore be observed separately and joined by the immutable activity identity.

## Decision

1. A provider-bound activity timeout, cancellation, or transport failure is represented
   as an observation of the Temporal history, not as a provider terminal result.
2. `TemporalioProviderClient.observe_workflow_history()` decodes the real Temporal
   history into `TemporalProviderActivityHistoryObservation`, including activity ID,
   attempt, schedule/start/terminal event IDs, timeout type, request fingerprint and
   provider result when one exists.
3. `reconcile_specialist_activity_history()` reads the PostgreSQL specialist receipt
   authority and the Artifact authority without submitting another provider operation.
   A `submitted` or cancellation-requested receipt remains `unknown_pending`; only a
   provider-confirmed terminal cancellation produces `definitive_failed` and a failed
   activity result.
4. The workflow-side runtime keeps provider-bound failures in `UNKNOWN`, while ordinary
   unbound activities retain their existing `FAILED` behavior.

## Verification

The disposable Kubernetes rehearsal used Temporal `1.29.7`, Python SDK `1.32.0`, and
PostgreSQL migration `246`. A real MMFE-bound activity wrote a PostgreSQL `submitted`
receipt and then exceeded its two-second Temporal start-to-close timeout. The observer
read an 11-event history and reported `timed_out`. Reconciliation produced:

- `submitted` receipt -> `unknown_pending` / `unknown`;
- cancellation requested, provider terminal state still absent -> `unknown_pending` /
  `unknown`;
- explicit provider terminal cancellation -> `definitive_failed` / `failed` with
  `ProviderCancellationConfirmed`.

Temporal history replay passed. Evidence:

- [report](../reports/agentops_temporal_specialist_history_reconciliation_2026-08-29.json),
  `report_sha256=a08dd5434505c47bd67df570567414853087a989027b1732921d82fc27f3c012`,
  file SHA-256 `20c99c84208abce70697f84663d326dbc60436a159277565a517be7aab6b3215`;
- [history](../reports/agentops_temporal_specialist_history_reconciliation_history_2026-08-29.json),
  file SHA-256 `db1189acf6909edf29720177a242dd8643d4d6ebc07635a085f67fe9f1a85598`.

## Limits

The terminal cancellation in this rehearsal is an authority transition used to prove
the join and state machine; it is not a provider-native cancellation API. Production
still requires provider-specific cancellation adapters, live cancellation observation,
cross-provider conformance, durable shared Artifact content, HA/DR, identity rotation,
and an operational cancellation SLA.
