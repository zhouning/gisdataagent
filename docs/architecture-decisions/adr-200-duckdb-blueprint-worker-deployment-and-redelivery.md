# ADR-200: DuckDB Blueprint Worker Deployment and Redelivery

**Status:** Accepted (deployment contract and disposable acceptance)

**Date:** 2026-08-20

**Related:** ADR-198, ADR-199

## Context

ADR-198 defined a managed DuckDB Blueprint command worker and ADR-199 removed
the API/worker shared-file requirement through immutable S3 I/O. Neither
decision made the process deployable with an isolated workspace, health probes,
scoped object-store identity and explicit network boundary. The remaining
worker-to-release risk was an ACK loss after provider success: an outbox
redelivery must not recompute or replace a successful output.

The Kubernetes base MinIO policy also contained an empty pod selector. Because
NetworkPolicies are additive, that rule allowed every pod in the namespace to
reach MinIO and would have neutralized a stricter optional worker policy.

## Decision

Docker Compose exposes `duckdb-blueprint-worker` only under the explicit
`blueprint` profile. The API and worker share only non-secret S3 bucket/prefix
configuration. The API constructs credential-free object identities; the
dedicated access key and secret are injected only into the worker. The worker
uses private workspace/status volumes, a read-only root filesystem, tmpfs,
all-capability drop, no-new-privileges, bounded database pools and its native
health command. MinIO bootstrap creates the output bucket with Object Lock and
default governance retention and attaches a prefix-scoped policy with no
delete or retention-bypass action.

`k8s/optional/duckdb-blueprint-worker` is an additive Kustomize package, not a
member of `k8s/base`. It runs as UID/GID 999 with `RuntimeDefault` seccomp, a
read-only root filesystem, no service-account token, no privilege escalation,
all capabilities dropped and only private `emptyDir` workspace/status/tmp
mounts. Its Secret contains only tenant and worker S3 credentials. Ingress is
empty and egress is limited to cluster DNS, PostgreSQL and MinIO; corresponding
PostgreSQL and MinIO ingress rules name only this workload. The permissive base
MinIO empty selector is removed.

Both deployments remain one replica with `Recreate`. The 900 second command
lease covers one 600 second execution ceiling, 240 second I/O budget and
control-plane margin. A 660 second Kubernetes termination grace period permits
the current provider ceiling to finish. Horizontal rollout is prohibited until
mid-query lease heartbeat and capacity evidence exist.

ACK-loss recovery uses the existing outbox and Run authority. If worker A
finishes provider execution but loses its ACK, worker B reclaims the expired
command, observes the terminal Run, ACKs the command and does not invoke the
provider. No deployment-local job state or scheduler is added.

## Verification

- Worker, object-store and deployment focused tests pass `27 passed`.
- `kubectl kustomize k8s/optional/duckdb-blueprint-worker` renders offline.
- Development and production Compose models render with the explicit
  `blueprint` profile; the production override sets 2 CPU/4 GiB limits.
- Scoped disposable MinIO certification passes 8/8: readiness probe authority,
  exact input execution, version-bound output, same-byte replay, and denial of
  cross-prefix read/write, delete and retention bypass. Report SHA-256:
  `e59f6d771ea5e717479c1e4592b182dfd795bf1882522fa140cd1e5eb03fb8b5`.
- PostgreSQL + scoped disposable MinIO worker-to-release acceptance passes. It
  deliberately expires the first worker lease after successful provider
  execution; the second claim raises command `attempt_count` to 2, performs one
  terminal reconciliation, preserves the exact S3 output version and passes
  the live DataProductVersion release gate. Report SHA-256:
  `1e5d2eeed390d99351475c1232bd89a2ea4ab527d6ccf4881c58383483d83c7d`.
- Both disposable MinIO runs remove their bucket and container.

## Consequences

The DuckDB Blueprint provider now has executable Compose and Kubernetes
deployment contracts and no longer depends on a shared API data mount. Scoped
IAM and at-least-once redelivery are proven against real MinIO and PostgreSQL,
not only mocks.

This is not staging or production rollout evidence. NetworkPolicy enforcement,
credential rotation, secret-manager/workload-identity integration, backup and
restore, capacity/SLO, mid-query lease extension, multi-replica HA and rolling
upgrade behavior remain promotion gates. Environment-specific external S3 or
PostgreSQL endpoints require reviewed egress patches.

## Revisit Trigger

Introduce lease heartbeat before permitting a Blueprint whose execution and
I/O budget can approach the current lease, or before increasing replicas.
Promote this optional profile only after a real cluster proves NetworkPolicy,
identity rotation, failure recovery and measured provider capacity.
