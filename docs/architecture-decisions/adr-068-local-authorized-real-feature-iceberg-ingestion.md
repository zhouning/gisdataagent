# ADR-068: Local authorized real-feature Iceberg ingestion

**Status**: Accepted

**Date**: 2026-07-31

**Decision owners**: Data Platform, Metadata Platform, Data Governance, GIS Platform, Security, Platform Architecture

**Related decisions**: [ADR-056](adr-056-local-spark-object-store-interoperability.md) · [ADR-062](adr-062-atomic-active-metadata-authorization-and-dispatch.md) · [ADR-067](adr-067-object-store-runtime-bound-active-metadata-promotion.md)

## Context

M3-21 bound the real Chongqing cultural-district ResourceVersion to a local JDBC/S3 provider runtime, but deliberately created an empty Iceberg table. It proved metadata promotion and restart continuity, not ingestion of source feature rows. The next slice must exercise the real spatial payload without committing the source files, local paths, feature identifiers or geometry bytes.

The source is the same 20-feature EPSG:4490 Shapefile bundle already content-bound in M3-16 and carried through M3-21. M3-22 must preserve that predecessor evidence, create an independent output ResourceVersion candidate and keep provider execution separate from GDA Control authority.

## Decision

### 1. Ingest one bounded real-data slice

M3-22 reads only the checked Chongqing central cultural-district bundle. The local source path is a runtime argument and never enters the plan or committed evidence. The bundle SHA remains `fd474fd65c8e4a71da241eb3fd07748ca3b972fbd2d3c32833376dbe71104007`.

Each input row is normalized to `BSM`, WKB geometry, SRID, four bounds and a canonical row SHA. The ephemeral payload is delivered through an immutable ConfigMap in a fresh namespace. Committed evidence keeps only the bundle inventory, aggregate spatial projection, row hashes and payload hash; it excludes BSM values, WKB and absolute paths.

### 2. Bind authorization to the exact source, output and runtime

The execution-plan Artifact binds source ResourceVersion `a6000000-0000-4000-8000-000000000001`, output ResourceVersion `a6000000-0000-4000-8000-000000000002`, source content SHA, row-set SHA, output content SHA, M3-21 predecessor candidate, target schema and stable JDBC/S3 runtime identity.

One allow PolicyDecision and independent ApprovalRecord authorize `metadata_fabric.ingest_real_feature_slice`. The Spark result must return the exact authorization fingerprint. The table is created by the schema-bounded Gravitino principal; catalog administration remains denied with `403`.

### 3. Require spatial quality, one append and exact replay

One Spark `3.5.0` + Sedona `1.9.0` Job reconstructs geometry through `ST_GeomFromWKB` and verifies all 20 rows for unique identifier, valid geometry, EPSG:4490, positive area and source-matching bounds. It writes the fixed eight-column schema through Iceberg `1.6.1`.

The first execution must append exactly once and produce one snapshot and one Parquet file. An immediate execution of the same plan must be `no_op/0` with identical row hashes, snapshot and data-file projections. Direct S3 inspection must agree with the Spark readback and exact Iceberg schema.

### 4. Keep local evidence non-authoritative

The output ResourceVersion, Artifact, independent QualityResult and LineageEvent are candidates only. They are not written to GDA Control, and the PlatformRun is not finalized. The local MinIO/JDBC runtime uses generated static material over HTTP on one Docker Desktop host and is deleted after the rehearsal.

Therefore protected workload identity, durable production catalog, production object storage, OIDC, TLS, complete Spark/Flink conformance, production ingestion, PlatformRun success and `production_ready` remain false.

## Verification

The local rehearsal recorded:

- 20 unique, valid, non-empty Polygon/MultiPolygon Z features in EPSG:4490;
- row-set SHA `c26ff708f4b6be082327dff63a6a8659420dbc4cab37dea1cac7b40f147512df` and output content SHA `bdc06792e8b935176ee6df6f6f6d4be1535622d54d9b994a778cabfe5a574618`;
- six Sedona quality counts equal to 20;
- first execution `appended/1`, one snapshot, one 20-row Parquet file, followed by immediate `no_op/0`;
- direct S3 inventory of one data file, two metadata JSON files and two Avro manifests, with current snapshot and eight fields matching Spark;
- path-free output ResourceVersion, Artifact, independent passed QualityResult and source-to-output LineageEvent candidates;
- contract SHA `af211f2d2f4830decb9ffe369cd9e7ec2c9349c2e2c8bd789347a6fdc288e1dc` and evidence SHA `42abd82613eaf28cb53c64280258bc75dba6cf841f9a513a4c801a9f798b9899`;
- complete namespace, PVC and port-forward cleanup.

## Consequences

**Positive**: the platform now has checked evidence that a real, content-bound GIS slice can cross authorization, spatial quality, Spark/Sedona execution, Iceberg storage, direct object inspection and path-free version/quality/lineage construction.

**Negative**: the evidence covers only 20 features in a temporary local environment. It does not prove large-volume partitioning, schema evolution for heterogeneous sources, concurrent ingestion, recovery after process loss, production identity/storage or authoritative publication.

**Next gate**: atomically promote the output ResourceVersion, Artifact, QualityResult and LineageEvent candidates through the versioned GDA Control ledger while preserving a non-success Run until the existing terminal evidence gate is satisfied. Production promotion still requires protected identity/TLS/KMS, selected object storage, independent failure domains, backup/PITR, tenant isolation and staging-scale verification.
