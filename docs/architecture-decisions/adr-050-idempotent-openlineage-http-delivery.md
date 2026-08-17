# ADR-050: Idempotent OpenLineage HTTP Delivery

**Status**: Accepted

**Date**: 2026-07-28

**Decision owners**: Data Platform, Metadata Platform, Data Governance, Security, Platform Architecture

**Related decisions**: [ADR-006](adr-006-openmetadata-governance-and-active-metadata-platform.md) · [ADR-020](adr-020-platform-resource-run-and-evidence-contracts.md) · [ADR-025](adr-025-platform-command-outbox-and-callback.md) · [ADR-047](adr-047-deterministic-metadata-fabric-ingestion-projection.md) · [ADR-048](adr-048-local-authorized-metadata-fabric-ingestion-replay.md) · [ADR-049](adr-049-tenant-scoped-metadata-fabric-binding-ledger.md)

## Context

M3-1 produced a content-bound OpenLineage `COMPLETE` RunEvent candidate. M3-2 applied the associated provider projections after policy and approval validation. M3-3 then persisted the verified provider binding through `PlatformGateway`. The event was still never sent over a wire.

An HTTP timeout or failed acknowledgement can occur after a receiver commits an event. Treating that outcome as success can lose events; blindly retrying without a stable key can create duplicate lineage. Network-level exactly-once delivery is not available, so the platform needs explicit at-least-once delivery state and receiver idempotency.

## Options Considered

| Option | Benefit | Cost/risk | Decision |
|---|---|---|---|
| Send directly from provider apply code | Short path | Couples provider mutation to receiver availability and loses durable retry state | Rejected |
| Mark HTTP 2xx directly on the immutable binding | No new table | Mutates the wrong authority and cannot represent claims, leases or retry | Rejected |
| Introduce Kafka or another event platform now | Mature transport | Adds an unproven second durability and operations boundary | Rejected |
| Add a narrow PostgreSQL outbox with stable HTTP idempotency | Reuses the control database, RLS and lease patterns; preserves authority boundaries | At-least-once delivery still requires receiver dedupe | Adopted |

## Decision

### 1. Delivery is derived from the authorized binding chain

Migration 098 adds `gda_control.metadata_fabric_lineage_outbox`. A deterministic delivery UUID and idempotency key bind the tenant, M3-3 binding UUID, target name and canonical OpenLineage event SHA-256. Only one matching event can be enqueued for that binding and target.

`PlatformGateway` reloads the binding and its execution-plan Artifact, parses the authorized apply plan and verifies the complete M3-1 source plan before insert. Tenant, ResourceVersion, run, source plan, event and event fingerprint must all match. The lineage emitter workload must be independent from the provider/binding recorder. Exact enqueue replay returns the existing row; different content conflicts or fails validation.

### 2. PostgreSQL owns delivery state, not lineage truth

The outbox has `pending`, `in_flight`, `delivered` and `failed` states, bounded attempts, worker identity and lease expiry. `FOR UPDATE SKIP LOCKED` permits multiple workers without double claim. Expired claims are reclaimable until the attempt limit.

The gateway role receives only table `SELECT/INSERT`. Three `SECURITY DEFINER` functions are the only mutation path for claim, completion and failure. They require transaction-local tenant context, the current claim owner and an unexpired lease. `FORCE ROW LEVEL SECURITY` prevents cross-tenant visibility.

This state is transport state only. It does not replace the immutable binding, PlatformRun, LineageEvent or receiver state.

### 3. HTTP is canonical, bounded and idempotent

The emitter sends canonical OpenLineage JSON to `/api/v1/lineage` with `Content-Type: application/json`, the deterministic `Idempotency-Key`, delivery UUID and event SHA headers. Only a 2xx response completes the outbox. Transport errors, 429 and 5xx are retryable; other 4xx responses fail closed. Response bodies are not stored, only a SHA-256 and content-bound receipt.

The M3-4 local profile accepts only an unauthenticated loopback HTTP endpoint and rejects credentials, redirects, remote hosts, query strings and fragments. This is a deliberate rehearsal boundary, not a production endpoint profile.

### 4. The rehearsal injects a commit-then-failed-ack outcome

The local receiver commits the first idempotency key and exact event, then returns 503. The outbox retains the event for retry. The second request carries the same key and body; the receiver returns a duplicate 200 without accepting a second lineage event. A completed row cannot be reclaimed.

This proves at-least-once delivery with receiver idempotency across the real Python HTTP stack. It does not prove network exactly-once semantics.

## Verification

The local PostgreSQL 16 and loopback HTTP rehearsal records:

- source M3-3 evidence SHA `518bfed363aba34e539ada19ea1dc708bacc9eba6578ccab165d11bccfc05223`;
- deterministic delivery UUID `49a54408-b3a8-5843-a27d-6395c080af99`;
- OpenLineage event SHA `4929e51c4126e09415a9fc1578c9401077c5d7c374294e70deeebd29c8216dd2`;
- idempotency key `e1a2862b7e246b3717ee2e65cf1a765a40865fdce13eed1b129319d9772c0073`;
- first acknowledgement 503, final acknowledgement 200 and two attempts;
- two wire requests but exactly one receiver acceptance and one duplicate response;
- receipt SHA `13852b5ebee6d0a9546914cd2e2080678910d7fba8dc3dc21e5a049a4220257e`;
- exact enqueue replay `created=false`, completed delivery not reclaimed;
- FORCE RLS, cross-tenant rejection and no direct gateway UPDATE/DELETE;
- evidence SHA `5aabe9950d2d3d0cfb50ee9d9163c8dee60b04e800f68baad5090e97319b5d8d`.

Unit tests cover deterministic identity, content tampering, endpoint restrictions and canonical wire headers/body. PostgreSQL integration covers retry completion, replay, source-plan mismatch, claim finality, RLS and direct mutation rejection.

## Claim Boundary

Allowed now:

- the exact M3-1 OpenLineage candidate can be gated by the M3-3 binding and delivered over a real local HTTP connection;
- a receiver commit followed by failed acknowledgement is recovered with a stable idempotency key and no second receiver acceptance;
- tenant-scoped PostgreSQL outbox state supports bounded claim, lease, retry, completion and failure;
- M3-4 performs no OpenMetadata, Gravitino or legacy mutation.

Fixed false now:

- protected workload OIDC, TLS, receiver authentication and credential rotation;
- a production OpenLineage/OpenMetadata receiver, receiver HA or durable receiver storage;
- `live_openlineage_emission_verified`, until protected receiver evidence exists;
- production outbox deployment, worker scaling, alerting, backup/recovery and SLO;
- OpenMetadata minimum privilege, Gravitino authentication and durable catalog conformance;
- production ingestion and `production_ready`.

## Consequences

**Positive**: lineage delivery no longer depends on a single synchronous HTTP outcome, and the exact event is traceable back through the authorized provider binding.

**Negative**: receiver idempotency remains mandatory. A non-idempotent production receiver cannot safely consume this at-least-once transport.

**Mitigation**: production activation requires a protected receiver profile, workload identity, TLS, receiver-specific idempotency/conformance evidence, managed worker deployment and operational gates.

**Revisit trigger**: replace PostgreSQL polling only when measured delivery volume or SLO requires another transport and a migration preserves tenant, idempotency, receipt and replay semantics.
