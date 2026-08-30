# ADR-344: Real Temporal specialists use the PostgreSQL operation receipt authority

## Status

Implemented and verified in the bounded Temporal + PostgreSQL rehearsal path and in
both managed-worker entrypoints; production readiness is not claimed.

## Context

ADR-342 defined the append-only PostgreSQL authority for MMFE/GWM provider operation
receipts. ADR-340's Temporal rehearsal still injected only the PostgreSQL Artifact
authority, so a real worker process could not recover a provider operation identity
after restart. The old wrapper also attempted Artifact replay after the rehearsal's
temporary content directory had already been deleted.

## Decision

The real specialist rehearsal now accepts an optional
`SpecialistOperationAuthority` and passes it to `BoundSpecialistExecutor`. The
PostgreSQL wrapper:

- applies migration `246_agentops_specialist_operation_receipt_authority.sql` to the
  disposable database before worker execution;
- injects `PostgresSpecialistOperationAuthority` alongside the PostgreSQL Artifact
  authority;
- verifies receipt-to-Temporal activity correlation, terminal success and output
  Artifact binding;
- creates a new executor instance before the temporary workspace is cleaned up and
  replays each provider request, proving that a worker restart observes the durable
  receipt and does not submit or execute MMFE/GWM a second time; and
- records the receipt backend, history cardinality, CAS result and replay result in the
  bounded report.

The workflow remains provider-neutral. PostgreSQL access stays in the injected
authority; provider handlers do not open database connections. The wrapper continues
to mark `production_readiness_claimed=false`.

The live CLI now uses the same authority boundary. Both the explicit workflow worker
and `--discover` worker call a shared startup assembler that requires:

- PostgreSQL `DATABASE_URL` and the pre-applied receipt authority migration 246;
- a PostgreSQL Artifact authority through `PlatformGateway`;
- an explicit filesystem backend for disposable runs or an S3/MinIO backend for
  deployment; S3/MinIO requires `VersionId` binding; and
- an absolute materialization root for provider input/output replay.

The assembler performs read-only receipt and Artifact-table probes before connecting
to Temporal. Missing database/schema/role/content configuration fails startup rather
than leaving a provider-bound activity to discover a missing dependency mid-cycle.
The discovery worker passes the same checkpoint, start-target, Artifact, and receipt
authorities into each per-target reconciler.

## Verification

The focused specialist/provider and authority suite passes (`16 passed, 1 skipped` in
the local run). The bounded Temporal + PostgreSQL specialist rehearsal completed six
activity schedules/completions for real MMFE and GWM specialists, created two durable
PostgreSQL receipts, exported 41 Temporal history events, and passed history replay. A
new executor instance replayed both provider requests to the same output Artifacts
without a second submission. Separately, the Kubernetes authority-boundary Pod was
rerun with image `gis-data-agent:agentops-specialist-20260828-v9` (manifest digest
`sha256:6b0106dc8ac9264f994012c4595af045eec862e01c881a548fc8044de099bf22`) and
passed all six PostgreSQL state-machine/RLS checks.

The primary report is
[agentops_temporal_postgres_artifact_authority_2026-08-28.json](../reports/agentops_temporal_postgres_artifact_authority_2026-08-28.json)
(`report_sha256=8e31a0e8e31721be0400bd162f06fe15bca12713f57441e1ee793ac102458e46`,
file SHA-256 `5d6e82dabf8f853e738e0956d6f9954438f99b48de92e01cd4121721f18b67b4`).
The PostgreSQL authority boundary report is
[agentops_specialist_operation_authority_postgres_2026-08-28.json](../reports/agentops_specialist_operation_authority_postgres_2026-08-28.json)
(`report_sha256=5ef38ebb9b6cf838d7fd776b2ec704e6fdf187fc8a1a37254eb10442c211f466`).
Both reports explicitly set `production_readiness_claimed=false`.

## Consequences and limits

The bounded path now exercises the intended authority boundary and restart replay
inside the lifetime of its content backend, and the live entrypoint cannot silently
fall back to an in-memory authority. This does not certify provider-native
cancellation, Temporal cancellation/history observation, MinIO/Iceberg/PostGIS target
providers, S3 object-lock/cross-region replication, HA/DR, identity rotation, or
production readiness. Migration rollout, bucket versioning, credentials, and
materialization storage remain deployment responsibilities.
