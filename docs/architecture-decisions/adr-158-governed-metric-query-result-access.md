# ADR-158: Governed Access to Metric Query Results

**Status**: Accepted

**Date**: 2026-08-05

**Related**: ADR-095, ADR-123, ADR-153, ADR-157

**Amended by**: ADR-159

## Context

ADR-157 made metric-query results immutable, content-addressed evidence in a dedicated S3/MinIO
location. The stable `s3://` Artifact URI is intentionally credential-free, but it is not a safe
delivery contract for a human, Agent or API consumer. Returning that URI or storage credentials
would bypass tenant and Run ownership checks. Proxying every result through the application would
centralize data transfer and still require a separate integrity and audit policy.

The current PostGIS provider emits bounded canonical JSON results, while the platform already has
tenant-scoped `MetricQueryExecutionAuthority`, `PlatformGateway` Artifact evidence and an immutable
`SecurityEventLedger`. The next slice should reuse those authorities without adding an Artifact
microservice, queue, cache or database migration.

## Options Considered

| Option | Benefits | Costs and risks | Decision |
|---|---|---|---|
| Return `s3://` plus storage credentials | Simple client implementation | Exposes durable authority and bypasses platform audit | Rejected |
| Proxy result bytes through the application | No signed URL at the client | Application becomes the transfer bottleneck and doubles bandwidth | Deferred for policy-required streaming |
| Issue a short S3 GET capability after authorization and verification | Storage serves bytes; API retains policy and audit control | Verification adds one full object read before each grant | Chosen |
| Add a result-access service and token database | Centralized lifecycle and revocation | Premature service and state-machine duplication | Rejected |

## Decision

The platform exposes
`POST /api/platform/v1/metric-query-runs/{run_id}/result-access`. The strict request accepts only an
`expires_in_seconds` value from 60 through 900, defaulting to 300. The response is a non-cacheable
`MetricQueryResultAccessGrant` containing an access ID, Run and Artifact IDs, delivery mode,
media type, size, SHA-256, issue/expiry times and one signed HTTP GET URL. It never returns the
stable storage URI, access secret or independently usable SDK credential. The URL contains only
the provider-required signing parameters for that bounded object GET capability.

`MetricQueryResultAccessService` evaluates the access synchronously inside the existing modular
API. It loads the Run through `MetricQueryExecutionAuthority` under the request tenant and permits
only the exact submitter or an `admin`/`platform_operator`. The Run and metric observation must both
be succeeded and bind one result Artifact. The Artifact must match tenant, Run, Artifact ID, role,
key, result SHA-256, plan Artifact, cache key and execution observations. Missing, cross-tenant,
unfinished or inconsistent evidence fails closed.

The S3 backend accepts only the deterministic managed location
`s3://{bucket}/{prefix}/{tenant_id}/{run_id}.json`. Before signing, it verifies HEAD content length,
media type and SHA-256 metadata against the Artifact, then streams the entire object through
SHA-256 and checks its exact byte count. Metadata alone is not integrity evidence. Only after these
checks does it create a SigV4 GET URL. SDK verification and caller-facing signing endpoints may be
different so an in-cluster MinIO address is not returned to an external caller.

Each successful grant must be appended to the immutable tenant security ledger before the URL is
disclosed. The event records actor, role, access ID, Run/Artifact IDs, TTL, media type, size and
content SHA-256, but never the signed URL or storage URI. An audit outage rejects issuance. Denied
ownership, missing Run and unfinished result attempts are recorded best-effort while remaining
denied even if the ledger is unavailable. The HTTP response uses `Cache-Control: no-store` and
`Pragma: no-cache`.

The API uses a separate S3 reader identity with `GetObject` only under the configured result prefix,
or an equivalent workload-identity chain. It does not reuse or disclose the writer's durable
credential. Explicit reader credentials, when required by a sandbox, use dedicated environment
keys; partial configuration is rejected and provider errors are redacted.

## Verification

- Result-access, execution, planning and result-store focused tests pass 54/54. They cover
  submitter/operator access, non-owner and unknown/cross-tenant denial, unfinished Runs, exact
  Artifact binding, actual-byte and metadata tamper detection, TTL bounds, separate verification
  and signing endpoints, provider error redaction, response non-caching and audit fail-closed.
- `scripts/certify_metric_query_s3_result_access.py` passes 13/13 checks against disposable MinIO
  `RELEASE.2025-04-22T22-12-26Z`: signed GET returns exact bytes and media type; a one-second
  provider signature is valid and then actually expires; tenant-key and 60-900 second policy bounds
  reject invalid requests; a same-size object overwrite with unchanged SHA metadata is detected;
  and the reader cannot write or delete. Random bucket, identities and container are removed, and
  neither signed URL nor runtime secret is retained in the report.
- The shared PlatformGateway/security-ledger/platform-contract regression passes 214 tests with two
  optional-DSN tests skipped. Ruff, Python compilation and diff checks pass.

## Consequences

- Human, Agent and API consumers can obtain a bounded result capability without receiving durable
  object-store authority.
- Run ownership, tenant RLS, immutable Artifact evidence and security audit are now one access path.
- A full object read is performed before every grant. This is acceptable for the current bounded
  JSON provider but must be benchmarked before larger Parquet or raster results use this path.
- ADR-159 resolves the verification-to-download overwrite race by binding Artifact evidence,
  HEAD, byte verification and the signed GET to one retained object `VersionId`.
- Signed URLs cannot be revoked individually after disclosure. The short TTL limits exposure;
  policy requiring immediate revocation must use an audited streaming proxy or provider capability
  with revocation support.
- The security ledger proves capability issuance, not whether the caller consumed the URL. A
  production profile requiring download receipts must ingest provider access logs and correlate
  object key, credential identity and request time, or route delivery through the audited proxy.
- This does not prove Kubernetes or cloud rollout, public endpoint routing, workload-identity
  rotation, production retention/lifecycle approval, backup/restore, access-volume SLO, distributed
  caching, provider access-log reconciliation, result-level ABAC, `MetricObservation` or
  intelligent attribution.

## Revisit Trigger

Replace full read verification only after every supported object provider exposes a certified,
immutable checksum bound to object version and Artifact evidence. Add a streaming proxy when data
classification requires per-request revocation, transformation or field filtering. Add cached
verification only after object versioning/retention and measured access volume provide a safe cache
invalidation key and demonstrate that repeated hashing misses its latency SLO.
