# DuckDB Blueprint Worker Optional Profile

This Kustomize package deploys one tenant-scoped DuckDB Blueprint command
worker without adding it to `k8s/base`. It requires migrations 197 through 202
to have been applied by the migration authority before rollout.

Provision `gis-agent-duckdb-blueprint-runtime` through the cluster secret
authority with these keys:

- `tenant-id`: the exact platform tenant;
- `s3-access-key-id` and `s3-secret-access-key`: a dedicated worker identity.

Do not commit this Secret, a root credential, an endpoint signed URL or any
input data. The worker reads no Kubernetes API token and does not receive a
MinIO administration credential.

Provision `gis-agent-blueprint-results` as a new bucket with versioning and
Object Lock enabled at creation time, with a positive default `GOVERNANCE` or
`COMPLIANCE` retention. The scoped identity requires:

- `GetBucketLocation` for the admitted input and output buckets;
- `GetBucketVersioning` and `GetBucketObjectLockConfiguration` on the output
  bucket;
- `GetObject` and `GetObjectVersion` only under
  `gis-agent-lakehouse/products/`, `gis-agent-uploads/admitted/`, and the
  Blueprint output prefix;
- `PutObject` only under `blueprint-duckdb-results/v1/` in the output bucket.

It must not receive `DeleteObject`, retention-bypass, user-upload write,
cross-prefix write or bucket-administration permissions. Patch the ConfigMap
for environment bucket names and prefixes before applying.

The pod has no ingress, and its egress is limited to cluster DNS, PostgreSQL
and MinIO. Its private workspace and status files use `emptyDir`; S3 is the
only result authority. The profile intentionally has one replica and
`Recreate`: this worker has no mid-query lease heartbeat or multi-replica SLO
evidence yet. `terminationGracePeriodSeconds` covers the 600 second provider
ceiling plus bounded I/O.

The worker image pins DuckDB and contains its matching signed Spatial extension
at `/app/duckdb-extensions/spatial.duckdb_extension`. Runtime configuration
sets `GDA_BLUEPRINT_DUCKDB_SPATIAL_EXTENSION_PATH` to that immutable file.
Spatial Blueprints cannot install or auto-load an extension. They must declare
`require_spatial: true` and `spatial_output_srid`, produce
`geometry_wkb`/`srid`/`bbox`, and emit GeoParquet 1.1 plus extension-binary
evidence. Patch this path only for a reviewed, version-matched replacement;
do not enable worker egress merely to download an extension.

Render and inspect without changing a cluster:

```bash
kubectl kustomize k8s/optional/duckdb-blueprint-worker
```

This is a deployment contract, not a staging or production rollout. Promotion
still requires scoped-identity rotation, NetworkPolicy enforcement, real
worker-to-release ACK-loss rehearsal, object-store permission fault injection,
backup/restore and measured capacity/SLO evidence.
