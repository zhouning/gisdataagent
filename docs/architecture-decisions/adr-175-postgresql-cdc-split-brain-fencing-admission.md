# ADR-175: PostgreSQL CDC Split-Brain Fencing Admission

**Status**: Accepted

**Date**: 2026-08-06

**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2

**Related**: ADR-106, ADR-172, ADR-173, ADR-174

## Context

ADR-174 required the old PostgreSQL primary to be stopped before promotion, but only the ordered
stop event was asserted. A failover controller that trusts a stale stop flag can still promote a
standby while the old primary remains reachable. Both servers can then accept writes on different
WAL timelines, and moving the stable source alias would hide the fork rather than prevent it.

The platform must distinguish a physically replayed standby from a fenced CDC source. The admission
decision must fail closed before alias transfer or SourceSync advancement when the old primary can
still write.

## Decision

Extend `gda.postgres_cdc_failover_continuity_admission.v1` with a typed
`gda.postgresql_primary_fencing.v1` witness. The approved fencing mode for the current profile is
`stop_and_detach`, and it requires:

- the old primary container is observed stopped;
- the old primary is detached from the source network;
- a post-fence write-path probe was attempted and was not accepted.

Missing, malformed or unapproved fencing evidence adds a deterministic fail-closed reason. The
admission result retains the existing cluster, replay, timeline, publication and logical-slot gates;
fencing does not make a missing logical slot safe and does not create a second cursor authority.

The companion certification intentionally performs the opposite fault injection using a real
PostgreSQL 16 physical standby: it promotes the standby while the old primary remains live and
  attached, writes divergent revisions to the same road on both servers, confirms the old alias was
  not transferred, and verifies that admission rejects before any alias transfer. This standalone
  provider does not invoke SourceSync.

No automatic fencing daemon, lease service, broker, scheduler or split-brain repair path is added.
The certification is a negative safety gate, not a production HA implementation.

## Verification

- `data_agent/test_chongqing_osm_postgres_cdc_failover.py` covers valid fencing, missing fencing,
  malformed fencing and a live old-primary split-brain witness.
- `PYTHONPATH=. uv run python scripts/certify_chongqing_osm_postgres_cdc_failover.py` passed with
  the existing PostgreSQL 16/Flink provider: fencing mode `stop_and_detach`, rejected write probe,
  16/16 top-level gates and complete cleanup. The report SHA-256 was
  `aa64c01362ace0dd1cd004a2525ce02e127ff30b34e8eb819207bfcf02928652`.
- `PYTHONPATH=. uv run python scripts/certify_chongqing_osm_postgres_cdc_split_brain.py` passed
  against a real PostgreSQL 16 primary/standby. Both writers accepted divergent rows, timeline
  `1 -> 2` and cluster identity were preserved, the old alias remained attached, and admission
  returned `rejected_fail_closed` with the fencing failure reasons. The report SHA-256 was
  `5f922455708c4d31f19b1d482804d827ec59ae178affd0e8f19e0d8f5629b364`.
- All temporary primary/standby containers and the standby volume were removed after both runs.

## Consequences and Boundary

The platform cannot silently treat a split-brain physical promotion as a valid CDC continuation.
Operators still need an approved slot-continuity recovery mechanism, resnapshot/reconciliation
workflow and a new governed Run after rejection. This does not certify production RPO/RTO,
automatic fence acquisition, lease expiry, multi-zone HA, Kubernetes recovery, native PostgreSQL
failover slots or direct CDC-to-Iceberg exactly-once behavior.

## Revisit Triggers

- a production fencing protocol can provide an independently verifiable lease/token and recovery
  evidence;
- PostgreSQL native failover slots or an approved resnapshot workflow is certified;
- measured workload fan-out, RPO/RTO and freshness requirements justify a durable external event
  boundary;
- multi-zone promotion or Kubernetes controller integration enters the AR-2 profile.
