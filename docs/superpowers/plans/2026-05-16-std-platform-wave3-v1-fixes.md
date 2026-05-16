# Standards Platform Wave 3 — v1 Limitation Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix six correctness/quality issues from the Wave 2 code review and lay schema groundwork for the future review (审定) sub-tab.

**Architecture:** One DB migration extends `std_reference` with new FK columns + insert/verify column split + consistency CHECK. Three Python files get targeted fixes (`citation_sources.py`, `citation_rerank.py`, `api/standards_routes.py::citation_insert`). Two test files have their duplicated fixtures hoisted into a new `conftest.py`. Each task is one independent commit.

**Tech Stack:** PostgreSQL 16 + PostGIS (UUID, CHECK constraints), Python 3.13 + SQLAlchemy 2 + Starlette, pytest fixtures.

**Spec:** `docs/superpowers/specs/2026-05-16-std-platform-wave3-v1-fixes-design.md`

**Branch:** `feat/v12-extensible-platform` (continue on existing branch — single PR scope)

---

## Pre-flight

- [ ] **Step 0.1: Confirm baseline is clean**

Run:
```powershell
cd D:\adk
git status --short
git log --oneline -1
```
Expected: HEAD is `60234f9` (or later) with the spec already committed. Untracked files in worktree are fine and unrelated.

- [ ] **Step 0.2: Confirm `std_reference` is empty (no backfill needed)**

Run:
```powershell
.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv('data_agent/.env'); from sqlalchemy import text; from data_agent.db_engine import get_engine; e=get_engine(); print(e.connect().execute(text('SELECT count(*) FROM std_reference')).scalar())"
```
Expected: `0`. If non-zero, STOP — the migration's `UPDATE` statements need review for data preservation before proceeding.

- [ ] **Step 0.3: Audit `verified_by` / `verified_at` references repo-wide**

Run:
```powershell
git grep -n "verified_by\|verified_at" -- data_agent/ frontend/
```
Expected: matches only in `data_agent/api/standards_routes.py` (the INSERT we are fixing), `data_agent/migrations/073_std_references_and_snapshots.sql`, and `data_agent/standards_platform/tests/test_migrations_070_to_075.py`. **Note any other matches** — if found, append a fix-up task at the end of the plan before proceeding.

(Independent matches in `data_agent/reference_queries.py` and `data_agent/migrations/054_reference_queries.sql` are unrelated — they belong to the NL2SQL reference query store, not `std_reference`.)

---

## Task 1: Migration 076 — extend `std_reference`

**Files:**
- Create: `data_agent/migrations/076_std_reference_extend_targets.sql`
- Create: `data_agent/standards_platform/tests/test_migration_076.py`

- [ ] **Step 1.1: Write the migration**

Create `data_agent/migrations/076_std_reference_extend_targets.sql`:

```sql
-- 076: extend std_reference to support std_data_element / std_term targets,
--      split inserter from verifier semantics, and add verification_status.

ALTER TABLE std_reference
  ADD COLUMN IF NOT EXISTS target_data_element_id UUID REFERENCES std_data_element(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS target_term_id         UUID REFERENCES std_term(id)         ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS inserted_by            TEXT,
  ADD COLUMN IF NOT EXISTS inserted_at            TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS verification_status    TEXT NOT NULL DEFAULT 'pending';

-- Historical rows: prior to this migration, verified_by/verified_at actually
-- held inserter info. Move those values to the new columns. Currently 0 rows
-- in std_reference, so this is a no-op in practice but kept for safety.
UPDATE std_reference
   SET inserted_by = verified_by,
       inserted_at = verified_at
 WHERE inserted_by IS NULL;

-- Reset verified_* so they are filled by the review stage only (Wave 4).
UPDATE std_reference SET verified_by = NULL, verified_at = NULL;

-- Extend allowed target_kind values
ALTER TABLE std_reference DROP CONSTRAINT IF EXISTS std_reference_target_kind_check;
ALTER TABLE std_reference ADD CONSTRAINT std_reference_target_kind_check
  CHECK (target_kind IN (
    'std_clause','std_data_element','std_term','std_document',
    'external_url','web_snapshot','internet_search'));

-- target_kind <-> FK column consistency
ALTER TABLE std_reference DROP CONSTRAINT IF EXISTS std_reference_target_consistency;
ALTER TABLE std_reference ADD CONSTRAINT std_reference_target_consistency CHECK (
  (target_kind = 'std_clause'       AND target_clause_id        IS NOT NULL) OR
  (target_kind = 'std_data_element' AND target_data_element_id  IS NOT NULL) OR
  (target_kind = 'std_term'         AND target_term_id          IS NOT NULL) OR
  (target_kind = 'std_document'     AND target_document_id      IS NOT NULL) OR
  (target_kind IN ('external_url','web_snapshot','internet_search')
                                    AND target_url              IS NOT NULL)
);

ALTER TABLE std_reference DROP CONSTRAINT IF EXISTS std_reference_verification_status_check;
ALTER TABLE std_reference ADD CONSTRAINT std_reference_verification_status_check
  CHECK (verification_status IN ('pending','approved','rejected'));

CREATE INDEX IF NOT EXISTS idx_std_reference_tgt_de              ON std_reference(target_data_element_id);
CREATE INDEX IF NOT EXISTS idx_std_reference_tgt_term            ON std_reference(target_term_id);
CREATE INDEX IF NOT EXISTS idx_std_reference_verification_status ON std_reference(verification_status);
```

