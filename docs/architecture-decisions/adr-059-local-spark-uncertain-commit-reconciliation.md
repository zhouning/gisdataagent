# ADR-059: Local Spark uncertain-commit reconciliation

- Status: Accepted
- Date: 2026-07-30
- Scope: local Docker Desktop evidence only
- Depends on: ADR-058 / M3-12 checked evidence

## Context

ADR-058 proves that a known pre-forward HTTP 503 changes no visible table state and that one explicit retry produces one commit. It does not cover the harder outcome where Gravitino commits successfully but Spark does not receive the success response. Blindly submitting the logical write again can create a duplicate snapshot and row.

Iceberg `1.6.1` maps table-commit HTTP `500`, `502`, and `504` responses to `CommitStateUnknownException`. HTTP `503` is a generic service failure instead; a discarded local attempt confirmed that it can trigger staged-file cleanup after the provider has committed. That attempt was cleaned up and is not retained as accepted evidence.

## Decision

Reuse the fingerprinted M3-12 PostgreSQL, Gravitino, MinIO, identity, namespace, and suspended Spark Job runtime without modifying its files. Before releasing the Job, replace only its ConfigMap probe with the M3-13 probe.

The Spark driver loopback proxy forwards one armed table commit to Gravitino. After the provider returns HTTP 200, the proxy drops that response and returns HTTP 504. One transport retry is suppressed with the same unknown-state response. Spark then performs read-only table refresh and verifies the intended row, one child append snapshot, and one additional referenced Parquet. The decision is `committed_do_not_resubmit`; no second logical write is issued.

## Evidence

- Baseline: 1 append snapshot, 2 rows, 1 referenced Parquet.
- Uncertain commit: exactly 1 provider forward, provider status 200, exactly 1 dropped success response, and 1 suppressed transport retry.
- Reconciliation: 2 parent-linked append snapshots, 3 rows including `spark-uncertain-commit`, 2 referenced Parquet, `readback_attempts=1`, and `write_resubmitted=false`.
- Direct MinIO inventory: 2 data files, 3 metadata JSON files, and 4 Avro manifest files; 9 objects total.
- Gravitino bounded API readback remains valid; catalog creation remains denied with 403.
- Spark Job completed `1/1`; namespace, both persistent volumes, and port-forwards were removed.
- Contract fingerprint: `7a8d75a1d6b4558b982c6c3242d8d356c5046955f8aae7a45e5c297b6f4d4132`
- Evidence fingerprint: `d6462fff78d07047311b1f715d5f2c7f08c0ce8fbdd5c8b26a3d95ddc3474786`
- Dependency evidence fingerprint: `39571cdac1e4043bcfc2d03a73b2b12ff925210daf8ae36bc640b8cb14d89401`

## Consequences

This proves a deterministic local post-forward commit-state-unknown path and a no-resubmit readback decision for one append. It does not provide a durable production reconciliation controller, operation key ledger, crash recovery between exception and readback, concurrent-writer proof, arbitrary mutation conformance, network exactly-once, protected identity/TLS, production object storage, cancel/lineage, Flink, full Spark conformance, production ingestion, or production readiness. The broad `spark_reconcile_verified` and all production claims remain `false`.
