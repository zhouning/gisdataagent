# ADR-216: Authenticated Gateway MVT Access Evidence

**Status**: Superseded for consumer authorization by ADR-218; the request audit and private-cache decision boundary remains active.  
**Date**: 2026-08-21  
**Related roadmap**: [GIS Data Agent Roadmap](../roadmap.md), AR-4.4  
**Related decisions**: [ADR-202](adr-202-release-bound-mvt-private-cache-policy.md), [ADR-204](adr-204-release-bound-mvt-service-policy.md), [ADR-205](adr-205-release-bound-mvt-serving-projection.md), [ADR-215](adr-215-martin-release-bound-conformance.md)

> **Supersession note, 2026-08-21.** The product-level `ConsumerBinding`
> discussed below was the initial MVT admission fact. It has been replaced at
> the MVT Gateway by the exact-release `ServiceConsumerBinding` defined in
> [ADR-218](adr-218-exact-release-gis-service-consumer-binding.md). Product
> bindings remain the authority for product promotion and consumer-impact
> workflows; they no longer authorize a tile endpoint.

## Context

ADR-215 proved that a disposable active release can be read through Martin. It
did not prove the client-facing path: whether an HTTP principal, the exact
ConsumerBinding, the active service policy and the static serving projection
remain tied together before a tile becomes visible.

The MVT route already had individual checks, but it did not produce one
immutable request decision spanning those facts. That left no auditable link
between a signed HTTP session and the subsequent Martin read, and cache identity
could not include the authorization decision that admitted the tile.

## Decision

### A request-scoped MVT access decision

`MVTAccessService` builds a self-verifying `MVTAccessRequest` and
`MVTAccessDecision` before the Gateway calls Martin. Its SHA-256 fingerprint
binds exactly one request's:

- `SubjectContext` parsed from the signed Chainlit cookie;
- tenant, service, source ProductVersion, release and service-policy IDs/hashes;
- MVT serving-projection ID/hash and `z/x/y` coordinate;
- exact ConsumerBinding ID/hash when the policy requires it.

The service policy currently accepts exactly one authenticated role per MVT
request. It checks the role, whether a ConsumerBinding is required, binding
subject/product/version identity, and the required `read` operation. The
decision expires after five minutes. This is a request fingerprint, not a
general policy language or a digitally signed entitlement token.

### Audit ordering and failure handling

For an admitted read, the immutable `security_event` chain is written in this
order:

```text
admitted (provider_invocations=0) -> Martin read -> outcome (provider_invocations=1)
```

The same decision SHA-256 appears in both admitted and outcome events. The
provider content and provider URL are never written to the ledger; successful
outcomes keep only content length and SHA-256, while failures keep the exception
type. Missing binding or policy failures create a `denied` event before the
route returns `403`.

The Gateway refuses to expose a successful provider response when either
admission or outcome evidence cannot be recorded. An audit-storage failure does
not turn a denied request into an allow.

### Private cache identity

The successful tile ETag and opaque cache namespace derive from the existing
cache policy plus tenant, active release, service policy, serving projection,
endpoint state, authenticated principal, ConsumerBinding (when present), tile
coordinate and `MVTAccessDecision` fingerprint. A change to any of those facts
creates a different cache identity.

The decision includes request evaluation time, so this baseline deliberately
does not reuse a decision fingerprint across separate requests. It establishes
isolation first; a shared cache or broader reuse needs a separately certified
revocation and invalidation model.

### HTTP certification

`scripts/certify_gis_mvt_gateway_http.py` extends the active Martin fixture
through its `after_activation` callback. In one temporary database and
short-lived Martin container it executes the FastAPI HTTP contract with three
requests:

| Request | Expected result |
|---|---|
| no cookie | `401` |
| signed cookie, no ConsumerBinding | `403 consumer_binding_required` |
| signed cookie, exact-version ConsumerBinding | non-empty MVT `200` |

The certification also checks private cache headers, active release headers,
the `denied -> admitted -> outcome` ledger sequence, common decision SHA-256,
provider invocation counts and full immutable-ledger chain verification. The
fixture removes its database, roles and Martin container after the result is
captured.

## Trade-offs

Putting this at the Gateway gives a precise, testable boundary using the
existing control plane and ConsumerBinding ledger. It also means Martin still
sees only a release-bound static projection. Dynamic row, column, spatial,
temporal and purpose constraints are not represented in this decision and are
not pushed to Martin.

Request-scoped decision identity favors authorization isolation over cache hit
rate. The current response cache contract is private only; no Redis, CDN,
GeoWebCache, purge worker or shared cache is introduced by this ADR.

## Verification

```bash
uv run pytest -q \
  data_agent/test_gis_mvt_access.py \
  data_agent/test_platform_gis_mvt_route.py \
  data_agent/test_certify_martin_active_release.py \
  data_agent/test_certify_gis_mvt_gateway_http.py

uv run python scripts/certify_gis_mvt_gateway_http.py \
  --database-url postgresql://postgres:postgres@127.0.0.1:5433/gis_agent \
  --report .tmp/gis-mvt-gateway-http-certification/report.json
```

The post-supersession certification and its current report hash are recorded in
[ADR-218](adr-218-exact-release-gis-service-consumer-binding.md).

## Revisit Triggers

- deploy a production OIDC/workload-identity gateway rather than the current
  signed-cookie test identity;
- introduce dynamic row/column/spatial/temporal/purpose obligations with a
  provider that can enforce and certify them;
- add Redis/CDN/shared caching, revocation propagation, purge/warmup and
  cache-hit telemetry;
- prove high availability, rate/quota enforcement, SLO/incident handling and
  non-Martin provider conformance.
