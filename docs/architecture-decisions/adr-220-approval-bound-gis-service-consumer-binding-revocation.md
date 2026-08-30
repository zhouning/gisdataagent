# ADR-220: Approval-Bound GIS Service Consumer Binding Revocation

**Status**: Accepted  
**Date**: 2026-08-21  
**Related roadmap**: [GIS Data Agent Roadmap](../roadmap.md), AR-4.4  
**Depends on**: [ADR-219](adr-219-approval-bound-gis-service-consumer-binding-issuance.md)

## Context

ADR-219 made new `ServiceConsumerBinding` issuance dependent on an approved
grant plan. The binding itself is immutable, so changing it in place to carry a
revoked flag would destroy the original authorization evidence and would make
replay/audit ambiguous. The online Gateway also needs revocation to take effect
without waiting for binding expiry or a provider restart.

## Decision

Migration 214 adds the tenant-scoped append-only
`gda_control.service_consumer_binding_revocation` fact. Each binding can have
one revocation fact. The fact stores:

- the exact binding ID and binding SHA-256;
- the deterministic revoke `ApprovalCase` and revoke-plan SHA-256;
- reason, structured context, approving human and decision timestamp.

`ServiceConsumerBindingRevokePlan` freezes the target binding, service,
release, consumer, revocation ID, reason and context. Its deterministic case
uses action `gis_service_consumer_binding.revoke`. The SQL recorder verifies the
tenant, live approved case, target and plan fingerprint, full case context,
current immutable binding checksum and the approving human before inserting.
Direct table INSERT/UPDATE/DELETE remains unavailable to the Gateway role.

Gateway active-binding lookup excludes any binding with a revocation fact. The
same transaction therefore makes the revoked binding unavailable to MVT
admission immediately. A repeated identical revoke returns the existing fact;
changed payloads fail closed.

## Trade-offs

| Option | Decision | Reason |
|---|---|---|
| Update the immutable binding with `revoked_at` | Rejected | loses the original grant payload and weakens append-only audit |
| Keep revocation only in a cache or provider | Rejected | does not provide a tenant-scoped platform authority and can lag |
| Add a second revocation approval registry | Rejected | duplicates `ApprovalCase` lifecycle and reviewer authority |
| Add an append-only fact and filter it in Gateway SQL | Chosen | preserves evidence, fails closed at the database boundary and takes effect on the next lookup |

The accepted cost is one extra indexed anti-join in the active lookup and a
second typed/SQL representation of the revoke payload. Both are bounded to the
MVT consumer-binding profile; renewal, migration notification, emergency
incident override, quota and cross-protocol authorization remain separate
decisions.

## Verification

The disposable PostgreSQL control-plane certification passed with:

- pending revoke rejected;
- approved revoke inserted once and replayed with `created=false`;
- changed revoke reason rejected against the approved case;
- active lookup present before revoke and absent after revoke;
- revocation table RLS/FORCE RLS enabled, Gateway table INSERT denied and only the typed recorder executable.

The real Martin/PostGIS/FastAPI certification passed with:

- no cookie: `401`;
- signed but unbound subject: `403 service_consumer_binding_required`;
- approved exact binding: `200`, 122-byte MVT;
- same signed subject after approval-bound revoke: `403 service_consumer_binding_required`;
- security event chain valid and no provider invocation after the revoked request.

The local Compose migration ledger is `214/214`, `in_sync`, with catalog and
database fingerprint
`1a3dad016662e43557d0be71aecd9573900300aaedabd1814019d429d9dbcf5f`.
