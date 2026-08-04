# ADR-135: Architecture drift enters unified approval before version change

- Status: accepted
- Date: 2026-08-03

## Context

ADR-133 made the schema, data contract, physical location and their binding
immutable for one `ResourceVersion`. ADR-134 made PostGIS structural changes,
physical replacement and tombstones observable without adopting them. A drift
status and a suggested action are still not a governed human decision, however.

The next slice needs to admit reviewable drift into the existing ApprovalCase
authority. It must not create another approval store, treat an observation hash
as the whole review scope, copy provider schema documents into approval JSON or
allow an approval verdict to mutate the accepted architecture binding.

## Options considered

| Option | Benefit | Cost |
|---|---|---|
| Automatically replace the current binding after drift | Fast convergence | Makes provider DDL authoritative and destroys immutable version semantics |
| Add an architecture-specific approval table | Domain-specific columns and queries | Duplicates tenant isolation, lifecycle, event and human-verdict authority |
| Point a generic ApprovalCase only at the observation hash | Minimal new code | Does not bind the accepted architecture, target dataset, candidates or required actions |
| Build a typed review envelope and persist it through ApprovalCase | Reuses verified authority while retaining domain-specific validation | A later version-creation flow must consume and revalidate the verdict |

## Decision

Architecture change review reuses the migration-103 ApprovalCase authority. No
new database migration is introduced in this slice.

Only `schema_drift`, `location_drift`, `schema_and_location_drift` and
`tombstoned` are reviewable. `unobserved`, `unbound`, `in_sync` and `stale` fail
closed before an ApprovalCase is created. A reviewable change must already have
a complete accepted architecture binding and an immutable provider observation.
Present-object drift must also be fresh when evaluated.

The typed `ArchitectureChangeReview` fingerprint binds:

- tenant and original dataset ResourceURN;
- `ResourceVersion` and provider observation identities;
- observation and accepted architecture-binding SHA-256 values;
- reconciliation status;
- candidate schema and physical-location SHA-256 values;
- the exact required actions for that status.

The ApprovalCase uses action `data_architecture.change_review`. Its deterministic
ResourceURN is derived from the immutable observation UUID, so retrying the same
request is idempotent and submitting a different immutable request under the
same observation conflicts. `target_resource_urn` is the original dataset, and
`target_fingerprint` is the full review fingerprint rather than only the
observation hash.

`request_context` contains exactly eight bounded values: ResourceVersion ID,
observation ID and hash, binding hash, reconciliation status, candidate schema
and location hashes, and required actions. It contains no full schema, provider
catalog rows, endpoint, credential or connection string.

Human, workload or agent identities may request review. An approved or rejected
verdict still requires an independent human identity through ApprovalCase's
single terminal compare-and-set transition. Approval alone cannot update the
current architecture binding. Adoption requires a separate, later flow that
creates a new `ResourceVersion` and new architecture binding after compatibility
and impact gates pass.

## Verification

A disposable `postgis/postgis:16-3.4` acceptance used PostgreSQL 16.4 and
PostGIS 3.4.3. One real table produced schema drift, physical-location drift and
a tombstone. Each change created a distinct deterministic ApprovalCase against
the same dataset. Replaying the same schema-drift request was idempotent; a
different payload conflicted. Workload and agent approval attempts failed, an
independent human approval succeeded, and a cross-tenant read failed.

The final ledger held three cases (`approved: 1`, `pending: 2`) and four events.
All cases used the fixed action and the eight-field context. Approval tables had
forced RLS, immutable update/delete guards and gateway `SELECT/INSERT` without
direct mutation privileges. The accepted schema, contract, location and binding
remained exactly one row each after approval. The temporary container was
removed.

The repeatable entry point is
`scripts/certify_architecture_change_approval.py`. Its secret-free report is
`.tmp/data-architecture-change-approval/acceptance-report.json`, SHA-256
`d86068481ae71ae58c00e12d3e0287de9485f38e39364ae09835e3c0ef6a4a94`.

## Consequences and boundary

Provider drift now reaches one tenant-scoped, immutable and human-governed
decision authority without changing accepted architecture truth. Reviewers can
identify exactly which provider observation and accepted binding were compared,
while the control ledger remains a reference ledger rather than a schema copy.

This does not classify field-level compatibility, store a field diff, calculate
lineage or consumer impact, create or promote a successor `ResourceVersion`, or
schedule notifications and escalations. An ApprovalCase can become stale when a
newer provider observation arrives; the future adoption flow must recheck latest
observation, compatibility, impact and current binding before creating a new
version. This slice does not validate Gravitino, Iceberg, STAC, object storage or
DuckDB and does not complete AR-1 or the next-generation Data Platform.

## Revisit triggers

Add a governed diagnostic artifact when reviewers require field-level diffs or
compatibility evidence. Add database-enforced consumption binding when the
successor-version workflow is implemented. Extend beyond dataset ResourceURNs
only after another resource kind has a native observation and adoption test.
Revisit the single-verdict ApprovalCase model if policy requires quorum,
separation across multiple roles or time-bounded reapproval.
