# ADR-231: Asynchronous MVT Cache Reclamation After Service Transitions

## Status

Accepted and implemented.

## Context

MVT cache namespace rollover makes a cutover or rollback correct even when
Redis is unavailable, but it leaves the retired generation to TTL.  A
transition must not wait for Redis and must not make Redis the source of
active-pointer truth.  Cleanup therefore needs its own durable delivery
record, tied to the immutable transition receipt.

## Decision

Migration `222_gis_mvt_cache_purge_outbox.sql` adds a tenant-isolated,
append-only-by-transition outbox with `pending`, `in_flight`, `done`,
`failed`, and explicit `bypassed` states.  `AFTER INSERT` triggers on the
cutover and rollback receipt tables enqueue one idempotent task in the same
PostgreSQL transaction.  The task stores the immutable release/policy/
projection/endpoint context and a generation token; PostgreSQL computes the
token using the same canonical JSON field set as the Python cache adapter.

A dedicated `GISMVTCachePurgeWorker` claims only as
`workload:gis-mvt-cache-purge-controller`, purges the exact Redis prefix with
bounded `SCAN` + `UNLINK`, verifies zero residual keys, and reports counts.
Redis errors return the task to `pending` (or `failed` after the attempt limit);
they never change the active pointer.  Legacy or incomplete cache contexts are
recorded as `bypassed` with a reason rather than being reported as success.

## Alternatives considered

| Option | Decision | Reason |
|---|---|---|
| Wait for Redis inside cutover/rollback | Rejected | Couples control-plane availability to a rebuildable cache. |
| Reuse `platform_command_outbox` | Rejected | Cache reclamation is not a PlatformRun/provider command and has a different receipt and lease contract. |
| TTL only | Retained as fallback | Correct, but gives no bounded reclamation or operational evidence. |
| Dedicated transition outbox + worker | Chosen | Durable, replayable, tenant-scoped and independently retryable. |

## Verification

The disposable PostgreSQL migration-impact certification applied all 222
migrations and passed real cutover and rollback transactions.  It verified one
task per transition, replay idempotency, SQL/Python generation parity, wrong
worker rejection, Redis-failure retry, lease reclaim, zero-residue completion,
RLS and direct-write denial.  The report was generated at
`.tmp/gis-mvt-cache-purge-certification/migration-impact-report.json`.
Its SHA-256 is
`c7398639623de0f9d7d1bfcba491567794b4acb068b9b6ef3e3dae78339ce3d7`.

The disposable `redis:7-alpine` certification exercised the actual worker:
`1` task claimed, `2` target keys matched/deleted, `0` target keys remaining,
`1` adjacent-generation key preserved, and the async Redis client closed.  The
report SHA-256 is
`4c67f0e8b632c4c9722fd6bcc9814505f508a542e0f6bda3b61598d74cc6b81a`.
