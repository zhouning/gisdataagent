# ADR-136: PostGIS schema evidence and lineage impact precede version adoption

- Status: accepted
- Date: 2026-08-03

## Context

ADR-135 admitted provider architecture drift into the unified ApprovalCase
authority, but an observation hash cannot explain whether a schema change is
compatible or which downstream versions may be affected. Treating two unequal
hashes as a field diff would require guessing. Creating a successor
`ResourceVersion` from that guess would bypass both consumer impact and the
immutable content/data-contract prerequisites.

ADR-134 deliberately kept detailed provider schemas out of the control ledger
and named a separate governed evidence artifact as the revisit path when
field-level diagnosis became necessary. This slice now needs that evidence, but
must not create another metadata registry or duplicate lineage and approval
authorities already present in the platform.

## Options considered

| Option | Benefit | Cost |
|---|---|---|
| Ask an LLM to infer compatibility from old and new hashes | Minimal implementation | Hashes contain no reversible field evidence; verdict is unverifiable |
| Copy provider catalog rows into ApprovalCase context | Easy reviewer access | Leaks unbounded expressions and turns approval JSON into a schema store |
| Add a local schema registry and impact graph | Domain-specific queries | Duplicates planned OpenMetadata/Gravitino and existing LineageEvent authority |
| Store normalized snapshots as external Artifact evidence and reuse lineage impact | Deterministic, bounded and uses existing authorities | Artifact availability and successor creation remain separate responsibilities |

## Decision

No new database migration or local metadata registry is added. The implementation
reuses the existing immutable `Artifact`, `LineageEvent`/lineage-impact and
ApprovalCase authorities.

The PostGIS harvester now returns a typed `PostgisSchemaSnapshot` in addition to
the observation and architecture candidates. It contains relation kind and
ordered column names, PostgreSQL types, nullability, identity and generated
flags. Default expressions, constraint definitions and index definitions are
represented only by SHA-256, never by their source text. It contains no row
values, credentials, endpoint authority or connection string.

The serialized snapshot is stored outside the control ledger. Its Artifact row
contains a stable storage URI, content SHA-256, size and a four-field manifest:
snapshot schema, observation ID, observation SHA-256 and snapshot SHA-256. The
compatibility service reloads the registered Artifact facts and recomputes both
snapshot bindings before producing a verdict.

Compatibility uses explicit conservative rules:

- adding a nullable column, or a required column populated by a default,
  identity or generated expression, is backward-compatible;
- removing a column, changing its PostgreSQL type or tightening nullability is
  breaking;
- relaxing nullability and adding a default are backward-compatible;
- changing identity/generated semantics, removing or changing a default, and
  adding/removing/changing a constraint are indeterminate;
- index-only changes are schema-compatible for this assessment; performance
  and SLO impact remain a separate gate;
- any breaking change dominates the overall verdict, followed by indeterminate,
  then backward-compatible.

The assessment fingerprint binds tenant, `ResourceVersion`, both observations,
both Artifact identities and content hashes, both snapshot hashes, every
normalized change and the overall verdict. The service additionally verifies
that the baseline snapshot is the schema named by the accepted architecture
binding and that the candidate Artifact belongs to the latest fresh drift
observation.

Downstream impact is not reimplemented. The service calls the existing bounded
`assess_lineage_impact(..., change_type="schema")` projection. Incomplete
lineage traversal fails closed. The resulting assessment SHA-256, disposition,
edge count and impacted version/product counts are combined with compatibility
evidence in an `AssessedArchitectureChangeReview`.

The resulting ApprovalCase uses action
`data_architecture.assessed_change_review`. Its target fingerprint covers the
raw drift review, compatibility assessment and lineage impact. Approval context
contains only identifiers, hashes, verdicts and counts, not schema fields. It
always retains two blockers:

- `new_content_snapshot_required`;
- `successor_data_contract_required`.

Therefore an independent human may approve the assessment conclusion, but that
verdict cannot authorize or manufacture a successor `ResourceVersion`.

## Verification

A disposable `postgis/postgis:16-3.4` acceptance used PostgreSQL 16.4 and
PostGIS 3.4.3. One real table and one real downstream `LineageEvent` were used.
Adding a nullable column produced `backward_compatible`; subsequently removing
an existing column produced `breaking`. Each assessment created a distinct
deterministic ApprovalCase bound to the same lineage-impact evidence.

The final database held three provider observations and three distinct external
schema-evidence Artifacts. It held two assessed cases (`approved: 1`,
`pending: 1`) and three approval events. Both cases retained both successor
blockers and no schema detail appeared in request context. Artifact,
observation, lineage and approval tables had forced tenant RLS. The original
dataset still had exactly one `ResourceVersion`; schema, contract, location and
binding remained exactly one row each. The temporary container was removed.

The repeatable entry point is
`scripts/certify_architecture_change_assessment.py`. Its secret-free report is
`.tmp/data-architecture-change-assessment/acceptance-report.json`, SHA-256
`0da96bc2f77ee1c0e4e8d9f5749fdd77c853a1f5ef13f8fd3d102088e809cfc1`.

## Consequences and boundary

PostGIS schema drift now has reproducible compatibility and bounded downstream
impact evidence before human review. The control ledger remains a reference and
decision ledger rather than a provider-schema copy, and deterministic behavior
does not depend on an LLM.

This does not create a successor content snapshot, successor data-contract
version, successor architecture binding, promotion, rollback pointer or
notification workflow. It does not prove external Artifact durability beyond
the Artifact authority contract. Lineage impact covers the GDA control-ledger
projection; missing OpenMetadata/provider lineage cannot be inferred. The
compatibility rules intentionally do not recognize PostgreSQL widening casts or
application-specific consumer tolerance. Location-only drift and tombstones use
the earlier review path. Gravitino, Iceberg, STAC, object storage and DuckDB are
not validated, and AR-1 or the next-generation Data Platform is not complete.

## Revisit triggers

Add type-widening rules only with versioned PostgreSQL cast and consumer
conformance tests. Revisit index-only compatibility when performance/SLO impact
is bound to the same review. Require online Artifact existence and retention
proof when the production Artifact store is certified. Extend the assessed
workflow to another provider only after it supplies a native normalized schema
snapshot and a real compatibility test. The next adoption decision may remove
the two blockers only after a new immutable content snapshot and successor data
contract are both present and the latest observation/binding preconditions are
rechecked atomically.
