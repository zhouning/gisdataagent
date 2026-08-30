# ADR-218: Exact-Release GIS Service Consumer Binding

**Status**: Accepted  
**Date**: 2026-08-21  
**Related roadmap**: [GIS Data Agent Roadmap](../roadmap.md), AR-4.4  
**Supersedes**: the product `ConsumerBinding` as the MVT Gateway admission fact in ADR-216  
**Related decisions**: [ADR-177](adr-177-formal-consumer-binding-authority.md), [ADR-204](adr-204-release-bound-mvt-service-policy.md), [ADR-205](adr-205-release-bound-mvt-serving-projection.md), [ADR-216](adr-216-authenticated-gateway-mvt-access-evidence.md)

## Decision

An MVT request is authorized by a `ServiceConsumerBinding` for the exact
`ServiceDefinitionVersion` and `ServiceReleaseBinding` selected by the active
GIS service. A data-product `ConsumerBinding` continues to govern product
promotion, compatibility and consumer-impact workflows. It does not grant
access to an online GIS protocol endpoint.

The first executable profile is intentionally narrow:

| Field | Bound value |
|---|---|
| Resource | tenant, GIS service URN, definition version, release binding |
| Principal | typed `human`, `workload`, `agent` or `service` subject |
| Permission | `mvt.read` for purpose `gis_mvt_read` |
| Scope | exactly `{"operations":["read"]}` |
| Evidence | credential reference, expiry, compatibility evidence and SHA-256 |

`migration 212` stores this fact in the append-only
`gda_control.service_consumer_binding` table. Foreign keys require the declared
definition and release to belong to the same tenant and GIS service. The
recorder verifies that the target is a vector-tile release. The table has RLS
and FORCE RLS; `gda_control_gateway` has `SELECT` and the controlled recorder's
`EXECUTE`, but no table `INSERT`, `UPDATE` or `DELETE` privilege. The insert
trigger also rejects writes that were not made through the recorder.

At request time the Gateway resolves the active service projection, then looks
up a non-expired binding by all of these keys:

```text
tenant + service URN + definition version + release binding + typed principal
```

`MVTAccessService` independently rechecks the selected binding's tenant,
service, definition, release, principal, action, purpose, expiry and `read`
scope. Its v2 request decision, security ledger events, private cache namespace
and ETag contain the selected binding ID and SHA-256. A new active release
therefore needs its own authorization fact; a binding for the preceding release
cannot match the lookup.

## Runtime Boundary

The current implementation provides the immutable authorization fact, Gateway
lookup and MVT enforcement path. New issuance is now approval-bound through
`ServiceConsumerBindingGrantPlan`, the existing `ApprovalCase` authority and
migration 213's database recorder; see [ADR-219](adr-219-approval-bound-gis-service-consumer-binding-issuance.md).
Renewal, revocation and consumer migration remain separate lifecycle slices.
There is also no generic ABAC engine, dynamic row/column/spatial/temporal
obligation, real-time quota counter, cross-protocol binding or ServiceSLO
policy in this slice.

## Verification

Focused contracts cover the immutable model, mapping fingerprint normalization,
recorder guard, MVT decision validation and Gateway route behavior:

```bash
.venv/bin/python -m pytest -q \
  data_agent/test_service_consumer_binding.py \
  data_agent/test_gis_mvt_access.py \
  data_agent/test_platform_gis_mvt_route.py \
  data_agent/test_certify_gis_mvt_gateway_http.py
```

On 2026-08-21 the disposable PostGIS/Martin certificate executed the normal
FastAPI route and produced:

| Case | Result |
|---|---|
| no session cookie | `401` |
| signed principal without service binding | `403 service_consumer_binding_required` |
| signed principal with matching service binding | `200`, 122-byte MVT |

The certificate also verified `denied -> admitted -> outcome`, the shared
admission/outcome decision SHA-256, one provider call only after admission,
the immutable security-event chain, `private, max-age=60, must-revalidate`,
RLS/FORCE RLS, no Gateway table `INSERT`, recorder `EXECUTE`, and direct-write
rejection with PostgreSQL SQLSTATE `42501`. It removed the temporary database,
roles and Martin container. Report:
`.tmp/gis-mvt-gateway-http-certification/service-consumer-binding-v2-report.json`,
SHA-256 `4d29dea8ce73b1aa560b543b89e3be9d04d7985af797fa1a85643fc193b0395e`.

The local Compose development database applied migrations `212` and `213`
through the fail-closed migration runner. Its ledger and source catalog both
contain 213 migrations with fingerprint
`467cf6d22c1b70ec8aacd8c03719dfacac71a2b2e56c897b8da916a2162a173d`.

## Revisit Triggers

- a product owner needs to issue, renew, revoke or migrate a service grant;
- another GIS protocol needs endpoint-level consumer authorization;
- policy requires dynamic spatial, temporal, row or column restrictions;
- shared caching, rate/quota enforcement, production identity or ServiceSLO
  evidence is introduced.
