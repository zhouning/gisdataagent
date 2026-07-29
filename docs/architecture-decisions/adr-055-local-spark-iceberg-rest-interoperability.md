# ADR-055: Local Spark and Gravitino Iceberg REST Interoperability

**Status**: Accepted

**Date**: 2026-07-29

**Decision owners**: Metadata Platform, Data Engineering, SRE, Platform Architecture

**Related decisions**: [ADR-006](adr-006-openmetadata-governance-and-active-metadata-platform.md) · [ADR-052](adr-052-local-gravitino-basic-bounded-provider-identity.md) · [ADR-054](adr-054-local-gravitino-jdbc-catalog-restart-continuity.md)

## Context

M3-8 proved authenticated Gravitino JDBC catalog continuity across controlled PostgreSQL and Gravitino restarts. It did not prove that Spark can use that catalog through a standard engine protocol. ADR-006 requires real Spark/Flink create, read, write, schema evolution, snapshot, cancellation, reconciliation and lineage conformance before Gravitino can become the sole production catalog for those engines. Trino success or provider documentation cannot substitute for that evidence.

The next bounded step is real Spark 3.5 interoperability through Gravitino's standard Iceberg REST server. It must reuse the same JDBC database and warehouse as the Gravitino API, preserve the M3-6 authorization denial, and prove bidirectional metadata visibility. It is not the complete ADR-006 conformance suite.

## Decision

### 1. Use one isolated same-node catalog boundary

The rehearsal creates only `gda-metadata-spark-interop` in Docker Desktop Kubernetes. PostgreSQL stores Gravitino entities and the separate Iceberg JDBC catalog. A Gravitino `1.3.0` StatefulSet runs the authenticated API and the bundled Iceberg REST `1.11.0` server as two containers. They mount the same local warehouse PVC and use the same PostgreSQL `iceberg` database.

Spark `3.5.0` with Iceberg runtime `1.6.1` runs as a suspended Job that is released only after Gravitino creates the table. The Job, Gravitino and PostgreSQL are pinned to `desktop-worker`; Spark and Gravitino mount the same `ReadWriteOnce` warehouse PVC. This deliberately avoids adding object storage to the first interoperability slice, so the result applies only to one local node and failure domain.

No Secret is committed. Administrator, bounded-user and database materials are generated for one run and excluded from the observation. Dedicated ServiceAccounts disable token automount. The namespace and its dynamically provisioned volumes must be absent before evidence can pass.

### 2. Keep authenticated control and engine protocol claims separate

The Gravitino API uses the built-in Basic IdP and authorization. The bounded role contains exactly `USE_CATALOG` on `lakehouse`, plus `USE_SCHEMA` and `CREATE_TABLE` on `lakehouse.published`. That user creates and reads `gda_spark_interop_probe`; catalog creation must return 403 before Spark runs and again afterward.

Spark connects to `http://gravitino-persistence:9001/iceberg`, the standard Iceberg REST endpoint. This local endpoint is unauthenticated HTTP. The authenticated Gravitino create/read and denial checks do not turn Spark's connection into protected workload identity, OIDC, TLS or production provider authorization evidence.

### 3. Require cross-client data and metadata verification

The Spark Job must:

- read the zero-row table and required `probe_id` column created by Gravitino;
- append two deterministic rows through Iceberg REST;
- add nullable `quality`, then append a third deterministic row;
- read the exact evolved schema and three current rows;
- observe two append snapshots and time-travel to the first snapshot;
- emit one structured result whose Spark, Iceberg, catalog URI and table identity match the checked profile.

After the Job succeeds, the bounded Gravitino user must read back the new `quality` column from the same JDBC catalog. Evidence binds the Docker host image index and the Kubernetes ARM64 manifest identity separately, because those runtimes report different but legitimate identifiers for the Spark image.

### 4. Do not promote the result to full conformance

Evidence may set these local claims to true: `local_spark_iceberg_rest_interoperability_verified`, create/read/write, schema evolution, snapshot/time-travel, Gravitino API metadata readback and same-node shared-PVC verification.

`spark_conformance_verified` remains false because cancellation, reconcile and production lineage were not exercised. Flink conformance, persistent production identity binding, protected workload identity, OIDC, TLS, object-store durability, production ingestion and `production_ready` also remain false.

## Verification

The final Docker Desktop rehearsal produced contract fingerprint `a78b95d36a6a5d5f4b5e303be21263d00fdd7102c3a70ce282ba69f2d8cdcd2e` and evidence fingerprint `50f9d0021db11e22364697d1ad8928ee068d28dc8046556bbca1a4e1c819f8e0`.

- the bounded Gravitino user created/read the table and received 403 for catalog creation before and after Spark;
- Spark read the Gravitino-created table, committed two append snapshots, evolved the schema and read three exact rows;
- time travel to the first snapshot returned only `spark-a` and `spark-b`;
- Gravitino read back the Spark-added nullable `quality` column;
- Spark, Gravitino and PostgreSQL ran on `desktop-worker`, and Spark/Gravitino referenced the same warehouse PVC;
- the Spark Job completed once using the checked ARM64 manifest, all ServiceAccounts had token automount disabled, the port-forward stopped, and the namespace/PVs were deleted.

Focused tests cover profile and dependency drift, committed Secret rejection, suspended Job/security/resource requirements, engine image and PVC identity, REST readiness, deterministic rows, snapshot operations, time travel, API schema readback, authorization denial, cleanup, sensitive material, evidence tampering and production overclaim. CI validates the checked evidence without running Kubernetes; the live rehearsal remains an explicit local operator action.

## Consequences

**Positive**: the catalog path now has real Spark 3.5 create/read/write, schema evolution, snapshot and bidirectional metadata evidence through the standard Iceberg REST protocol. Trino or documentation is not used as a proxy.

**Negative**: all components share one Docker Desktop node, one local RWO PVC, Basic credentials and unauthenticated HTTP. This does not test object storage, multiple Spark executors, cancellation, reconcile, OpenLineage, tenant isolation or failures during commits.

**Mitigation**: keep the independent authenticated Iceberg REST provider as the production fallback required by ADR-006. The next conformance slices must move the warehouse to the selected object store, use protected identity/TLS, add multi-node Spark/Sedona and Flink, and test cancel/reconcile/lineage plus failure injection.

**Revisit trigger**: Gravitino, Spark or Iceberg version changes; catalog or warehouse implementation changes; production authentication is selected; or the full ADR-006 conformance suite is introduced.
