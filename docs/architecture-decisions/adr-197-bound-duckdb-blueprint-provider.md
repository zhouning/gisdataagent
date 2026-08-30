# ADR-197: Bound DuckDB Provider for Blueprint Test Runs

**Status:** Accepted (bounded lightweight-profile conformance)

## Context

Blueprint test admission and deterministic evidence generation already used the
shared `PlatformRun`, Artifact, quality, lineage, retry, cancellation and
reconciliation authorities. They did not execute the admitted logical
definition against real input bytes. Treating the deterministic-local receipt
as DuckDB conformance would leave input location, SQL safety, output bytes and
provider metrics unproved.

## Options Considered

1. Keep the deterministic-local executor as the only implementation. This is
   the smallest option, but it cannot prove input bytes, provider behavior or
   deployable output.
2. Add a bounded synchronous DuckDB/Parquet adapter to the lightweight
   profile. This proves a real execution path while reusing every existing
   control-plane authority.
3. Build the distributed worker and Spark provider first. This is closer to a
   production topology, but adds queueing, cancellation, object-store and HA
   concerns before the portable Blueprint contract has provider evidence.

## Decision

The lightweight profile gets one concrete synchronous DuckDB adapter. A
DuckDB Blueprint must declare the typed portable SQL subset and every admitted
input must have a complete architecture binding whose `PhysicalLocation` is a
content-bound local Parquet file. Admission copies those immutable identifiers,
checksums and the deterministic output URI into the existing execution-plan
Artifact.

The provider reads only those files through PyArrow, verifies their SHA-256,
registers them as in-memory relations, disables DuckDB external access and
accepts one read-only query that references only admitted relations. Output is
bounded, ordered when determinism is required, written atomically as Parquet
and returned as a typed receipt containing the real DuckDB version, row/byte
metrics and output checksum. The provider has no control-ledger credentials.

Migration 199 extends the existing Blueprint success function. The database
accepts the provider receipt only when it binds the same execution plan,
definition, output Artifact, QualityResult and DuckDB observation. The release
gate accepts that database-verified receipt as well as the legacy explicitly
non-production deterministic receipt. No registry, scheduler or Run lifecycle
authority is added.

## Consequences

The platform now has real local DuckDB/Parquet execution and provider-local
deterministic replay evidence. This is not production certification. The
adapter is synchronous, so external cancel/reconcile is not applicable;
DuckDB Spatial is fail-closed unless its extension is preinstalled. Spatial
conformance and the worker deployment contract are completed by ADR-200 and
ADR-201; Spark execution, HA and staging/production rollout remain open gates.

## Trade-offs Accepted

The chosen adapter is intentionally local and single-process. It favors a
small auditable provider boundary and deterministic evidence over horizontal
scale, long-running cancellation and shared storage. PyArrow materializes each
admitted input after enforcing its byte bound, so this adapter is unsuitable
for inputs that approach distributed-processing scale.

## Revisit Triggers

Revisit this decision for remote or object-store inputs beyond the bounded
profile, execution beyond the local limits, external cancel/reconcile semantics,
multiple worker replicas, Spatial extension upgrades, or a production SLO. At
that point the new provider must retain the same execution-plan, Artifact,
quality, lineage and success-authority bindings rather than introduce a second
Run lifecycle.
