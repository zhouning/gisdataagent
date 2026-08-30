# ADR-199: Immutable Object-Store I/O for DuckDB Blueprints

**Status:** Accepted (deployment contract and scoped acceptance verified;
environment rollout pending)

## Context

ADR-198 moved DuckDB execution out of the API process, but both admitted input
Parquet and provider output still depended on a shared `file://` mount. That
prevents host-independent workers and makes an output URI insufficient proof of
the exact bytes accepted by the control plane. The repository already proves
the required immutable S3 semantics for metric-query results: conditional
create, object VersionId/ETag evidence, exact-version read-back, versioning and
Object Lock.

## Decision

The S3/MinIO Blueprint profile binds each admitted input to a credential-free
`s3://` URI, its ResourceVersion SHA-256 and the PhysicalLocation `revision_ref`
as an exact object VersionId. Admission accepts only deployment-allowlisted
bucket/key prefixes. The worker fetches that exact version into a private local
workspace, enforces the aggregate byte limit while streaming, recomputes the
SHA-256, and only then exposes the Parquet table to DuckDB. DuckDB external
access remains disabled.

Output uses one stable key,
`{prefix}/{tenant_id}/{run_id}.parquet`. Publication uses
`If-None-Match: *`; both create and precondition-conflict paths bind the returned
VersionId/ETag, verify size/media type/SHA metadata, and stream an exact-version
GET to recompute the checksum. A replay may reuse identical bytes but can never
overwrite different bytes. The receipt, Artifact manifest and framework
observation carry the same `gda.s3_object_version.v1` evidence. Migration 201
adds database constraints requiring this evidence for every S3 Blueprint
output.

Object-store dependency failures are retryable and leave the Run nonterminal;
URI, version, checksum, byte-bound and immutable-content conflicts remain
terminal contract failures. SDK retries are disabled and connect/read timeouts
are bounded so the outbox owns retry policy. The API constructs object URIs but
does not require data-plane credentials; the worker owns the S3 client and
readiness probe.

## Compatibility and Security

`file://` remains the default lightweight compatibility profile. S3 endpoints,
credentials and signed URLs never enter execution plans, receipts, Artifacts or
worker status. Worker IAM must be limited to exact-version reads on admitted
input prefixes, conditional writes and reads on the output prefix, and bucket
versioning/Object Lock inspection. Delete and retention-bypass permissions are
not required.

## Consequences

The code contract no longer requires an API/worker shared data mount in the S3
profile, and a successful Run is bound to an immutable output object version.
`scripts/certify_duckdb_blueprint_object_store.py` passed 12/12 checks against a
disposable MinIO with versioning and Object Lock, including an input current-
version change after admission, exact-version execution, conditional output,
same-byte replay, different-byte rejection, exact output verification after a
new current version was written, and complete cleanup. The report
SHA-256 is
`3ab007d9841f1e87c8cfbe68eb58b4d9e6b133ddc8aadd83a18d2c34ae72f199`.

ADR-200 now supplies an optional Compose workload, an optional Kubernetes
Kustomize profile, scoped MinIO identity verification and PostgreSQL + MinIO
ACK-loss recovery through the live release gate. This ADR still does not claim
NetworkPolicy enforcement in a real cluster, multi-replica HA, mid-query lease
heartbeat, staging/production rollout or production SLO evidence.
