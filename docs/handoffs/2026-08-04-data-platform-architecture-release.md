# GIS Data Agent Data Platform continuation handoff

## Resume point

- Branch: `feat/data-platform-architecture-release-20260804`
- Repository: `zhouning/gisdataagent`
- Read ADR-138 and this handoff before changing code.
- Do not reset or clean the worktree. It contains many unrelated local research,
  frontend, benchmark and roadmap changes that are intentionally outside this
  branch checkpoint.

## Completed authority chain

The committed slice connects the following existing authorities without adding
a parallel registry:

1. provider architecture observation and reconciliation;
2. compatibility and lineage-impact assessment;
3. assessed architecture `ApprovalCase`;
4. independently approved atomic successor `ResourceVersion` adoption;
5. independently approved `DataProductVersion` release;
6. ADR-122 consumer-aware staging/promotion;
7. deterministic immediate-predecessor rollback and audited re-promotion.

Migration 116 adds an append-only, forced-RLS
`data_product_architecture_release` binding. A deferred constraint prevents the
generic `publish()` path or direct SQL from committing a product version that
points at an adopted architecture successor without its approved release
binding.

## Verification baseline

- An index-only checkout of the staged tree passes its complete changed test
  suite: `129 passed, 7 skipped`.
- Critical Ruff rules and Python compilation pass for every changed Python
  module and script.
- Disposable PostgreSQL 16.4 / PostGIS 3.4.3 release certification passes.
- Existing ADR-122 consumer-impact certification passes after migration 116.
- Repeatable entry point:
  `uv run python scripts/certify_architecture_successor_data_product_release.py`
- Local generated report (ignored by Git):
  `.tmp/data-product-architecture-successor-release/acceptance-report.json`
- Report SHA-256 at this checkpoint:
  `d649f3e23abc42cf05d7f963310283c3e49f5418c89f6d77f292a40ccfcf1b7f`
- Certification containers were removed after each run.

## Honest boundary

This is a verified platform slice, not completion of the next-generation Data
Platform. It does not yet certify production object-store bytes, formal
`ConsumerBinding`, consumer notification and migration windows, compatibility
policy enforcement, DataSLO/DataIncident automation, serving revisions,
retention, or non-PostGIS provider conformance.

The generated acceptance report is intentionally not committed because `.tmp/`
is ignored. Regenerate it with the certification entry point when evidence is
needed.

The local source-connector/schema-drift Python slice and the fail-closed
migration-runner rewrite remain uncommitted because each has a wider dependency
closure than this release. Migration 102 remains in this branch as the SQL
dependency required by unified ApprovalCase migration 103. Do not delete or
reset those local files when resuming.

## Next implementation slice

Implement formal `ConsumerBinding + DataSLO/DataIncident` authority around the
existing product release state machine:

1. Replace transitional version-locked distribution grants as the only
   consumer evidence with immutable product/version-range bindings.
2. Bind compatibility verdict, notification status, migration deadline and
   consumer acknowledgement into promotion impact.
3. Require rollback of an architecture successor to reference either an
   approved incident or an explicit Human rollback ApprovalCase.
4. Recompute consumer impact inside the same product advisory-lock transaction;
   stale acknowledgement must remain fail-closed.
5. Preserve the release plan's immediate rollback target and append-only event
   history; do not add another product registry or scheduler.
6. Add a disposable PostgreSQL/PostGIS certification covering active consumers,
   deadline changes, stale acknowledgement, incident rollback, idempotent retry,
   RLS and direct-SQL bypass attempts.

Revisit the emergency rollback exception documented by ADR-122 and ADR-138 when
this slice is implemented. Keep AR-2, AR-3 and AR-4 marked in progress until the
broader production gates pass.

## Suggested first commands

```bash
git branch --show-current
git log -1 --oneline
git status --short
sed -n '1,260p' docs/handoffs/2026-08-04-data-platform-architecture-release.md
sed -n '1,320p' docs/architecture-decisions/adr-138-approval-bound-architecture-successor-data-product-release.md
```

For GitHub access on this machine, the user has authorized the local proxy at
`127.0.0.1:7897`.
