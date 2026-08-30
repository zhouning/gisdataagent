# ADR-227: Managed Martin Warmup Command and Atomic Settlement

## Status

Accepted

## Date

2026-08-22

## Context

Migration 220 defines the immutable, release-bound GIS endpoint warmup receipt.
ADR-226 proves that the Martin origin can execute the exact three-coordinate
sample set, but an adapter certificate alone does not connect that evidence to
the platform's Run lifecycle. Without a managed path, admission, provider
execution, evidence persistence and pointer-gate receipt recording could drift
into separate state machines.

The platform already has a tenant-scoped `PlatformRun` and shared
`platform_command_outbox`. The worker must run outside the request process,
survive ACK loss, retry provider outages and fail closed on contract drift,
while leaving Martin read-only.

## Decision

Migration 221 adds `gis_service.endpoint_warmup` to the existing command type
allowlist and provides two controlled database functions:

- `finalize_gis_service_endpoint_warmup_success(...)` validates the admitted
  execution plan, exact Martin observation, evidence Artifact, passed
  QualityResult, source-to-definition LineageEvent and RunSuccessEvidence, then
  records the migration 220 receipt in the same transaction.
- `fail_gis_service_endpoint_warmup_command_terminal(...)` converges a
  deterministic contract failure to `Run=failed` and `Command=failed` without
  manufacturing provider evidence.

`PlatformGateway.admit_gis_service_endpoint_warmup_run(...)` creates the Run,
execution-plan Artifact and shared outbox command atomically. The managed
`GISServiceEndpointWarmupConsumer` claims that outbox row, advances
`accepted -> dispatching -> running`, calls the private Martin origin through
`MartinVectorTileProvider`, publishes a content-verified receipt, builds the
five evidence records and calls atomic settlement. Two receipt profiles are
supported: `local` writes a single-host, write-once file; `s3` writes a stable
credential-free `s3://bucket/prefix/tenant/run/...json` identity with
conditional create, then requires versioning and Object Lock default retention.
The S3 profile records `VersionId` and normalized `ETag` in the Artifact
manifest and performs HEAD/GET against that exact version, checking bytes, size,
content type and SHA-256 metadata before settlement. AWS credentials remain in
the worker's standard SDK chain and never enter a Run, plan, receipt or status
file. A settled Run is reconciled before ACK, so an ACK lost after commit only
completes the command and never executes Martin a second time. Provider
unavailability uses bounded retry; identity, plan, endpoint, release, catalog,
sample-set or receipt-storage contract drift is terminal.

The long-running `GISServiceEndpointWarmupWorker` supplies configuration,
lease/request budgets, status-file observability and SIGTERM handling. Martin
cannot activate an endpoint, mutate the active pointer or write the receipt
table directly.

## Options Considered

| Option | Result | Reason |
|---|---|---|
| Create a second warmup queue and Run state machine | Rejected | duplicates tenant, lease, replay and evidence semantics already provided by the PlatformRun/outbox |
| Let Martin or its worker write the 220 receipt directly | Rejected | makes replaceable provider runtime an authority and bypasses atomic evidence gates |
| Execute warmup synchronously in the admission request | Rejected | couples request latency and provider outage to control-plane writes; no durable redelivery |
| Reuse shared outbox with a dedicated finalizer | Chosen | preserves one command delivery contract while keeping the Martin-specific evidence gate explicit |

## Trade-offs Accepted

- The first managed implementation is Martin-specific; GeoServer, ArcGIS,
  Gateway, Redis, CDN and GeoWebCache require separate adapters and contracts.
- The local receipt store remains a single-host compatibility profile. The S3
  profile provides version-bound evidence on MinIO/S3 but does not by itself
  provide multi-replica worker HA/RTO, bucket replication, cross-region DR or
  automatic incident/SLO handling.
- Worker leases and bounded request budgets protect the command but do not by
  themselves provide multi-replica HA or an SLO.

## Verification

The disposable PostgreSQL managed-worker certification covers admission replay,
shared-outbox claim, HTTP adapter behavior, five evidence records, atomic Run
success plus migration 220 receipt, receipt-file/content binding, terminal
contract failure, forced-RLS and least-privilege checks. Report:
`.tmp/gis-service-endpoint-warmup-worker-certification/report.json`, SHA-256
`9935ed85622c53b412be4f69cd1e3e2458ff14b59d86147350f0f2babd9dbd5f`.

The real-container certification composes the same managed consumer with the
existing Martin active-release fixture. It applies migration 221, starts
`ghcr.io/maplibre/martin:v0.18.0`, reads `0/0/0`, `1/1/0` and `2/3/1` as
non-empty HTTP 200 MVT responses, claims one shared-outbox command, settles
`Run=succeeded` and `Command=done`, records one observation, Artifact,
QualityResult, LineageEvent and migration 220 receipt, and verifies
receipt-file SHA equality. Report:
`.tmp/martin-managed-warmup-certification/report.json`, SHA-256
`393ff5d09e4cd97ab5788f36e4c51ed60bfd3ce2eb451f839c00da6444cd4a10`.

The S3 store unit and worker tests cover conditional first publication,
same-byte replay, different-byte conflict, exact VersionId/ETag HEAD/GET
read-back, missing or invalid VersionId, metadata/size/content/version drift,
location validation, versioning/Object Lock/retention probes, mutually
exclusive local/S3 configuration and credential-free worker status. These are
contract and fault-path tests; they are not described as real object-store
evidence.

The isolated real-environment certification composes the same managed consumer
with disposable PostgreSQL/PostGIS, `ghcr.io/maplibre/martin:v0.18.0` and
`minio/minio:RELEASE.2025-04-22T22-12-26Z`. It passes 18/18 checks: the three
real MVT reads settle the five database evidence records and a version-bound S3
Artifact; exact-VersionId metadata and bytes are read back; Object Lock
governance retention is present; a typed same-content replay returns the same
URI, SHA, size, VersionId and ETag while the object still has exactly one
version; different content is rejected; the scoped writer cannot write outside
the configured prefix or bypass retention. The disposable bucket, MinIO
container and Martin/PostGIS fixture are all cleaned up. Report:
`.tmp/martin-managed-warmup-s3-certification/report.json`, SHA-256
`6ed8e487b7f6b6c1520183368b32bbc52d87dd345280f2a4ecb3848f8fc1b094`.

The development database audit after applying 221 is `221/221 in_sync`; both
catalog and database fingerprint are
`5ebdd1e1e9082b1455fc36a7058b62f01e01fbccef4183925a2a4c444fa508fc`.

## Consequences

The Martin provider-origin warmup path is now an executable, replayable
PlatformRun rather than a fixture-only certificate. Cutover and rollback can
consume a receipt whose producer, sample set and release identity are tied to
one atomic settlement.

This does not mean the active consumer Gateway or any shared cache was warmed.
Production bucket replication, worker HA/RTO, deployment rollout, automated
Incident/SLO handling, provider rebuild/health refresh and non-Martin adapters
remain AR-4 work.

## Revisit Trigger

Revisit when a second provider, replicated receipt store, multi-replica worker
deployment or measured ServiceSLO requires a provider-neutral command payload,
cross-provider compensation or a new durability/lease contract.
