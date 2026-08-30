# ADR-348: Flink/Iceberg terminal-checkpoint kill evidence refresh

## Status

Accepted as a current-environment evidence refresh for ADR-254; no new
production capability or exit gate is claimed.

## Context

ADR-254 already defines the bounded Flink/Iceberg physical-kill and network
uncertainty profile. This run refreshes the kill evidence in the current
workspace so the report is directly available under `docs/reports/`; it does
not introduce a second reconciliation design.

## Decision

The certification uses a real Chongqing OSM source slice, a pinned
Flink runtime, a temporary Iceberg JDBC catalog, and MinIO object storage. It
injects `SIGKILL` into the Flink container only after the terminal source
checkpoint marker is observed. The control plane then reconciles the provider
snapshot independently and applies the existing commit identity and retry
preflight rules:

- the kill leaves the control-plane cursor unchanged until reconciliation;
- an uncommitted pre-checkpoint cancellation does not publish a
  `DataProductVersion`;
- a committed provider snapshot is adopted exactly once;
- retry preflight reuses the reconciled commit and does not submit a second
  provider write;
- temporary catalog, Flink container, object prefix, and authority rows are
  removed after the rehearsal.

The result refreshes evidence for the `Flink/Iceberg kill/network uncertainty`
bounded exit gate already described by ADR-254. It does not change the rule
that provider and control-plane commits require independent evidence before
advancing a SourceSync.

## Verification

The real rehearsal passed all 14 top-level checks (including the nested fault
checks), including source binding, supply-chain
artifact verification, terminal checkpoint observation, control-plane
non-advancement on cancellation, exact snapshot reconciliation, no duplicate
retry snapshot, and complete cleanup:

- [report](../reports/chongqing_osm_flink_iceberg_kill_uncertainty_2026-08-29.json)
  file SHA-256 `52092866728798cc29a839fc4def85ab375bbd19c9f5a632bf7bb6aac1c27e4e`;
- command: `python -m scripts.certify_chongqing_osm_flink_iceberg_reconciliation --fault-mode kill`;
- runtime: Flink `1.19.3`, Iceberg runtime `1.7.2`, JDBC catalog on PostgreSQL
  `16.15`, and the repository's pinned MinIO profile.

## Limits and next evidence

This remains a disposable, single-task, single-slot physical-kill rehearsal.
It does not prove automatic Flink restart, Kubernetes lease/fencing, arbitrary
network partitions, multi-cluster HA, cross-region replication, production
throughput, or RPO/RTO. Those remain AR-2 and AR-5 exit gates. The rehearsal
also does not turn the Flink job into an AgentOps specialist provider;
provider-native cancel/observe integration and cross-process Temporal history
reconciliation remain separate work.
