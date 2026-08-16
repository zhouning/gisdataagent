# ADR-046: Production NetworkPolicy Readiness Gate

**Status**: Accepted

**Date**: 2026-07-28

**Decision owners**: Metadata Platform, SRE, Security, Platform Architecture

**Related decisions**: [ADR-019](adr-019-configuration-and-runtime-truth.md) · [ADR-037](adr-037-local-metadata-fabric-foundation-sandbox.md) · [ADR-044](adr-044-production-observability-readiness-gate.md) · [ADR-045](adr-045-local-cross-node-network-policy-enforcement.md)

## Context

M2d-1 proved that the local two-node Docker Desktop kindnet data plane enforced a bounded synthetic ingress/egress sequence. It did not select a production cluster or CNI, apply provider policies, bind production workload identities, isolate real tenants, deliver policy logs or rehearse a production rollback.

Promoting that local result to a production claim would erase the most important boundaries in the evidence. Conversely, leaving the production requirements only in roadmap prose would not prevent incomplete traffic matrices, mutable image references, stale attestations or self-asserted production claims from passing review.

M2d-2 therefore needs a machine-verifiable decision contract that remains valid while production inputs are explicitly pending. It must not deploy NetworkPolicy, modify OpenMetadata or Gravitino, hold credentials, or independently authorize overall GIS Data Agent production readiness.

## Options Considered

| Option | Benefit | Cost/risk | Decision |
|---|---|---|---|
| Treat the M2d-1 kindnet run as production evidence | No new contract | Local synthetic traffic does not bind production CNI, providers or tenants | Rejected |
| Apply a generic default-deny policy to the existing provider namespace | Quickly creates policy objects | Unapproved selectors and flows could interrupt providers; API acceptance is not enforcement evidence | Rejected |
| Keep the production checklist only in roadmap text | No new code | CI cannot reject drift, placeholders, stale evidence or overclaims | Rejected |
| Versioned pending profile plus fresh profile-bound attestation | Separates decisions from observations and fails closed without inventing production values | Requires explicit ownership of profile and attestation lifecycle | Adopted for M2d-2 |

## Decision

### 1. Checked-in profile records intent, not a deployment

`config/metadata-fabric-network-policy.production.yaml` fixes:

- OpenMetadata `1.13.1` and Gravitino `1.3.0` as the provider baseline;
- a production cluster, Kubernetes version, selected CNI and exact DNS selectors/ports;
- ingress and egress default-deny, admission-bound workload identity labels and a digest-pinned OCI policy bundle;
- eight provider/control/observability/backup/storage workload bindings;
- namespace-per-tenant isolation and admission-controlled tenant labels;
- exactly ten tenant-scoped provider API, metrics, storage and backup flows;
- policy logging, incident owner, operational runbook and rollback runbook;
- every self-reported production claim fixed to `false`.

The allowed production CNI inventory is `antrea`, `calico`, `cilium` or `cloud_managed`; local `kindnet` is deliberately excluded. `null`, empty selectors, an empty traffic inventory and `decision_status=pending` are valid explicit blockers, so the checked-in profile can pass structural validation without pretending the production design is complete.

Placeholder values, unexpected workload or flow inventory, changed source/destination/port/purpose, non-HTTPS or loopback runbooks, a mutable OCI reference, credential-bearing fields, provider version drift or any self-asserted production claim makes the profile invalid.

### 2. A separate attestation establishes the single gate result

`data_agent.metadata_fabric_network_policy_gate` derives:

1. `profile_valid`: profile structure, approved baseline and claim boundaries are valid;
2. `ready_for_protected_verification`: all cluster, CNI, DNS, identity, tenancy, traffic and operational decisions are complete;
3. `production_network_policy_gate_passed`: a fresh protected production environment attestation is additionally valid and bound to the current profile.

The attestation binds the profile fingerprint, source revision, provider versions, cluster/CNI/DNS configuration, digest-pinned policy bundle, workload-binding and traffic-matrix fingerprints, and both runbook versions. Its exact 17-check inventory must pass rendered policy validation; CNI ingress/egress enforcement; label admission; both default-deny directions; allowed API, storage, observability and backup paths; unauthorized and cross-tenant denials; DNS; policy-log delivery; rollback; and preserved provider health.

Observation time must be within 24 hours of evaluation, expiry must remain in the future and the validity interval cannot exceed seven days. Evidence must use a non-local HTTPS URI. Any profile drift, binding mismatch, failed check, expired evidence, malformed inventory or sensitive field closes the gate.

### 3. This gate does not establish overall production readiness

When the single gate passes, the report may derive `production_network_policy_enforcement_verified`, `metadata_provider_network_policy_verified` and `tenant_isolation_verified` from that same bound attestation. `production_ready` remains fixed to `false` because production recovery, observability, OIDC, upgrades, registry provenance, ingestion and the remaining AR-0/AR-1 exit gates are independent.

`validate` checks the checked-in profile and succeeds for a valid pending contract. `evaluate` requires an attestation and succeeds only when the production NetworkPolicy gate passes. `verify` rejects report fingerprint drift, inconsistent derived claims and any overall production-readiness overclaim.

## Verification

The checked-in profile currently produces:

- profile fingerprint `686e6f476c7b36d8a837776b6f48bb42d5c3d45014ef3de7fef3a512ad4ae5d1`;
- `profile_valid=true` and no profile errors;
- 62 explicit external production blockers;
- `ready_for_protected_verification=false` and `attestation_valid=false`;
- all production NetworkPolicy/provider/tenant claims and `production_ready` fixed to `false`.

The 23 focused tests cover the pending and complete profiles, fresh bound synthetic attestation, cluster/CNI/DNS drift, workload identity/selector/admission drift, missing/extra/changed traffic, cross-tenant denial, logging and rollback checks, placeholder/HTTP/loopback and mutable OCI references, sensitive fields, self-asserted claims, expiry, malformed YAML, report tampering and production overclaim.

## Claim Boundary

Allowed now:

- M2d-2 production NetworkPolicy readiness contract is established;
- the checked-in pending profile is structurally valid and exposes its blockers;
- synthetic complete profile/attestation fixtures verify the gate logic.

Fixed false now:

- `production_network_policy_gate_passed`;
- `production_network_policy_enforcement_verified`;
- `metadata_provider_network_policy_verified`;
- `tenant_isolation_verified`;
- `production_ready`.

There is no selected production cluster/CNI, deployed provider policy bundle, protected production attestation, verified production policy logging or production rollback evidence in this change.

## Consequences

**Positive**: production NetworkPolicy decisions are explicit, reviewable and drift-bound. CI can reject incomplete or broadened flow contracts without turning pending values into deployments or evidence.

**Negative**: M2d-2 adds no packet filtering by itself. The gate remains blocked until Platform, Security and SRE approve concrete production identities, traffic, logging and rollback inputs and execute them in the protected environment.

**Next gate**: approve and materialize the production profile, publish the digest-pinned policy bundle, apply it in the protected environment, and produce a fresh bound attestation from the selected production CNI. Then complete independent production recovery, observability, identity, upgrade, provenance and M3 ingestion gates before any overall production claim.
