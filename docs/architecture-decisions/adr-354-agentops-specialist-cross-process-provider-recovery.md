# ADR-354: Cross-process recovery after a specialist provider commit

## Status

Accepted and verified for the bounded PostgreSQL Artifact-authority rehearsal.
Production worker HA/DR and production readiness are not claimed.

## Context

The specialist executor can lose its Temporal activity response after the provider
has committed its side effect. A replacement worker must be able to distinguish that
case from a provider that was never submitted. Re-running the provider is unsafe: it
can create a second side effect, a second output object, and a second retry-budget
admission. The existing receipt authority (ADR-342) and retry-budget authority
(migration 248) provide the durable state needed for recovery, but the boundary had
not yet been exercised with two independent worker processes and a real provider.

## Decision

The recovery contract is:

1. Worker A submits the provider operation through the PostgreSQL receipt authority,
   writes the output through the PostgreSQL Artifact authority, and records the
   terminal `succeeded` receipt. If the activity response is lost, it returns an
   `unknown` envelope and may terminate; the durable receipt and Artifact remain the
   source of truth.
2. Worker B creates fresh authority/store instances and replays the same request.
   It first observes `operation_ref`; a terminal `succeeded` receipt causes it to
   resolve and validate the existing output Artifact. It does not call the provider,
   append another receipt transition, or request another retry-budget admission.
3. `provider_ref://run_id/tool_call_id` is the retry-budget operation family. Worker
   identity is audit metadata only; replacing a worker cannot reset the budget.
4. The disposable filesystem store may rehydrate an output from its immutable bytes
   and manifest for local rehearsal. Production recovery must use the PostgreSQL
   Artifact authority with a shared content plane (S3/MinIO with immutable VersionId
   binding, or the equivalent governed backend).

No scheduler or provider-internal state is added. Reconciliation remains a read/settle
operation and never submits a second provider operation for an existing receipt.

## Verification

`scripts/rehearse_agentops_specialist_worker_recovery.py` starts a temporary
PostgreSQL database and a shared filesystem content backend. A child worker process
executes the real GWM provider, persists its result, and is then terminated with
`SIGKILL` (exit `-9`). A replacement worker uses fresh PostgreSQL receipt/retry
authority and Artifact-store instances to recover the request.

The 2026-08-29 report passed all four checks:

- worker A died after the provider commit and returned `unknown`;
- worker B recovered the same terminal receipt and output Artifact;
- receipt history remained two rows and the content plane contained one output;
- retry budget remained at one attempt and one admission.

Report: `docs/reports/agentops_specialist_worker_recovery_2026-08-29.json`.
The report's `report_sha256` is
`6c0565388c4e5e54d47bdad3fcb67820c8cd85dff2601b414d97992c080d77c1`; file
SHA-256 is `6ddbf0250cc9036ef7ee65e5ff91a7024f860427b7f998c7be354a0a24b2cb3b`.
The separate retry-budget authority rehearsal also passed all checks; its report
SHA-256 is `97dc0f256903b833b1523de28a3053833cd7004260a01bd8e856140ded37122f`.

Focused specialist provider regression passed `12` tests. Ruff and compileall passed.

## Consequences and limits

This closes the bounded cross-process provider-recovery and worker-replacement retry
budget slice for the real GWM specialist. It does not certify production S3/MinIO
object locking or cross-region replication, Temporal worker deployment HA, lease or
fencing under Kubernetes failure, backup/RPO/RTO, provider permission rollout, or
production readiness. The AR-5 production gates remain open.
