# ADR-204: Release-Bound MVT Gateway Service Policy

## Decision

Each governed MVT `ServiceReleaseBinding` may have one immutable
`ServicePolicyBinding`. The first executable profile is deliberately limited to
the MVT Gateway read path:

- action: `mvt.read`
- enforcement point: `gateway`
- admitted roles
- roles that require an active, exact-version `ConsumerBinding`
- required ConsumerBinding operation: `read`

The binding belongs to one service definition and one release. A new MVT
endpoint or active-pointer update is rejected unless its release has both the
existing private cache policy and this service policy. The Gateway reads the
active binding before it calls Martin, rejects a role outside the policy, and
performs the ConsumerBinding lookup only for the roles declared by the policy.
The service-policy ID and fingerprint participate in the private tile cache
identity.

The table is tenant-RLS protected and immutable. The Gateway can read it and
execute the recorder, but has no direct write privilege.

## Consequences

The operational operator/admin path is now explicit in a release policy rather
than implicit in the route. Changing the allowed role set or the binding rule
requires a new immutable policy and a new deployment/endpoint release path.

This does not implement a general policy language, PolicyDecision audit
records, row/column/spatial/temporal/purpose obligations, controlled serving
projections, or provider-side authorization pushdown. Those remain separate
acceptance slices because Martin MVT cannot safely infer them from a role list.

## Verification

- `31 passed` focused contract and route tests cover policy fingerprinting,
  missing policy, role denial, consumer binding enforcement, and policy-aware
  cache identity.
- Disposable PostgreSQL certification applies migration 204, proves policy
  recorder idempotency, RLS, Gateway read/no-direct-insert privileges, and an
  active projection joined to the exact policy binding.
