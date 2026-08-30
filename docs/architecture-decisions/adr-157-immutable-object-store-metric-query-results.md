# ADR-157: Immutable Object-Store Results for Metric Queries

**Status**: Accepted

**Date**: 2026-08-05

**Related**: ADR-001, ADR-095, ADR-154, ADR-155, ADR-156

**Amended by**: ADR-159

## Context

ADR-156 made the PostGIS metric-query worker deployable, but its result Artifact remained a
`file://` path on an RWO PVC. That path was unavailable outside the pod storage topology and forced
single-writer rollout semantics. The platform already has boto3 and MinIO/S3 infrastructure, but
the user-file `StorageManager` exposes mutable upload methods, boolean error results and no
conditional-create or exact read-back contract. Treating it as an immutable evidence publisher
would overstate its guarantees.

Metric-query command recovery can execute a provider more than once. A result backend therefore
must bind one stable Run identity to exactly one byte sequence, return a credential-free URI and
distinguish a temporary provider failure from an immutable identity conflict.

## Options Considered

| Option | Benefits | Costs and risks | Decision |
|---|---|---|---|
| Keep the RWO PVC | No object-store dependency | Pod-topology URI, no horizontal ownership model | Rejected for the default lakehouse profile |
| Upload through `StorageManager` | Reuses a broad facade | Mutable upload and swallowed-error semantics do not prove immutable evidence | Rejected |
| Add a new Artifact service or queue | Central policy surface | Duplicates the existing command and storage infrastructure before scale requires it | Rejected |
| Add a narrow result-store port with local and S3 implementations | Preserves lightweight mode and adds only required guarantees | One more provider contract and S3 read-back cost | Chosen |

## Decision

`MetricQueryResultStore` is the narrow publication boundary used by
`PostGISMetricQueryProvider`. `LocalMetricQueryResultStore` retains the lightweight/disposable path
and now uses write-once filesystem linking instead of overwrite. `S3MetricQueryResultStore` writes
to the deterministic key
`{prefix}/{tenant_id}/{run_id}.json` using `If-None-Match: *`. A successful create or a precondition
race is followed by an exact object read-back; size and SHA-256 must match the canonical JSON bytes.
Same-content replay returns the same URI. Different bytes at the stable key are a terminal provider
contract error and are never overwritten. Transport, authorization and availability errors become
redacted transient provider errors so the existing `PlatformCommand` retry authority remains in
control.

The Artifact URI is the stable credential-free `s3://bucket/key`; endpoint URLs, signed query
parameters and credentials never enter the Artifact, worker status or safe configuration summary.
The stored object carries the same SHA-256 as metadata, but metadata does not replace byte-level
read-back verification.

The worker selects `local|s3` explicitly. S3 bucket and prefix are validated, local and S3 settings
cannot be configured simultaneously, and boto3 uses bounded connect/read timeouts with SDK retries
disabled because command recovery owns retries. Lease and health budgets include conditional put,
read-back and bucket probe time. Each cycle probes the result bucket after PostGIS and before
claiming a command; an unavailable bucket makes readiness fail closed without taking command
ownership.

The optional Kubernetes profile uses a dedicated result bucket and credential keys, grants no
direct Secret manifest, removes the result PVC and adds only MinIO port 9000 to worker egress. The
writer contract requires `ListBucket` on the dedicated bucket and `GetObject`/`PutObject` under the
configured prefix, with no `DeleteObject` or user-upload access. The Deployment remains one replica
with `Recreate` until query concurrency and database capacity have measured SLO evidence.

## Verification

- Result-store, provider, worker and deployment focused tests pass 44/44. They cover local
  write-once replay/conflict, S3 conditional create and exact read-back, unsafe location rejection,
  failure redaction, provider error classification, credential-free configuration, bounded client
  construction, pre-claim probing, Secret refs, PVC removal and exact Postgres/MinIO egress.
- The shared control-plane regression passes 203 tests with two optional-DSN tests skipped.
- `scripts/certify_metric_query_s3_result_store.py` passes 12/12 checks against disposable MinIO
  `RELEASE.2025-04-22T22-12-26Z`. A random scoped writer can probe, conditionally create and replay
  one canonical result; different content is rejected, exact bytes/content type/SHA metadata are
  verified, writes outside the prefix and deletion are denied, and the object survives the denied
  delete. The random bucket and container are removed and the report contains no runtime secret.
- Ruff, Python compilation, offline Kustomize rendering and diff checks remain release gates.

## Consequences

- Metric result Artifacts are addressable by every authorized cluster consumer and no longer depend
  on a worker PVC.
- At-least-once command recovery cannot silently replace an existing result with different bytes.
- The local backend remains available for disposable certification and lightweight deployments.
- Exact read-back adds one object GET and bounded latency per new or replayed publication; this is
  accepted until provider-native checksums have equivalent cross-provider certification.
- Bucket versioning, retention/lock and exact object-version evidence are added by ADR-159. This
  does not prove a Kubernetes rollout, cloud S3/OBS/GCS portability, credential rotation,
  backup/restore, multi-replica capacity, result retrieval API,
  distributed result cache, cancellation, `MetricObservation` or intelligent attribution.

## Revisit Trigger

Replace full read-back only when a provider checksum contract is certified across every supported
object store. Increase replicas or change rollout strategy after PostGIS and object-store
concurrency/latency SLOs pass. Promote the profile only after a live sandbox and staging rehearsal
prove scoped identity rotation, NetworkPolicy enforcement, retention, backup/restore and command
recovery across pod termination.
