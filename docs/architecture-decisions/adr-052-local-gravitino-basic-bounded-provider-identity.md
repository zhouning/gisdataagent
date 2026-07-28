# ADR-052: Local Gravitino Basic Bounded Provider Identity

**Status**: Accepted

**Date**: 2026-07-28

**Decision owners**: Metadata Platform, Data Governance, Security, Platform Architecture

**Related decisions**: [ADR-006](adr-006-openmetadata-governance-and-active-metadata-platform.md) · [ADR-024](adr-024-dispatch-authorization-evidence.md) · [ADR-037](adr-037-local-metadata-fabric-foundation-sandbox.md) · [ADR-047](adr-047-deterministic-metadata-fabric-ingestion-projection.md) · [ADR-051](adr-051-local-openmetadata-bounded-provider-identity.md)

## Context

M3-2 used the OpenMetadata bootstrap administrator and an unauthenticated Gravitino `simple` authenticator. M3-5 then proved a bounded OpenMetadata grant, but the Gravitino side still had no honest authentication or authorization evidence. Gravitino `1.3.0` ships a Basic IdP extension, so a separately isolated rehearsal can validate the provider-native identity boundary without mutating the retained M3-2 projection.

The `simple` authenticator is deliberately excluded: upstream behavior accepts unvalidated usernames and therefore cannot count as authentication. This rehearsal also cannot establish protected Kubernetes workload identity, OIDC federation, TLS, durable catalog conformance or production readiness.

## Decision

### 1. Run an isolated, ephemeral provider

The rehearsal uses Docker Desktop Kubernetes context `docker-desktop` and a pre-existing, checksum-verified Gravitino PostgreSQL schema (`7a2d605a677a462ca619dba594ce7ebcf500358345560ad084c1b67a25c722df`). It creates only the `gda-metadata-identity` namespace, two single-replica StatefulSets, ClusterIP Services, dedicated ServiceAccounts with token automount disabled, and runtime-generated Kubernetes Secret values. The namespace is deleted before evidence can pass; no Secret value or provider error body enters source, evidence or logs.

The server is Gravitino `1.3.0` (`gda/gravitino:1.3.0-local-arm64`) with `gravitino.authenticators=basic`, the Basic IdP REST extension and `gravitino.authorization.enable=true`. The provider's relational entity store uses the ephemeral PostgreSQL instance; the probe catalog remains an ephemeral memory catalog and is not a production technical-metadata authority.

### 2. Keep the administrator as a provisioner only

The built-in Basic IdP administrator `gda-identity-admin` creates the temporary metalake, catalog, schema, user, role and grant. The exercised principal `gda-metadata-projection` is not a service administrator and receives exactly `gda-table-projection`.

The role contains only:

- `USE_CATALOG` on catalog `lakehouse`;
- `USE_SCHEMA` and `CREATE_TABLE` on schema `lakehouse.published`.

The API client sends the Gravitino 1.3.0 `RoleGrantRequest` field `roleNames` and normalizes provider read-back enum casing at the HTTP boundary. Any extra privilege, role, object or changed scope blocks evidence.

### 3. Require positive, negative and lifecycle probes

The rehearsal must observe service-admin authentication (200), an unregistered principal rejection (401), bounded-user authentication (200), table create/read (200/200), and catalog create denial (403). The administrator resets the user password; the old material must return 401 and the replacement must read the probe table. The administrator then deletes the IdP user; the replacement material must return 401 and the IdP lookup must be absent.

The four local claims are intentionally narrow: `local_gravitino_basic_identity_verified`, `local_gravitino_minimum_privilege_verified`, `local_gravitino_login_rotation_verified` and `local_gravitino_revocation_verified`. They do not imply a protected workload identity or a production provider identity.

### 4. Preserve the claim boundary

Evidence fixes `gravitino_authentication_verified=false`, `provider_minimum_privilege_verified=false`, `protected_workload_identity_verified=false`, `oidc_verified=false`, `tls_verified=false`, `production_identity_verified=false` and `production_ready=false`. The local provider result is not combined with M3-5 into a dual-provider production claim: M3-2 still uses the bootstrap administrator, and this rehearsal is isolated from the retained projection and binding ledger.

## Verification

The final Docker Desktop rehearsal on 2026-07-28 produced evidence fingerprint `f0b0de1f80f079d43318937e0a0cc151a8546e9e307bef204738b1367f9b29fd` and contract fingerprint `c1c8b08e52c88742fd273378735491626bc4a185f3416746eafa4932374a3704`.

- Gravitino `1.3.0` and PostgreSQL each reached one ready replica;
- the Basic IdP rejected an unregistered principal with 401 and authenticated the bounded user with 200;
- the bounded role read back exactly `USE_CATALOG`, `USE_SCHEMA` and `CREATE_TABLE` on the declared catalog/schema;
- table create/read returned 200/200 and unauthorized catalog create returned 403;
- password reset invalidated the old material (401), the replacement read the table (200), and IdP deletion invalidated the replacement (401);
- namespace deletion completed, the namespace was absent, all port-forwards stopped and no provider object was retained.

Focused tests cover strict profile and manifest validation, sensitive-field rejection, exact role scope, positive/negative probes, enum read-back normalization, rotation/revocation, cleanup and evidence tampering. Required CI validates the static contract and runs the focused test module; live Kubernetes evidence remains a local verification artifact.

## Consequences

**Positive**: Gravitino now has a real, bounded local authentication and authorization rehearsal with explicit lifecycle and cleanup evidence. The API contract is checked against the actual 1.3.0 DTO instead of relying on a mock-only request shape.

**Negative**: Basic IdP credentials are locally provisioned by an administrator, the catalog is ephemeral, transport is loopback HTTP, and the provider workload is not authenticated with its Kubernetes ServiceAccount.

**Mitigation**: retain all production and protected-identity claims as false. The next identity gate must select and validate the protected OIDC/workload exchange, Secret delivery and rotation mechanism for both metadata providers, durable catalog profile, TLS, tenant policy and production conformance.

**Revisit trigger**: Gravitino version, Basic IdP API, authorization model, catalog backend, cluster identity model or production deployment profile changes.
