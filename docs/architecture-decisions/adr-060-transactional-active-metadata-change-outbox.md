# ADR-060: Transactional Active Metadata Change Outbox

- Status: Accepted for local AR-1 verification
- Date: 2026-07-30
- Owners: Metadata Platform / Data Platform

## Context

The Metadata Fabric can reconcile provider state, generate projection plans,
persist provider bindings, and deliver OpenLineage. It did not yet have an
authoritative change signal connecting a newly registered ResourceVersion to
an Active Metadata action. Polling the ledger would lose producer intent,
while creating an event after the version commit would permit missing events
and fabricated historical backfill.

## Decision

For the first event type, `resource_version.registered`, create the
ResourceVersion and its deterministic `MetadataChangeEvent` in one PostgreSQL
transaction. The event ID is derived from the ResourceVersion ID, and the
event fingerprint binds tenant, resource/version identity, predecessor,
content checksum, authenticated producer, workload consumer, and occurrence
time.

Store delivery state in migration 099 under tenant-forced RLS. The gateway may
only select and insert directly; claim, complete, and fail transitions use
security-definer functions with workload scoping, worker ownership, leases,
bounded attempts, retry delay, and terminal finality. Exact replay creates
nothing. If only the ResourceVersion already exists, the transaction fails and
does not synthesize a historical event.

The consumer output is a deterministic `metadata_fabric.projection_plan`
activation intent. It explicitly carries
`provider_apply_authorized=false`, `provider_mutations_executed=false`, and
`production_ingestion_verified=false`. This slice adds no resident worker or
scheduler. A later managed consumer must submit authorized work through
DolphinScheduler rather than execute provider mutations itself.

## Consequences

- Active Metadata now has a durable event spine tied to the platform version
  authority instead of a catalog polling convention.
- Delivery is at least once. Event and activation fingerprints provide stable
  idempotency; they do not claim network exactly once.
- Existing ResourceVersions remain historical records and are not silently
  backfilled with events.
- Provider policy, production workload identity, protected scheduling,
  production ingestion, and provider mutation evidence remain future gates.

## Local Verification

The checked PostgreSQL 16 evidence proves atomic registration, exact replay,
consumer scoping, wrong-worker rejection, retry, lease-expiry reclaim,
processed finality, tenant isolation, forced RLS, direct update/delete denial,
and rollback of a legacy-version event attempt. It records one authoritative
event, three delivery attempts, contract fingerprint
`3429cd1d7fc5015dab7dfd27b3972c4628238bc18d13c76ad28bb16697898e75`,
and evidence fingerprint
`d85a4575a6103e2f7107f8e11153c080a430e82f6cf6db547295f14ef909e96a`.

This is local transactional evidence only and does not establish production
Active Metadata readiness.
