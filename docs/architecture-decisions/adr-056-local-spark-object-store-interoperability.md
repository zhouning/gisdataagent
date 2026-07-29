# ADR-056: Local Spark Object-Store Interoperability

**Status**: Accepted

**Date**: 2026-07-29

**Decision owners**: Metadata Platform, Data Engineering, SRE, Platform Architecture

**Related decisions**: [ADR-006](adr-006-openmetadata-governance-and-active-metadata-platform.md) · [ADR-053](adr-053-production-metadata-fabric-identity-readiness-gate.md) · [ADR-055](adr-055-local-spark-iceberg-rest-interoperability.md)

## Context

M3-9 proved that Spark `3.5.0` can use Gravitino's bundled Iceberg REST server to read and mutate a JDBC-backed Iceberg table. Spark and Gravitino nevertheless shared one `ReadWriteOnce` warehouse PVC on `desktop-worker`, so the result did not prove a storage boundary usable by compute on another node. ADR-055 therefore made an object-store warehouse the next bounded conformance slice.

The next step must preserve the M3-9 data, schema, snapshot, time-travel and authorization checks while removing the shared warehouse volume. It must also verify the resulting Iceberg objects independently of Spark and Gravitino. A local MinIO service can prove the protocol and cross-node topology, but it cannot stand in for a production cloud object store or its failure domains.

## Decision

### 1. Replace the shared warehouse PVC with a local S3-compatible boundary

The rehearsal creates only `gda-metadata-spark-object-store` in Docker Desktop Kubernetes. MinIO runs on `desktop-control-plane` with its own PVC. PostgreSQL, Gravitino and the Spark Job run on `desktop-worker`. PostgreSQL retains the Iceberg JDBC catalog metadata, while the warehouse is `s3://gda-metadata-warehouse/warehouse` using `org.apache.iceberg.aws.s3.S3FileIO` and path-style access to the MinIO ClusterIP Service.

Spark and Gravitino must mount no warehouse PVC. Their only shared table-data boundary is the S3-compatible service across Kubernetes nodes. This proves local cross-node object-store interoperability, not independent infrastructure or production object-store durability, because both nodes still belong to one Docker Desktop host and cluster.

No Secret is committed. Database, MinIO and Gravitino materials are generated for one run, passed through an ephemeral Kubernetes Secret and excluded from observations, errors and evidence. Dedicated ServiceAccounts disable token automount. The namespace, both dynamic volumes and every port-forward must be absent before evidence can pass.

### 2. Keep identity and transport claims bounded

The authenticated Gravitino API continues to use the M3-6 Basic role: `USE_CATALOG` on `lakehouse`, plus `USE_SCHEMA` and `CREATE_TABLE` on `lakehouse.published`. The bounded user creates and reads the initial table, while catalog creation must return 403 before and after Spark runs.

Spark uses the local unauthenticated HTTP Iceberg REST endpoint and runtime-generated static object-store credentials. These controls do not prove protected workload identity, OIDC, TLS, persistent catalog identity binding or production credential delivery. MinIO's S3 API compatibility does not make it a verified production cloud storage service.

### 3. Require engine, catalog and object-level agreement

The Spark Job must read the zero-row Gravitino-created table, commit two deterministic one-file appends, add nullable `quality`, read the exact three current rows, observe two append snapshots and time-travel to the first snapshot. Gravitino must then read back the evolved schema.

The rehearsal also lists the MinIO prefix directly. It requires two Parquet data objects, four Iceberg metadata JSON objects and four Avro manifest objects. The latest metadata JSON must contain the same table location, evolved schema and current snapshot observed by Spark. This independent object inspection prevents REST or catalog success alone from being treated as storage evidence.

### 4. Do not promote local object storage to production conformance

Evidence may set local Spark object-store interoperability, create/read/write, schema evolution, snapshot/time-travel, Gravitino metadata readback, cross-node object-store access and object-level metadata verification to true.

`production_object_store_verified`, `spark_conformance_verified`, `flink_conformance_verified`, `persistent_catalog_identity_binding_verified`, `protected_workload_identity_verified`, `oidc_verified`, `tls_verified`, `production_ingestion_verified` and `production_ready` remain false. Cancellation, reconciliation, production lineage and commit failure injection are outside this slice.

## Verification

The final Docker Desktop rehearsal on 2026-07-29 produced contract fingerprint `9713cdb3040e1b6532489f329aef7ed7b5266e0757551252f537cb83476b4bee` and evidence fingerprint `05844457efb378581fb7fc2e7ed3c706819b2d8fa5a52b2f82577051d38c2cd1`.

- MinIO ran on `desktop-control-plane`; PostgreSQL, Gravitino and Spark ran on `desktop-worker`;
- Spark and Gravitino mounted no warehouse PVC, and both addressed the same S3-compatible warehouse;
- the bounded Gravitino user created/read the table and received 403 for catalog creation before and after Spark;
- Spark committed two append snapshots, evolved the schema, read three exact rows and time-travelled to the first two-row snapshot;
- direct MinIO inspection found exactly two Parquet files, four Iceberg metadata JSON files and four Avro manifest files;
- the latest object-store metadata location, schema and current snapshot matched Spark, and Gravitino read back the Spark-added `quality` column;
- the Spark Job completed once, all ServiceAccounts disabled token automount, and the namespace, both PVs and all port-forwards were deleted.

Focused tests cover dependency and profile drift, manifest topology, missing warehouse mounts, node separation, object-store configuration, deterministic engine results, direct object inventory, metadata agreement, authorization denial, cleanup, sensitive-material rejection, evidence tampering and production overclaim. CI validates the checked evidence without running Kubernetes; the live rehearsal remains an explicit local operator action.

## Consequences

**Positive**: the interoperability path no longer depends on a same-node shared warehouse PVC. Spark, Gravitino and direct object inspection agree on the same S3-backed Iceberg table across two Kubernetes nodes.

**Negative**: MinIO, both Kubernetes nodes and their persistent volumes still share one Docker Desktop host and operational failure domain. Static local credentials, Basic identity and unauthenticated HTTP remain unsuitable for production.

**Mitigation**: keep production storage and conformance claims false. The next production-oriented slices must select and attest the real object store, protected identity and TLS path, then add commit failure injection, cancellation/reconciliation/lineage, multi-node Spark/Sedona and Flink conformance.

**Revisit trigger**: object-store provider, S3 client, Gravitino, Spark or Iceberg version changes; warehouse layout changes; protected identity/TLS is selected; or the complete ADR-006 conformance suite is introduced.
