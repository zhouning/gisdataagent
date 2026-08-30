# ADR-355: Versioned MinIO content for specialist worker recovery

## Status

Accepted and verified for the bounded PostgreSQL + MinIO rehearsal.
Production object-lock, replication, HA/DR and production readiness are not claimed.

## Context

ADR-354 proved that a replacement worker can recover a provider commit from durable
PostgreSQL receipt and Artifact authorities, but its content plane was a disposable
filesystem. A multi-replica worker deployment needs the same output bytes to be
available outside either worker process, and it must not silently read a later object
version after a replay or overwrite.

## Decision

For a shared object-storage content plane:

1. PostgreSQL remains authoritative for tenant, Artifact identity, checksum, manifest
   and the provider receipt state machine.
2. The content backend uses an S3/MinIO-compatible bucket with versioning enabled.
   Every input and output Artifact manifest binds the exact `VersionId`; reads require
   that binding and do not fall back to the bucket's latest object.
3. Worker replacement creates a fresh Artifact-store instance, observes the terminal
   PostgreSQL receipt, and reads the exact output VersionId. It does not call the
   provider, append a receipt transition, or issue another object PUT.
4. The rehearsal creates a unique temporary bucket and removes all object versions and
   the bucket before reporting success. Object Lock and cross-region replication are
   separate production gates.

## Verification

`scripts/rehearse_agentops_specialist_worker_recovery.py` now accepts an S3 endpoint.
With the local MinIO service, it creates a versioned temporary bucket and runs two
independent worker processes against the same PostgreSQL database and bucket. Worker A
executes the real GWM provider, persists the output and terminal receipt, returns an
`unknown` activity result, and is killed with `SIGKILL`. Worker B recovers the request
from fresh authority/store instances.

The 2026-08-30 MinIO report passed all six checks:

- worker A died after the provider commit and returned `unknown`;
- worker B recovered the same terminal receipt and output Artifact;
- receipt history stayed at two rows and the output object stayed at one version;
- input and output Artifacts bound their exact MinIO VersionIds;
- retry budget stayed at one attempt and one admission;
- all temporary object versions and the bucket were removed.

Report: `docs/reports/agentops_specialist_worker_recovery_minio_2026-08-30.json`.
Its `report_sha256` is
`cad97bd8b319e1ad1f6fb1df918ce067cd9f54078d1a603798f57b0f08f90ecd` and file
SHA-256 is `90a2ff83f43f621486dc7c97d230d32e3efd6c168a8188e76a2ff5cd26e5a145`.

The focused S3 Artifact-store regression proves that a replacement instance keeps
reading the original VersionId even after a later object version is written, and that
same-identity output replay performs no second PUT. Specialist provider tests passed
`13` tests; Ruff and compileall passed.

## Consequences and limits

This closes the bounded shared MinIO content-plane recovery slice for the GWM
specialist. It does not certify Object Lock retention enforcement, bucket replication,
cross-region recovery, production credentials/identity rotation, Kubernetes worker
HA/fencing, Temporal server HA, backup/RPO/RTO or production rollout. The AR-5 exit
status remains `in_progress`.
