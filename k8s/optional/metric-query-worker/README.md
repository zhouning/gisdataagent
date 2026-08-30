# Metric Query Worker Optional Profile

This Kustomize package deploys one tenant-scoped PostGIS metric-query worker without adding it to
the default platform base. It targets the in-cluster PostgreSQL/PostGIS sandbox and assumes
migrations 137 through 139 have already been applied by the migration authority.

Before applying it, provision `gis-agent-metric-query-postgis-runtime` in namespace `gis-agent`
through the cluster secret authority. It must contain:

- `tenant-id`: the exact platform tenant;
- `database-url`: a PostgreSQL URL whose user matches
  `GDA_METRIC_QUERY_POSTGIS_DATABASE_ROLE`;
- `s3-access-key-id` and `s3-secret-access-key`: a dedicated result-writer identity.

The database role must be a non-superuser, must not belong to `gda_control_gateway`, and should
receive only `USAGE` on the governed serving schema plus `SELECT` on approved metric relations. Do
not commit a Secret manifest, database URL or object-store credential to this directory.

Provision the dedicated `gis-agent-metric-query-results` bucket before rollout with versioning
enabled and Object Lock enabled with a positive default `GOVERNANCE` or `COMPLIANCE` retention.
The result-writer identity needs `GetBucketVersioning` and
`GetBucketObjectLockConfiguration` on that bucket and `GetObject`/`PutObject` only under
`metric-query-results/v1/`; it does not need `DeleteObject`, retention bypass or access to user
uploads. The worker probes these bucket contracts before claiming work, uses conditional object
creation and reads back the exact returned `VersionId`. An existing stable key with different bytes
fails closed.

The application API needs a separate result-reader identity with `GetObject` and
`GetObjectVersion` only under the same prefix. Inject it through the environment's secret authority as
`GDA_METRIC_QUERY_RESULT_ACCESS_KEY_ID` and
`GDA_METRIC_QUERY_RESULT_ACCESS_SECRET_ACCESS_KEY`, or use the platform workload-identity chain.
The application also needs the same `GDA_METRIC_QUERY_RESULT_S3_BUCKET` and
`GDA_METRIC_QUERY_RESULT_S3_PREFIX`. When `AWS_ENDPOINT_URL` is cluster-internal, set
`GDA_METRIC_QUERY_RESULT_ACCESS_ENDPOINT_URL` to the externally reachable S3 endpoint used to sign
the caller's URL. Do not commit reader credentials or a signed URL. A successful access grant is
limited to 60-900 seconds, is bound to the Artifact's exact `VersionId`, and is recorded in the
immutable security ledger before disclosure.

The projected Secret is mounted only into a non-root init container. The init container copies it
to a memory-backed `emptyDir` as UID/GID 10001 with mode 0400. The main container sees only that
owner-scoped copy, runs with a read-only root filesystem and has no Kubernetes API token.

Render and inspect without changing a cluster:

```bash
kubectl kustomize k8s/optional/metric-query-worker
```

Patch the ConfigMap, image tag and NetworkPolicy for each environment before applying. The included
egress policy allows only cluster DNS plus the in-namespace `postgres` and `minio` pods. An external
serving database or object store requires an environment-specific egress patch and security review.

This profile still uses a single replica and `Recreate` updates until concurrency and capacity SLOs
are certified, but result Artifacts are now cluster-accessible `s3://` objects rather than
PVC-backed files. It is a sandbox deployment contract, not staging/production evidence. Production
promotion additionally requires workload identity/secret rotation, environment-specific retention
and lifecycle approval, backup/restore, capacity/SLO evidence and a live failure-recovery rehearsal.
