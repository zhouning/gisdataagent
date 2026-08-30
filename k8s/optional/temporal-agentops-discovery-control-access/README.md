# AgentOps Discovery Control-Database Access

This optional package adds the one cross-namespace ingress rule required by the
Temporal start-target discovery worker. It targets the `gis-agent` PostgreSQL
pods and permits TCP/5432 only from the `gis-agent-agentops-discovery` pods in
the `gda-agentops-sandbox` namespace.

Apply it only after the discovery worker's runtime Secret
`gis-agent-agentops-discovery-runtime` has been provisioned in the sandbox
namespace. That Secret must contain `database-url` and `tenant-id`; the URL's
login must be a member of the existing `gda_control_gateway` database role and
must not be a superuser. Migration 242 and the preceding checkpoint/fencing
migrations remain the schema authority.

The policy does not grant database permissions, create a Secret, or establish
production HA. Review the cluster CNI and database role grants before enabling
the discovery deployment.

Render without contacting a cluster:

```bash
kubectl kustomize k8s/optional/temporal-agentops-discovery-control-access
```