- [ ] **Step 1.2: Apply the migration locally**

Run:
```powershell
$env:PYTHONPATH="D:\adk"
.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv('data_agent/.env'); from sqlalchemy import text; from data_agent.db_engine import get_engine; sql=open('data_agent/migrations/076_std_reference_extend_targets.sql','r',encoding='utf-8').read(); e=get_engine(); conn=e.connect(); conn.execute(text(sql)); conn.commit(); print('OK')"
```
Expected: `OK`. (Project does not have an automated migration runner per `CLAUDE.md` — applying via psycopg/sqlalchemy is the convention.)

- [ ] **Step 1.3: Verify schema after migration**

Run:
```powershell
.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv('data_agent/.env'); from sqlalchemy import text; from data_agent.db_engine import get_engine; e=get_engine(); cols = [r[0] for r in e.connect().execute(text(\"SELECT column_name FROM information_schema.columns WHERE table_name='std_reference' ORDER BY column_name\")).fetchall()]; print(cols)"
```
Expected output contains: `inserted_at`, `inserted_by`, `target_data_element_id`, `target_term_id`, `verification_status`.

- [ ] **Step 1.4: Write the migration test**

Create `data_agent/standards_platform/tests/test_migration_076.py`:

```python
"""Schema-level checks for migration 076 (std_reference extension)."""
from __future__ import annotations

import os
import uuid

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from data_agent.db_engine import get_engine


def _get_engine_or_skip():
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path, override=False)
    eng = get_engine()
    if eng is None:
        pytest.skip("DB engine unavailable")
    return eng


def _seed_clause(eng):
    """Create a throwaway document/version/clause; return clause_id."""
    doc_id = str(uuid.uuid4())
    ver_id = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    with eng.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_document (id, doc_code, title, source_type, "
            "status, owner_user_id) VALUES (:i, :c, 't', 'draft', "
            "'ingested', 'admin')"
        ), {"i": doc_id, "c": f"T-076-{doc_id[:6]}"})
        conn.execute(text(
            "INSERT INTO std_document_version (id, document_id, "
            "version_label, status, semver_major) VALUES (:i, :d, 'v1.0', "
            "'draft', 1)"
        ), {"i": ver_id, "d": doc_id})
        conn.execute(text(
            "INSERT INTO std_clause (id, document_id, document_version_id, "
            "ordinal_path, clause_no, kind, body_md) VALUES (:i, :d, :v, "
            "CAST('1' AS ltree), '1', 'clause', 'hello')"
        ), {"i": cid, "d": doc_id, "v": ver_id})
    return cid, ver_id


def test_new_columns_exist():
    eng = _get_engine_or_skip()
    with eng.connect() as c:
        cols = {r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='std_reference'"
        )).fetchall()}
    assert {"target_data_element_id", "target_term_id",
            "inserted_by", "inserted_at",
            "verification_status"}.issubset(cols)


def test_target_kind_check_accepts_new_values():
    eng = _get_engine_or_skip()
    cid, _ = _seed_clause(eng)
    de_id = str(uuid.uuid4())
    with eng.begin() as conn:
        # Need a real data_element to satisfy the FK
        conn.execute(text(
            "INSERT INTO std_data_element (id, document_version_id, "
            "name_zh, code) VALUES (:i, "
            "(SELECT document_version_id FROM std_clause WHERE id=:c), "
            "'测试要素', 'TEST_DE_076')"
        ), {"i": de_id, "c": cid})
        ref_id = str(uuid.uuid4())
        conn.execute(text(
            "INSERT INTO std_reference (id, source_clause_id, target_kind, "
            "target_data_element_id, citation_text) "
            "VALUES (:i, :s, 'std_data_element', :t, 'cite')"
        ), {"i": ref_id, "s": cid, "t": de_id})
    # cleanup
    with eng.begin() as conn:
        conn.execute(text("DELETE FROM std_reference WHERE id=:i"), {"i": ref_id})
        conn.execute(text("DELETE FROM std_data_element WHERE id=:i"), {"i": de_id})


def test_target_consistency_rejects_mismatch():
    """target_kind=std_clause but target_clause_id NULL must be rejected."""
    eng = _get_engine_or_skip()
    cid, _ = _seed_clause(eng)
    with pytest.raises(IntegrityError):
        with eng.begin() as conn:
            conn.execute(text(
                "INSERT INTO std_reference (id, source_clause_id, "
                "target_kind, target_clause_id, citation_text) "
                "VALUES (:i, :s, 'std_clause', NULL, 'bad')"
            ), {"i": str(uuid.uuid4()), "s": cid})


def test_verification_status_defaults_pending():
    eng = _get_engine_or_skip()
    cid, _ = _seed_clause(eng)
    ref_id = str(uuid.uuid4())
    with eng.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_reference (id, source_clause_id, target_kind, "
            "target_clause_id, citation_text) "
            "VALUES (:i, :s, 'std_clause', :s, 'cite')"
        ), {"i": ref_id, "s": cid})
    with eng.connect() as conn:
        row = conn.execute(text(
            "SELECT verification_status FROM std_reference WHERE id=:i"
        ), {"i": ref_id}).first()
    assert row[0] == "pending"
    with eng.begin() as conn:
        conn.execute(text("DELETE FROM std_reference WHERE id=:i"), {"i": ref_id})


def test_verification_status_check_rejects_invalid():
    eng = _get_engine_or_skip()
    cid, _ = _seed_clause(eng)
    with pytest.raises(IntegrityError):
        with eng.begin() as conn:
            conn.execute(text(
                "INSERT INTO std_reference (id, source_clause_id, "
                "target_kind, target_clause_id, citation_text, "
                "verification_status) "
                "VALUES (:i, :s, 'std_clause', :s, 'c', 'bogus')"
            ), {"i": str(uuid.uuid4()), "s": cid})


def test_external_url_target_requires_url():
    eng = _get_engine_or_skip()
    cid, _ = _seed_clause(eng)
    with pytest.raises(IntegrityError):
        with eng.begin() as conn:
            conn.execute(text(
                "INSERT INTO std_reference (id, source_clause_id, "
                "target_kind, target_url, citation_text) "
                "VALUES (:i, :s, 'external_url', NULL, 'c')"
            ), {"i": str(uuid.uuid4()), "s": cid})
```

