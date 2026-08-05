# ADR-164: Provider-Neutral SourceSync Quarantine Recorder

**Status**: Accepted

**Date**: 2026-08-05

**Related**: ADR-104, ADR-105, ADR-160, ADR-161, ADR-163

**Extended by**: ADR-165

## Context

ADR-163 made a physical quarantine receipt mandatory for every new governed Silver/Gold
SourceSync commit, but its first provider proof assembled the ResourceVersion, Artifact and evidence
inside the Flink certification script. Repeating that assembly in Spark, CDC, object and other
adapters would duplicate identity, manifest and replay rules and allow the providers to drift from
the PostgreSQL binder.

The platform still needs the provider to own the physical rejection decision and output. Moving
record classification or file writing into a central quarantine service would create another
runtime, queue and transaction boundary without a demonstrated scaling or retention requirement.

## Options Considered

| Option | Benefit | Cost and risk | Decision |
|---|---|---|---|
| Keep provider-specific assembly | No shared component | Duplicates canonical identity and replay rules in every adapter | Rejected |
| Add a quarantine service and queue | Independent execution and retention | Splits physical commit from SourceSync authority and adds reconciliation | Deferred |
| Add a provider-neutral recorder in the existing platform gateway | Reuses current ledgers and transaction authority | Provider must still prove its physical receipt; registration may require idempotent retry | Adopted |

## Decision

Add `SourceSyncQuarantineRecorder` as a small platform component. A provider first commits its own
quarantine output and returns `ProviderQuarantineReceipt` with storage URI, media type, content
SHA-256, size, rejected count, canonical reason counts and optional provider facets. The recorder
does not classify rows, write provider data, schedule work or advance a checkpoint. It only:

- validates that the definition is Silver/Gold and names the same quarantine ResourceURN;
- rejects provider facets that attempt to override canonical receipt identity;
- derives stable ResourceVersion and Artifact IDs from the SourceSync commit ID;
- registers the quarantine Resource, commit-bound ResourceVersion and `quarantine` Artifact;
- produces the canonical `SourceSyncQuarantineEvidence` consumed by ADR-163's binder;
- reports an identity replay when all three registrations already exist.

`LakehouseMaterializationRecorder` remains responsible for the target ResourceVersion, output and
quality Artifacts, QualityResult and LineageEvent. `SourceSyncAuthority` remains the only component
that atomically binds governance evidence, quarantine evidence, commit and checkpoint. The recorder
therefore adds no registry, scheduler, queue or mutable projection.

Provider execution and governance addressing are separate URI concerns. Spark continues to use
`s3a://` for Hadoop S3A access, while the registered Artifact uses the provider-neutral `s3://`
object URI accepted by the platform contract. This mapping occurs at the certification adapter
boundary and does not alter the physical Spark write.

## Spark/Iceberg Provider Proof

The existing Chongqing OSM Spark/Iceberg certification is promoted from an ODS-only provider commit
to two governed Silver micro-batch commits. The published 50,366-road source creates a full baseline
snapshot, then a second Run performs one insert, one update and one delete with `MERGE INTO`. Each
phase independently records target, quality, lineage and OpenMetadata outbox evidence, writes and
hashes an explicit zero-rejection `quarantine-receipt.json`, and submits both receipts to the same
atomic SourceSync commit.

The baseline snapshot is `4946718755623873398`; the incremental snapshot is
`5804234102856417302`. Checkpoint state advances exactly `0 -> 1 -> 2`. A third legal Run finds the
incremental source slice before provider execution, creates no third snapshot and recovers the
original governance and quarantine evidence.

## Verification

- Focused SourceSync, quarantine-recorder and platform-contract tests pass 45/45; Ruff, Python
  compilation and diff whitespace checks pass.
- The real Spark/Iceberg acceptance passes 12/12 end-to-end checks, including both governed phases,
  both physical zero-rejection receipt hashes, snapshot time travel and cross-Run dual-evidence
  replay.
- The baseline reads and outputs 50,366 records. The incremental slice reads three mutations and
  preserves 50,366 output records after one insert, one update and one delete.
- The random PostgreSQL database, MinIO prefix and work directory are removed. Persistent
  SourceSync definition/checkpoint/commit tables remain unchanged and empty.
- Spark report: `.tmp/source-sync-certification/chongqing-osm-report.json`, SHA-256
  `211ae24a532dd5060049ce2c139bfc50f6a43c76d42d7a5e54d4aeb908d5f2f5`.
- ADR-163's cumulative authority and Flink reports remain respectively
  `48889777cb4ca2201cba8ab12d9e3ce3a6bd8323c650a391f3ef2ba01242aeb1` and
  `413561aff0b8608b44645b05679180816a5ea57cedbd919bf463cf63ffea70ed`.
- ADR-165/166 add a third provider class: PostgreSQL CDC routes two invalid geometry-hash changes to
  a checkpoint-consistent physical quarantine, retains the same slot across a bounded network
  partition and passes all 12 provider plus 13 top-level checks. Report SHA-256:
  `216f318c9e3cf29c75bf3342cd4c013c66c2aa582d45ee47d364ce80230731f8`.

## Trade-offs and Consequences

- Batch and event-stream adapters now share one canonical recording path without sharing provider
  rejection logic.
- A zero-rejection phase must still produce a signed physical receipt; the absence of a rejection
  file is not interpreted as success.
- Resource, ResourceVersion and Artifact registration can precede the SourceSync transaction. A
  later authority failure may leave unbound immutable evidence, but deterministic IDs make retry
  idempotent and no checkpoint can advance without the final atomic binding.
- The proof covers Spark/Iceberg micro-batch zero-rejection, Flink filesystem event-stream
  duplicate/late rejection and PostgreSQL CDC invalid-record rejection. It does not certify document,
  imagery, video, point-cloud, time-series or other database CDC providers.
- The disposable PostgreSQL and local Docker evidence is not a persistent development, staging,
  Kubernetes, production or cloud rollout.

## Revisit Triggers

- A provider requires asynchronous quarantine finalization after SourceSync commit admission;
- object-lock, legal hold or independent retention requires a separately operated quarantine
  service;
- physical receipt verification must move from provider conformance into a trusted remote
  attestation or object-store event protocol.
