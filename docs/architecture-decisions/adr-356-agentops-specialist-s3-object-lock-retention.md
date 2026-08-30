# ADR-356: Specialist Artifact content requires S3 Object Lock retention

## Status

Accepted and verified for the bounded disposable MinIO specialist-content rehearsal.
Production object-store replication, cross-region recovery, identity rotation, HA/DR,
and production readiness remain open.

## Context

ADR-354 and ADR-355 established the durable recovery path for MMFE/GWM specialist
operations: PostgreSQL owns the operation receipt, retry budget and Artifact identity,
while a shared versioned S3/MinIO content plane holds the bytes. Exact `VersionId`
binding prevents a replacement worker from reading a later object version. Versioning
alone does not prevent an operator, cleanup job, or over-privileged worker from deleting
that version while a terminal receipt still points at it.

The live reconciler therefore needs a startup gate that checks the content-plane
immutability controls before it polls Temporal. A missing or unsupported S3 control must
be a configuration failure, not a degraded runtime mode.

## Decision

1. `S3ArtifactContentBackend` exposes a read-only `probe()` for bucket versioning.
2. When `require_object_lock_retention=True`, the probe additionally requires:
   - bucket versioning `Enabled`;
   - Object Lock `Enabled`;
   - a positive default retention in `GOVERNANCE` or `COMPLIANCE` mode.
3. The managed specialist reconciler always enables this requirement for `s3`/`minio`
   backends. An explicit false setting is rejected before Temporal polling.
4. Filesystem content remains available only for disposable/local profiles; it does not
   claim object-lock semantics.
5. Artifact manifests continue to bind the exact `VersionId`; Object Lock is an
   additional retention control, not a replacement for PostgreSQL Artifact authority.

## Trade-offs

| Choice | Result |
|---|---|
| Require only VersionId | Easier provider compatibility, but a receipt can point at a deleted version. Rejected for live specialist S3 workers. |
| Require Object Lock + positive default retention | Startup can fail when a provider/profile is not configured, but recovery evidence remains durable and deletion is controlled. Adopted. |
| Let the worker set per-object retention | Requires broader write/admin permissions and creates a race before retention is applied. Rejected; bucket default retention is the admission contract. |

## Verification

The following focused checks pass:

- `data_agent/test_agentops_specialist_providers.py` covers enabled, suspended,
  disabled-lock and missing-retention probes.
- `data_agent/test_agentops_temporal_reconciler_worker.py` proves a bucket without
  Object Lock is rejected before durable authority wiring.
- `scripts/certify_agentops_specialist_s3_object_lock.py` runs against a disposable
  MinIO bucket created with Object Lock and one-day Governance retention. It verifies
  specialist probe, exact VersionId capture/readback, retention application, root
  deletion rejection for the retained version, survival after the rejected delete, and
  scoped-writer retention-bypass rejection. Cleanup removes all object versions and the
  bucket.

Report: [`agentops_specialist_s3_object_lock_2026-08-30.json`](../reports/agentops_specialist_s3_object_lock_2026-08-30.json)

- `report_sha256`: `fb5b3d74b6044a67281af86b5cd700cb40cddcdf3f5082ccb9bc5c6813399aed`
- file SHA-256: `08ac61734fb02052694359b3b4f697d8df60856c3fe1256f84b7b888f349f21e`
- all 9 checks passed; `production_readiness_claimed=false`.

## Limits

This ADR does not certify bucket replication, cross-region VersionId remapping,
Kubernetes worker HA/fencing, Temporal server HA, backup/RPO/RTO, production workload
identity rotation, or a staging/production rollout. Those remain AR-5 exit gates.
