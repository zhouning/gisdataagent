# ADR-137: Two-stage approval and atomic architecture successor adoption

- Status: accepted
- Date: 2026-08-03

## Context

ADR-136 deliberately left `new_content_snapshot_required` and
`successor_data_contract_required` on an assessed architecture-change case.
Approving compatibility and downstream impact is not authority to create a new
data version. Adoption must bind the actual content snapshot, contract, schema,
location and successor identity, then recheck that the reviewed provider fact
is still current before any authority row is written.

The existing ledger already owns immutable `ResourceVersion`, `SchemaVersion`,
`DataContractVersion`, `PhysicalLocation`, architecture binding,
`LineageEvent` and `ApprovalCase` objects. Adding a successor registry or a
second version state machine would split authority. A sequence of public
gateway calls would also expose partial successors when a later write failed.

## Options considered

| Option | Benefit | Cost |
|---|---|---|
| Let the approved assessed case create a successor | One decision and little code | The approved fingerprint does not contain the new content or contract |
| Store a mutable successor draft registry | Easy incremental editing | Duplicates version authority and creates another lifecycle to reconcile |
| Use one application transaction without serializing observations | Atomic writes | A newer observation can arrive between latest-check and commit |
| Bind a typed plan to a second ApprovalCase and one serialized gateway transaction | Explicit authority, atomic and reuses existing ledgers | Adds a second human decision and one narrow database lock migration |

## Decision

Adoption uses an immutable `ArchitectureSuccessorPlan`. Its SHA-256 covers the
approved assessed-case identity and fingerprint, predecessor and binding,
provider observation, candidate schema Artifact, complete successor
`ResourceVersion`, and the complete schema/contract/location/binding
registration. A predecessor-to-successor `derive` LineageEvent is
deterministically derived from that plan hash, so it cannot be replaced after
approval.

The plan clears both ADR-136 blockers only when all of these checks pass:

- the assessed case is independently Human-approved and still binds the same
  predecessor, observation, binding, candidate Artifact and two blockers;
- successor content SHA-256 differs from the predecessor, matches the physical
  snapshot checksum, and the snapshot reference is new;
- `authority_version_ref` binds the snapshot, revision, content hash,
  observation and candidate Artifact identities;
- the successor contract has a new contract identity and external authority
  version;
- successor schema and location, when re-keyed to the predecessor identity,
  reproduce the exact hashes in the assessed provider observation;
- the external schema Artifact has the expected evidence media type and exact
  four-field observation manifest.

The second ApprovalCase uses action
`data_architecture.create_successor_version`. Its target fingerprint is the
complete plan SHA-256 and its context contains only identities, hashes and
cleared blockers. An independent Human must approve this case; the earlier
assessment decision cannot substitute for it.

`PlatformGateway.adopt_architecture_successor()` is the only adoption write
path. One PostgreSQL transaction reloads both terminal cases and the original
immutable evidence, rejects another child of the same predecessor, checks the
latest observation and freshness, then inserts:

1. successor `ResourceVersion`;
2. successor `SchemaVersion`;
3. successor `DataContractVersion`;
4. successor `PhysicalLocation`;
5. complete successor architecture binding;
6. predecessor-to-successor `LineageEvent`.

All inserts use the existing compare-after-`ON CONFLICT DO NOTHING` semantics.
A conflicting identity rolls back the complete transaction. A fully committed
plan is an idempotent retry and returns `created=false`, even if a later
observation has since arrived. A partial plan must still pass current latest
and freshness checks before it can be completed.

Migration 115 adds one transaction-scoped advisory lock keyed by tenant and
predecessor `ResourceVersion`. `BEFORE INSERT` triggers make every provider
observation and every `ResourceVersion` with a predecessor take the same lock
as adoption, including direct inserts by the least-privilege gateway role.
This closes both the latest-observation race and concurrent-successor race
without granting `UPDATE` or `FOR SHARE` privileges. Approved ApprovalCases do
not need row locks because the existing transition trigger makes terminal state
immutable.

## Trade-offs

The second Human decision adds workflow latency, but it separates evidence
acceptance from a concrete write authorization. Advisory locks serialize only
one tenant/version key and can reduce concurrency for a hot provider object;
they do not lock unrelated resources. Successor branches are rejected by the
adoption script and migration trigger whenever either child carries the
architecture-adoption evidence keys. Generic predecessor chains that do not use
this adoption contract retain their existing branch semantics.

Plan validation is implemented in typed Python and rechecked inside the gateway
transaction. The database continues to enforce foreign keys, uniqueness,
immutability and RLS; it does not duplicate canonical JSON fingerprint logic in
PL/pgSQL.

## Verification

A disposable `postgis/postgis:16-3.4` acceptance used PostgreSQL 16.4 and
PostGIS 3.4.3. A real table was harvested before and after an additive schema
change and a new content snapshot. The pending adoption case produced no new
version. Two separate Human decisions then authorized the assessment and
adoption.

The committed ledger contained one root and one successor with two distinct
content hashes and version keys. Schema, contract, location and binding counts
were all two. Exactly one plan-bound successor LineageEvent existed. Repeating
the transaction returned `created=false`; repeating again after a newer
provider observation also returned `created=false`. A subsequent unreviewed
child of the adopted predecessor was rejected. All eight relevant tables had
forced tenant RLS and both observation/successor adoption lock triggers existed.

The repeatable entry point is
`scripts/certify_architecture_successor_adoption.py`. Its secret-free report is
`.tmp/data-architecture-successor-adoption/acceptance-report.json`, SHA-256
`6fe6a8dfd2ff2c129287f2129ece6c42eb7b6903ace7fd94aa549ac9e5958819`.

## Consequences and boundary

The PostGIS schema-change path can now move from observed drift through
compatibility/impact review to an atomic, auditable successor architecture
version without creating a parallel registry. Failed or stale adoption is
fail-closed, and an unknown-commit retry is deterministic.

This does not prove that referenced content bytes or schema Artifact remain
durable in a production object store. It does not promote a DataProductVersion,
activate a serving revision, notify consumers, or create rollback and retention
policy. Location-only drift and tombstones are not adopted by this path.
Gravitino, Iceberg, STAC, object storage, DuckDB and cloud-managed providers
still require native successor conformance. AR-2 and the next-generation Data
Platform remain in progress.

## Revisit triggers

Move fingerprint enforcement into a database procedure only if another trusted
writer must adopt successors without the gateway implementation. Add explicit
branch policy if a product needs parallel successor histories. Bind online
Artifact existence, retention and content verification when the production
Artifact store is certified. Add promotion and rollback authority only after
the DataProduct release state machine is available.
