# ADR-187: Gravitino persistent metadata plane acceptance boundary

## Status

Accepted

## Context

The first Gravitino bridge acceptance proved the metadata contract with the
default memory-backed catalog. That established the `ResourceURN` crosswalk,
technical object reference, provider observation and tombstone projection, but
it could not prove that metadata survives a service restart.

The platform needs a durable technical metadata plane without turning the GDA
PostgreSQL control ledger into a second catalog. The acceptance must therefore
exercise both Gravitino entity metadata and Iceberg catalog metadata as
independent persistence boundaries.

This decision is a local Docker acceptance boundary. It is not a production
availability, identity or disaster-recovery certification.

## Decision

1. Gravitino entity metadata uses its relational entity store. The local
   acceptance pins the entity store to a file-backed H2 database under a
   dedicated persistent volume. Production profiles must replace this local
   fixture with a supported managed relational database and its own backup,
   restore, HA and upgrade evidence.
2. The Iceberg catalog uses Gravitino's JDBC catalog backend, with PostgreSQL
   catalog metadata and a persistent warehouse path. Catalog creation must
   carry the backend, JDBC driver, URI, credentials reference, initialization
   flag and warehouse explicitly; an in-memory default is not accepted for the
   durable profile.
3. GDA remains the authority for `ResourceURN`, `ResourceVersion`, policy,
   approval, run, audit and evidence contracts. It stores a stable Gravitino
   metalake/catalog/namespace/object reference and provider observations, not a
   copy of Gravitino catalog metadata or Iceberg table contents.
4. The repeatable acceptance runs `seed`, removes and recreates only the
   Gravitino container, then runs `recover` against the same entity-store
   volume and PostgreSQL database. It requires the stable technical table
   projection (identity, schema, properties and location) to preserve its
   fingerprint. Provider-managed `audit` fields are recorded as volatile
   evidence and are excluded from the revision fingerprint because Gravitino
   reconstructs them after restart. The acceptance then verifies the existing
   reference/binding, replay and tombstone contracts.

## Evidence

The acceptance uses the pinned image
`gda/gravitino:1.3.0-local-arm64` with image ID
`sha256:d355dc7e92f9e3545d717f3eab2cbdf412115f2b82e1e544d7f6235c1eacd5a5`.
The reproducible runner is
`scripts/metadata-fabric-gravitino-acceptance.sh`; the latest local report is
`.tmp/metadata-fabric/gravitino-metadata-bridge-acceptance-report.json`, schema
`gda.gravitino_metadata_bridge_acceptance.v4`, report fingerprint
`ff81a05ad9a93b35d187135b3a59791e8efa35e429744b986ef3bca2418cd6d3` and file
permissions `0600`.

The 2026-08-18 run passed these checks:

- H2 entity metadata survived one Gravitino restart.
- JDBC Iceberg catalog metadata survived the same restart.
- `gda_acceptance -> iceberg -> transportation -> parcels` was recovered with
  the same stable table fingerprint, `iceberg/parquet`, format version 2 and
  physical warehouse location. The provider `audit` projection changed from
  a populated create record to an empty runtime projection after restart and
  is explicitly excluded from the stable revision.
- The recovered object was read through the provider-read bridge, projected
  through the GDA reference/binding, and verified through deterministic
  present replay and post-delete not-found/tombstone flow.

## Consequences

The metadata foundation now has executable local evidence for persistence and
has a clear authority boundary: Gravitino owns technical catalog facts and GDA
owns crosswalk/control/evidence facts. A restart test cannot be reported as
production readiness.

The following remain explicit AR-1 work:

- OIDC and workload identity for Gravitino and its database.
- Production HA, backup/restore and point-in-time recovery.
- MinIO/object-byte and Iceberg snapshot verification.
- Spark/Sedona/Flink create/read/write, schema evolution, cancel, reconcile
  and lineage conformance.
- Provider-backed search, dual-tenant isolation and failure injection.

## Revisit triggers

- The production deployment selects a relational backend different from the
  local H2 fixture.
- HA or restore objectives require a separate catalog database, object-store
  versioning policy or active/passive Gravitino topology.
- A provider conformance result requires a different Iceberg catalog backend or
  changes the technical metadata authority boundary.
