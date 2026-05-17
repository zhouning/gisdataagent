# Standards Platform — Wave 4: Review Sub-Tab

**Date:** 2026-05-17
**Branch:** `feat/v12-extensible-platform`
**Status:** design — ready for implementation plan
**Parent spec:** `docs/superpowers/specs/2026-05-13-data-standard-lifecycle-platform-design.md`
**Predecessors:** Wave 1 (`2026-05-15-std-platform-drafting-wave1-design.md`), Wave 2 (`2026-05-15-std-platform-drafting-wave2-design.md`), Wave 3 (`2026-05-16-std-platform-wave3-v1-fixes-design.md`)
**Scope:** Two-tier review workflow — reference-level audit + document-level single-reviewer round — landing the parent spec's §4.2.6 「审定」 stage as a new sub-tab.

## 0. Why this spec

Wave 3 prepared the soil: `std_reference` now carries `verification_status`, `verified_by`, `verified_at` with a `pending` default, leaving room for an audit step. The parent spec §4.2.6 sketched `std_review_round` / `std_review_comment` tables but never landed them; the `review/` directory in `standards_platform/` is still empty.

This spec lands the review stage end-to-end as a new ReviewSubTab so a standards version can move `drafting → reviewing → approved`. It is the precursor to publishing (Wave 5).

## 1. Scope

**In scope**

- New role `standard_reviewer` (4th role alongside viewer/analyst/admin)
- Two new tables: `std_review_round`, `std_review_comment`
- Three-tier state machine:
  - `std_document_version.status`: `drafting → reviewing → approved | drafting`
  - `std_review_round.status`: `open → closed` with `outcome ∈ {approved, rejected}`
  - `std_reference.verification_status`: `pending → approved | rejected` (Wave 3 column, now actively driven)
- 7 new REST endpoints under `/api/std/reviews/*`
- Server-side gating on `POST /api/std/reviews/rounds/{id}/close` enforcing "all references approved + all comments resolved" when outcome is `approved`
- Server-side block on drafting endpoints when `document_version.status='reviewing'`
- New ReviewSubTab (4-column layout) + 5 sub-components
- `standardsApi.ts` SDK additions
- RBAC: reviewer is RW on review endpoints (only their own round) + R on other sub-tabs; admin retains full power
- ~28 new tests across schema, handler, and drafting-gate surfaces

**Out of scope**

- Publishing (snapshot, exporter, supersede) — Wave 5
- Multi-round / serial reviewers (business expert → tech expert → committee)
- Comment @mentions, email/webhook notifications, attachments
- "Approve all" batch reference audit — audit is intentionally per-reference
- Reviewer delegation / handoff
- In-editor comment markers visible to the drafter — UX polish for a later wave
- Reopening a closed round — admin must start a new round to re-review
- Multi-tenant isolation
- The 5 deferred Wave-3 Minor items — separate cleanup ticket
- Migrating existing `verified_by/verified_at` data (no rows exist with content yet)

## 2. Architecture

### 2.1 State machine

```
std_document_version.status:
    ingested → drafting → reviewing → approved → released → ...
                              ▲           │
                              │           └─→ when round closes with outcome='approved'
                              │
                              └─ entered when admin starts a review_round

std_review_round.status:
    open → closed (with outcome ∈ {approved, rejected})
       │       ▲
       │       └─ gating (only when outcome='approved'):
       │          · all std_reference rows on this version have verification_status='approved'
       │          · all std_review_comment rows in this round have resolution != 'open'
       │          · the closing user IS the round's reviewer
       │
       └─ exists only while document_version.status='reviewing'

std_reference.verification_status:  (Wave 3 column)
    pending → approved | rejected
```

Transitions are atomic with the parent state where related:
- `start_round` transaction: INSERT round + UPDATE version.status='reviewing'
- `close_round(approved)` transaction: gating SELECT + UPDATE round.status='closed', outcome='approved' + UPDATE version.status='approved'
- `close_round(rejected)` transaction: UPDATE round.status='closed', outcome='rejected' + UPDATE version.status='drafting' (no gating)

### 2.2 New role

`auth.py` role enum gains `standard_reviewer`. Specifics:

| Aspect | Behavior |
|---|---|
| Self-registration | LoginPage allows selecting standard_reviewer alongside existing roles |
| Admin dashboard | User management lists the new role; admin can grant/revoke |
| Default RBAC | R on viewer/analyst sub-tabs (mimics viewer); RW on review endpoints scoped to their own rounds |
| Admin uplift | Admin role always allowed to perform any reviewer action (no additional grant needed) |

The role addition is additive — existing role checks are unaffected.

### 2.3 Component map

