# ADR-045: Local Cross-Node NetworkPolicy Enforcement Evidence

**Status**: Accepted

**Date**: 2026-07-28

**Decision owners**: Metadata Platform, SRE, Security, Platform Architecture

**Related decisions**: [ADR-019](adr-019-configuration-and-runtime-truth.md) · [ADR-037](adr-037-local-metadata-fabric-foundation-sandbox.md) · [ADR-044](adr-044-production-observability-readiness-gate.md)

**Evidence**: [metadata-fabric-network-policy-enforcement-2026-07-28.json](../evidence/metadata-fabric-network-policy-enforcement-2026-07-28.json)

## Context

Metadata Fabric foundation manifests contain NetworkPolicy, but Kubernetes accepting a policy object does not prove that the installed CNI enforces it. M2d-1 needs a bounded live test that distinguishes API acceptance from data-plane behavior without changing OpenMetadata, Gravitino, GIS Data Agent, provider credentials, persistent data or RBAC.

The available Docker Desktop cluster uses a two-node kind topology. The kubectl client is `v1.36.1`, while the Kubernetes server and both kubelets are `v1.35.5`; the server is therefore recorded as `v1.35.5`, not inferred from the client. The CNI is the two-ready-pod `kindnet` DaemonSet with image `docker.io/kindest/kindnetd:v20260528-9350166c`.

This local environment is not a production cluster and does not carry a production tenant/workload identity model. The decision must therefore prove only isolated local cross-node enforcement and keep provider policy, tenant isolation and production claims false.

## Options Considered

| Option | Benefit | Cost/risk | Decision |
|---|---|---|---|
| Treat accepted NetworkPolicy resources as enforcement evidence | No live probe required | API persistence does not prove packet filtering | Rejected |
| Add policies directly to provider namespaces | Tests provider-adjacent traffic | Risks disrupting shared workloads and confounds policy design with CNI verification | Rejected |
| Test only same-node Pod traffic | Simple placement | Misses the cross-node overlay path | Rejected |
| Run digest-pinned probes in a short-lived namespace across two nodes | Exercises the actual kindnet data path and can be deleted atomically | Proves only this local cluster and synthetic traffic | Adopted for M2d-1 |

## Decision

### 1. Isolated and bounded probe topology

`config/metadata-fabric-network-policy-enforcement.local.yaml` and `k8s/metadata-fabric-network-policy-enforcement/` fix:

- context `docker-desktop`, namespace `gda-metadata-network-policy-rehearsal`, server node `desktop-control-plane` and client node `desktop-worker`;
- one HTTP server and two clients using BusyBox digest `sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662`;
- restricted Pod security contexts, no privilege escalation, all capabilities dropped, read-only root filesystems, no service-account token mount, no Secret/PVC/RBAC and no host namespace or hostPath access;
- one ClusterIP Service, one bounded ResourceQuota and four labeled NetworkPolicy resources;
- a fixed response body whose SHA-256 is retained instead of the raw response.

The server is scheduled on the control-plane node and both clients on the worker. Each traffic probe first checks the independent Kubernetes exec channel, so a failed HTTP request cannot be counted as policy enforcement merely because the Pod or exec transport is unavailable.

### 2. Five ordered enforcement stages

The runner applies policies cumulatively and accepts only this sequence:

| Stage | Authorized client | Denied client | Required interpretation |
|---|---|---|---|
| `baseline` | connected | connected | Cross-node Service path works without policy |
| `ingress_default_deny` | blocked | blocked | Server ingress default-deny is enforced |
| `ingress_authorized` | connected | blocked | Pod selector restores only authorized ingress |
| `egress_default_deny` | blocked | blocked | Authorized client egress default-deny is enforced |
| `egress_authorized` | connected | blocked | DNS plus server TCP/8080 restores only the allowed path |

Every connected result must have exit code zero and the exact response hash. Every blocked result must have a healthy exec channel, a non-zero request exit and no retained response hash. All three Pods must remain Ready after every stage.

### 3. Fail-closed identity, cleanup and evidence

`platform_truth.RUNTIME_INVENTORY` registers the runner as `metadata_network_policy_enforcement_rehearsal` with production role `local_verification_only`. Before apply it fixes the cluster UID, two node UIDs/versions/IPs/readiness, kindnet UID/image/readiness and existing provider identities. The runner refuses a pre-existing rehearsal namespace.

After the five stages it validates the exact labeled runtime inventory and policy spec fingerprints. Kubernetes API omission of empty default-deny rule arrays is normalized only for runtime fingerprint comparison; checked-in YAML must still explicitly contain `ingress: []` or `egress: []`.

The entire namespace is deleted in `finally`. Evidence is valid only if cleanup completes, the namespace is absent, provider identities are unchanged, and the cluster/node/CNI snapshot is unchanged. Contract drift, stale observation, unexpected resources, failed cleanup, sensitive fields or any production overclaim blocks the result.

## Verification

The 2026-07-28 Docker Desktop run completed in `29.953` seconds:

- Kubernetes server and both kubelets were `v1.35.5`; the two nodes were Ready;
- kindnet remained `2 desired / 2 ready / 2 available` with the fixed image;
- all five traffic stages matched the decision table, including both ingress and egress default-deny and selector-based recovery;
- server placement was `desktop-control-plane`; both clients were on `desktop-worker`;
- the exact 10-resource runtime inventory was present during the final stage;
- the rehearsal namespace was deleted and reported no remaining resources;
- GIS Data Agent and Metadata Fabric provider identities, node identities and kindnet identity were preserved;
- contract fingerprint: `b22dd622a68b7a413a22b1e51fd38724a3753d25797973e826f9bd411f20de42`;
- observation fingerprint: `cc48a5344a728c605f1eba07629b8a9a2e90da81695673b3c9dcc45e0a6d7a2f`;
- evidence fingerprint: `22b1ebe55e47bd05fee9cc17577c4eac861031b6b5bbb6c417c4b9f1ca29d060`.

Required tests cover profile and manifest drift, process/storage/privilege boundaries, Kubernetes API normalization, malformed nested objects, all five outcomes, CNI/server/node drift, cleanup/provider identity failure, stale contracts, sensitive fields, evidence tampering, production overclaim, runtime inventory registration and committed evidence integrity.

## Claim Boundary

Allowed:

- `local_network_policy_enforcement_verified=true`;
- scope `isolated_local_cross_node_kindnet_enforcement`;
- this exact local kindnet data plane enforced the five synthetic ingress/egress stages during the recorded run.

Fixed false:

- `production_network_policy_enforcement_verified`;
- `metadata_provider_network_policy_verified`;
- `tenant_isolation_verified`, `oidc_verified` and `upgrade_verified`;
- `writes_to_gda_enabled` and `production_ready`.

## Consequences

**Positive**: NetworkPolicy support is now backed by a real cross-node data-plane result instead of API object acceptance. The evidence is reproducible, contract-bound and leaves no rehearsal workload behind.

**Negative**: The probe uses synthetic Pods and one local kindnet cluster. It does not test production CNI configuration, provider-specific traffic matrices, multi-tenant identities, DNS failure modes, policy logging, upgrades or rollback.

**Next gate**: define approved production provider traffic and tenant/workload identity matrices, render provider-specific default-deny/allow policies, and verify them in a protected staging environment with the selected production CNI, DNS, observability and rollback procedure. Production enforcement and tenant isolation remain blocked until that independent attestation exists.
