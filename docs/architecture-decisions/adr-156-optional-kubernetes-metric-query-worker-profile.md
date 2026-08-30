# ADR-156: Optional Kubernetes Profile for the Metric Query Worker

**Status**: Accepted

**Date**: 2026-08-05

**Related**: ADR-095, ADR-154, ADR-155

**Superseded in part by**: ADR-157 replaces the PVC-backed result topology.

## Context

ADR-155 defined a managed PostGIS metric-query process, but it did not define how Kubernetes should
preserve the process boundary, owner-only provider credential, health semantics and local Artifact
path. Adding an unproven worker to the default base would silently change every environment. A
projected Secret is normally readable by the pod group and cannot directly satisfy the worker's
owner-only file contract.

The current provider writes `file://` result Artifacts. Multiple replicas cannot safely share that
local result authority, and an RWO volume cannot support a general horizontally scaled worker.

## Options Considered

| Option | Benefits | Costs and risks | Decision |
|---|---|---|---|
| Add the worker to `k8s/base` | Automatic rollout with the platform | Changes all environments before live acceptance | Rejected |
| Put the provider URL directly in an environment variable | Simple Secret reference | Expands credential exposure and violates the file contract | Rejected |
| Mount the projected Secret directly into the worker | No init step | Projected mode/ownership does not prove owner-only access | Rejected |
| Ship an optional single-replica profile with an init materializer | Explicit adoption and preserves the worker contract | Requires environment patches and remains a sandbox topology | Chosen |

## Decision

`k8s/optional/metric-query-worker` is an additive Kustomize package and is not referenced by
`k8s/base`. It creates a tenant-scoped Deployment, ConfigMap, ServiceAccount, result PVC and two
NetworkPolicies. Environments must explicitly render, patch and apply it after migrations 137
through 139 and the required Secret have been provisioned by their authorities.

The pod and both containers run as UID/GID 10001 with `RuntimeDefault` seccomp, no privilege
escalation, a read-only root filesystem, all Linux capabilities dropped and no service-account
token. The projected provider Secret is visible only to the init container. A non-root shell
materializer atomically copies its non-empty URL to a memory-backed `emptyDir`, verifies current-UID
ownership and mode 0400, and emits no credential content. The worker mounts only that copy. Platform
control credentials continue to use the existing Secret references and explicitly disable admin
credential fallback.

Startup and liveness call the local liveness command; readiness calls the stricter health command.
A fresh degraded worker therefore remains live while becoming unready, and a stale or stopped
worker fails closed. The pod has no ingress. Egress is limited to cluster DNS and the in-namespace
PostgreSQL pod. A second ingress policy adds the worker to PostgreSQL access using Kubernetes'
additive NetworkPolicy semantics, preserving the access already granted by `k8s/base`.

The Deployment has one replica, uses `Recreate` and writes results to an RWO PVC. These constraints
prevent concurrent local Artifact ownership during updates. The package assumes the base namespace,
PostgreSQL labels and secrets already exist; external databases and cluster-specific DNS require
reviewed NetworkPolicy patches.

## Verification

- Offline deployment tests parse the YAML and verify optional composition, Secret non-generation,
  non-root and no-escalation controls, main-container Secret separation, admin fallback disablement,
  fail-closed probes, exact network peers and the single-replica RWO persistence contract.
- The materializer tests prove mode 0400/current-UID output, redacted stdout/stderr and rejection of
  a symlink destination without changing its target.
- `kubectl kustomize k8s/optional/metric-query-worker` renders successfully without contacting a
  cluster. Shell syntax, Python/Ruff and shared regression checks remain release gates.

## Consequences

- Operators can adopt the PostGIS worker without changing the default platform base.
- The main process never mounts the broadly projected provider credential.
- Network, storage and rollout assumptions are visible and testable rather than implicit.
- This is a deployment contract only. It is not evidence of a staging or production rollout,
  NetworkPolicy enforcement, secret rotation, backup/restore, capacity/SLO behavior or live failure
  recovery.
- The PVC-backed `file://` result path is a sandbox limitation. Production promotion requires a
  cluster-accessible object-store Artifact backend and a corresponding multi-replica ownership
  design before horizontal scaling.

## Revisit Trigger

Replace the RWO/local-result topology when the Artifact authority supports cluster-accessible
object storage. Add replicas or autoscaling only after provider concurrency, lease behavior and
query latency have measured SLOs. Promote the profile into an environment base only after a live
rollout, NetworkPolicy enforcement, secret rotation and failure-recovery rehearsal pass there.
