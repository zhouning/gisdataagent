# ADR-054: Local Gravitino JDBC Catalog Restart Continuity

**Status**: Accepted

**Date**: 2026-07-29

**Decision owners**: Metadata Platform, Data Governance, SRE, Platform Architecture

**Related decisions**: [ADR-037](adr-037-local-metadata-fabric-foundation-sandbox.md) · [ADR-052](adr-052-local-gravitino-basic-bounded-provider-identity.md) · [ADR-053](adr-053-production-metadata-fabric-identity-readiness-gate.md)

## Context

M3-6 proved that a Gravitino `1.3.0` Basic user can be limited to table creation while catalog creation is denied. Its memory-backed catalog and ephemeral database could not prove that the same authenticated identity, authorization objects and table metadata remain usable after a provider or catalog database restart. M3-7 therefore kept `persistent_catalog_restart` as a required production attestation check.

The next bounded step is a real local persistence rehearsal, not another self-asserted production gate. It must reuse the exact M3-6 privilege boundary, place both the Iceberg catalog metadata and warehouse on persistent volumes, restart both stateful providers and read the same table afterward. It still cannot prove production OIDC, TLS, storage durability, protected workload identity or engine conformance.

## Decision

### 1. Isolate an authenticated persistent catalog rehearsal

The rehearsal creates only the temporary `gda-metadata-catalog-persistence` namespace in Docker Desktop Kubernetes. PostgreSQL `16.10-bookworm` stores both the Gravitino relational entity schema and a separate `iceberg` catalog database on one `standard` PVC. Gravitino stores the local Iceberg warehouse on a second `standard` PVC. Both workloads use StatefulSets, ClusterIP Services and dedicated ServiceAccounts with token automount disabled.

No Secret is committed. The administrator, bounded-user and database materials are generated for one run, projected through an ephemeral Kubernetes Secret and excluded from observations, errors and evidence. The namespace and both dynamically provisioned volumes must be deleted before evidence can pass.

### 2. Use the real Iceberg JDBC backend and isolated plugin driver

The catalog provider is `lakehouse-iceberg`, `catalog-backend=jdbc`, with URI `jdbc:postgresql://gravitino-persistence-postgresql:5432/iceberg` and warehouse `file:///var/lib/gravitino/warehouse`. An initContainer copies the PostgreSQL driver from the versioned local Gravitino image into the Iceberg plugin's isolated classloader path; the runtime must prove that this mounted driver is readable.

The checked profile distinguishes the Docker host image ID (`d355dc7e...`) from the Kubernetes node runtime image ID (`18e24b43...`). Docker Desktop's local kind node reports the latter in Pod status even though host `docker image inspect` reports the former. Treating both fields as one image digest caused the first otherwise-successful rehearsal to fail closed, so each identity now has an explicit name and contract field.

### 3. Preserve the M3-6 authorization boundary across restart

The Basic service administrator provisions metalake `gda_persistence`, catalog `lakehouse`, schema `published`, the bounded user and role. The bounded role contains exactly:

- `USE_CATALOG` on `lakehouse`;
- `USE_SCHEMA` and `CREATE_TABLE` on `lakehouse.published`.

Before restart, the bounded user must authenticate, create/read `gda_persistence_probe`, and receive 403 when attempting to create `unauthorized_catalog`. The rehearsal then restarts PostgreSQL followed by Gravitino. After restart, it creates a new authenticated client using the same bounded identity, reads the same table projection and role, and must again receive 403 for catalog creation.

### 4. Require stable stateful identity and changed process identity

For both workloads, the StatefulSet UID and PVC UID must remain unchanged while the Pod UID must change. Each PVC must remain `Bound` on `standard`, each StatefulSet must return to one ready replica, the expected runtime image identity must match, and the table projection fingerprint must be byte-for-byte identical before and after restart.

Evidence may set only four local claims to true: `local_gravitino_jdbc_catalog_restart_verified`, `local_authenticated_catalog_persistence_verified`, `local_postgresql_pvc_restart_verified` and `local_warehouse_pvc_restart_verified`. `persistent_catalog_identity_binding_verified`, `protected_workload_identity_verified`, `oidc_verified`, `tls_verified`, Spark/Flink conformance, production ingestion and `production_ready` remain false.

## Verification

The final Docker Desktop rehearsal on 2026-07-29 produced contract fingerprint `f622d8a61bae49171bc76a16bfe64280c616c028bddf88479f1ad04acb1dadf0` and evidence fingerprint `34792bb47ad71041a87adeb644439bf9b6aa3f4855cdc98782d6e3b4282bf1aa`.

- PostgreSQL and Gravitino Pod UIDs changed while both StatefulSet UIDs and PVC UIDs remained stable;
- both PVCs remained `Bound` on `standard`, and both workloads returned to one ready replica;
- the bounded principal authenticated before and after restart, while catalog creation returned 403 both times;
- the exact role read back before and after restart without privilege expansion;
- table create/read returned 200 before restart and read returned 200 afterward;
- table projection fingerprint `25845cd3890a9e4dc1663cf9e77bfe6a63144223d29ab788f12af6448d0717a3` remained identical;
- both port-forwards stopped, the namespace was deleted, and no provider object or persistent volume was retained.

Focused tests cover profile, dependency and manifest validation; Pod replacement; StatefulSet/PVC continuity; runtime image identity; table, role, authentication and denial continuity; cleanup; sensitive-field rejection; evidence tampering; and production overclaim. Required CI validates the checked evidence and runs the focused module. The live Kubernetes rehearsal remains an explicit local operator action.

## Consequences

**Positive**: the Gravitino path now has tangible, authenticated Iceberg JDBC persistence evidence instead of a memory-catalog assumption. Restart continuity is bound to both storage identity and the exact minimum-privilege role.

**Negative**: the database and warehouse are two local Docker Desktop PVCs in one cluster and failure domain. Basic credentials, loopback HTTP and `file://` warehouse storage remain local-only mechanisms. The rehearsal deletes its volumes, so it proves controlled restart continuity rather than backup recovery or long-duration durability.

**Mitigation**: keep all protected identity, OIDC, TLS, cross-cluster storage, production ingestion and conformance claims false. Production acceptance still requires a selected protected authentication path, immutable registry provenance, object-store warehouse, managed catalog database, backup/PITR, tenant isolation, Spark/Flink interoperability and protected-environment attestation.

**Revisit trigger**: Gravitino version, Iceberg catalog implementation, JDBC schema, driver classloading, storage class, production identity architecture or catalog durability target changes.
