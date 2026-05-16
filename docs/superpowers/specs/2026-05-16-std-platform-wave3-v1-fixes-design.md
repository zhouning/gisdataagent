# Standards Platform — Wave 3: v1 Limitation Fixes

**Date:** 2026-05-16
**Branch:** `feat/v12-extensible-platform`
**Status:** design — ready for implementation plan
**Parent spec:** `docs/superpowers/specs/2026-05-13-data-standard-lifecycle-platform-design.md`
**Predecessors:** Wave 1 (`2026-05-15-std-platform-drafting-wave1-design.md`), Wave 2 (`2026-05-15-std-platform-drafting-wave2-design.md`)
**Scope:** Six correctness/quality fixes carried over from Wave 2 code review, plus schema groundwork for the future review (审定) sub-tab.

## 0. Why this spec

Wave 2 shipped the citation assistant (13 feature commits + 3 fix/ops commits, all on GitHub as of `b442876`). During implementation a code review surfaced seven follow-up items. Item #7 (embedding_gateway diagnostic) is a separate infra workstream and is not in scope here. The remaining six are correctness or test-hygiene fixes that block a clean foundation for Wave 4 (审定 sub-tab):

1. `search_kb` returns `extra.title = None` because it looks at the wrong key
2. `citation_rerank` trusts the LLM's reported order with no final sort
3. `citation_insert` writes `target_kind='std_clause'` + `target_clause_id=NULL` for `std_data_element` / `std_term` targets — a data-integrity bug
4. Empty `citation_text` can be inserted
5. Column `verified_by` is misnamed — it currently stores the inserter, not a verifier
6. Test fixtures (`_get_engine_or_skip`, `_seed_clause`, `fresh_clause`) are duplicated across `test_api_drafting.py` and `test_api_citation.py`

Current `std_reference` row count: **0**. No backfill or data migration needed.

## 1. Scope

**In scope**

- DB migration `076_std_reference_extend_targets.sql` — add FK columns for `std_data_element` / `std_term` targets, add `inserted_by` / `inserted_at` / `verification_status` columns, extend `target_kind` CHECK, add consistency CHECK
- Fix #1: `search_kb` title fallback in `citation_sources.py`
- Fix #2: stable confidence sort in `citation_rerank.py`
- Fix #3: correct FK dispatch in `citation_insert` handler
- Fix #4: 400 guard for empty `citation_text`
- Fix #5: write to `inserted_by` / `inserted_at` instead of `verified_by` / `verified_at`; leave the latter NULL for the review stage
- Fix #6: extract shared fixtures into `tests/conftest.py`
- New tests covering all six fixes (~14 cases — see §4 for the matrix)

**Out of scope**

