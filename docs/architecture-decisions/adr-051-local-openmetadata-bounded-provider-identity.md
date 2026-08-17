# ADR-051: Local OpenMetadata Bounded Provider Identity

**Status**: Accepted

**Date**: 2026-07-28

**Decision owners**: Metadata Platform, Data Governance, Security, Platform Architecture

**Related decisions**: [ADR-006](adr-006-openmetadata-governance-and-active-metadata-platform.md) · [ADR-024](adr-024-dispatch-authorization-evidence.md) · [ADR-037](adr-037-local-metadata-fabric-foundation-sandbox.md) · [ADR-048](adr-048-local-authorized-metadata-fabric-ingestion-replay.md) · [ADR-050](adr-050-idempotent-openlineage-http-delivery.md)

## Context

M3-2 mutated the local providers with the OpenMetadata bootstrap administrator and unauthenticated Gravitino. M3-3 and M3-4 then proved binding persistence and idempotent lineage delivery without calling either provider. The next identity slice must answer a narrower question before protected OIDC is available: can OpenMetadata `1.13.1` provision a dedicated non-admin bot, restrict the project-specific grant to the required resource operation, reject an administrative mutation, and invalidate old credentials after rotation and revocation?

The local Gravitino `1.3.0` deployment uses the `simple` authenticator with `gravitino.authorization.enable=false`. It cannot support an honest equivalent claim in this sandbox. Kubernetes ServiceAccounts also have token automount disabled and are not used to authenticate the local HTTP caller. This decision therefore separates a bounded OpenMetadata provider-native result from protected workload identity and the unverified Gravitino boundary.

## Options Considered

| Option | Benefit | Cost/risk | Decision |
|---|---|---|---|
| Reuse `IngestionBotRole` | Provider-native and immediately available | Grants Create/Delete/EditAll across all resources and cannot prove a bounded project role | Rejected |
| Keep the bootstrap administrator in the ingestion path | Matches M3-2 | No least-privilege or credential-lifecycle evidence | Rejected |
| Create a dedicated OpenMetadata policy, role and JWT bot for one ephemeral probe | Exercises real provider authorization, rotation and revocation | OpenMetadata still attaches its mandatory `DefaultBotRole`; bootstrap admin provisions the identity | Adopted for local OpenMetadata only |
| Enable Gravitino access control without a validated identity backend | Appears to complete both providers | Would turn configuration presence into a false authentication claim | Rejected |

## Decision

### 1. The bootstrap administrator is only an ephemeral provisioner

The local Basic administrator may create and remove the dedicated policy, role, bot user and bot. Its access value remains in memory and never enters evidence or exceptions. The bot principal must report `isAdmin=false`, `isBot=true` and exactly two roles: provider-mandatory `DefaultBotRole` plus `GdaMetadataTableProjectionRole`. Any pre-existing rehearsal object blocks before mutation.

The administrator is not described as minimum privilege. Kubernetes ServiceAccount identity is observed only to confirm the provider workload still uses `openmetadata` with token automount disabled; it is not presented as the HTTP caller.

### 2. The only project-specific grant is `Create` on `table`

`GdaMetadataTableProjectionPolicy` contains exactly one allow rule: operation `Create`, resource `table`. Broad resources, `EditAll`, `Delete`, `All`, extra roles or a changed policy block evidence. OpenMetadata mandatorily attaches `DefaultBotRole`; therefore `local_openmetadata_minimum_privilege_verified=true` is explicitly scoped to `dedicated_table_create_grant_with_provider_mandatory_default_role`. It does not mean that all provider defaults contain only this operation.

The positive probe creates and reads back `gda_lakehouse.land_use.published.gda_provider_identity_probe`. The same bot then attempts to create `GdaUnauthorizedPolicyProbe`; only HTTP 403 passes. OpenMetadata HTTP 200 and 201 are both valid successful create outcomes, while an unexpectedly accepted denied probe is tracked for administrator cleanup and blocks evidence.

### 3. Rotation and revocation must invalidate the exercised JWT

