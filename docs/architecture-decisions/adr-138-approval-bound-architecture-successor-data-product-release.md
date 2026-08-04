# ADR-138: Approval-bound architecture successor DataProduct release

- Status: accepted
- Date: 2026-08-03

## Context

ADR-137 can atomically adopt an approved architecture successor as a complete
`ResourceVersion`, but deliberately stops before product release. The existing
`DataProductRegistry` already owns immutable `DataProductVersion` records,
active pointers, consumer-aware forward promotion and audited rollback. A new
release registry or state machine would split that authority. Calling the
architecture gateway and product registry in separate transactions would also
allow an unapproved or partially validated successor to become a product.

The missing authority boundary is therefore narrow: prove that the current
product output is the predecessor of the adopted output, bind live architecture,
quality and distribution evidence to one release plan, obtain an independent
Human decision, and make the product version plus release binding atomic.

## Options considered

| Option | Benefit | Cost |
|---|---|---|
| Trust the architecture adoption ApprovalCase during product publish | No additional workflow | Adoption does not cover product contract, quality, distribution, consumers or rollback |
| Put release metadata only in the generic distribution manifest | No migration | A caller can omit it, and promotion cannot reliably distinguish governed successors |
| Add a second product/release registry | Strong isolation | Duplicates `DataProductVersion`, pointer and event authority |
| Add a typed plan, independent ApprovalCase and append-only binding to the existing registry | One product authority and fail-closed evidence | Adds one Human decision and a narrow migration |

## Decision

An `ArchitectureSuccessorDataProductReleasePlan` is the complete immutable
release unit. Its canonical SHA-256 covers:

- immutable `DataProduct` metadata;
- the current predecessor and proposed successor `DataProductVersion` contracts;
- the complete ADR-137 successor plan and approved adoption case;
- the quality evidence `Artifact` bound to the successor output;
- every distribution `Artifact`, including identity, content hash and size;
- the immediate predecessor as the deterministic rollback target.

The plan is valid only when the predecessor product output equals the
architecture predecessor and the proposed product output equals the adopted
successor. Quality evidence must have role `evidence`; every distribution
entry must bind exactly one role `output` Artifact; all must reference the
successor `ResourceVersion`.

The release uses action `data_product.publish_architecture_successor` in a new
ApprovalCase. Its target is the `DataProduct` URN, its target fingerprint is the
release plan SHA-256, and its immutable context contains the complete typed plan
plus the identities and hashes needed for database enforcement. The generic
ApprovalCase authority still requires an independent Human terminal decision;
architecture assessment or adoption approval cannot substitute for release
approval.

`DataProductRegistry.publish()` remains the only product write path. When given
an architecture release plan it takes the existing product advisory lock and,
in one PostgreSQL transaction, reloads and compares the product predecessor,
successor `ResourceVersion`, complete architecture registration, adoption and
release cases, lineage, quality evidence and distribution Artifacts. It then
uses the existing publication behavior:

- no active consumers: insert the version and release binding, advance the
  pointer and record `advanced`;
- active consumers: insert the version and release binding, retain the old
  pointer and record `staged` with the ADR-122 impact snapshot.

Migration 116 adds append-only, tenant-scoped
`data_product_architecture_release`. A deferred constraint trigger rejects any
`DataProductVersion` whose output has ADR-137 successor lineage unless the same
transaction also inserts its approved release binding. This protects direct
uses of the old generic `publish()` and direct SQL writes, not only the new
service facade. Foreign keys and the insert guard bind the exact product chain,
resource chain, architecture fingerprint, both ApprovalCases, quality Artifact,
distribution Artifacts and rollback pointer.

Promotion reloads the plan from immutable ApprovalCase context and revalidates
its stored release binding before applying the existing latest consumer-impact
gate. Rollback now shares the product advisory lock and, when the current
version is an architecture successor release, may target only the immediate
rollback pointer approved in that release plan. It still writes the existing
immutable `rolled_back` event.

## Trade-offs

Persisting the complete plan in ApprovalCase context is larger than storing
only references, but it makes the Human decision self-contained and permits
promotion-time reconstruction without another mutable draft authority.
Validation deliberately duplicates selected relationships in Python and SQL:
Python owns canonical model/fingerprint semantics, while SQL owns the
non-bypassable transactional boundary.

The additional release decision increases latency. This is intentional because
architecture adoption does not authorize product quality, distribution or
consumer exposure. Release reuses the existing advisory lock, so operations on
one hot product serialize while unrelated products remain concurrent.

Rollback is now bounded to the approved immediate predecessor but does not yet
require a fresh consumer-impact acknowledgement, incident reference or a fourth
ApprovalCase. This preserves the ADR-122 emergency rollback exception and must
be reconsidered with formal `ConsumerBinding` and incident authority.

## Verification

Contract tests cover plan fingerprints, architecture/product chain mismatch,
wrong quality binding, wrong distribution content, empty distribution and
migration enforcement. The related architecture, approval and product suite
reports `59 passed, 5 skipped` when provider-backed tests are not configured.

The repeatable entry point
`scripts/certify_architecture_successor_data_product_release.py` uses a disposable
`postgis/postgis:16-3.4` database. It proves that an unapproved direct
`publish()` is rolled back by the deferred constraint, a pending release case
cannot publish, and three approved cases produce exactly two product versions,
one release binding and one active successor. It then replays publication
idempotently, rolls back to the approved pointer, and promotes the successor
again through the existing impact gate. The resulting product ledger contains
`published`, `advanced`, `rolled_back` and `promoted` events. The release table
has forced RLS and its trigger is both deferrable and initially deferred.

The secret-free report is
`.tmp/data-product-architecture-successor-release/acceptance-report.json`,
SHA-256 `d6df71d5ec2089b25360ba09b3477b18c2174b50b45797a486d2a4f179426ddc`.

## Consequences and boundary

The first PostGIS architecture successor can now move from observation and
assessment through adoption into an approved, consumer-aware
`DataProductVersion`, with an explicit rollback pointer and without a parallel
registry. Approval, evidence or chain mismatch is fail-closed, and committed
publication is idempotent.

This does not certify the durability or online existence of referenced S3
bytes, formal `ConsumerBinding`, compatibility-driven consumer migration,
notifications, deprecation, retention, DataSLO/incident automation, serving
deployment, or non-PostGIS providers. It also does not make every generic
`DataProductVersion` architecture-ready; migration 116 applies the new gate only
to outputs carrying ADR-137 successor lineage. AR-2, AR-3, AR-4 and the
next-generation Data Platform remain in progress.

## Revisit triggers

- Formal `ConsumerBinding` makes rollback impact materially different from the
  current version-locked distribution grants.
- Incident authority can issue a bounded emergency rollback authorization.
- Multiple trusted writers need database-native canonical plan verification.
- Distribution manifests support non-Artifact endpoints or streaming outputs.
- A non-PostGIS provider passes the same adoption and release conformance suite.
