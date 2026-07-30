# ADR-061: Durable inert Active Metadata activation request

- Status: Accepted for local AR-1 verification
- Date: 2026-07-30
- Owners: Metadata Platform / Data Platform / Security
- Related decisions: ADR-024, ADR-025, ADR-027, ADR-047, ADR-060

## Context

ADR-060 establishes an authoritative `MetadataChangeEvent` when a new
ResourceVersion is registered. The event identifies a changed resource version
and a deterministic projection route, but it is not executable work. It does
not contain a PlatformDefinitionVersion, PlatformRun, execution-plan Artifact,
PolicyDecision, ApprovalRecord, or provider read-back contract.

Turning that event directly into a DolphinScheduler `PlatformCommand` would
silently invent the missing authorization and execution context. Letting the
consumer call OpenMetadata or Gravitino would also combine observation,
authorization, scheduling, and provider mutation in one credential-bearing
process.

## Options considered

| Option | Benefit | Cost / risk | Decision |
|---|---|---|---|
| Convert each event directly to a `PlatformCommand` | Shortest path to a scheduler | Fabricates Definition/Run/policy/approval bindings and bypasses command authorization | Rejected |
| Let the consumer mutate metadata providers | Fewer durable hops | Gives the event consumer provider credentials and collapses policy, execution, and evidence boundaries | Rejected |
| Persist an inert activation request, then authorize it separately | Durable intent, replay safety, explicit authorization boundary | Adds one ledger object and a later promotion step | Accepted |

## Decision

Migration 100 adds the tenant-scoped
`gda_control.metadata_activation_request` ledger. A managed consumer claims an
event, derives a content-bound `MetadataActivationRequest`, and calls
`stage_metadata_activation_request`. The database persists the request and
marks the event processed in the same PostgreSQL transaction. Exact replay
returns the existing request; conflicting content or an expired/wrong worker
claim fails closed.

Every new request has immutable status `awaiting_authorization` and fixes these
claims to `false`:

- `provider_apply_authorized`
- `provider_mutations_executed`
- `production_scheduler_submission_verified`
- `production_ingestion_verified`
- `production_ready`

The previous `complete_metadata_change` path may not process an event unless an
exact durable request already exists. The managed consumer owns only its
tenant-scoped PostgreSQL credential. It has no provider or scheduler secret,
no Kubernetes API token, and no provider mutation or command-submission client.
The base Deployment remains at zero replicas until an environment explicitly
supplies its database identity and scales it.

A later authorization component must bind the request to a real Definition,
Run, execution plan, PolicyDecision, and Approval before the existing
DolphinScheduler command boundary can be used. That promotion is outside this
decision.

## Rationale

The request ledger preserves the fact that an event was routed without
pretending that routing authorized an action. Atomic stage-and-complete avoids
both processed events with no durable request and requests detached from event
delivery. Separating scheduler/provider credentials limits the consumer's
blast radius and keeps production claims evidence-driven.

## Trade-offs

- Provider ingestion is not immediate; an authorization/promotion controller
  is still required.
- `awaiting_authorization` requests can accumulate, so production needs queue
  age, retry/dead-letter, alert, and SLO ownership before scaling the worker.
- Database durability does not prove protected workload identity, scheduler
  submission, provider mutation, or production ingestion.

## Local verification

Checked PostgreSQL evidence contains two processed events and exactly two
inert activation requests. It proves the no-request completion guard, exact
request replay, managed consumer staging, tenant isolation, forced RLS,
gateway direct UPDATE/DELETE denial, and zero `platform_command_outbox` rows.
The static deployment contract proves zero base replicas, no provider or
scheduler secret, disabled Kubernetes token mounting, and admission of the
consumer selector to PostgreSQL ingress.

- Contract fingerprint:
  `2256daa97c1f3a2e71f4d7026592171daea802b371f5616fbbd72a63939ee6b5`
- Evidence fingerprint:
  `029aaf7de476115dcf6385ca4a0e05bb84492ebea8ddecf6c3edf36edd76dbef`

`deployment_applied`, `production_workload_identity_verified`,
`production_scheduler_submission_verified`, `production_ingestion_verified`,
and `production_ready` remain `false`.

## Revisit triggers

Revisit this decision only if an event schema itself becomes an authorized,
content-bound command carrying the complete Definition/Run/execution-plan/
PolicyDecision/Approval chain, or if a different durable authorization service
can prove equivalent atomicity, tenant isolation, idempotency, and credential
separation.
