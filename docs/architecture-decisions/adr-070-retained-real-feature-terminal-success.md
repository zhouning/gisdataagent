# ADR-070: Retained real-feature terminal success rehearsal

**Status**: Accepted

**Date**: 2026-07-31

**Decision owners**: Data Platform, Metadata Platform, Data Governance, GIS Platform, Security, Platform Architecture

**Related decisions**: [ADR-007](adr-007-dolphinscheduler-temporal-orchestration-platform.md) · [ADR-026](adr-026-evidence-gated-run-success.md) · [ADR-068](adr-068-local-authorized-real-feature-iceberg-ingestion.md) · [ADR-069](adr-069-atomic-real-feature-output-ledger-promotion.md)

## Context

M3-22 proved real Spark/Sedona ingestion into a temporary JDBC/S3 Iceberg runtime. M3-23 proved that its path-free output, quality and lineage candidates could be promoted atomically into a temporary GDA Control ledger. Both rehearsals deliberately deleted their material and left the correlated PlatformRun non-terminal because complete authorization Artifacts, a provider success observation and independently created quality evidence were not all present together.

The next gate must prove the complete chain against one retained output without weakening the existing authority boundaries. A scheduler state alone cannot finalize a Run, a ledger promotion alone cannot make missing material readable, and retained local infrastructure cannot be described as production.

## Decision

### 1. Execute the checked real-data plan through DolphinScheduler

M3-24 uses the same content-bound Chongqing 20-feature EPSG:4490 cultural-district slice as M3-22. A DolphinScheduler `3.4.2` Shell task calls a bounded ephemeral executor, and that executor runs the checked Spark `3.5.0` + Sedona `1.9.0` JDBC/S3 Iceberg ingestion plan.

The execution plan, PolicyDecision and Approval Artifacts are written to GDA Control before dispatch. The provider callback is accepted only when it binds the exact tenant, Run, definition, compiled workflow and request. The resulting FrameworkAttemptObservation must contain a real DolphinScheduler `SUCCESS`; it remains an observation rather than the PlatformRun authority.

### 2. Retain material long enough to audit terminal success

After successful ingestion, the source ConfigMap containing identifiers and WKB payload is deleted. The namespace UID, PVC-backed catalog state, MinIO/Iceberg output and dedicated GDA Control PostgreSQL database are retained for seven days under one `retention_id` and one expiry timestamp.

Committed evidence contains aggregate inventory, hashes, counts and bounded runtime identities. It does not contain the source absolute path, feature identifiers, geometry bytes, credentials or the source payload. `retained_staging_material_verified=true` means the recorded output was readable during the rehearsal and remains available for bounded audit until expiry; it does not establish production durability.

### 3. Re-evaluate the retained Parquet independently

The quality evaluator reopens the single retained Parquet object independently of the ingestion executor. It recomputes the canonical row-set fingerprint and verifies feature count, unique identifiers, non-empty/valid Z geometry, SRID, positive area and source-matching bounds.

The evaluator creates its own quality evidence Artifact. That Artifact creator must equal the QualityResult evaluator and must differ from the output creator. An executor-authored substitute fails the existing success gate.

### 4. Keep output promotion and terminal authority separate

M3-24 reuses the M3-23 atomic promoter without modifying the evidence-bound PlatformGateway. The output ResourceVersion, output Artifact, evaluator evidence Artifact, passed QualityResult and source-to-output LineageEvent are appended as one exact-replay bundle.

Only after retained material readback, complete authorization, the exact provider success observation, independent quality provenance and lineage all agree may migration 096's existing database finalizer move the Run from `reconciling@2` to `succeeded@3`. Exact terminal replay must create no new output facts, attempt observation or Run event.

### 5. Make cleanup explicit and identity-bound

Cleanup is a separate operator action. It requires intact checked evidence and an exact `retention_id`; it verifies namespace UID/label and control container/volume labels before deleting anything. The recorded M3-24 cleanup invocation is:

```bash
./scripts/metadata-fabric-retained-real-feature-terminal-success.sh \
  cleanup --retention-id m3-24-229740ac50ebb53b
```

The retained resources must not be cleaned before their audit window is complete unless an authorized operator deliberately invokes that bounded command. This ADR records the lifecycle contract; it does not authorize early cleanup.

### 6. Cap claims below production

M3-24 is a retained local staging rehearsal. Its scheduler is temporary, its executor callback is ephemeral, its catalog/object store and GDA Control database run on one development host, and its identities are not protected production workload identities. It does not prove production scheduler HA, independent storage failure domains, KMS/TLS/OIDC, tenant attestation, backup/PITR, restart recovery, staging scale or production ingestion.

Therefore `production_scheduler_verified`, `protected_workload_identity_verified`, `production_object_store_verified`, `production_tenant_attestation_verified`, `production_ingestion_verified` and `production_ready` remain false.

## Verification

The M3-24 rehearsal recorded:

- contract SHA `9c8f20ca1fb9995530c4e988ced627f665857ecdf0e104bb7d07c4a4a486057a` and evidence SHA `d966668b5a2ea57c7a4b2a3bc9824daab9b0128d9f94e515d7be649b145de418`;
- retention ID `m3-24-229740ac50ebb53b`, namespace UID `824a5904-70cc-4a85-8503-ca83acbcde16` and expiry `2026-08-07T04:15:23.082316Z`;
- output content SHA `bdc06792e8b935176ee6df6f6f6d4be1535622d54d9b994a778cabfe5a574618`, row-set SHA `c26ff708f4b6be082327dff63a6a8659420dbc4cab37dea1cac7b40f147512df` and one 94,603-byte Parquet object;
- nine independent quality counts equal to 20;
- one PolicyDecision, one Approval, one execution plan, five total Artifacts, two attempt observations, one QualityResult and one LineageEvent;
- a real DolphinScheduler `SUCCESS`, final PlatformRun `succeeded@3` and an exact terminal replay with no additional facts;
- deleted source payload ConfigMap and scheduler container, with the namespace/PVC/material and dedicated GDA Control database retained.

## Consequences

**Positive**: the platform now has one auditable real-data path from authorization through scheduler execution, spatial lakehouse material, atomic control-ledger promotion and database-authoritative terminal success.

**Negative**: retained local resources require an explicit lifecycle and consume workstation capacity for seven days. The result remains below production because the scheduler, executor, identities, storage and control database are not production deployments.

**Next gate**: repeat the same authority chain with protected production identities and tenant binding, selected production catalog/object storage, persistent scheduler/executor deployments, independent failure domains, backup/PITR and restart/recovery evidence. Then add staging-scale and Spark/Flink conformance before claiming production ingestion.

**Revisit trigger**: replace the seven-day local retention policy when an approved staging environment supplies durable lifecycle automation, immutable retention policy, ownership, backup and auditable cleanup through the platform control plane.
