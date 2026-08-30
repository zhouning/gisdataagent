# ADR-350: Live Flink provider cancellation integration

## Status

Accepted and verified for the bounded live Flink provider cancellation
integration; Temporal server cross-process settlement and production readiness
are not claimed.

## Context

ADR-349 defined the Flink REST adapter and ADR-346 defined the provider-neutral
AgentOps cancellation contract. A contract transport alone does not prove that
the adapter reaches a real long-running provider or that the provider's
terminal state remains consistent with the existing Iceberg reconciliation
path.

## Decision

The Flink/Iceberg reconciliation certification now publishes the temporary
Flink REST port and uses `FlinkProviderCancellationAdapter` for the cancellation
window when the cluster starts. The certification builds a hash-bound
`TemporalActivityRequest` after the real Flink job ID is returned:

- provider binding: `provider:flink`;
- operation: `flink.iceberg.reconciliation.v1`;
- receipt: `flink://job/<job_id>`;
- cancellation transport: `PATCH /jobs/<job_id>?mode=cancel`;
- terminal observation: `GET /jobs/<job_id>` with `state=CANCELED`.

The adapter observation is recorded alongside the existing source checkpoint,
Iceberg snapshot, SourceSync authority, and cleanup evidence. A successful
HTTP request without the terminal Flink state cannot advance the control plane.
The default script path now exercises this live adapter; no CLI cancel fallback
is used once the REST endpoint is published.

## Verification

The real `ack-loss` profile passed all 14 top-level checks and the nested
cancellation checks, including source emission, zero completed checkpoint
before cancellation, provider `CANCELED`, unchanged baseline Iceberg state,
exact independent snapshot reconciliation, no duplicate retry snapshot, and
complete temporary resource cleanup.

- [report](../reports/chongqing_osm_flink_iceberg_agentops_cancel_2026-08-29.json)
  file SHA-256 `584c04907ccb05f155c8752f93703054eeb8b2896bb127b75769a8ca8aa01542`;
- provider observation status: `confirmed`;
- provider receipt: `flink://job/e55df253b0604b376aea03707647bcdb`;
- runtime: Flink `1.19.3`, Iceberg runtime `1.7.2`, temporary JDBC catalog,
  MinIO S3FileIO, and PostgreSQL authority.

## Limits and next evidence

The run uses a real Flink process and REST API, but the certification process
is not itself a Temporal worker and does not export Temporal history events.
It therefore does not prove Temporal activity cancellation delivery,
cross-process PostgreSQL receipt settlement, retry-budget enforcement under
worker restart, Kubernetes NetworkPolicy, HA/fencing, or RPO/RTO. The next
evidence is a Temporal worker activity that submits or binds this Flink job and
settles the same provider observation through the durable specialist receipt
authority and history reconciler.