- [ ] **Step 1.5: Run migration tests**

Run:
```powershell
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_migration_076.py -v
```
Expected: 6 passed.

- [ ] **Step 1.6: Run existing migration suite to ensure no regression**

Run:
```powershell
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_migrations_070_to_075.py -v
```
Expected: all green (same count as before).

- [ ] **Step 1.7: Commit**

```powershell
git add data_agent/migrations/076_std_reference_extend_targets.sql data_agent/standards_platform/tests/test_migration_076.py
git commit -m "feat(std-platform): migration 076 -- extend std_reference targets + verification status"
```

---

## Task 2: Extract `conftest.py`

**Files:**
- Create: `data_agent/standards_platform/tests/conftest.py`
- Modify: `data_agent/standards_platform/tests/test_api_drafting.py`
- Modify: `data_agent/standards_platform/tests/test_api_citation.py`

- [ ] **Step 2.1: Create the conftest**

Create `data_agent/standards_platform/tests/conftest.py`:

```python
"""Shared fixtures for standards_platform API tests.

Replaces the duplicated _get_engine_or_skip / _seed_clause helpers that
previously lived in test_api_drafting.py and test_api_citation.py.
"""
from __future__ import annotations

import os
import uuid

import pytest
from dotenv import load_dotenv
from sqlalchemy import text

from data_agent.db_engine import get_engine


@pytest.fixture
def engine():
    """Engine or pytest.skip if DB unavailable."""
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path, override=False)
    eng = get_engine()
    if eng is None:
        pytest.skip("DB engine unavailable")
    return eng


@pytest.fixture
def fresh_clause(engine):
    """Insert a throwaway document/version/clause and return (clause_id, doc_id, version_id).

    Note: returns three values now (vs. two in the old _seed_clause). Tests
    that only need clause_id/doc_id can unpack with `cid, did, _ = fresh_clause`.
    Returning version_id makes Task 4's data_element/term seeding straightforward.
    """
    doc_id = str(uuid.uuid4())
    ver_id = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_document (id, doc_code, title, source_type, "
            "status, owner_user_id) VALUES (:i, :c, 't', 'draft', "
            "'ingested', 'admin')"
        ), {"i": doc_id, "c": f"T-CONFTEST-{doc_id[:6]}"})
        conn.execute(text(
            "INSERT INTO std_document_version (id, document_id, "
            "version_label, status, semver_major) VALUES (:i, :d, 'v1.0', "
            "'draft', 1)"
        ), {"i": ver_id, "d": doc_id})
        conn.execute(text(
            "INSERT INTO std_clause (id, document_id, document_version_id, "
            "ordinal_path, clause_no, kind, body_md) VALUES (:i, :d, :v, "
            "CAST('1' AS ltree), '1', 'clause', 'hello')"
        ), {"i": cid, "d": doc_id, "v": ver_id})
    return cid, doc_id, ver_id
```

