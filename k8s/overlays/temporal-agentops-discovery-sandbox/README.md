# Temporal AgentOps Discovery Sandbox Overlay

This overlay enables the Temporal metadata database, Temporal frontend, and two
discovery worker replicas for a disposable sandbox. It is separate from the base
profile and requires both external Secrets to exist before applying:

- `gis-agent-temporal-runtime` with `database-password`
- `gis-agent-agentops-discovery-runtime` with `database-url` and `tenant-id`

Apply the control-database ingress policy from
`k8s/optional/temporal-agentops-discovery-control-access` separately. The overlay
does not prove production HA, backup/restore, RPO/RTO, identity rotation, network
partition recovery, or rollout safety until those failure scenarios are exercised
against the target cluster.

Run the read-only deployment preflight before applying either package:

```bash
.venv/bin/python scripts/preflight_agentops_temporal_discovery_sandbox.py \
  --schema-report /path/to/authorized-migration-status.json
```

The report fails closed unless migrations 240/241/242/246, the external runtime Secret,
and the cross-namespace policy are observed. ServiceMonitor is an optional
observability package; check it separately when Prometheus Operator is installed.
Before a
post-apply check, the expected Deployment is allowed to be absent; pass
`--expect-deployed` to require two replicas. It never creates or mutates
Kubernetes resources. Use `--static-only` in CI when cluster observation is
intentionally unavailable.
