# ADR-159: Version-Locked Metric Query Result Publication

**Status**: Accepted

**Date**: 2026-08-05

**Related**: ADR-095, ADR-121, ADR-157, ADR-158

## Context

ADR-157 conditionally published a stable metric-query result key and ADR-158 verified its bytes
before issuing a signed GET. Those controls did not make verification and later download one
operation: a new current object version written after verification could be returned by a URL that
named only the key. Artifact SHA-256 evidence detected earlier tampering but did not prevent this
time-of-check/time-of-use race.

The fix must preserve the existing Artifact schema, deterministic credential-free `s3://` URI,
command recovery and modular API. It must not add a result microservice, database migration, queue
or application data proxy merely to carry an object-store identity.

## Options Considered

| Option | Benefits | Costs and risks | Decision |
|---|---|---|---|
| Keep stable-key signing and rely on writer IAM | No new contract | Privileged or accidental overwrite can change a later GET | Rejected |
| Add Object Lock but continue key-only signing | Retains prior versions | GET still follows the current version | Rejected |
| Proxy every result through the API | One verification and transfer path | Doubles bandwidth and makes the API the data-plane bottleneck | Deferred |
| Bind publication, Artifact, verification and signing to one `VersionId` | Closes the overwrite race without new stateful infrastructure | Requires bucket versioning, retention and version-aware IAM | Chosen |

## Decision

`MetricQueryResultStore.put()` returns a narrow `MetricQueryResultPublication` instead of a URI
string. Local publication remains write-once and records only local evidence. S3 publication must
return a non-`null` `VersionId` and normalized ETag. A successful conditional PUT is read back by
its returned version; a same-content replay resolves and reads the current exact version. The
provider places only `gda.s3_object_version.v1` evidence (`version_id` and `etag`) in the existing
result Artifact manifest. Endpoint, signed URL and credentials remain excluded.

Before a worker claims a command, the S3 store requires bucket versioning `Enabled`, Object Lock
`Enabled`, and a positive default `GOVERNANCE` or `COMPLIANCE` retention. Missing configuration or
probe authority fails readiness closed. The writer needs bucket-level `GetBucketVersioning` and
`GetBucketObjectLockConfiguration`, plus prefix-scoped `GetObject`/`PutObject`; it receives no
delete or governance-retention-bypass authority.

The result-access backend strictly parses the Artifact storage evidence. Its HEAD, streamed GET and
SigV4 GET parameters all include the same `VersionId`; HEAD must also return the bound version and
ETag before size, media type, SHA metadata and actual bytes are checked. The API reader needs only
prefix-scoped `GetObject`/`GetObjectVersion` and receives no write or delete authority. The stable
Artifact URI remains key based because the immutable version identity is structured evidence, not
a query parameter hidden inside a URI.

## Verification

- Result-store, provider, worker and result-access focused tests pass 65/65. They cover publication
  receipts, same-version replay, provider manifest propagation, missing/forged evidence, versioned
  HEAD/GET/signing, current-version overwrite isolation, bucket-contract failure and error redaction.
- The metric-query chain plus shared PlatformGateway, Artifact contract and security-ledger
  regression passes 215/215.
- `scripts/certify_metric_query_s3_result_store.py` passes 17/17 checks against disposable MinIO
  `RELEASE.2025-04-22T22-12-26Z`. It proves scoped probing, captured version/ETag, exact-version
  read-back, default governance retention, replay/conflict behavior, prefix isolation, delete and
  retention-bypass denial, and complete bucket/container cleanup.
- `scripts/certify_metric_query_s3_result_access.py` passes 16/16 checks against the same disposable
  MinIO release. After a privileged write creates a different current version with different bytes,
  the old Artifact still verifies and its real signed URL returns the original bytes. TTL, tenant
  binding, signature expiry, reader write/delete denial and cleanup also pass. Reports retain no
  runtime secret or signed URL.
- Ruff, Python compilation and diff checks pass.

## Consequences

- An overwrite of the stable key after verification no longer changes the bytes downloadable from
  an existing Artifact grant.
- Default retention consumes storage until expiry. Environment owners must approve retention and
  lifecycle periods and monitor version growth; this disposable certification does not select a
  production duration.
- `GOVERNANCE` mode permits an explicitly authorized administrator to bypass retention. That role
  remains inside the object-store trust boundary and must be separately audited in production.
- Signed URLs still cannot be individually revoked after disclosure, and the security ledger proves
  capability issuance rather than actual GET consumption. Immediate revocation requires a proxy;
  consumption evidence requires provider access-log reconciliation.
- This is a local disposable MinIO contract certification, not Kubernetes, staging, production or
  cloud-provider rollout evidence. Backup/restore, credential rotation, capacity/SLO and provider
  access-log reconciliation remain open.

## Revisit Trigger

Revisit the full pre-sign byte read when certified provider checksums are cryptographically bound to
the same retained version. Use an audited streaming proxy when classification policy requires
immediate revocation, row/field filtering or synchronous consumption receipts.