- [ ] **Step 2.2: Modify `test_api_drafting.py` to use the fixture**

In `data_agent/standards_platform/tests/test_api_drafting.py`:

1. Delete lines 19-27 (`_get_engine_or_skip` definition).
2. Delete lines 30-54 (the local `_seed_clause` definition — find where it ends; it's the function that returns `(cid, doc_id)`).
3. Remove unused imports: `import os`, `from dotenv import load_dotenv`, `from data_agent.db_engine import get_engine`.
4. For each test that previously called `_seed_clause()`, change the signature to accept `fresh_clause` and unpack the three values:

```python
def test_lock_acquire(fresh_clause):
    cid, doc_id, _ = fresh_clause
    # ... rest of test body unchanged ...
```

For tests that previously called `_get_engine_or_skip()`, change the signature to accept `engine`:

```python
def test_something(engine, fresh_clause):
    cid, doc_id, _ = fresh_clause
    # use `engine` directly instead of calling _get_engine_or_skip()
```

- [ ] **Step 2.3: Modify `test_api_citation.py` the same way**

In `data_agent/standards_platform/tests/test_api_citation.py`:

1. Delete lines 18-26 (`_get_engine_or_skip`).
2. Delete lines 29-50 (local `_seed_clause`).
3. Remove unused imports the same way.
4. Replace calls in test bodies the same way.

- [ ] **Step 2.4: Run the modified test files**

Run:
```powershell
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_api_drafting.py data_agent/standards_platform/tests/test_api_citation.py -v
```
Expected: all previously-green tests still green (same count as before — should be 6 API tests total per the Wave 2 baseline).

- [ ] **Step 2.5: Commit**

```powershell
git add data_agent/standards_platform/tests/conftest.py data_agent/standards_platform/tests/test_api_drafting.py data_agent/standards_platform/tests/test_api_citation.py
git commit -m "refactor(std-platform): extract test fixtures into conftest.py"
```

---

## Task 3: Fix #1 — `search_kb` title fallback

**Files:**
- Modify: `data_agent/standards_platform/drafting/citation_sources.py:120-122`
- Test: `data_agent/standards_platform/tests/test_citation_sources.py` (create or extend)

- [ ] **Step 3.1: Append the failing tests**

Both `test_citation_sources.py` and `test_citation_rerank.py` already exist. Append the two new test functions below to the end of `data_agent/standards_platform/tests/test_citation_sources.py`. If `unittest.mock.patch` is not already imported in that file, add `from unittest.mock import patch` near the top; same for `from data_agent.standards_platform.drafting.citation_sources import search_kb` if not already imported.

```python
def test_search_kb_title_from_metadata():
    """search_kb should pull title from chunk['metadata']['title'] (Fix #1)."""
    fake_chunks = [{
        "chunk_id": "c1",
        "content": "some snippet",
        "score": 0.9,
        "doc_id": "doc-x",
        "chunk_index": 0,
        "metadata": {"title": "测绘行业标准 X"},
        "kb_id": 7,
    }]
    with patch("data_agent.knowledge_base.search_kb",
               return_value=fake_chunks):
        out = search_kb("test query")
    assert len(out) == 1
    assert out[0]["extra"]["title"] == "测绘行业标准 X"


def test_search_kb_title_falls_back_to_doc_id():
    """When metadata has no title, fall back to doc_id (Fix #1)."""
    fake_chunks = [{
        "chunk_id": "c2",
        "content": "x",
        "score": 0.5,
        "doc_id": "DOC-FALLBACK",
        "chunk_index": 0,
        "metadata": {},
        "kb_id": 7,
    }]
    with patch("data_agent.knowledge_base.search_kb",
               return_value=fake_chunks):
        out = search_kb("q")
    assert out[0]["extra"]["title"] == "DOC-FALLBACK"
```

- [ ] **Step 3.2: Run the tests to verify they fail**

Run:
```powershell
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_citation_sources.py::test_search_kb_title_from_metadata data_agent/standards_platform/tests/test_citation_sources.py::test_search_kb_title_falls_back_to_doc_id -v
```
Expected: FAIL with `assert None == '测绘行业标准 X'` (current code reads `ch.get("title")` which is missing).

- [ ] **Step 3.3: Apply the fix**

In `data_agent/standards_platform/drafting/citation_sources.py`, find the `search_kb` function (line ~93). Locate the loop that builds candidates (line ~113-122). Replace the `extra` dict construction:

**Before:**
```python
        out.append({
            "kind": "kb_chunk",
            "target_id": str(ch.get("chunk_id") or ""),
            "target_url": None,
            "snippet": (ch.get("content") or "")[:500],
            "base_score": float(ch.get("score") or 0.0),
            "extra": {"kb_id": ch.get("kb_id"),
                      "title": ch.get("title")},
        })
```

**After:**
```python
        title = (
            (ch.get("metadata") or {}).get("title")
            or ch.get("doc_id")
            or "(无标题)"
        )
        out.append({
            "kind": "kb_chunk",
            "target_id": str(ch.get("chunk_id") or ""),
            "target_url": None,
            "snippet": (ch.get("content") or "")[:500],
            "base_score": float(ch.get("score") or 0.0),
            "extra": {"kb_id": ch.get("kb_id"), "title": title},
        })
```

- [ ] **Step 3.4: Run the tests to verify pass**

Run:
```powershell
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_citation_sources.py -v
```
Expected: 2 passed (or more if the file already had tests).

---

## Task 4: Fix #2 — `citation_rerank` final sort

**Files:**
- Modify: `data_agent/standards_platform/drafting/citation_rerank.py:114`
- Test: `data_agent/standards_platform/tests/test_citation_rerank.py` (append)

- [ ] **Step 4.1: Append the failing test**

`test_citation_rerank.py` already exists. Append the test function below to its end. If `unittest.mock.patch` and `rerank` are not already imported, add `from unittest.mock import patch` and `from data_agent.standards_platform.drafting.citation_rerank import rerank` near the top.

```python
def test_rerank_sorts_by_confidence_descending():
    """LLM may return entries in any order; rerank must finalize sort by
    confidence descending (Fix #2)."""
    cands = [
        {"kind": "std_clause", "target_id": "a", "target_url": None,
         "snippet": "a", "base_score": 0.1, "extra": {}},
        {"kind": "std_clause", "target_id": "b", "target_url": None,
         "snippet": "b", "base_score": 0.1, "extra": {}},
        {"kind": "std_clause", "target_id": "c", "target_url": None,
         "snippet": "c", "base_score": 0.1, "extra": {}},
    ]
    # LLM returns entries deliberately out of order
    fake_llm_json = (
        '[{"index": 0, "confidence": 0.5, "reason": "ok"},'
        ' {"index": 1, "confidence": 0.9, "reason": "best"},'
        ' {"index": 2, "confidence": 0.7, "reason": "mid"}]'
    )
    with patch(
        "data_agent.llm_client.generate_text",
        return_value=fake_llm_json,
    ):
        out = rerank("query", cands)
    confidences = [c["extra"]["confidence"] for c in out]
    assert confidences == sorted(confidences, reverse=True), \
        f"output not sorted by confidence desc: {confidences}"
    # Specifically: index=1 (conf 0.9) should be first
    assert out[0]["target_id"] == "b"
```

- [ ] **Step 4.2: Run the test to verify it fails**

Run:
```powershell
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_citation_rerank.py::test_rerank_sorts_by_confidence_descending -v
```
Expected: FAIL — current code returns entries in LLM-reported index order (0, 1, 2 → 0.5, 0.9, 0.7), which is not sorted descending.

- [ ] **Step 4.3: Apply the fix**

In `data_agent/standards_platform/drafting/citation_rerank.py`, find the last line of `rerank` (line 114). Replace:

**Before:**
```python
    return out[:top_k]
```

**After:**
```python
    out.sort(
        key=lambda c: -float(c.get("extra", {}).get("confidence", 0.0) or 0.0)
    )
    return out[:top_k]
```

- [ ] **Step 4.4: Run the test to verify it passes**

Run:
```powershell
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_citation_rerank.py -v
```
Expected: PASS.

- [ ] **Step 4.5: Commit Tasks 3 + 4 together**

```powershell
git add data_agent/standards_platform/drafting/citation_sources.py data_agent/standards_platform/drafting/citation_rerank.py data_agent/standards_platform/tests/test_citation_sources.py data_agent/standards_platform/tests/test_citation_rerank.py
git commit -m "fix(std-platform): search_kb title fallback + citation_rerank confidence-desc sort"
```

---

## Task 5: Fix #3 + #4 + #5 — `citation_insert` handler

**Files:**
- Modify: `data_agent/api/standards_routes.py:317-366` (the `citation_insert` function)
- Test: `data_agent/standards_platform/tests/test_api_citation.py` (extend)

- [ ] **Step 5.1: Write the failing tests**

Append to `data_agent/standards_platform/tests/test_api_citation.py` (after the existing tests). The fixtures `engine` and `fresh_clause` are now provided by conftest from Task 2.

```python
import uuid

from sqlalchemy import text


def _seed_data_element(engine, version_id):
    de_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_data_element (id, document_version_id, "
            "name_zh, code) VALUES (:i, :v, '测试要素', :c)"
        ), {"i": de_id, "v": version_id, "c": f"DE-W3-{de_id[:6]}"})
    return de_id


def _seed_term(engine, version_id):
    t_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_term (id, document_version_id, term_zh, "
            "definition_zh) VALUES (:i, :v, '测试术语', '定义')"
        ), {"i": t_id, "v": version_id})
    return t_id


def test_citation_insert_data_element_target(engine, fresh_clause):
    """Fix #3: target_kind=std_data_element writes target_data_element_id,
    not target_clause_id."""
    cid, _, vid = fresh_clause
    de_id = _seed_data_element(engine, vid)
    client = _client()
    cookies = _auth_user(client, "admin", "admin123")
    resp = client.post("/api/std/citation/insert", json={
        "clause_id": cid,
        "candidate": {
            "kind": "std_data_element",
            "target_id": de_id,
            "snippet": "数据要素引用",
            "extra": {"confidence": 0.85},
        },
    }, cookies=cookies)
    assert resp.status_code == 200, resp.text
    ref_id = resp.json()["ref_id"]
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT target_kind, target_clause_id, target_data_element_id, "
            "target_term_id, inserted_by, verified_by, verification_status "
            "FROM std_reference WHERE id=:i"
        ), {"i": ref_id}).first()
    assert row[0] == "std_data_element"
    assert row[1] is None
    assert str(row[2]) == de_id
    assert row[3] is None
    assert row[4] == "admin"      # inserted_by populated (Fix #5)
    assert row[5] is None         # verified_by NULL (Fix #5)
    assert row[6] == "pending"    # verification_status default (Fix #5)


def test_citation_insert_term_target(engine, fresh_clause):
    """Fix #3: target_kind=std_term writes target_term_id."""
    cid, _, vid = fresh_clause
    t_id = _seed_term(engine, vid)
    client = _client()
    cookies = _auth_user(client, "admin", "admin123")
    resp = client.post("/api/std/citation/insert", json={
        "clause_id": cid,
        "candidate": {
            "kind": "std_term",
            "target_id": t_id,
            "snippet": "术语引用",
            "extra": {"confidence": 0.75},
        },
    }, cookies=cookies)
    assert resp.status_code == 200, resp.text
    ref_id = resp.json()["ref_id"]
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT target_kind, target_term_id, target_clause_id "
            "FROM std_reference WHERE id=:i"
        ), {"i": ref_id}).first()
    assert row[0] == "std_term"
    assert str(row[1]) == t_id
    assert row[2] is None


def test_citation_insert_clause_target_still_works(engine, fresh_clause):
    """Regression: target_kind=std_clause still works post-fix."""
    cid, _, _ = fresh_clause
    client = _client()
    cookies = _auth_user(client, "admin", "admin123")
    resp = client.post("/api/std/citation/insert", json={
        "clause_id": cid,
        "candidate": {
            "kind": "std_clause",
            "target_id": cid,  # self-reference for test purposes
            "snippet": "条款引用",
            "extra": {"confidence": 0.9},
        },
    }, cookies=cookies)
    assert resp.status_code == 200, resp.text


def test_citation_insert_empty_text_rejected(engine, fresh_clause):
    """Fix #4: empty citation_text returns 400."""
    cid, _, _ = fresh_clause
    client = _client()
    cookies = _auth_user(client, "admin", "admin123")
    resp = client.post("/api/std/citation/insert", json={
        "clause_id": cid,
        "candidate": {
            "kind": "std_clause",
            "target_id": cid,
            "snippet": "",
            "extra": {"confidence": 0.5},
        },
    }, cookies=cookies)
    assert resp.status_code == 400
    assert "citation_text" in resp.json().get("error", "")


def test_citation_insert_whitespace_text_rejected(engine, fresh_clause):
    """Fix #4: whitespace-only citation_text returns 400."""
    cid, _, _ = fresh_clause
    client = _client()
    cookies = _auth_user(client, "admin", "admin123")
    resp = client.post("/api/std/citation/insert", json={
        "clause_id": cid,
        "candidate": {
            "kind": "std_clause",
            "target_id": cid,
            "snippet": "   \n\t",
            "extra": {"confidence": 0.5},
        },
    }, cookies=cookies)
    assert resp.status_code == 400


def test_citation_insert_web_snapshot_target(engine, fresh_clause):
    """Regression: web_snapshot target writes target_url."""
    cid, _, _ = fresh_clause
    # Create a snapshot row for FK
    snap_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_web_snapshot (id, url, http_status, "
            "extracted_text) VALUES (:i, 'https://example.com/x', 200, "
            "'snippet')"
        ), {"i": snap_id})
    client = _client()
    cookies = _auth_user(client, "admin", "admin123")
    resp = client.post("/api/std/citation/insert", json={
        "clause_id": cid,
        "candidate": {
            "kind": "web_snapshot",
            "target_id": snap_id,
            "target_url": "https://example.com/x",
            "snippet": "网页引用",
            "extra": {"confidence": 0.6},
        },
    }, cookies=cookies)
    assert resp.status_code == 200, resp.text
    ref_id = resp.json()["ref_id"]
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT target_kind, target_url, snapshot_id "
            "FROM std_reference WHERE id=:i"
        ), {"i": ref_id}).first()
    assert row[0] == "web_snapshot"
    assert row[1] == "https://example.com/x"
    assert str(row[2]) == snap_id
```

- [ ] **Step 5.2: Run the new tests to verify they fail**

Run:
```powershell
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_api_citation.py -v -k "data_element_target or term_target or empty_text or whitespace_text"
```
Expected: FAIL — current `citation_insert` maps `std_data_element` and `std_term` to `target_kind='std_clause'`, doesn't validate empty `citation_text`, and doesn't write `inserted_by`/`verification_status`.

- [ ] **Step 5.3: Apply the fix**

In `data_agent/api/standards_routes.py`, replace the entire `citation_insert` function (lines 317-366) with:

```python
async def citation_insert(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    forbid = _require_editor_or_403(role)
    if forbid: return forbid
    body = await request.json()
    clause_id = body.get("clause_id")
    cand = body.get("candidate") or {}
    if not clause_id or not cand:
        return JSONResponse({"error": "clause_id and candidate required"},
                            status_code=400)

    # Fix #4: validate citation_text early
    citation_text = (cand.get("snippet") or "").strip()[:500]
    if not citation_text:
        return JSONResponse({"error": "citation_text is required"},
                            status_code=400)

    # Fix #3: dispatch target_kind to the correct FK column
    kind = cand.get("kind", "")
    target_clause_id = None
    target_data_element_id = None
    target_term_id = None
    target_document_id = None
    target_url = None
    snapshot_id = None

    if kind == "std_clause":
        target_kind = "std_clause"
        target_clause_id = cand.get("target_id")
    elif kind == "std_data_element":
        target_kind = "std_data_element"
        target_data_element_id = cand.get("target_id")
    elif kind == "std_term":
        target_kind = "std_term"
        target_term_id = cand.get("target_id")
    elif kind == "std_document":
        target_kind = "std_document"
        target_document_id = cand.get("target_id")
    elif kind == "kb_chunk":
        # KB chunk has no FK target — record as internet_search with the
        # source URL if the candidate carried one.
        target_kind = "internet_search"
        target_url = cand.get("target_url")
    elif kind == "web_snapshot":
        target_kind = "web_snapshot"
        snapshot_id = cand.get("target_id")
        target_url = cand.get("target_url")
    elif kind == "external_url":
        target_kind = "external_url"
        target_url = cand.get("target_url")
    else:
        return JSONResponse(
            {"error": f"unsupported candidate kind: {kind}"},
            status_code=400)

    confidence = cand.get("extra", {}).get("confidence")
    eng = get_engine()
    import uuid as _u
    ref_id = str(_u.uuid4())
    # Fix #5: inserted_by/inserted_at instead of verified_by/verified_at;
    # verification_status defaults to 'pending' via DB DEFAULT.
    with eng.begin() as conn:
        conn.execute(text("""
            INSERT INTO std_reference (
                id, source_clause_id, target_kind,
                target_clause_id, target_data_element_id, target_term_id,
                target_document_id, target_url, snapshot_id,
                citation_text, confidence,
                inserted_by, inserted_at)
            VALUES (:i, :sc, :tk,
                    :tc, :tde, :tt,
                    :td, :tu, :sn,
                    :ct, :cf,
                    :u, now())
        """), {
            "i": ref_id, "sc": clause_id, "tk": target_kind,
            "tc": target_clause_id, "tde": target_data_element_id,
            "tt": target_term_id, "td": target_document_id,
            "tu": target_url, "sn": snapshot_id,
            "ct": citation_text, "cf": confidence,
            "u": username,
        })
    return JSONResponse({"ref_id": ref_id, "citation_text": citation_text})
```

- [ ] **Step 5.4: Run the new tests to verify pass**

Run:
```powershell
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_api_citation.py -v
```
Expected: all tests pass (existing + 6 new = ~10 total in this file).

- [ ] **Step 5.5: Commit**

```powershell
git add data_agent/api/standards_routes.py data_agent/standards_platform/tests/test_api_citation.py
git commit -m "fix(std-platform): citation_insert -- correct target FK dispatch + citation_text guard + insert/verify column split"
```

---

## Task 6: Regression gate

- [ ] **Step 6.1: Run full standards_platform test suite**

Run:
```powershell
$env:PYTHONPATH="D:\adk"
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/ -v
```
Expected: ≥ 41 passed (27 prior + ~14 new across the four test files). Zero failures.

- [ ] **Step 6.2: Run full project test suite**

Run:
```powershell
.venv\Scripts\python.exe -m pytest data_agent/ --ignore=data_agent/test_knowledge_agent.py -q
```
Expected: same pass count as before this PR + the new tests, with no new failures. (Pre-existing failures in `test_model_gateway` per `MEMORY.md` are unrelated and acceptable.)

- [ ] **Step 6.3: Run frontend build**

Run:
```powershell
cd frontend
npm run build
cd ..
```
Expected: exit 0, no new TypeScript errors. (Frontend unchanged in this PR; this is a smoke check.)

- [ ] **Step 6.4: Manual browser smoke**

Hand off to user. Repro:
1. Start chainlit (already running per Wave 2 handoff; if not: `.\scripts\restart_chainlit.ps1`).
2. Browser → DataPanel → 数据标准 → 起草 → pick FT.1.
3. 「查找引用」 → search `图斑` → click 插入 on a `std_data_element` hit.
4. SQL verify:
   ```sql
   SELECT target_kind, target_clause_id, target_data_element_id, target_term_id,
          inserted_by, verified_by, verification_status
     FROM std_reference ORDER BY created_at DESC LIMIT 1;
   ```
   Expected: `target_kind='std_data_element'`, `target_data_element_id IS NOT NULL`, all other `target_*` NULL, `inserted_by='admin'`, `verified_by IS NULL`, `verification_status='pending'`.
5. Try inserting with empty `citation_text` (snippet="") → DevTools Network shows 400.
6. Re-run the Wave 2 11-step E2E flow from the handoff — must still pass.

- [ ] **Step 6.5: Push branch**

```powershell
git push origin feat/v12-extensible-platform
```
Expected: 5 new commits land on GitHub on top of `b442876` (migration, conftest, sources+rerank, handler, plus any earlier spec commit `60234f9`).

---

## Done criteria

- 5 commits land on `feat/v12-extensible-platform` covering Tasks 1, 2, 3+4, 5 (the spec doc commit `60234f9` was made earlier).
- `pytest data_agent/standards_platform/` ≥ 41 green.
- `pytest data_agent/ --ignore=data_agent/test_knowledge_agent.py -q` no new regressions.
- Manual browser smoke (Step 6.4) reproduces correctly.
- `MEMORY.md` index entry pointing at this plan + a note that v1 fixes are shipped (handled separately after merge).
