# ADR-067: Object-store runtime-bound Active Metadata promotion

**Status**: Accepted

**Date**: 2026-07-31

**Decision owners**: Data Platform, Metadata Platform, Data Governance, Security, Platform Architecture

**Related decisions**: [ADR-056](adr-056-local-spark-object-store-interoperability.md) · [ADR-057](adr-057-production-object-store-readiness-gate.md) · [ADR-066](adr-066-runtime-bound-durable-active-metadata-promotion.md)

## Context

M3-20 bound the real Chongqing Active Metadata ResourceVersion to a restart-continuous Gravitino JDBC runtime, but its Iceberg warehouse was a local `ReadWriteOnce` PVC mounted by Gravitino. M3-10 separately proved cross-node MinIO interoperability for a synthetic Spark table. Neither evidence proved that the real ResourceVersion promotion was served by a JDBC catalog whose table metadata lived behind an object-store boundary.

Changing the M3-20 candidate or reusing its SHA would erase the distinction between filesystem and object-store provider runtimes. M3-21 therefore creates a new successor candidate and keeps all predecessor evidence immutable.

## Decision

### 1. Promote from M3-20 without rewriting history

The M3-21 plan contains the exact M3-20 promotion candidate SHA as `predecessor_promotion_candidate_sha256`. It creates a new logical Gravitino target at `gda_chongqing_m3_21/lakehouse/cultural_heritage/cultural_districts`, a new runtime binding and a new promotion candidate. No M3-19/M3-20 schema, evidence or GDA Control row is changed.

The same retained OpenMetadata UUID, ResourceVersion UUID, content SHA, governance refs and snapshot are read before provider apply. OpenMetadata remains read-only.

### 2. Bind both catalog and object-store runtime identity

The stable binding includes cluster and namespace UID; Gravitino and MinIO Service UIDs; PostgreSQL, Gravitino and MinIO StatefulSet UIDs; PostgreSQL and MinIO PVC/volume identity; pinned container image IDs; node separation; JDBC URI; S3 warehouse, FileIO, endpoint, region, path-style mode and bucket.

Pod UIDs are excluded from the stable hash. PostgreSQL and Gravitino Pod UIDs must rotate during ordered restart. The MinIO Pod, Service, StatefulSet and PVC must remain unchanged. Gravitino must expose an empty PVC list and may not mount the object-store warehouse volume.

### 3. Require provider and direct S3 agreement

An ephemeral admin creates the JDBC catalog with `org.apache.iceberg.aws.s3.S3FileIO`; a schema-bounded Basic principal has only `USE_CATALOG`, `USE_SCHEMA` and `CREATE_TABLE`. Catalog administration must return `403` before and after restart.

The first authorized apply creates exactly one table. Immediate replay and the first post-restart replay must both be `no_op/0 mutations`. Direct S3 inspection must find the table under `warehouse/cultural_heritage/cultural_districts/`, with the exact `BSM string required` and `geometry binary required` Iceberg schema. Because M3-21 is a metadata promotion rather than row ingestion, the prefix must contain one metadata JSON and no Parquet or manifest files. The object inventory, ETag and metadata body SHA must be unchanged across restart.

### 4. Local MinIO is not production object storage

MinIO, both Kubernetes nodes and both PVCs share one Docker Desktop host. Credentials are generated static local material; transport is HTTP; there is no KMS, protected workload identity, independent account or failure domain. Namespace and volumes are deleted after the rehearsal.

Therefore `durable_catalog_verified`, `production_object_store_verified`, `source_feature_rows_ingested`, protected identity, OIDC, TLS, production ingestion and `production_ready` remain false.

## Verification

The local rehearsal recorded:

- Chongqing ResourceVersion `a6000000-0000-4000-8000-000000000001`, content SHA `fd474fd65c8e4a71da241eb3fd07748ca3b972fbd2d3c32833376dbe71104007` and OpenMetadata UUID `9d043410-02b5-487d-bb70-da5f3969a978`;
- M3-20 predecessor candidate `bb6672cb7f98fa53305e17bbca2cb5b3756d4a335a94d79114fb4184273871d1`;
- one bounded `gravitino.table.create`, immediate `no_op/0`, and first post-restart `no_op/0`;
- stable direct S3 object key, ETag and metadata body SHA with no data or manifest objects;
- PostgreSQL and Gravitino Pod rotation with stable MinIO Pod, Services, StatefulSets, PVCs and images;
- logical binding SHA `614ce5e4c45dba1437dc888cbd79b2d58954184113a62c20170ab84b5570d9e1`;
- runtime binding SHA `dd63917b6354a2e92853763ddc3e3a981cb40717f84c0f819b1a4e6844ae100b`;
- promotion candidate SHA `63812c311b3f239bc6a944748c4ff384250eb9c9ed9009d3384fc699f1d3eaa9`;
- contract SHA `b1a2db34a70eaa7dd55da1d6c85da9f420c755c71868aafe7972e3794034a6cc` and evidence SHA `d73754c53cf16d888aa345baa5d079cc7fd98d8b84db747f52188c1a69bf1628`;
- complete namespace, PVC and port-forward cleanup.

## Consequences

**Positive**: the real Active Metadata target is now content-bound to a restart-continuous JDBC catalog and an independently observed cross-node S3-compatible warehouse, without weakening historical evidence.

**Negative**: the table contains metadata only, the candidate is not authoritative, and local MinIO does not satisfy the production storage gate.

**Next gate**: ingest a bounded real Chongqing feature slice through an authorized Spark/Sedona path into this provider model, then define the versioned promotion ledger transaction. Production promotion still requires selected object storage, protected identity/TLS/KMS, independent failure domains, backup/PITR and tenant isolation.