```
data_agent/standards_platform/review/
├─ __init__.py
├─ round_repo.py              # CRUD on std_review_round
├─ comment_repo.py            # CRUD on std_review_comment
├─ gating.py                  # close-round gating check (pure SQL)
└─ handlers.py                # Starlette handlers for /api/std/reviews/*

data_agent/api/standards_routes.py
└─ + 7 routes wired in `standards_routes = [...]`

data_agent/migrations/
├─ 078_std_review_tables.sql      # round + comment tables, FK, CHECK, INDEX
└─ 079_role_standard_reviewer.sql # extend auth role enum (only if enum-backed)

frontend/src/components/datapanel/standards/
├─ ReviewSubTab.tsx           # 4-column layout
├─ review/
│   ├─ RoundSelector.tsx
│   ├─ ClauseAuditList.tsx
│   ├─ CommentThread.tsx
│   ├─ ReferenceAuditCard.tsx
│   └─ CloseRoundDialog.tsx   # shows gating precheck before submit
└─ standardsApi.ts            # +types and 7 SDK functions

data_agent/auth.py            # role enum + register_user accepts standard_reviewer
```

## 3. DB design

### 3.1 Migration 078: review tables

```sql
-- 078: review_round + review_comment tables for the review stage
--      (parent spec §4.2.6).

CREATE TABLE std_review_round (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id  UUID NOT NULL REFERENCES std_document_version(id) ON DELETE CASCADE,
    reviewer_user_id     TEXT NOT NULL,
    initiated_by         TEXT NOT NULL,
    initiated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at            TIMESTAMPTZ NULL,
    status               TEXT NOT NULL DEFAULT 'open',
    outcome              TEXT NULL,
    CONSTRAINT std_review_round_status_check
        CHECK (status IN ('open','closed')),
    CONSTRAINT std_review_round_outcome_check
        CHECK ((status = 'open' AND outcome IS NULL)
            OR (status = 'closed' AND outcome IN ('approved','rejected'))),
    CONSTRAINT std_review_round_closed_at_check
        CHECK ((status = 'open' AND closed_at IS NULL)
            OR (status = 'closed' AND closed_at IS NOT NULL))
);

-- At most one open round per document_version
CREATE UNIQUE INDEX idx_std_review_round_one_open_per_version
    ON std_review_round(document_version_id) WHERE status = 'open';

CREATE INDEX idx_std_review_round_reviewer
    ON std_review_round(reviewer_user_id, status);

CREATE TABLE std_review_comment (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    round_id            UUID NOT NULL REFERENCES std_review_round(id) ON DELETE CASCADE,
    clause_id           UUID NOT NULL REFERENCES std_clause(id) ON DELETE CASCADE,
    parent_comment_id   UUID NULL REFERENCES std_review_comment(id) ON DELETE CASCADE,
    author_user_id      TEXT NOT NULL,
    body_md             TEXT NOT NULL,
    resolution          TEXT NOT NULL DEFAULT 'open',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at         TIMESTAMPTZ NULL,
    resolved_by         TEXT NULL,
    CONSTRAINT std_review_comment_resolution_check
        CHECK (resolution IN ('open','accepted','rejected','duplicate')),
    CONSTRAINT std_review_comment_body_nonempty_check
        CHECK (length(btrim(body_md)) > 0),
    CONSTRAINT std_review_comment_resolved_consistency_check
        CHECK ((resolution = 'open' AND resolved_at IS NULL AND resolved_by IS NULL)
            OR (resolution != 'open' AND resolved_at IS NOT NULL AND resolved_by IS NOT NULL))
);

CREATE INDEX idx_std_review_comment_round_clause
    ON std_review_comment(round_id, clause_id);

CREATE INDEX idx_std_review_comment_open
    ON std_review_comment(round_id) WHERE resolution = 'open';
```

`parent_comment_id` enables threaded replies; `ON DELETE CASCADE` handles round teardown. The body-nonempty CHECK is the DB-side counterpart to the application's strip+400 guard (mirrors Wave 3 Fix #4 discipline).

### 3.2 Migration 079: standard_reviewer role

If the project's role storage is column-typed TEXT (likely, based on Wave 3 patterns), no migration is needed — auth.py just accepts the new string. If it is a Postgres ENUM, add:

```sql
-- 079: add standard_reviewer to the role enum
ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'standard_reviewer';
```

Implementation plan will grep `auth.py` and `migrations/` to confirm storage shape and decide whether 079 is needed.

## 4. API design

All routes return JSON. All mutating routes require auth (cookie session). 403 from RBAC, 401 from missing auth, 400/409 from validation/state errors. Bodies use snake_case.