The bot first authenticates with a one-hour JWT. The administrator rotates it through the provider API. The old value must then return 401, while the new value must authenticate as the same provider user. After explicit revocation, the new value must also return 401. No JWT, password, Secret, credential hash or provider error body is recorded.

This is a local provider-native static JWT lifecycle. It is not OIDC federation, short-lived workload exchange, external secret delivery, protected provisioning, automated rotation scheduling or production IAM.

### 4. The rehearsal leaves no provider object behind

The probe table, bot, user, role, dedicated policy and any unexpectedly created denial probe are removed in dependency order. Final natural-key lookups must all return absent, and the loopback port-forward must stop before evidence can pass. The historical M3-2 projection and GDA control data are not mutated.

### 5. Gravitino remains blocked

Evidence fixes `gravitino_authentication_verified=false`, `provider_minimum_privilege_verified=false`, `protected_workload_identity_verified=false`, `oidc_verified=false`, `production_identity_verified=false` and `production_ready=false`. Gravitino requires a separately selected authenticated backend, enabled access control, durable catalog profile and positive/negative provider tests before any of those boundaries may change.

## Verification

The local Docker Desktop rehearsal records:

- OpenMetadata workload `openmetadata` at `1.13.1`, ServiceAccount `openmetadata`, token automount disabled and one ready replica;
- non-admin bot user UUID `4b492bb1-b32d-4f05-9cb6-878a6a2bce45` and bot UUID `94ed8f54-d1eb-44a4-a28b-34f19a5c5505`;
- dedicated policy UUID `df3b5584-6185-49b9-8e29-e43fbadd174c` and role UUID `e41ffd2b-2bea-41a0-beaa-22fe0df9f21c`;
- table create HTTP 201, read-back HTTP 200 and provider table UUID `740124bc-b972-419e-9990-5b071ba8ca1e`;
- policy create HTTP 403;
- old JWT after rotation HTTP 401, rotated JWT HTTP 200 and rotated JWT after revocation HTTP 401;
- all six natural-key cleanup checks passed and the port-forward stopped;
- evidence fingerprint `61b6a3429ae948f563bfc2bd012d8b586be581704cec646fd5e74b991243f03f`.

Focused tests cover strict profile parsing, broad policy and production-claim rejection, sensitive-field rejection, role/policy/denial/lifecycle/cleanup drift, evidence tampering and a stateful HTTP transport that exercises create, rotate, revoke and cleanup without projecting JWT values.

## Claim Boundary

Allowed now:

- one ephemeral local OpenMetadata bot used a dedicated `table/Create` grant and was denied `policy/Create`;
- provider JWT rotation invalidated the old value and explicit revocation invalidated the replacement;
- the bounded identity and probe objects were removed after the rehearsal;
- `local_openmetadata_bounded_identity_verified`, scoped local minimum privilege, JWT rotation and JWT revocation are true for this observation.

Fixed false now:

- minimum privilege across both metadata providers;
- protected workload identity, Kubernetes-to-provider identity exchange and OIDC;
- Gravitino authentication, authorization and durable catalog conformance;
- production credential provisioning, storage, delivery, scheduled rotation and incident recovery;
- production ingestion and `production_ready`.

## Consequences

**Positive**: M3 no longer relies only on bootstrap-admin behavior to understand OpenMetadata authorization. A dedicated provider identity now has a real allow result, administrative denial, rotation result, revocation result and cleanup proof.

**Negative**: the test identity is provisioned by a local administrator and OpenMetadata adds a mandatory default bot role. The identity is ephemeral and is not wired into the retained M3-2 projection or a protected worker.

**Mitigation**: keep the overall provider and production claims false. In a protected environment, replace local Basic provisioning with an attested identity workflow, bind the exact workload and deployment revision, deliver short-lived credentials without repository or evidence exposure, repeat positive/negative tests, and independently enable and validate Gravitino authentication and access control.

**Revisit trigger**: change this contract when OpenMetadata provider defaults, JWT APIs, protected OIDC exchange or Gravitino's selected authentication and authorization model changes.