- Wave 4 「审定」 sub-tab itself (state machine, UI, API endpoints)
- Embedding gateway root-cause investigation (separate workstream)
- Renaming the `verified_by` / `verified_at` columns (kept; semantics realigned via Fix #5)
- Any frontend changes — Wave 2 UI is unchanged

## 2. DB design

### 2.1 Schema changes

Migration `076_std_reference_extend_targets.sql`:

> All `target_*_id` FKs use `ON DELETE CASCADE` because the `target_consistency` CHECK would otherwise reject the `SET NULL` update fired by Postgres when a target row is deleted — the CHECK requires the FK column to be `NOT NULL` whenever `target_kind` matches that column.

```sql
ALTER TABLE std_reference
  ADD COLUMN IF NOT EXISTS target_data_element_id UUID REFERENCES std_data_element(id) ON DELETE CASCADE,
  ADD COLUMN IF NOT EXISTS target_term_id         UUID REFERENCES std_term(id)         ON DELETE CASCADE,
  ADD COLUMN IF NOT EXISTS inserted_by            TEXT,
  ADD COLUMN IF NOT EXISTS inserted_at            TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS verification_status    TEXT NOT NULL DEFAULT 'pending';

-- Historical rows (currently 0): treat old verified_* as inserted_*
UPDATE std_reference
   SET inserted_by = verified_by,
       inserted_at = verified_at
 WHERE inserted_by IS NULL;

-- Reset verified_* so they are filled by the review stage only
UPDATE std_reference SET verified_by = NULL, verified_at = NULL;

ALTER TABLE std_reference DROP CONSTRAINT IF EXISTS std_reference_target_kind_check;
ALTER TABLE std_reference ADD CONSTRAINT std_reference_target_kind_check
  CHECK (target_kind IN (
    'std_clause','std_data_element','std_term','std_document',
    'external_url','web_snapshot','internet_search'));

-- Note: internet_search is permitted to have NULL target_url because it is
-- the catch-all bucket for KB-chunk citations (which have no real URL);
-- other URL-bearing kinds (external_url, web_snapshot) still require a URL.
-- Migration 077 relaxed the original CHECK that grouped internet_search
-- with the URL-required kinds (Wave 3 post-PR critical fix C1).
ALTER TABLE std_reference ADD CONSTRAINT std_reference_target_consistency CHECK (
  (target_kind = 'std_clause'       AND target_clause_id        IS NOT NULL) OR
  (target_kind = 'std_data_element' AND target_data_element_id  IS NOT NULL) OR
  (target_kind = 'std_term'         AND target_term_id          IS NOT NULL) OR
  (target_kind = 'std_document'     AND target_document_id      IS NOT NULL) OR
  (target_kind IN ('external_url','web_snapshot') AND target_url IS NOT NULL) OR
  (target_kind = 'internet_search')
);

ALTER TABLE std_reference ADD CONSTRAINT std_reference_verification_status_check
  CHECK (verification_status IN ('pending','approved','rejected'));

CREATE INDEX IF NOT EXISTS idx_std_reference_tgt_de            ON std_reference(target_data_element_id);
CREATE INDEX IF NOT EXISTS idx_std_reference_tgt_term          ON std_reference(target_term_id);
CREATE INDEX IF NOT EXISTS idx_std_reference_verification_status ON std_reference(verification_status);
```

### 2.2 Column semantics after migration

| Column | Meaning | Filled by |
|---|---|---|
| `inserted_by` / `inserted_at` | Who inserted the citation chip, when | `citation_insert` (Wave 2/3) |
| `verified_by` / `verified_at` | Who approved/rejected the citation, when | Review stage (Wave 4) |
| `verification_status` | `pending` / `approved` / `rejected` | DEFAULT `pending` at insert; updated by review |
| `target_data_element_id` | FK to `std_data_element` when `target_kind='std_data_element'` | `citation_insert` (Wave 3) |
| `target_term_id` | FK to `std_term` when `target_kind='std_term'` | `citation_insert` (Wave 3) |

Note: `verified_by` / `verified_at` are intentionally NOT renamed. RENAME COLUMN is hard to make idempotent and risks breaking external references. Semantic realignment via Fix #5 + DEFAULT NULL is sufficient.

## 3. Code changes

### 3.1 `citation_sources.py` — Fix #1

In `search_kb()`, when constructing the per-hit `extra` dict:

```python
title = (ch.get("metadata") or {}).get("title") or ch.get("doc_id") or "(无标题)"
extra = {"title": title, ...}
```

### 3.2 `citation_rerank.py` — Fix #2

At the end of the rerank function, before returning:

```python
out.sort(key=lambda x: -float(x.get("confidence") or 0.0))
return out
```

### 3.3 `citation_insert` handler — Fixes #3, #4, #5

Location: the function that backs `POST /api/std/citation/insert` (in `standards_platform/handlers.py` or whichever module currently owns it; the implementation plan will confirm by grep).

**Behavior:**

1. **Input validation (Fix #4):** trim `citation_text`; if empty, return `JSONResponse({"error": "citation_text is required"}, status_code=400)`.
2. **target_kind dispatch (Fix #3):** map `target_kind` to the correct FK column:

   | `target_kind` | Column(s) written | Other `target_*` columns |
   |---|---|---|
   | `std_clause` | `target_clause_id` | NULL |
   | `std_data_element` | `target_data_element_id` | NULL |
   | `std_term` | `target_term_id` | NULL |
   | `std_document` | `target_document_id` | NULL |
   | `external_url` / `web_snapshot` / `internet_search` | `target_url` (required) + `snapshot_id` (optional) | NULL |
   | any other value | (none — handler returns 400) | (N/A) |

3. **Insert/verify column split (Fix #5):**
   - Write `inserted_by = <caller user_id>`, `inserted_at = now()`.
   - Do NOT write `verified_by` / `verified_at` — leave NULL.
   - Do NOT write `verification_status` — rely on DEFAULT `'pending'`.

Returns: `{"id": <ref_id>}` on success (same shape as today).

### 3.4 `tests/conftest.py` — Fix #6

New file `data_agent/standards_platform/tests/conftest.py`:

```python
import pytest
from sqlalchemy import text

def _get_engine_or_skip():
    from data_agent.db_engine import get_engine
    e = get_engine()
    if e is None:
        pytest.skip("DB not configured")
    return e

@pytest.fixture
def engine():
    return _get_engine_or_skip()

@pytest.fixture
def fresh_clause(engine):
    # Body moved verbatim from test_api_drafting.py / test_api_citation.py
    ...
```

`test_api_drafting.py` and `test_api_citation.py`: delete the local `_get_engine_or_skip` / `_seed_clause` / `fresh_clause` definitions; use the fixtures by parameter name.

## 4. Test matrix

| File | New cases | Modification |
|---|---|---|
| `test_citation_sources.py` | Fix #1: title from `metadata.title` ×1, fallback to `doc_id` ×1 | — |
| `test_citation_rerank.py` | Fix #2: scrambled confidence input → sorted output ×1 | — |
| `test_api_citation.py` | Fix #3: data_element / term / document target each ×1 (3 total); Fix #4: empty / whitespace-only citation_text ×2; Fix #5: `verification_status='pending'`, `verified_by IS NULL`, `inserted_by` populated ×1 | Remove local fixtures, use conftest |
| `test_api_drafting.py` | — | Remove local fixtures, use conftest |
| `test_migration_076.py` (new) | CHECK rejects mismatched kind+FK ×1; CHECK accepts each valid kind ×4 (clause, data_element, term, document); CHECK accepts external_url with target_url ×1; verification_status defaults to `pending` ×1; old `std_reference_target_kind_check` is replaced ×1 | — |

Approximate new tests: **~14 cases**.

Existing tests that must remain green: 21 unit + 6 API in `standards_platform/`, plus the full project suite excluding `test_knowledge_agent.py`.

## 5. Implementation order

Each step is an independent commit and an independent pass-criteria gate:

1. **Migration 076 + `test_migration_076.py`** — apply locally, all migration tests green.
2. **`conftest.py` extract + import updates in two test files** — full standards_platform suite still 27 green.
3. **Fix #1 (search_kb title) + Fix #2 (rerank sort) + their unit tests** — 3 new passing tests.
4. **Fix #3 + #4 + #5 (citation_insert handler) + 6 new API tests** — 6 new passing tests.
5. **Regression gate:** `pytest data_agent/ --ignore=data_agent/test_knowledge_agent.py -q` green; `cd frontend && npm run build` exits 0.

Rationale for ordering: schema first so subsequent code can rely on new columns; conftest second so subsequent test additions use shared fixtures directly; pure-function fixes third (fastest green baseline); handler change last (highest blast radius, but rests on everything above).

## 6. Error handling

- Migration failures: surfaced by `test_migration_076.py`. Migration is idempotent (`ADD COLUMN IF NOT EXISTS`, `DROP CONSTRAINT IF EXISTS`).
- Invalid `target_kind` in `citation_insert`: 400 with explicit error message; covered by a test.
- Empty `citation_text`: 400 with `{"error": "citation_text is required"}`.
- DB CHECK violations from buggy callers post-fix: surfaced as 500 (Postgres `IntegrityError`); acceptable — represents a real bug, not a user input issue.

## 7. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| `verified_by` / `verified_at` referenced elsewhere in repo or frontend | Medium | First step of implementation: `grep -rn "verified_by\|verified_at" data_agent/ frontend/` and adjust if found. |
| conftest fixture scope mismatch (function vs module) breaks existing isolation | Low | Keep `function` scope (matches today's per-test fresh data). |
| Handler dispatch misses a `target_kind` branch | Low | 6-case test matrix; default `else` branch returns 400. |
| Migration `verification_status NOT NULL DEFAULT 'pending'` slow on large tables | Low | Current row count = 0. Future scale concerns are not in this scope. |

## 8. Acceptance criteria

**Automated (CI):**

- `pytest data_agent/standards_platform/ -v` ≥ 41 passed (27 existing + ~14 new)
- `pytest data_agent/ --ignore=data_agent/test_knowledge_agent.py -q` green (no regressions)
- `cd frontend && npm run build` exits 0

**Manual smoke (one round in browser):**

1. DataPanel → 数据标准 → 起草 → FT.1 clause.
2. 「查找引用」 → search `图斑` (matches `std_data_element`) → insert top hit.
3. SQL verify:
   ```sql
   SELECT target_kind, target_clause_id, target_data_element_id, target_term_id,
          inserted_by, verified_by, verification_status
     FROM std_reference ORDER BY created_at DESC LIMIT 1;
   ```
   Expected: `target_kind='std_data_element'`, `target_data_element_id IS NOT NULL`, all other `target_*` NULL, `inserted_by='admin'`, `verified_by IS NULL`, `verification_status='pending'`.
4. Attempt to insert with empty `citation_text` → Network panel shows 400.

**Wave 2 regression:** the 11-step browser E2E flow from the Wave 2 handoff still passes end-to-end.

## 9. YAGNI exclusions

- No rename of `verified_by` / `verified_at` columns.
- No review state machine, review UI, or review API (those belong to Wave 4).
- No frontend changes.
- No embedding_gateway diagnostic work (separate workstream).
- No backfill of historical `std_reference` rows (the table is empty).

## 10. Estimated effort

~2.5 hours wall time across the 5 steps. Each commit is independently shippable.