### 4.1 Rounds

```
POST /api/std/reviews/rounds
  auth: admin
  body: {document_version_id: UUID, reviewer_user_id: str}
  → 201 {round_id: UUID}
  errors: 400 invalid reviewer, 409 round already open, 409 version not drafting

GET /api/std/reviews/rounds?version_id=&reviewer_user_id=&status=
  auth: any logged-in
  → 200 [{id, document_version_id, reviewer_user_id, initiated_by, initiated_at,
           closed_at, status, outcome}]
  filter params optional; default no filter

GET /api/std/reviews/rounds/{round_id}/close-precheck
  auth: round.reviewer_user_id == current_user OR admin
  → 200 {pending_refs: int, open_comments: int, blocking: bool}

POST /api/std/reviews/rounds/{round_id}/close
  auth: round.reviewer_user_id == current_user OR admin
  body: {outcome: 'approved' | 'rejected'}
  → 200 {round_id, status: 'closed', outcome, version_status: 'approved'|'drafting'}
  errors: 409 round already closed, 409 gating not satisfied (when outcome='approved')
```

### 4.2 Comments

```
GET /api/std/reviews/rounds/{round_id}/comments?clause_id=
  auth: any logged-in
  → 200 [{id, round_id, clause_id, parent_comment_id, author_user_id,
           body_md, resolution, created_at, resolved_at, resolved_by}]
  results ordered by created_at; clause_id filter optional

POST /api/std/reviews/rounds/{round_id}/comments
  auth: round.reviewer_user_id == current_user OR admin
  body: {clause_id: UUID, body_md: str, parent_comment_id?: UUID}
  → 201 {comment_id: UUID}
  errors: 400 empty body, 400 parent_comment_id in different round, 409 round closed

POST /api/std/reviews/comments/{comment_id}/resolve
  auth: round.reviewer_user_id == current_user OR admin
  body: {resolution: 'accepted'|'rejected'|'duplicate'}
  → 200 {comment_id, resolution}
  errors: 400 invalid resolution, 409 round closed
```

### 4.3 Reference audit

```
PATCH /api/std/reviews/references/{ref_id}/status
  auth: round.reviewer_user_id == current_user OR admin
  body: {verification_status: 'approved' | 'rejected', round_id: UUID}
  → 200 {ref_id, verification_status, verified_by, verified_at}
  errors: 400 pending not allowed via this endpoint,
          403 not the assigned reviewer,
          404 ref not on this round's version,
          409 round closed
```

Notes:
- `round_id` in the body lets the server cross-check that the ref belongs to a clause in this round's version, and that the reviewer is authorized for this specific round.
- We do not expose a way to revert a reference to `pending` from this endpoint — once audited, audit is final within the round. Admin can SQL-fix if absolutely needed (escape hatch, not documented in UI).

### 4.4 Drafting endpoint gate

Existing drafting endpoints (`/api/std/clauses/{id}` PUT, `/api/std/clauses/{id}/lock`, etc.) gain a new server-side check:

```python
# Before any write
if version.status == 'reviewing':
    return JSONResponse({"error": "version is under review, drafting blocked"},
                        status_code=409)
```

Read endpoints are unaffected. Reviewing's lock pattern (Wave 1's editor_session) still operates; this is just a coarse gate that blocks even unlocked writes once status='reviewing'.

## 5. Frontend design

