# ADR-127: ArcGIS Ingestion Control and Data Plane

## Status

Accepted

## Context

GIS Data Agent must do more than query a public ArcGIS layer for preview. It
must materialize a bounded, reproducible snapshot into platform-owned storage,
operate independently of an interactive web request, and publish the result as
a governed data asset with version, quality, metadata, and lineage evidence.

The upstream service is read-only and may change while a run is paging. A DMT
layer can contain hundreds of thousands of features, so accumulating an entire
layer in application memory is not acceptable. Public reachability also does
not imply unrestricted republication rights; source access and policy limits
must remain visible in metadata.

## Decision

Use a modular-monolith ingestion subsystem with separate control- and data-plane
responsibilities:

- PostgreSQL `agent_ingestion_definitions`, `agent_ingestion_runs`, and
  `agent_ingestion_batches` are the authoritative operational ledger and
  lease-based work queue.
- The worker first freezes a sorted ArcGIS object-ID snapshot, then reads and
  writes bounded pages. The snapshot hash, batch evidence, counts, and quality
  result make a run reproducible and auditable.
- The raw data-lake representation is an immutable partitioned GeoParquet
  snapshot. Parts and `manifest.json` are staged first; `_SUCCESS` is the commit
  marker and is uploaded last for object storage.
- PostGIS is an optional serving projection. Pages go to a run-scoped staging
  table, then an atomic table rename publishes the complete snapshot.
- A run is cancellable while `queued`, `running`, or `cancelling`. After quality
  validation it atomically enters `committing`; cancellation is then rejected
  while requested sinks, catalog records, and lineage are published.
- A data asset is published only after all requested storage sinks commit.
  `agent_data_assets`, `agent_asset_versions`, and `agent_asset_lineage` hold the
  catalog projection. Technical, business, operational, and lineage metadata
  include storage location, CRS/schema/checksums, classification/quality,
  ingestion policy/run identity, and the source-to-target transformation.
- The platform bridge registers source and target Resources, immutable
  ResourceVersions, and a LineageEvent in `gda_control`. OpenMetadata remains a
  downstream Metadata Fabric projection and does not become ingestion authority.
- Local host development may use the embedded worker, and local Compose may use
  its bounded interval poller as a sandbox convenience. Production Compose and
  Kubernetes set the schedule driver to `external`: DolphinScheduler owns
  calendars, dependencies, complement/backfill, resource queues, and alerts,
  then submits work through the same durable run API with an idempotency key
  stable for the scheduled occurrence. The ingestion worker owns extraction
  leases and batch progress, not production schedule truth.
- Schema changes are owned by the migration runner. Application and worker
  processes never create or alter control tables at runtime.

## Commit and Recovery Semantics

The lifecycle is:

`queued -> running -> committing -> succeeded`

Cancellation follows `queued -> cancelled` or
`running -> cancelling -> cancelled`. Failures may terminate a running or
committing run as `failed`.

Worker ownership is a database lease. An expired `running` or `committing` run
returns to the queue. Re-execution uses the same run ID, deterministic lake path,
run-scoped PostGIS staging name, checksum comparison, version deduplication, and
lineage event identity. A crash may therefore leave an unreferenced committed
sink, but replay converges without publishing a duplicate asset version. Cleanup
of permanently failed orphan snapshots is a separate retention operation.

## Options Considered

Directly loading ArcGIS pages in the web request was rejected because request
timeouts, process restarts, and horizontal scaling would make progress and
ownership unreliable.

Writing only to PostGIS was rejected because it provides a serving database but
not an immutable raw snapshot suitable for replay, audit, and downstream engines.

Writing directly to Iceberg was deferred. GeoParquet is already interoperable
with the platform's geospatial stack and keeps this source adapter focused. A
later curated-zone job may promote committed raw snapshots to Iceberg without
changing source extraction or lineage identity.

A new message broker was rejected for now. PostgreSQL `FOR UPDATE SKIP LOCKED`
and leases solve execution ownership and crash recovery with infrastructure the
platform already operates. They do not replace DolphinScheduler's production
schedule authority. A broker becomes justified only if measured throughput or
cross-service fan-out exceeds this execution queue.

## Consequences

Positive outcomes are bounded memory, durable scheduling, explicit cancellation
and commit semantics, repeatable recovery, platform-owned raw data, and catalog
and lineage integration.

Accepted costs are a PostgreSQL polling loop, temporary local disk while cloud
parts are prepared, and eventual consistency between the authoritative catalog
transaction and optional OpenMetadata projection. Production operators must
size worker scratch storage, configure lifecycle retention for failed snapshots,
bind Resources in OpenMetadata before expecting lineage projection, and review
source licensing before redistribution. Unbound lineage changes remain pending
without consuming provider retry attempts.

## Revisit Triggers

Revisit the queue when sustained concurrency requires more workers than the
database can claim efficiently. Revisit raw GeoParquet when curated consumers
require Iceberg transactions, incremental merge, or time travel. Add incremental
watermark ingestion only after a source exposes a stable edit timestamp or
change-tracking contract; full snapshot remains the safe default otherwise.
