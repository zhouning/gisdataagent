# ADR-062: Atomic Active Metadata authorization and dispatch

- Status: Accepted for local AR-1 verification
- Date: 2026-07-30
- Owners: Metadata Platform / Data Platform / Security
- Related decisions: ADR-024, ADR-025, ADR-027, ADR-047, ADR-060, ADR-061

## Context

ADR-061 deliberately stops an Active Metadata change at an immutable
`awaiting_authorization` request. That request binds the changed
ResourceVersion but is not a DefinitionVersion, Run, execution plan,
PolicyDecision, Approval, or scheduler command.

The next boundary must prevent two unsafe partial states: a dispatch command
without complete authorization, and an authorization row committed without
its dispatch command. It must also distinguish realistic acceptance input from
authority. Local Chongqing files can prove content identity, spatial metadata,
and conformance, but their presence cannot authorize execution or establish
production provenance.

## Options considered

| Option | Benefit | Cost / risk | Decision |
|---|---|---|---|
| Reuse ordinary `submit_run(request_dispatch=true)` | No new ledger | The activation request is not bound and can be bypassed | Rejected |
| Write authorization, then enqueue in a later transaction | Simple components | Leaves orphan authorization and retry ambiguity | Rejected |
| Append authorization and dispatch in one transaction with a database guard | Exact replay, fail-closed evidence chain, no partial commit | Adds migration, deferred FK, trigger, and dedicated gateway API | Accepted |

## Decision

Migration 101 adds tenant-scoped, append-only
`gda_control.metadata_activation_authorization`. Its security-definer function
accepts only a content-bound `MetadataActivationAuthorization` and validates
the exact durable request, ResourceVersion/content hash, DataOps
DefinitionVersion with capability `metadata_fabric.projection_plan`, accepted
workload Run and input binding, execution-plan Artifact, allow PolicyDecision,
and approved independent ApprovalRecord. The authorizer is a fourth independent
workload identity and must differ from executor, evaluator, and approver.

The gateway role has SELECT but no direct INSERT/UPDATE/DELETE on this ledger.
The authorization row has a deferred foreign key to its command. The dedicated
gateway transaction appends the authorization first, then inserts one pending
DolphinScheduler dispatch. A command trigger rejects activation dispatch when
the exact authorization is absent or its request/policy/plan/payload binding
differs. Calling the authorization function without inserting the command
therefore fails at commit and rolls back the authorization.

Ordinary `submit_run(request_dispatch=true)` explicitly rejects the metadata
projection capability. Other DataOps capabilities retain the existing generic
command path. Exact replay returns the existing authorization and command;
conflicting identity or content fails closed.

Creation of a pending command proves local durable enqueue only. It does not
prove DolphinScheduler submission, provider apply authorization, provider
mutation, production ingestion, or production readiness. All those claims
remain `false`.

## Real data boundary

The local golden slice is the Chongqing central-city historical cultural
district Shapefile bundle. Every same-stem component, including spatial index
and XML sidecars, is hashed. Checked evidence retains only component suffixes,
sizes, SHA-256 values, format, feature/field counts, geometry type, CRS, bounds,
and the canonical bundle fingerprint. It contains no absolute source path and
does not commit source data.

The bundle fingerprint becomes the source ResourceVersion `content_sha256`.
This makes real data useful as acceptance input and immutable content evidence,
while policy and approval remain the only authorization evidence. CI validates
the checked inventory and evidence fingerprints without requiring the local
dataset. DEM and TAP remain candidates for later raster and scale/time-series
conformance; TAP is not policy-outcome authority.

## Consequences and trade-offs

- A dedicated authorizer identity and approval are mandatory, increasing
  operational setup but preserving separation of duties.
- The Run and all evidence Artifacts must exist before promotion; malformed or
  expired evidence cannot be partially accepted.
- Deferred constraints make authorization and enqueue atomic, but actual
  scheduler delivery remains the existing leased outbox worker's responsibility.
- One request maps to one authorization, Run, and dispatch command. A future
  re-plan requires a new immutable activation request rather than rewriting the
  ledger.
- Local files improve realism but do not establish license, vintage,
  authoritative custody, protected provenance, or production availability.

## Local verification

The checked PostgreSQL rehearsal proves ordinary dispatch rejection, rollback
of authorization without a command, exact authorization/command replay, forced
RLS, function-only INSERT, direct UPDATE/DELETE denial, one authorization and
one pending dispatch. The real bundle contains 20 `PolygonZ` features and 33
fields in EPSG:4490, with the recorded Chongqing central-city bounds.

- Dataset bundle fingerprint:
  `fd474fd65c8e4a71da241eb3fd07748ca3b972fbd2d3c32833376dbe71104007`
- Contract fingerprint:
  `cef78f91058a8529f4e86330790e714b52b73725a45ffe4dc9eded35bc8ccfa4`
- Evidence fingerprint:
  `6ae387240e3bcebaafe2ad7acc73f4e09d53df2e73b2ec63cd92edbc262d831e`

`deployment_applied`, `production_workload_identity_verified`,
`provider_apply_authorized`, `provider_mutations_executed`,
`production_scheduler_submission_verified`, `production_ingestion_verified`,
and `production_ready` remain `false`.

## Revisit triggers

Revisit when a protected production authorization service can provide an
equivalent atomic append/enqueue proof, when one request legitimately needs
multiple independently governed Runs, when policy obligations gain an
executable and audited implementation, or when a real scheduler submission and
provider read-back slice is ready to replace the local pending-command proof.