### 5.1 ReviewSubTab layout (4 columns)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ ReviewSubTab                                                                │
├──────────────┬───────────────────┬─────────────────────────┬────────────────┤
│              │                   │                         │                │
│ Round list   │ Clause tree       │ Audit panel             │ Close round    │
│ (left rail)  │ (with audit badge │ (right panel for        │ (footer card)  │
│              │  per clause)      │  selected clause)       │                │
│              │                   │                         │                │
│ - Versions   │ ▾ Section 1       │ ▎References (N pending) │ Precheck:      │
│ - Status     │   ▾ 1.1 …         │  ☐ [ref-1] approved     │  pending: 2    │
│ - Reviewer   │     · 1.1.1 [3🟠] │  ☐ [ref-2] pending      │  comments: 1   │
│   filter     │   ▾ 1.2 …         │  ☐ [ref-3] pending      │  blocking: yes │
│              │                   │                         │                │
│ [Start round]│                   │ ▎Comments (M open)      │ Outcome:       │
│  (admin)     │                   │  - thread 1 [open]      │  ( ) approved  │
│              │                   │    └ reply              │  ( ) rejected  │
│              │                   │  + new comment          │ [Close round]  │
└──────────────┴───────────────────┴─────────────────────────┴────────────────┘
```

Routing: enter ReviewSubTab from DataPanel tabs (between AnalyzeSubTab and DraftSubTab is a reasonable placement). When `role` is `standard_reviewer`/`admin`, the tab is interactive; viewer/analyst see read-only.

### 5.2 Component responsibilities

| Component | Owns | Talks to |
|---|---|---|
| `ReviewSubTab.tsx` | Layout, selectedRoundId, selectedClauseId | RoundSelector, ClauseAuditList, audit panel state |
| `RoundSelector.tsx` | Round list filter + start-round button (admin) | `GET /rounds`, `POST /rounds` |
| `ClauseAuditList.tsx` | Tree of clauses with pending-count badges | `GET /clauses`, badge counts via `GET /references` |
| `ReferenceAuditCard.tsx` | Per-reference status toggle | `PATCH /references/{id}/status` |
| `CommentThread.tsx` | Comments for a clause, threaded display + reply input + resolve button | `GET/POST /comments`, `POST /comments/{id}/resolve` |
| `CloseRoundDialog.tsx` | Precheck panel + outcome radio + close button | `GET /close-precheck`, `POST /close` |

Each component talks only through `standardsApi.ts` — no fetch calls in components.

### 5.3 SDK additions in `standardsApi.ts`

```typescript
export type ReviewRound = {
  id: string;
  document_version_id: string;
  reviewer_user_id: string;
  initiated_by: string;
  initiated_at: string;
  closed_at: string | null;
  status: 'open' | 'closed';
  outcome: 'approved' | 'rejected' | null;
};

export type ReviewComment = {
  id: string;
  round_id: string;
  clause_id: string;
  parent_comment_id: string | null;
  author_user_id: string;
  body_md: string;
  resolution: 'open' | 'accepted' | 'rejected' | 'duplicate';
  created_at: string;
  resolved_at: string | null;
  resolved_by: string | null;
};

