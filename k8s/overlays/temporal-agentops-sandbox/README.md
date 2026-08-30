# Temporal AgentOps Sandbox Overlay

This overlay is an explicit opt-in for a local Temporal provider rehearsal. It enables one
Temporal server and one dedicated metadata PostgreSQL replica while leaving the AgentOps worker
disabled at `replicas: 0`.

The required Secret is external to this repository:

```bash
# Create the namespace once; the Kustomize package also declares it.
kubectl apply -f k8s/optional/temporal-agentops-sandbox/namespace.yaml
kubectl -n gda-agentops-sandbox create secret generic gis-agent-temporal-runtime \
  --from-literal=database-password='REPLACE_WITH_CLUSTER_SECRET'
```

Use the command only with a cluster secret authority in a disposable sandbox. Never put the
password in Git or shell history used for a shared environment. Render first and inspect the
result:

```bash
kubectl kustomize k8s/overlays/temporal-agentops-sandbox
```

Applying this overlay does not start a worker and does not constitute production readiness.
