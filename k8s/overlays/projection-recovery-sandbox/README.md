# Projection Recovery Sandbox Overlay

This overlay is the explicit opt-in switch for the optional projection recovery
worker. It composes `k8s/optional/projection-recovery-worker` and patches only its
replica count to `1`; the optional profile itself remains at `replicas: 0`.

The environment must already have the normal `gis-agent` base services running,
including `postgres`, `minio` and `gis-agent-secret`. Before applying this overlay,
provision these two Secret objects through the environment's secret workflow:

- `gis-agent-projection-recovery-runtime`, key `tenant-id`;
- `gis-agent-projection-recovery-admission`, key `admissions.json`.

The overlay intentionally contains no Secret, provider credential, row bundle or
external egress patch. PostGIS/pgvector rebuilds still require the plan-bound row
bundle volume described by the optional profile. Missing evidence causes the worker
to fail closed.

Render or apply:

```bash
kubectl kustomize k8s/overlays/projection-recovery-sandbox
kubectl apply -k k8s/overlays/projection-recovery-sandbox
```

This is a sandbox enablement contract. It does not establish production OIDC,
Secret Manager rotation, controller HA, provider replication/PITR or RPO/RTO.
