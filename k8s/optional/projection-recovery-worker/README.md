# Projection Recovery Worker Optional Profile

This profile deploys the durable projection recovery worker with the PostgreSQL-backed
cross-store controller adapter. It is intentionally excluded from `k8s/base` and defaults to
`replicas: 0`; an environment overlay must scale it after provisioning these runtime objects:

- `gis-agent-projection-recovery-runtime`, containing only `tenant-id`;
- `gis-agent-projection-recovery-admission`, containing the server-owned `admissions.json` bundle
  keyed by sealed `plan_sha256`.

The admission bundle contains recovery identity evidence, not provider credentials. It is mounted
read-only and validated against the job tenant, binding fingerprint, and the sealed plan's source
ResourceVersion/content SHA-256 before a provider is called.

The bundle format is `gda.cross_store_recovery_admission_bundle.v1`. An environment-owned recovery
controller should build it with
`ProjectionRecoveryAdmissionBundle.from_admissions(...)` only after source/restored manifest
comparison and durable authority read-back, then publish it with
`rotate_projection_recovery_admission_bundle(...)`. Rotation is same-directory `fsync` plus atomic
`os.replace`; the worker therefore reads either the old complete bundle or the new complete bundle.
The bundle has no signing or credential semantics by itself, so production publication still needs
the environment's workload identity/OIDC and Secret Manager policy.
The worker has no Kubernetes API token, runs as UID/GID 10001 with a read-only root filesystem, and
uses a dedicated ServiceAccount. The NetworkPolicy allows only cluster DNS, in-namespace
PostgreSQL and MinIO. Add an environment-reviewed egress patch before enabling an RDF or external
lakehouse provider.

PostGIS/pgvector rebuilds additionally require an environment-owned volume containing plan-bound row
bundles at `/var/lib/gda/projection-recovery-rows`; the base profile uses an empty memory volume so
missing bundles fail closed rather than reading arbitrary host data.

Render without changing a cluster:

```bash
kubectl kustomize k8s/optional/projection-recovery-worker
```

To explicitly enable this worker in a sandbox environment, use
`k8s/overlays/projection-recovery-sandbox`. That overlay patches only the
Deployment replica count and still requires the environment-owned Secrets and
base PostgreSQL/MinIO services described above.

This is a sandbox deployment contract. It does not establish controller HA, production workload
identity/OIDC, provider replication/PITR, or RPO/RTO.