// 7 SDK functions, one per endpoint
export async function startReviewRound(...) { ... }
export async function listReviewRounds(...) { ... }
export async function closeReviewPrecheck(roundId: string) { ... }
export async function closeReviewRound(...) { ... }
export async function listReviewComments(...) { ... }
export async function postReviewComment(...) { ... }
export async function resolveReviewComment(...) { ... }
export async function patchReferenceStatus(...) { ... }
```

## 6. Error handling

| Scenario | HTTP | Body | Origin |
|---|---|---|---|
| Start round, open round already exists | 409 | `{error, round_id}` | UNIQUE index + precheck |
| Start round, version not in 'drafting' | 409 | `{error, current_status}` | POST /rounds |
| reviewer_user_id not found or wrong role | 400 | `{error: "invalid reviewer"}` | POST /rounds |
| Non-round-reviewer attempts mutating action | 403 | `{error: "not the assigned reviewer"}` | PATCH/POST handlers |
| Close round, gating fails (outcome=approved) | 409 | `{error, pending_refs, open_comments}` | POST /close |
| Close round, already closed | 409 | `{error: "round already closed"}` | POST /close |
| Comment body empty/whitespace | 400 | `{error: "body_md is required"}` | POST comment + DB CHECK |
| `parent_comment_id` in different round | 400 | `{error: "parent must belong to same round"}` | POST comment |
| Reference status set to 'pending' | 400 | `{error: "verification_status must be approved or rejected"}` | PATCH ref |
| Reference not on this round's version | 404 | `{error: "reference not in round"}` | PATCH ref |
| Drafting attempt while reviewing | 409 | `{error: "version is under review, drafting blocked"}` | drafting handlers |

Transactions: start_round and close_round both wrap their UPDATE pairs in a single transaction with `SELECT ... FOR UPDATE` on the round row to prevent the race "two simultaneous close calls".

## 7. Testing

| File | Type | Cases |
|---|---|---|
| `test_migration_078.py` (new) | schema | 5 — 3 tables exist with expected columns; round.status / outcome CHECKs reject invalid combos; comment resolution CHECK; comment body-nonempty CHECK; UNIQUE index rejects 2nd open round on same version |
| `test_migration_079.py` (new, if needed) | schema | 2 — enum contains 'standard_reviewer'; existing role values unchanged |
| `test_review_round_handler.py` (new) | API | 8 — start happy, start when not drafting (409), start with open round (409), list filtered, close approved happy, close rejected happy, close gating fail (409), close by non-reviewer (403) |
| `test_review_comment_handler.py` (new) | API | 6 — post comment, post threaded reply, resolve comment, empty body 400, parent in different round 400, non-reviewer 403 |
| `test_review_reference_handler.py` (new) | API | 5 — PATCH approved, PATCH rejected, PATCH pending 400, non-round-reviewer 403, closed round 409 |
| `test_api_drafting.py` (extend) | API | 1 — drafting blocked when version.status='reviewing' (409) |
| `test_auth.py` (extend) | unit | 1 — standard_reviewer role accepted on register_user |

**Total: ~28 new tests**, all on real Postgres via `conftest.py` fixtures from Wave 3.

`fresh_clause` fixture is reused. New helpers in tests/conftest.py:
- `fresh_round(engine, fresh_clause) → (round_id, version_id, reviewer_id)` — seeds a round on the version + a clause
- `fresh_reference(engine, fresh_clause) → ref_id` — seeds a `pending` reference on the clause for audit tests

These helpers follow the yield/teardown pattern established in Wave 3 (commit `19d9806`).

## 8. Implementation order

Each step is one commit (or two for the larger T3):

1. **Migration 078 (+ 079 if needed) + migration tests** (T1)
2. **`review/round_repo.py` + `review/comment_repo.py` + `review/gating.py` + unit tests on repo/gating logic** (T2)
3. **`review/handlers.py` + wire 7 routes + handler tests** (T3) — may split into 3a (rounds), 3b (comments), 3c (references) if commit grows beyond ~600 LOC
4. **Drafting endpoints status gate + test** (T4)
5. **`auth.py` role extension + admin/register UI option + test** (T5)
6. **`standardsApi.ts` SDK additions** (T6)
7. **`ReviewSubTab.tsx` + 5 sub-components** (T7)
8. **DataPanel tab registration + RBAC routing** (T8)
9. **Regression gate + npm build + manual E2E smoke** (T9)

Rationale: schema first → repo layer → handlers (use repo) → auth + frontend (mostly orthogonal but ordered by dependency).

## 9. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| auth.py role storage is enum-backed and migration 079 forgotten | Medium | T5 explicitly greps; CI test asserts standard_reviewer round-trips through register/login |
| Concurrent close_round calls race | Low | Transaction with `FOR UPDATE` on round row |
| `fresh_clause` fixture from Wave 3 doesn't clean up nested review_round rows | Low | ON DELETE CASCADE chain: document → version → clause → reference; round depends on version, so cascades cleanly |
| ReviewSubTab UX confusion for viewers | Low | Read-only mode shows the same panels but disables all buttons; standardsApi returns 403 if misclicked |
| Drafter is editing while admin starts a round | Medium | Start-round transaction sets status='reviewing'; next drafting save returns 409 with clear message. Drafter's in-progress edits remain in memory; the recommended UX is a banner on DraftSubTab when status changes |

## 10. Acceptance criteria

**Automated (CI):**
- `pytest data_agent/standards_platform/ -v` ≥ 145 passed (117 existing + ~28 new). The single pre-existing test_handlers.py failure stays as-is.
- `pytest data_agent/ --ignore=data_agent/test_knowledge_agent.py -q` no new regressions beyond the pre-existing 81 known failures.
- `cd frontend && npm run build` exits 0.

**Manual smoke (single E2E pass by user):**
1. admin uploads a docx → ingest → drafting (Wave 1 flow). Insert 2-3 citations (Wave 2 flow).
2. admin: ReviewSubTab → 「启动审定」 → assign self as reviewer (or admin-as-reviewer). Version status changes to `reviewing`.
3. Switch to DraftSubTab → attempt edit → 409 banner appears.
4. Back to ReviewSubTab → audit each reference (mix approve/reject).
5. Post a comment on a clause, reply to it, mark resolution.
6. Click 「关闭审定」 with outcome `approved` → precheck shows blocking if any pending refs or open comments → fix those → close succeeds → version status becomes `approved`.
7. SQL verify:
   ```sql
   SELECT v.status, r.status, r.outcome
     FROM std_document_version v
     JOIN std_review_round r ON r.document_version_id = v.id
    ORDER BY r.closed_at DESC LIMIT 1;
   ```
   Expected: `v.status='approved'`, `r.status='closed'`, `r.outcome='approved'`.

## 11. YAGNI exclusions (reiterated)

Listed in §1 "Out of scope" — repeated here for review-time scanning:

- No publishing
- No multi-round / serial reviewers
- No @mention / notifications / attachments
- No "approve all" batch
- No reviewer delegation
- No in-editor comment markers (drafter view)
- No reopen-closed-round
- No multi-tenant
- No piggyback on Wave-3 deferred Minor items
- No data migration for verified_*

## 12. Estimated effort

~2-3 wall days. ~9 commits, each independently shippable. Aligns with Wave 1's scope (which shipped 15 tasks in similar time).
