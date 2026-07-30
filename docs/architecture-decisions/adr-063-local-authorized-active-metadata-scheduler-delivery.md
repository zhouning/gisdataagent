# ADR-063: Local authorized Active Metadata scheduler delivery

- Status: Accepted for local AR-1 verification
- Date: 2026-07-30
- Owners: Metadata Platform / Data Platform / Security
- Related decisions: ADR-023, ADR-024, ADR-025, ADR-026, ADR-027, ADR-060, ADR-061, ADR-062

## Context

ADR-062 ends with one content-bound authorization and one pending
DolphinScheduler dispatch in the same PostgreSQL transaction. That proves the
promotion boundary but not that the existing provider adapter and leased
command consumer can deliver this exact command to a real scheduler, recover
the correlation variables, and project provider state back into GDA Control.

The next slice must close that local control-loop gap without turning a
standalone development server into production evidence. It must also preserve
the platform terminal-state rule: scheduler `SUCCESS` is attempt evidence, not
permission to mark a `PlatformRun` succeeded.

## Options considered

| Option | Benefit | Cost / risk | Decision |
|---|---|---|---|
| Add an HTTP mock around the adapter | Fast and deterministic | Repeats unit coverage and proves no provider compatibility | Rejected |
| Execute the metadata projection against OpenMetadata/Gravitino | Demonstrates a business mutation | Conflates scheduler delivery with provider authorization, rollback, and ingestion | Rejected |
| Submit a no-side-effect workflow to official local DolphinScheduler and read it back | Proves the exact adapter/consumer/provider boundary while keeping mutation scope closed | Requires ephemeral scheduler/database provisioning and bounded polling | Accepted |

## Decision

M3-17 uses the official ARM64
`apache/dolphinscheduler-standalone-server:3.4.2` image with ID
`sha256:485a1b37dd1c4088c8c8335f9fccbd229e5e703c32e21f318eb00cbb60b1af9d`.
The rehearsal creates an ephemeral standalone container, project, API token,
workflow, and PostgreSQL database. Token and login session values remain only
in memory and are never written to evidence.

The checked M3-16 evidence supplies the path-free Chongqing dataset inventory
and source ResourceVersion content fingerprint. M3-17 constructs a new
provider-native `PlatformDefinitionVersion`, compiles a single Shell task that
only emits a log line, publishes and releases the workflow, and converts the
returned project/code/version/compiled fingerprint into the immutable
DolphinScheduler binding Artifact.

That exact binding is referenced by a new accepted Run, allow PolicyDecision,
independent ApprovalRecord, and independent
`MetadataActivationAuthorization`. Migration 101 and the existing gateway then
atomically append the authorization and pending command. Exact authorization
replay creates nothing.

The existing `DolphinSchedulerCommandConsumer` claims the command and calls the
existing `DolphinSchedulerAdapter`; the rehearsal does not introduce another
queue or scheduler. Provider terminal-state polling is bounded by an explicit
timeout. The provider instance must return every controlled GDA definition and
Run correlation variable exactly, and a correlation scan must find exactly one
matching instance.

The adapter records one `submitted` and one `success` attempt observation with
one external correlation. Reconciliation of provider `SUCCESS` moves the Run
to `reconciling`. Only the separate evidence-gated platform success finalizer
may later produce `succeeded`; M3-17 deliberately does not call it.

## Real data boundary

The same Chongqing central-city historical cultural district bundle remains the
acceptance input: 8 Shapefile components, 20 `PolygonZ` features, 33 fields,
EPSG:4490, and content fingerprint
`fd474fd65c8e4a71da241eb3fd07748ca3b972fbd2d3c32833376dbe71104007`.
The source path and source files are not committed, and CI validates only the
checked inventory and evidence.

Real data is required here because a synthetic hash would not prove continuity
from discovered spatial content through ResourceVersion, activation request,
authorization, Run, scheduler correlation, and attempt evidence. Reopening the
raw Shapefile is unnecessary for every downstream slice once that content
inventory is checked, hashed, and validated as a dependency.

DEM, roads, CLCD, buildings, population, POI/AOI, commuting, search index, TAP,
and township boundaries remain valuable for later raster, temporal, scale, and
multi-source conformance. They should be introduced only when the next claim
needs their specific structure; loading the entire corpus into every control
plane rehearsal would add cost without increasing the claim strength.

## Consequences and trade-offs

- The local workflow definition and workflow instance are real scheduler
  control-plane mutations. `provider_mutations_executed=false` refers narrowly
  to governed metadata/data providers: no OpenMetadata, Gravitino, lakehouse,
  legacy, or source dataset mutation was authorized or executed.
- Standalone uses its development identity and embedded runtime. It proves API
  compatibility, not protected workload identity, tenant isolation, durable
  scheduler metadata, HA, upgrade, backup/restore, or production capacity.
- Readiness and terminal state use bounded polling instead of fixed delays.
  Host load protection can delay command consumption, so the explicit terminal
  timeout is ten minutes.
- The container and temporary database are removed on success and exception;
  cleanup is part of checked evidence.
- Workflow creation precedes binding-bound authorization. A production
  definition publisher must be separated from the protected promotion
  controller and must provide durable provider identity evidence.

## Local verification

The final rehearsal produced one authorization, one claimed/completed dispatch,
one successful provider instance, two observations (`submitted`, `success`),
one external correlation, and exact read-back of six controlled GDA variables.
The final PlatformRun status was `reconciling`, never `succeeded`. Both the
standalone container and temporary PostgreSQL database were absent after the
run.

- Contract fingerprint:
  `dcf97c8fa002e9fe6b6bc3a7603ee2ebd5ddb053544801ce35143a095e648edb`
- Evidence fingerprint:
  `00d4ea062c40f8d97557eadc357a36c6d1ccd56e12a94a44694113681e5d55f4`
- M3-16 dependency fingerprint:
  `6ae387240e3bcebaafe2ad7acc73f4e09d53df2e73b2ec63cd92edbc262d831e`

`deployment_applied`, `production_workload_identity_verified`,
`provider_apply_authorized`, `provider_mutations_executed`,
`production_scheduler_submission_verified`, `production_ingestion_verified`,
and `production_ready` remain `false`.

## Revisit triggers

Revisit when a protected identity can publish and submit the same immutable
binding in staging, when DolphinScheduler metadata moves to an independently
backed-up PostgreSQL service, when worker lease/restart and callback failure are
injected against the deployed consumer, or when a separately authorized
idempotent metadata projection is ready to prove provider mutation and
read-back without weakening the platform success gate.
