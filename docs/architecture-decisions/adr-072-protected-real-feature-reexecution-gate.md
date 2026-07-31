# ADR-072: Protected real-feature re-execution gate

**Status**: Accepted

**Date**: 2026-07-31

**Decision owners**: Data Platform, Metadata Platform, Data Engineering, Security, SRE, Platform Architecture

**Related decisions**: [ADR-053](adr-053-production-metadata-fabric-identity-readiness-gate.md) | [ADR-057](adr-057-production-object-store-readiness-gate.md) | [ADR-071](adr-071-retained-real-feature-restart-recovery.md)

## Context

M3-25 proved that one real Chongqing 20-feature authority remains byte-stable across ordered local process restart. Its namespace, PVC, MinIO, Gravitino and GDA Control database still share one development host and use local credentials and HTTP. The roadmap therefore requires protected identity, object storage and tenant attestation before another production-path execution can be considered.

ADR-053 and ADR-057 already define fail-closed production identity and object-store gates, but they do not bind one another or a real feature predecessor. Evaluating them independently could accept attestations from different source revisions, and neither gate alone prevents an operator from treating the retained local material as a production promotion candidate.

## Considered options

### 1. Promote the retained local Iceberg material

This would avoid re-ingestion, but it would carry a single-host MinIO/PVC authority and local identity into a protected environment. The physical material does not satisfy the production storage, tenancy or identity contracts. Rejected.

### 2. Run another local backup or scale rehearsal first

This could add local evidence, but it would bypass the roadmap order and leave the actual production identity/storage decision unresolved. Such rehearsals remain useful after the protected provider profile is selected, not as a substitute for that selection. Rejected as the next gate.

### 3. Evaluate identity and object storage separately

This reuses existing contracts with no new code, but does not bind both attestations to one source revision or the checked M3-25 ResourceVersion/content/quality/ledger predecessor. Rejected.

### 4. Compose both gates around the immutable predecessor

This makes the exact external blockers and cross-gate binding machine-verifiable while preserving the claim ceiling. Adopted as M3-26.

## Decision

### 1. Bind the gate to checked real-data facts

M3-26 accepts only the checked M3-25 evidence file SHA `6880ff81dcde37f824ab3c7d04f62863375d5a6f1ada2a2dbfa832e77da7cfb1` and evidence SHA `1b5a5ceeadee88868bab6237b3f3280c8b13793cc54193592fec7dbbfdd4e8a6`.

The decision records the source tenant and Run, output ResourceVersion/content SHA, Iceberg snapshot and object inventory, Parquet body and row-set SHA, 20-feature count, GDA Control facts SHA and `succeeded@3`. It contains no source path, feature payload or credential material.

### 2. Require both protected production gates

The gate re-evaluates the current identity and object-store profiles through their existing validators. Eligibility requires both fresh protected attestations to pass their complete checks, including workload identity, provider minimum privilege, TLS, KMS/durability, persistent catalog and cross-tenant denial.

Both attestations must bind the same valid 40-character source revision. A valid identity attestation from one revision and object-store attestation from another fails closed even when each individual gate passes.

### 3. Re-ingest; never promote local material

The retained local namespace, PVC, Iceberg objects and GDA Control database are audit evidence only. They are not an input dependency for the protected execution and cannot be copied or promoted as production material. Once the composed gate passes, a new PolicyDecision/Approval may authorize fresh ingestion of the same content-bound source through the protected provider path.

M3-26 itself never authorizes scheduler submission or provider mutation. `scheduler_submission_authorized`, `provider_mutation_authorized`, `production_ingestion_verified` and `production_ready` remain false even when `ready_for_protected_reexecution` becomes true.

### 4. Commit the current blocked decision

The checked production profiles are structurally valid but intentionally pending. The M3-26 decision therefore has status `blocked_pending_protected_attestation`, with 85 explicit blockers: 40 identity profile decisions, one missing identity attestation, 43 object-store profile decisions and one missing object-store attestation.

This is a valid fail-closed decision, not a failed test and not a production readiness claim. The `evaluate` command returns success only after the approved profiles and both fresh attestations pass; `validate` verifies the integrity of the checked pending decision.

## Verification

- contract SHA `39411248b37b7d8d43ac7ad37737de15d6b6d4c5e4feb2088f0a87cec888b5f9`;
- decision SHA `39246eacdd1793f23aecb71195cc4c9d8c63d7125aad8cd9bbb59a96c588cd73`;
- decision file SHA `62624b96d83b085cbb82d29d618042d7f4faa5193847c26af859ec1c87cd4f11`;
- checked M3-25 predecessor, identity profile and object-store profile all validate;
- current decision has 85 blockers and `ready_for_protected_reexecution=false`;
- focused tests cover predecessor drift, report tampering, outer rehash, source-revision alignment, local material prohibition and production overclaim.

## Consequences

**Positive**: the next real-data execution now has one deterministic admission boundary rather than a checklist of unrelated production gates. Local evidence cannot silently become production material, and attestations from different revisions cannot be combined.

**Negative**: M3-26 does not deploy identity, storage, catalog, scheduler or ingestion infrastructure. It deliberately remains blocked until the external owners approve and materialize the profiles.

**Next gate**: approve the production identity and object-store profiles, deploy their protected paths and generate both fresh attestations on one source revision. Then create a tenant-bound PolicyDecision/Approval for a fresh protected re-execution, deploy the persistent scheduler/executor, and validate ingestion, backup/PITR, independent failure domains, scale and Spark/Flink conformance without weakening this gate.

**Revisit trigger**: supersede this ADR if the production provider is not S3-compatible, the identity integration modes change, or a unified protected-environment attestation service replaces the two existing gates.
