# Temporal AgentOps Sandbox Profile

This optional Kustomize package defines the first deployable boundary for the AgentOps
Temporal runtime. It is deliberately separate from `k8s/base` and renders in namespace
`gda-agentops-sandbox`.

Before applying it, provision the external Secret `gis-agent-temporal-runtime` with key
`database-password` after the declared namespace exists. Do not commit a Secret manifest or
database password. The profile declares the namespace and uses a dedicated PostgreSQL StatefulSet for Temporal metadata,
not the GIS Data Agent control database.

The profile is closed by default: Temporal PostgreSQL, Temporal server, the placeholder
execution worker, and the start-target discovery worker all render with `replicas: 0`. The server image is pinned to the available
`temporalio/auto-setup:1.29.7`; the Python worker SDK is separately pinned to `temporalio==1.32.0`.
The server binds to `0.0.0.0` inside the pod so an explicitly requested local `kubectl port-forward`
can reach the frontend; this is a sandbox connectivity setting, not a public-network exposure.
The execution worker remains disabled in Kubernetes because this repository does not ship a certified
AgentOps action-handler image. The discovery worker is a separate disabled-by-default deployment;
when enabled it uses the GDA control database (`DATABASE_URL`) and a tenant-id Secret, claims
start targets from migration 242, and observes Temporal history. The worker also requires the
specialist operation-receipt authority from migration 246 and an explicit Artifact content backend;
the base sandbox uses a disposable filesystem backend mounted as an `emptyDir`. It does not execute
activities or create workflows. Scaling only the server and metadata database is a provider sandbox,
not an AgentOps execution environment.

For a disposable two-replica discovery rehearsal, use
`k8s/overlays/temporal-agentops-discovery-sandbox`. That opt-in overlay changes
discovery to two replicas with `RollingUpdate` (`maxUnavailable: 0`, `maxSurge: 1`)
and a one-pod disruption budget. It still requires the external discovery runtime
Secret and a separately applied cross-namespace control-database policy.

Render without contacting a cluster:

```bash
kubectl kustomize k8s/optional/temporal-agentops-sandbox
```

The explicit sandbox overlay enables only the metadata database and Temporal server:

```bash
kubectl kustomize k8s/overlays/temporal-agentops-sandbox
kubectl apply -k k8s/overlays/temporal-agentops-sandbox
```

That overlay still leaves `gis-agent-agentops-worker` and `gis-agent-agentops-discovery` at `replicas: 0`. It is suitable for
server/namespace connectivity and provider-adapter rehearsal only. It does not prove Temporal
workflow execution, durable retries, crash/restart or replay, timers, signal handling, worker
HA, OIDC/workload identity, backup/restore, RPO/RTO, or production SLOs.

The NetworkPolicies allow worker-to-frontend and Temporal-to-PostgreSQL traffic, plus cluster DNS;
there is no ingress from the public network. Review the cluster CNI's enforcement behavior before
using this profile as a security boundary.

The discovery metrics Service is part of the core worker profile. The Prometheus Operator
`ServiceMonitor` is intentionally separate in
`k8s/optional/temporal-agentops-discovery-observability`; clusters without that CRD can still run
the worker and inspect its native `/metrics` endpoint.

The discovery worker's connection to the GDA control PostgreSQL is a cross-namespace rule and is
kept in the separate `k8s/optional/temporal-agentops-discovery-control-access` package. Apply that
package only after reviewing the `gis-agent` database boundary; the Temporal sandbox package itself
does not mutate policies in another namespace.
