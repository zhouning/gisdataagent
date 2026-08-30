# ADR-151: Canonical Versioned Metric Definition Authority

**Status**: Accepted

**Date**: 2026-08-05

**Related**: ADR-001, ADR-002, ADR-006, ADR-103, ADR-146

## Context

GDA currently exposes metric-like definitions through the static semantic catalog,
`agent_semantic_metrics`, semantic-model YAML, optimization objectives and world-model contracts.
Those surfaces serve different consumers, but none provides one canonical identity, immutable
version, dependency graph and approved publication pointer. Updating the legacy metric table in
place can silently change the meaning of an existing NL2SQL answer or Gold aggregate.

Lakehouse data versions, semantic meaning and physical query execution also have different
lifecycles. A metric must bind an immutable DataProductVersion and semantic-model version without
making PostgreSQL the warehouse or making an external interchange format the GDA write authority.

## Options Considered

| Option | Benefits | Costs and risks | Decision |
|---|---|---|---|
| Extend `agent_semantic_metrics` in place | Small schema change and immediate legacy compatibility | Mutable rows, owner-scoped duplicate names, no approved active version or dependency safety | Rejected |
| Make OpenMetadata or OSSIE the metric write authority | External interoperability and catalog visibility | Provider availability enters publication, GIS semantics remain incomplete, authority is delegated outside GDA | Rejected |
| Add a tenant-scoped immutable GDA authority and project active versions outward | Exact identity, approval, rollback pointer and consumer-safe resolution | A migration path and projection adapters are required | Chosen |

## Decision

Migration 135 establishes `MetricDefinitionVersion` as the canonical write authority. A definition
uses `gda://{tenant}/metric_definition/{id}.v{n}`, is immutable, and contains one structured
`gda.metric_definition.v1` document. The document records:

- canonical/display names, aliases, domain, owner, steward and security classification;
- `semantic_expression_v1` formula, value type, unit, null/distinct policy and aggregation semantics;
- dimensions plus explicit time grain, timezone, spatial grain, CRS and spatial relationship;
- semantic-model measure bindings and immutable source DataProductVersion bindings;
- version-exact metric dependencies, quality policy and materialization policy.

Raw SQL is not an authoritative formula language. SQL generation belongs to a later metric query
compiler and must consume an exact active metric version.

`stage_metric_definition_version` verifies every source against the existing DataProductVersion
ledger and verifies every dependency already exists. It computes the fingerprint in PostgreSQL from
canonical JSONB. Replays preserve the first timestamp and fingerprint; conflicting evidence fails.

Publication uses a CAS active pointer. Activation requires a non-expired, human-decided approved
ApprovalCase with action `metric_definition.activate`, exact version ResourceURN and exact
fingerprint. Every dependency must already be active at its referenced version. Version, activation
and event tables use forced tenant RLS; the gateway has SELECT plus security-definer function access,
not direct INSERT/UPDATE/DELETE.

The platform API provides stage/list, approval request, admin-only activation, active retrieval,
event history and active-only metric resolution. Resolution ranks canonical name, display name and
alias, and fails on ambiguity. This is the safe semantic entry point for later NL2Metric2SQL work.

Legacy registries, MetricFlow-compatible YAML, OSSIE exports, OpenMetadata assets and world-model
contracts become read projections or import candidates. They do not independently activate a metric.

Lakehouse computation remains outside this control plane. Gold/Serving materializations, PostGIS or
DuckDB interactive execution, and Spark/Sedona batch execution must record the exact metric version
and source data snapshot selected by the future query planner.

## Verification

- Eight focused contract tests cover structured GIS semantics, tenant/version identity, immutable
  models, snapshot aggregation safety, statement rejection, active-pointer compilation, pagination,
  API operations and migration least privilege.
- `scripts/certify_metric_definition_authority.py` applies migrations through 135 to disposable
  PostgreSQL 16.14. All 16 checks pass: real DataProductVersion correlation, idempotent staging,
  pending/wrong-action rejection, approved activation, canonical/alias resolution, exact dependency
  activation, append-only events, mutation rejection, gateway write denial and cross-tenant RLS.
- The disposable database and container are removed after certification.

## Consequences

- Newly governed metrics have one identity and one active meaning for humans, agents and APIs.
- A metric cannot publish against a missing lakehouse product version or inactive metric dependency.
- Existing metric surfaces remain operational during migration, but their values are not canonical
  until projected from an active `MetricDefinitionVersion`.
- `semantic_model_version_ref` is structurally required, but a separate immutable semantic-model
  authority is not yet implemented, so migration 135 cannot enforce that reference with a foreign key.
- This increment does not implement metric SQL compilation, Gold materialization, result caching,
  MetricObservation, anomaly detection, attribution runs, OSSIE projection or UI lifecycle screens.

## Revisit Trigger

Revisit when the semantic-model authority can provide a version foreign key, when the metric query
compiler requires a richer expression AST, or when measured query SLOs prove that the existing
PostGIS/DuckDB/Iceberg execution profile needs a dedicated OLAP engine.
