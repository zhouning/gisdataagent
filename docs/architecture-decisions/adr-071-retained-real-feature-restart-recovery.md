# ADR-071: Retained real-feature restart recovery

**Status**: Accepted

**Date**: 2026-07-31

**Decision owners**: Data Platform, Metadata Platform, DataOps, Security, Platform Architecture

**Related decisions**: [ADR-054](adr-054-local-gravitino-jdbc-catalog-restart-continuity.md) | [ADR-067](adr-067-object-store-runtime-bound-active-metadata-promotion.md) | [ADR-070](adr-070-retained-real-feature-terminal-success.md)

## Context

M3-24 proved one complete real-data authority chain from authorized DolphinScheduler execution through Spark/Sedona JDBC/S3 Iceberg ingestion, independent spatial quality evaluation, atomic GDA Control promotion and database-authoritative `succeeded@3`. It retained the namespace, PVCs, Iceberg objects and dedicated GDA Control PostgreSQL database for seven days, but explicitly did not prove that those facts survive process restart.

The retained window creates a bounded opportunity to test recovery against the exact successful authority rather than building a new synthetic runtime. The rehearsal must not re-ingest the Chongqing features, create a new ResourceVersion or Run, repair provider state, change the successful verdict, expose retained credentials, or rewrite M3-24 evidence.

## Considered options

### 1. Wait for the production environment

This avoids another local rehearsal, but leaves the current retained authority untested and wastes its bounded audit window. Production identity and storage attestation are also not yet available.

### 2. Recreate the runtime and ingest again

This would test rebuild behavior, not continuity of the successful M3-24 authority. It would create new material and ledger facts, making it impossible to prove exact recovery of the retained state.

### 3. Restart the retained runtime in place

This directly tests the current gap. Stable infrastructure identity, rotating process identity, byte-stable data and exact ledger replay can all be checked without creating new authority facts. M3-25 adopts this option.

## Decision

### 1. Bind recovery to checked M3-24 evidence

M3-25 accepts only the checked M3-24 evidence SHA `d966668b5a2ea57c7a4b2a3bc9824daab9b0128d9f94e515d7be649b145de418` and retention ID `m3-24-229740ac50ebb53b`. The namespace UID, expiry, control container and volume, output ResourceVersion, content SHA, snapshot and object inventory must match before any restart.

Runtime credentials are read only from the retained Kubernetes runtime objects and Docker container environment into `SecretStr`. They are never written to evidence, logs or exceptions.

### 2. Restart stateful dependencies in order

The controlled order is PostgreSQL, MinIO object storage, Gravitino, and then the dedicated GDA Control PostgreSQL process. Each Kubernetes rollout must return to one ready replica before the next begins.

Namespace, StatefulSet, Service, PVC, volume, image and control container identity must remain stable. All three Kubernetes Pod UIDs must change. The GDA Control container ID and volume must remain stable while PostgreSQL PID and `StartedAt` change.

### 3. Require independent data and catalog continuity

Before and after restart, direct S3 readback must return the same object inventory SHA, Iceberg metadata body SHA, snapshot ID, schema and single Parquet file. The independent evaluator reopens that Parquet and requires all nine M3-24 spatial quality counts to remain 20, with unchanged row-set and data-body SHA.

Gravitino admin readback must return the same eight-column table projection, output ResourceVersion, content SHA and provider revision. No repair, table recreation or ingestion is allowed.

### 4. Keep the successful ledger byte-stable

The GDA Control authority counts, ledger counts, provider observation, `succeeded@3` state and combined facts SHA must be identical before restart, after restart and after terminal replay. The replay must use the original terminal verdict and return `promotion_created=false`; any additional Artifact, observation, QualityResult, lineage or Run event fails the gate.

### 5. Cap the claim at local process restart continuity

The namespace, Kubernetes nodes, PVCs, MinIO and control database remain on one Docker Desktop host. The rehearsal does not restore from backup, exercise PITR, lose a host or storage volume, use protected production identity, or run a persistent scheduler/executor.

Therefore backup/PITR, independent failure domains, production restart recovery, production ingestion and `production_ready` remain false.

## Verification

The M3-25 rehearsal recorded:

- contract SHA `83ed15ae4eed85e0c261c2b3a04ea2ad559f3deb7b86c7c2f2dedd0cf28d23d0` and evidence SHA `1b5a5ceeadee88868bab6237b3f3280c8b13793cc54193592fec7dbbfdd4e8a6`;
- unchanged namespace, three StatefulSet identities, three Service identities, PostgreSQL/MinIO PVC identities, images, control container ID and control volume;
- PostgreSQL, MinIO and Gravitino Pod UID rotation, plus GDA Control PostgreSQL PID rotation from `2087977` to `2093386`;
- unchanged object inventory SHA `de4a0efed9fdb68f0019b843377f6c8de71664de955130d0dd38e99eccdb8034`, snapshot `8034081021802585202`, 94,603-byte Parquet body SHA `6cc0fc9eaf48f8106f9afe192704c44407c86c9ea119ae20894bf369a8e74779` and row-set SHA `c26ff708f4b6be082327dff63a6a8659420dbc4cab37dea1cac7b40f147512df`;
- nine independent spatial quality counts equal to 20 and unchanged Gravitino projection SHA `f30feb94a5a8280597f331a7f965762bfabb9b82397af49dda05b61ce00bbb1e`;
- unchanged GDA Control facts SHA `5c0b8a58729e551c250b0410bcebdfe3f019f215a50b20d503f094fe1562d8b5`, five Artifacts, two attempt observations, one QualityResult, one LineageEvent, four Run events and `succeeded@3` before restart, after restart and after exact replay;
- absent source payload, stopped port forwards, zero credential material in evidence, no new ingestion and no new authority facts.

## Consequences

**Positive**: the retained real Chongqing output, technical catalog and control authority now have one content-bound, failure-closed process restart continuity proof. Recovery is verified against the exact terminal success instead of inferred from provider health.

**Negative**: the proof is time-bound to the M3-24 retention window and exercises process restart only. It consumes local runtime capacity and cannot support a production durability claim.

**Next gate**: provide protected production identity, storage and tenant attestation; deploy persistent scheduler/executor and control services; then exercise backup/PITR, host or availability-zone failure, staging scale, Spark/Flink conformance, alerting and runbook recovery.

**Revisit trigger**: supersede this decision when an approved staging environment can reproduce the same authority chain across independent failure domains with immutable retention, backup/PITR and audited lifecycle automation.
