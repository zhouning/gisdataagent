# ADR-221: Approval-Bound GIS Service Consumer Binding Renewal

**Status**: Accepted  
**Date**: 2026-08-21  
**Related roadmap**: [GIS Data Agent Roadmap](../roadmap.md), AR-4.4  
**Depends on**: [ADR-219](adr-219-approval-bound-gis-service-consumer-binding-issuance.md), [ADR-220](adr-220-approval-bound-gis-service-consumer-binding-revocation.md)

## Context

An exact-release `ServiceConsumerBinding` has a finite expiry, but the
original grant must remain available as evidence. Updating its expiry would
erase the authorization state that was approved and consumed. Renewal also
needs to take effect in the Gateway without relying on cache expiry or a
provider restart.

## Decision

Migrations 215-216 add an approval-bound renewal profile:

- renewal creates a new immutable `ServiceConsumerBinding` with a new ID and
  a later expiry; it does not update the source row;
- the target row records `renewal_of_binding_id`, its renewal ApprovalCase and
  plan fingerprint;
- append-only `gda_control.service_consumer_binding_renewal` stores source and
  target IDs/hashes, the deterministic ApprovalCase, plan fingerprint,
  approving human and decision timestamp;
- `ServiceConsumerBindingRenewalPlan` freezes source identity and the complete
  target payload. The case action is
  `gis_service_consumer_binding.renew`;
- the recorder verifies the live approved case, complete target payload,
  source checksum, same service definition/release/consumer, later expiry,
  absence of source revocation, and one-renewal-per-source invariant;
- active Gateway lookup excludes a source that has a renewal fact and then
  resolves the newest non-revoked, non-expired target. A repeated identical
  renewal is idempotent; changed content fails closed.

Migration 216 wraps the implementation recorder and verifies at the SQL
boundary that the renewal actor and timestamp exactly equal the approved
`ApprovalCase` decision. The implementation recorder is no longer executable
by the Gateway role.

Direct table writes remain unavailable to `gda_control_gateway`; only the
typed renewal recorder is executable.

## Trade-offs

| Option | Decision | Reason |
|---|---|---|
| Update the original binding expiry | Rejected | destroys the original grant evidence and makes replay ambiguous |
| Keep renewal in a cache/provider lease | Rejected | does not provide a tenant-scoped authority and can lag |
| Reuse a grant case for renewal | Rejected | hides lifecycle intent and weakens reviewer context |
| Add a new immutable target plus renewal fact | Chosen | preserves history, makes the active transition explicit and keeps approval/replay deterministic |

The accepted cost is one renewal relation and one anti-join in active lookup.
This profile still does not provide generic ABAC, quota/rate, cross-protocol
bindings, shared-cache invalidation or production identity federation.

## Verification

The disposable PostgreSQL control-plane certification passed with:

- pending renewal rejected;
- approved renewal inserted once and replayed with `created=false`;
- source active before renewal and target active after renewal;
- source and target binding/relation RLS, immutable triggers and recorder-only
  Gateway privileges;
- target revoked through the existing approval-bound revocation path and then
  absent from active lookup.

The local Compose PostgreSQL migration ledger is `216/216`, `in_sync`, with
catalog/database fingerprint
`7ed130a940debc6577587747461e24fb9694367a3e6c628d4a009c98cbca13c9`.
