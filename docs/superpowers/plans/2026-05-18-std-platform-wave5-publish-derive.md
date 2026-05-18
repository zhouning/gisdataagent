# Standards Platform Wave 5 — Publish + to_semantic_hint Derive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the parent spec's 「发布」 stage + first derivation strategy `to_semantic_hint` end-to-end. Admin publishes an `approved` version → version flips to `released` + outbox event → worker calls derivation runner → SemanticHintStrategy upserts rows into `agent_semantic_hints` keyed to `std_derived_link`. Released versions become immutable; admin can fork a new draft from any released version.

**Architecture:** New `data_agent/standards_platform/publishing/` (publish_repo + guards + handlers). New `data_agent/standards_platform/derivation/` (strategy_base + strategies/semantic_hint + link_repo + runner + handlers). Reuse existing outbox worker — register `release_published` handler. Migration 079 adds 3 binding columns to `std_data_element` + `std_publish_event` table. Migration 080 adds `std_version_id` + `derived_status` columns to `agent_semantic_hints` (its `std_derived_link_id` column already exists). New ReviewSubTab grew the audit infrastructure last wave; this wave adds PublishSubTab + DeriveSubTab as siblings.

**Tech Stack:** PostgreSQL 16 + PostGIS (UUID, CHECK, PARTIAL UNIQUE), Python 3.13 + SQLAlchemy 2 + Starlette, pytest fixtures (Wave 4 conftest), React 18 + TypeScript + Vite.

**Spec:** `docs/superpowers/specs/2026-05-18-std-platform-wave5-publish-derive-design.md`

**Branch:** `feat/v12-extensible-platform` (continue, current HEAD: `c27478d` after spec commit)

---

## Spec → Actual DB Reality (must read before starting)

The spec was written from blueprint memory. After actual schema inspection (see `git log --grep std_derived_link` for migration history), these realities differ from the spec — implement to **actual DB**, not what spec §3 says:

| Item | Spec assumed | Actual reality | Plan adapts to |
|---|---|---|---|
| `std_derived_link` table | New in Wave 5 | **Already exists** (created in P0) | Migration 079 does **NOT** create this table; just verify schema. |
| `std_derived_link.document_version_id` | column name | Actual column is `source_version_id` (FK to std_document_version) | All Python repo code uses `source_version_id`. |
| `std_derived_link.strategy` | column name | Actual column is `derivation_strategy` | Code uses `derivation_strategy`. |
| `std_derived_link.status` 5 states | active/stale/failed | Actual: `pending/active/stale/overridden/superseded` | Use `active`/`stale`. `failed` rows go in outbox failure table, not link.status. |
| `std_derived_link.target_kind` allowed values | `agent_semantic_hint` | Actual CHECK includes `semantic_hint`/`value_semantic`/`synonym`/`qc_rule`/`defect_code`/`data_model_attribute`/`table_column` | Use `semantic_hint` (singular, no `agent_` prefix). |
| `std_derived_link` UNIQUE constraint | spec §3.2 added PARTIAL UNIQUE | Not in actual table | Add via migration 079 ALTER. |
| `agent_semantic_hints.std_derived_link_id` column | Wave 5 adds | **Already exists** (FK + ON DELETE SET NULL) | Migration 080 does **NOT** add this column. |
| `agent_semantic_hints` schema | spec assumed `(source_id, table_name, column_name, description, data_type, nullable, value_constraint)` | Actual is `(scope_type, scope_ref, hint_kind, hint_text_zh, hint_text_en, severity, trigger_keywords, sample_sql, source_tag, owner_username)` | Field mapping is **completely different** — see Task 5 for actual mapping. |
| `agent_semantic_hints` UNIQUE constraint | not mentioned | Actual: `UNIQUE (scope_ref, hint_kind, hint_text_zh)` | upsert uses `ON CONFLICT (scope_ref, hint_kind, hint_text_zh)`. |
| `std_document_version.status` values | spec §1 used `drafting/reviewing/approved` | Actual CHECK is `draft/review/approved/released/retired` (Wave 4 already adapted) | Continue using `draft/review/approved/released`. |

**Concrete mapping for to_semantic_hint** (Task 5):

| Source: std_data_element | Target: agent_semantic_hints |
|---|---|
| (existence) | `scope_type = 'column'` |
| `bound_source_id` + `bound_table` + `bound_column` | `scope_ref = '{bound_source_id}::{bound_table}.{bound_column}'` |
| (existence) | `hint_kind = 'other'` (avoid specialized kinds) |
| `name_zh` + `datatype` + `obligation` | `hint_text_zh = '标准定义：{name_zh}（类型 {datatype}，{obligation}）'` |
| (existence) | `severity = 'info'` |
| `bound_column` + `name_zh` | `trigger_keywords = JSONB array [bound_column, name_zh]` |
| `version_id` | `source_tag = 'std:v{version_id}'` |
| created link.id | `std_derived_link_id = link.id` |

**Concrete mapping for std_derived_link** (Task 4):

| Field | Value |
|---|---|
| `source_kind` | `'data_element'` |
| `source_id` | `std_data_element.id` |
| `source_version_id` | `version_id` (was `document_version_id` in spec) |
| `target_kind` | `'semantic_hint'` (was `'agent_semantic_hint'` in spec) |
| `target_table` | `'agent_semantic_hints'` |
| `target_id` | `agent_semantic_hints.id::text` (table PK is bigint, cast to text) |
| `derivation_strategy` | `'to_semantic_hint'` |
| `status` | `'active'` initially |

---

## Pre-flight

- [ ] **Step 0.1: Confirm baseline + clean staged state**

Run:
```powershell
cd D:\adk
git status --short data_agent/standards_platform/publishing/ data_agent/standards_platform/derivation/ | head
git log --oneline -3
```
Expected: HEAD is `c27478d` (Wave 5 spec). NO files in `publishing/` or `derivation/` should appear in git status — those packages don't exist yet. Verify staged area is clean per Wave 4 lesson:
```powershell
git status --short | grep "^[AM] "
```
If any files are staged, run `git reset HEAD <file>` to clean.

- [ ] **Step 0.2: Confirm DB has Wave 4 migration 078 applied**

```powershell
.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv('data_agent/.env'); from sqlalchemy import text; from data_agent.db_engine import get_engine; e=get_engine(); rows=e.connect().execute(text(\"SELECT table_name FROM information_schema.tables WHERE table_name IN ('std_review_round','std_review_comment','std_derived_link','agent_semantic_hints') ORDER BY table_name\")).fetchall(); print([r[0] for r in rows])"
```
Expected: `['agent_semantic_hints', 'std_derived_link', 'std_review_comment', 'std_review_round']` — confirms Wave 4 + P0 schema is live.

- [ ] **Step 0.3: Verify std_derived_link existing schema matches plan assumption**

```powershell
.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv('data_agent/.env'); from sqlalchemy import text; from data_agent.db_engine import get_engine; e=get_engine(); rows=e.connect().execute(text(\"SELECT column_name FROM information_schema.columns WHERE table_name='std_derived_link' ORDER BY column_name\")).fetchall(); print([r[0] for r in rows])"
```
Expected list contains: `derivation_strategy`, `source_id`, `source_kind`, `source_version_id`, `status`, `target_id`, `target_kind`, `target_table`. If different, STOP — schema diverged further; reconfirm field names.

---

## Task 1: Migration 079 — std_data_element binding + std_publish_event

**Files:**
- Create: `data_agent/migrations/079_std_publish_derivation.sql`
- Create: `data_agent/standards_platform/tests/test_migration_079.py`

- [ ] **Step 1.1: Write the migration**

Create `data_agent/migrations/079_std_publish_derivation.sql`:

```sql
-- 079: Wave 5 — std_data_element binding columns + std_publish_event table
--      + tighten std_derived_link with PARTIAL UNIQUE (active per target).

-- (a) std_data_element binding columns ----------------------------------
ALTER TABLE std_data_element
    ADD COLUMN IF NOT EXISTS bound_source_id  UUID REFERENCES sources(id),
    ADD COLUMN IF NOT EXISTS bound_table      TEXT,
    ADD COLUMN IF NOT EXISTS bound_column     TEXT;

ALTER TABLE std_data_element
    DROP CONSTRAINT IF EXISTS std_data_element_binding_consistency_check;
ALTER TABLE std_data_element
    ADD CONSTRAINT std_data_element_binding_consistency_check
        CHECK ((bound_source_id IS NULL AND bound_table IS NULL AND bound_column IS NULL)
            OR (bound_source_id IS NOT NULL AND bound_table IS NOT NULL AND bound_column IS NOT NULL));

CREATE INDEX IF NOT EXISTS idx_std_data_element_bound_source
    ON std_data_element(bound_source_id, bound_table, bound_column)
    WHERE bound_source_id IS NOT NULL;

-- (b) std_publish_event table -------------------------------------------
CREATE TABLE IF NOT EXISTS std_publish_event (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id UUID NOT NULL REFERENCES std_document_version(id) ON DELETE CASCADE,
    event_type          TEXT NOT NULL,
    actor_user_id       TEXT NOT NULL,
    occurred_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes               TEXT,
    CONSTRAINT std_publish_event_type_check
        CHECK (event_type IN ('published','forked'))
);

CREATE INDEX IF NOT EXISTS idx_std_publish_event_version
    ON std_publish_event(document_version_id, occurred_at DESC);

-- (c) std_derived_link PARTIAL UNIQUE on active rows --------------------
-- Per spec §7 invariant 1: same (strategy, target) only one active row.
CREATE UNIQUE INDEX IF NOT EXISTS idx_std_derived_link_unique_active
    ON std_derived_link(derivation_strategy, target_kind, target_id)
    WHERE status = 'active';
```

- [ ] **Step 1.2: Apply locally**

```powershell
$env:PYTHONPATH="D:\adk"
.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv('data_agent/.env'); from sqlalchemy import text; from data_agent.db_engine import get_engine; sql=open('data_agent/migrations/079_std_publish_derivation.sql','r',encoding='utf-8').read(); e=get_engine(); conn=e.connect(); conn.execute(text(sql)); conn.commit(); print('OK')"
```
Expected: `OK`.

- [ ] **Step 1.3: Verify columns exist**

```powershell
.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv('data_agent/.env'); from sqlalchemy import text; from data_agent.db_engine import get_engine; e=get_engine(); cols={t: [r[0] for r in e.connect().execute(text(f\"SELECT column_name FROM information_schema.columns WHERE table_name='{t}' ORDER BY column_name\")).fetchall()] for t in ('std_data_element','std_publish_event')}; print(cols)"
```
Expected: `std_data_element` includes `bound_column`, `bound_source_id`, `bound_table`. `std_publish_event` includes all 6 columns.

- [ ] **Step 1.4: Write migration test**

Create `data_agent/standards_platform/tests/test_migration_079.py`:

```python
"""Schema-level checks for migration 079."""
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


def _seed_data_element(eng):
    """Returns (doc_id, ver_id, clause_id, element_id)."""
    doc_id = str(uuid.uuid4())
    ver_id = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    eid = str(uuid.uuid4())
    with eng.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_document (id, doc_code, title, source_type, "
            "status, owner_user_id) VALUES (:i, :c, 't', 'draft', "
            "'ingested', 'admin')"
        ), {"i": doc_id, "c": f"T-079-{doc_id[:6]}"})
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
        conn.execute(text(
            "INSERT INTO std_data_element (id, document_version_id, code, "
            "name_zh, datatype, obligation) VALUES (:i, :v, 'TEST', '测试', "
            "'string', 'optional')"
        ), {"i": eid, "v": ver_id})
    return doc_id, ver_id, cid, eid


def test_binding_columns_exist():
    eng = _get_engine_or_skip()
    with eng.connect() as c:
        cols = {r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='std_data_element'"
        )).fetchall()}
    assert {"bound_source_id", "bound_table", "bound_column"}.issubset(cols)


def test_binding_check_rejects_partial():
    """All-or-none constraint: setting only bound_table must fail."""
    eng = _get_engine_or_skip()
    doc_id, ver_id, cid, eid = _seed_data_element(eng)
    try:
        with pytest.raises(IntegrityError):
            with eng.begin() as conn:
                conn.execute(text(
                    "UPDATE std_data_element SET bound_table='x' WHERE id=:i"
                ), {"i": eid})
    finally:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                         {"i": doc_id})


def test_binding_accepts_all_three():
    """All three set: must succeed."""
    eng = _get_engine_or_skip()
    doc_id, ver_id, cid, eid = _seed_data_element(eng)
    try:
        # Find any source_id; if none exists, skip
        with eng.connect() as c:
            row = c.execute(text("SELECT id FROM sources LIMIT 1")).first()
        if row is None:
            pytest.skip("no sources rows to bind")
        sid = str(row[0])
        with eng.begin() as conn:
            conn.execute(text(
                "UPDATE std_data_element SET bound_source_id=:s, "
                "bound_table='t', bound_column='c' WHERE id=:i"
            ), {"s": sid, "i": eid})
    finally:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                         {"i": doc_id})


def test_publish_event_table_exists():
    eng = _get_engine_or_skip()
    with eng.connect() as c:
        cols = {r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='std_publish_event'"
        )).fetchall()}
    assert {"id", "document_version_id", "event_type", "actor_user_id",
            "occurred_at", "notes"}.issubset(cols)


def test_publish_event_type_check_rejects_invalid():
    eng = _get_engine_or_skip()
    doc_id, ver_id, cid, eid = _seed_data_element(eng)
    try:
        with pytest.raises(IntegrityError):
            with eng.begin() as conn:
                conn.execute(text(
                    "INSERT INTO std_publish_event (id, document_version_id, "
                    "event_type, actor_user_id) VALUES "
                    "(:i, :v, 'bogus', 'admin')"
                ), {"i": str(uuid.uuid4()), "v": ver_id})
    finally:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                         {"i": doc_id})


def test_derived_link_partial_unique_active():
    """Two 'active' links with same (strategy, target_kind, target_id) must conflict."""
    eng = _get_engine_or_skip()
    doc_id, ver_id, cid, eid = _seed_data_element(eng)
    l1 = str(uuid.uuid4())
    try:
        with eng.begin() as conn:
            conn.execute(text(
                "INSERT INTO std_derived_link (id, source_kind, source_id, "
                "source_version_id, target_kind, target_table, target_id, "
                "derivation_strategy, status) VALUES "
                "(:i, 'data_element', :s, :v, 'semantic_hint', "
                "'agent_semantic_hints', 'TG-1', 'to_semantic_hint', 'active')"
            ), {"i": l1, "s": eid, "v": ver_id})
        with pytest.raises(IntegrityError):
            with eng.begin() as conn:
                conn.execute(text(
                    "INSERT INTO std_derived_link (id, source_kind, source_id, "
                    "source_version_id, target_kind, target_table, target_id, "
                    "derivation_strategy, status) VALUES "
                    "(:i, 'data_element', :s, :v, 'semantic_hint', "
                    "'agent_semantic_hints', 'TG-1', 'to_semantic_hint', 'active')"
                ), {"i": str(uuid.uuid4()), "s": eid, "v": ver_id})
    finally:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM std_derived_link WHERE id=:i"),
                         {"i": l1})
            conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                         {"i": doc_id})


def test_derived_link_stale_allows_duplicate_target():
    """Multiple stale rows for same target should be permitted."""
    eng = _get_engine_or_skip()
    doc_id, ver_id, cid, eid = _seed_data_element(eng)
    l1, l2 = str(uuid.uuid4()), str(uuid.uuid4())
    try:
        with eng.begin() as conn:
            for lid in (l1, l2):
                conn.execute(text(
                    "INSERT INTO std_derived_link (id, source_kind, source_id, "
                    "source_version_id, target_kind, target_table, target_id, "
                    "derivation_strategy, status) VALUES "
                    "(:i, 'data_element', :s, :v, 'semantic_hint', "
                    "'agent_semantic_hints', 'TG-2', 'to_semantic_hint', 'stale')"
                ), {"i": lid, "s": eid, "v": ver_id})
        # No IntegrityError = pass
    finally:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM std_derived_link WHERE id IN (:a,:b)"),
                         {"a": l1, "b": l2})
            conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                         {"i": doc_id})
```

- [ ] **Step 1.5: Run migration tests**

```powershell
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_migration_079.py -v
```
Expected: 6 passed (test_binding_accepts_all_three may skip if no sources rows).

- [ ] **Step 1.6: Verify staged area + commit**

```powershell
git status --short | grep "^[AM] "  # should be empty
git add data_agent/migrations/079_std_publish_derivation.sql data_agent/standards_platform/tests/test_migration_079.py
git commit -m "feat(std-platform): migration 079 -- data_element binding + publish_event + active link unique"
```

---

## Task 2: Migration 080 — agent_semantic_hints derived columns

**Files:**
- Create: `data_agent/migrations/080_agent_semantic_hints_derived.sql`
- Create: `data_agent/standards_platform/tests/test_migration_080.py`

- [ ] **Step 2.1: Write migration**

Create `data_agent/migrations/080_agent_semantic_hints_derived.sql`:

```sql
-- 080: Wave 5 — agent_semantic_hints derived metadata columns.
--      std_derived_link_id already exists (from P0); add std_version_id +
--      derived_status only.

ALTER TABLE agent_semantic_hints
    ADD COLUMN IF NOT EXISTS std_version_id   UUID,
    ADD COLUMN IF NOT EXISTS derived_status   TEXT;

ALTER TABLE agent_semantic_hints
    DROP CONSTRAINT IF EXISTS agent_semantic_hints_derived_status_check;
ALTER TABLE agent_semantic_hints
    ADD CONSTRAINT agent_semantic_hints_derived_status_check
        CHECK (derived_status IS NULL OR derived_status IN ('active','stale'));

CREATE INDEX IF NOT EXISTS idx_agent_semantic_hints_derived
    ON agent_semantic_hints(std_version_id, derived_status)
    WHERE std_derived_link_id IS NOT NULL;
```

- [ ] **Step 2.2: Apply migration**

```powershell
.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv('data_agent/.env'); from sqlalchemy import text; from data_agent.db_engine import get_engine; sql=open('data_agent/migrations/080_agent_semantic_hints_derived.sql','r',encoding='utf-8').read(); e=get_engine(); conn=e.connect(); conn.execute(text(sql)); conn.commit(); print('OK')"
```
Expected: `OK`.

- [ ] **Step 2.3: Write migration test**

Create `data_agent/standards_platform/tests/test_migration_080.py`:

```python
"""Schema-level checks for migration 080."""
from __future__ import annotations

import os

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


def test_derived_columns_exist():
    eng = _get_engine_or_skip()
    with eng.connect() as c:
        cols = {r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='agent_semantic_hints'"
        )).fetchall()}
    assert "std_derived_link_id" in cols   # pre-existing from P0
    assert "std_version_id" in cols
    assert "derived_status" in cols


def test_derived_status_check_rejects_invalid():
    """derived_status must be NULL/'active'/'stale'."""
    eng = _get_engine_or_skip()
    with pytest.raises(IntegrityError):
        with eng.begin() as conn:
            conn.execute(text(
                "INSERT INTO agent_semantic_hints "
                "(scope_type, scope_ref, hint_kind, hint_text_zh, "
                " severity, trigger_keywords, derived_status) VALUES "
                "('column', 'X::y.z', 'other', 'h', 'info', '[]', 'bogus')"
            ))
```

- [ ] **Step 2.4: Run tests + commit**

```powershell
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_migration_080.py -v
```
Expected: 2 passed.

```powershell
git status --short | grep "^[AM] "  # should be empty
git add data_agent/migrations/080_agent_semantic_hints_derived.sql data_agent/standards_platform/tests/test_migration_080.py
git commit -m "feat(std-platform): migration 080 -- agent_semantic_hints std_version_id + derived_status"
```

---

## Task 3: publishing package — publish_repo + guards

**Files:**
- Create: `data_agent/standards_platform/publishing/__init__.py`
- Create: `data_agent/standards_platform/publishing/publish_repo.py`
- Create: `data_agent/standards_platform/publishing/guards.py`
- Create: `data_agent/standards_platform/tests/test_publish_repo.py`

- [ ] **Step 3.1: Create package init**

Create `data_agent/standards_platform/publishing/__init__.py`:

```python
"""Publishing stage — version status machine + fork + guards.

Wave 5 of standards platform. See spec
docs/superpowers/specs/2026-05-18-std-platform-wave5-publish-derive-design.md
"""
```

- [ ] **Step 3.2: Implement publish_repo.publish_version**

Create `data_agent/standards_platform/publishing/publish_repo.py`:

```python
"""CRUD on std_publish_event + version status machine + fork."""
from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import text

from ...db_engine import get_engine
from ..outbox import enqueue as _outbox_enqueue


def publish_version(*, version_id: str, by_user: str) -> dict:
    """Atomically: status approved->released + publish_event + outbox enqueue.

    Wave 5 picks event_type='version_released' (already in outbox EVENT_TYPES
    + std_outbox CHECK; no migration needed).

    Returns: {version_id, status, released_at, outbox_event_id}
    Raises:
      LookupError if version not found
      ValueError if status != 'approved' or already released
    """
    eng = get_engine()
    with eng.begin() as conn:
        row = conn.execute(text(
            "SELECT status FROM std_document_version WHERE id=:i FOR UPDATE"
        ), {"i": version_id}).first()
        if row is None:
            raise LookupError("version not found")
        if row[0] == 'released':
            raise ValueError("version already released")
        if row[0] != 'approved':
            raise ValueError(f"version status must be approved (got {row[0]})")
        conn.execute(text(
            "UPDATE std_document_version SET status='released', "
            "released_at=now(), updated_at=now(), updated_by=:u "
            "WHERE id=:i"
        ), {"u": by_user, "i": version_id})
        conn.execute(text(
            "INSERT INTO std_publish_event (document_version_id, event_type, "
            "actor_user_id) VALUES (:v, 'published', :u)"
        ), {"v": version_id, "u": by_user})
        released_at = conn.execute(text(
            "SELECT released_at FROM std_document_version WHERE id=:i"
        ), {"i": version_id}).scalar()
    # Enqueue OUTSIDE the publish transaction (separate txn in outbox.enqueue);
    # the std_outbox status default is 'pending' per migration 074.
    outbox_id = _outbox_enqueue("version_released", {"version_id": version_id})
    return {"version_id": version_id, "status": "released",
            "released_at": released_at.isoformat() if released_at else None,
            "outbox_event_id": outbox_id}
```

- [ ] **Step 3.3: Implement publish_repo.fork_version**

```python
def fork_version(*, source_version_id: str, new_label: str,
                 by_user: str) -> str:
    """Copy clause/data_element/term/value_domain/reference rows from
    a released source version into a new draft version.

    new_label must match v\\d+\\.\\d+(\\.\\d+)?  (e.g. 'v1.1', 'v2.0').
    Raises LookupError / ValueError on validation failure.

    Implementation strategy:
      1. SELECT FOR UPDATE source row, validate status='released'
      2. Validate (document_id, new_label) UNIQUE
      3. Parse semver from new_label
      4. INSERT std_document_version (status='draft', supersedes=source)
      5. Loop std_clause rows from source → INSERT new (gen new id) +
         build dict-based clause_id_map (Python-level, not TEMP TABLE,
         to avoid PostgreSQL TEMP TABLE quirks observed in earlier wave fix)
      6. Loop std_value_domain rows similarly → vd_id_map
      7. Loop std_data_element rows → INSERT preserving binding triple,
         remapping defined_by_clause_id via clause_id_map and
         value_domain_id via vd_id_map
      8. Loop std_term rows → INSERT (no clause FK)
      9. Loop std_reference rows:
         - source_clause_id always remapped via clause_id_map
         - target_clause_id: if old_id in clause_id_map → remap,
           else → keep (cross-doc reference)
         - target_data_element_id / target_term_id: keep as-is (Wave 6)
      10. INSERT std_publish_event (event_type='forked')
    Returns new_version_id.
    """
    # Implementation: dispatch subagent with this signature + spec §6.2 flow
    # + actual schemas (use Read on std_clause / std_data_element / std_term /
    # std_value_domain / std_reference to get column lists at impl time).
```

- [ ] **Step 3.4: Implement guards.py**

Create `data_agent/standards_platform/publishing/guards.py`:

```python
"""Version state guards used by drafting + publishing handlers."""
from sqlalchemy import text
from starlette.responses import JSONResponse
from ...db_engine import get_engine


def is_version_released(version_id: str) -> bool: ...

def block_if_not_drafting(version_id: str) -> JSONResponse | None:
    """Return 409 JSONResponse if version status != 'draft'.

    Replaces Wave 4's _block_if_reviewing. Carries clearer messaging:
      review     → 'version under review, drafting blocked'
      approved   → 'version status approved, drafting blocked'
      released   → 'version released, immutable'
      retired    → 'version status retired, drafting blocked'
      draft      → None (allow)

    Returns None for non-existent versions (downstream handler 404s).
    """
```

- [ ] **Step 3.5: Implement other publish_repo functions**

```python
def list_published_versions(*, document_id: Optional[str] = None) -> list[dict]
def get_publish_timeline(*, version_id: str) -> list[dict]
```
List released versions (filtered by document_id) and the std_publish_event timeline for a single version, both ORDER BY occurred_at DESC.

- [ ] **Step 3.6: Write publish_repo tests**

Create `data_agent/standards_platform/tests/test_publish_repo.py` with 8 tests:
1. `publish_version` happy → status=released + std_publish_event row + std_outbox 'version_released' row
2. `publish_version` from non-approved → ValueError
3. `publish_version` already released → ValueError
4. `fork_version` happy → new draft version + clauses copied + reference FK remapped
5. `fork_version` from non-released source → ValueError
6. `fork_version` duplicate (doc_id, label) → ValueError
7. `fork_version` invalid label format → ValueError
8. `list_published_versions` filter by document_id

Use Wave 4 conftest fixtures (`engine`, `fresh_clause`). Add new fixture `fresh_approved_version` (fresh_clause + UPDATE status='approved').

- [ ] **Step 3.7: Run + commit**

```powershell
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_publish_repo.py -v
git status --short | grep "^[AM] "  # should be empty
git add data_agent/standards_platform/publishing/__init__.py data_agent/standards_platform/publishing/publish_repo.py data_agent/standards_platform/publishing/guards.py data_agent/standards_platform/tests/test_publish_repo.py
git commit -m "feat(std-platform): publishing repo + guards (publish/fork/timeline)"
```

---

## Task 4: derivation package — strategy_base + link_repo

**Files:**
- Create: `data_agent/standards_platform/derivation/__init__.py`
- Create: `data_agent/standards_platform/derivation/strategy_base.py`
- Create: `data_agent/standards_platform/derivation/link_repo.py`
- Create: `data_agent/standards_platform/tests/test_link_repo.py`

- [ ] **Step 4.1: strategy_base.py — DerivationStrategy ABC + dataclasses**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

@dataclass
class DerivationLink:
    source_kind: str
    source_id: str
    target_kind: str
    target_id: str
    notes: dict | None = None

@dataclass
class DerivationResult:
    strategy: str
    new_links: list[DerivationLink]
    staled_links: list[str]
    failed: list[tuple[str, str]] = field(default_factory=list)

class DerivationStrategy(ABC):
    name: str
    description: str = ""
    @abstractmethod
    def run(self, *, version_id: str, by_user: str) -> DerivationResult: ...
```

- [ ] **Step 4.2: link_repo.py — std_derived_link CRUD**

Use **actual** column names: `source_version_id`, `derivation_strategy`, target_kind ∈ semantic_hint set, status ∈ pending/active/stale/overridden/superseded.

```python
def create_link(*, version_id, source_kind, source_id, derivation_strategy,
                target_kind, target_table, target_id, by_user, notes=None) -> str
def list_links_by_version(*, version_id, derivation_strategy=None, status=None) -> list[dict]
def list_active_links_for_doc(*, document_id, derivation_strategy) -> list[dict]
    # JOIN std_document_version ON source_version_id to filter by document_id
def mark_stale(*, link_ids: list[str]) -> int
def get_link(link_id) -> dict | None
```

- [ ] **Step 4.3: Tests (5)**

`test_link_repo.py`:
1. create_link / get_link round-trip
2. list_links_by_version filter by strategy + status
3. list_active_links_for_doc spans multiple versions of same doc
4. mark_stale bulk update
5. PARTIAL UNIQUE: create active twice with same target → IntegrityError

- [ ] **Step 4.4: Commit**

```powershell
git add data_agent/standards_platform/derivation/__init__.py data_agent/standards_platform/derivation/strategy_base.py data_agent/standards_platform/derivation/link_repo.py data_agent/standards_platform/tests/test_link_repo.py
git commit -m "feat(std-platform): derivation strategy_base + link_repo"
```

---

## Task 5: SemanticHintStrategy

**Files:**
- Create: `data_agent/standards_platform/derivation/strategies/__init__.py`
- Create: `data_agent/standards_platform/derivation/strategies/semantic_hint.py`
- Create: `data_agent/standards_platform/tests/test_semantic_hint_strategy.py`

- [ ] **Step 5.1: Implement strategy**

Per "Spec → Actual DB Reality" mapping table at top of plan:

```python
class SemanticHintStrategy(DerivationStrategy):
    name = "to_semantic_hint"
    description = "派生标准数据元到 agent_semantic_hints 表 (column-scope hint)"

    def run(self, *, version_id, by_user):
        # 1. 读 bound data_element
        # SELECT id, code, name_zh, datatype, obligation,
        #        bound_source_id, bound_table, bound_column
        # FROM std_data_element WHERE document_version_id=:v
        #   AND bound_source_id IS NOT NULL

        # 2. 找 doc 的 prev active links (同 derivation_strategy):
        # JOIN std_document_version ON ... WHERE document_id = (this doc)

        # 3. 对每条 element: 构造 (scope_ref, hint_kind='other', hint_text_zh)
        #    → upsert agent_semantic_hints via ON CONFLICT (scope_ref, hint_kind, hint_text_zh)
        #      DO UPDATE SET trigger_keywords=..., source_tag=..., updated_at=now(),
        #                    std_derived_link_id=:new_link_id, std_version_id=:v,
        #                    derived_status='active'
        #      RETURNING id
        #    → if existing hint had std_derived_link_id IS NULL: SKIP (手工行不动)
        #      Detection: SELECT std_derived_link_id BEFORE upsert; if NULL → continue.
        #    → INSERT std_derived_link (target_id = hint.id::text)

        # 4. mark stale: prev_active links not in new target_ids
        #    UPDATE std_derived_link SET status='stale' WHERE id IN (...)
        #    UPDATE agent_semantic_hints SET derived_status='stale'
        #      WHERE std_derived_link_id IN (...)

        # All in one transaction.
```

Field mapping (from plan top "Spec → Actual DB Reality"):
- `scope_type='column'`
- `scope_ref = f"{bound_source_id}::{bound_table}.{bound_column}"`
- `hint_kind='other'`
- `hint_text_zh = f"标准定义：{name_zh}（类型 {datatype}，{obligation}）"`
- `severity='info'`
- `trigger_keywords=json.dumps([bound_column, name_zh])`
- `source_tag=f"std:v{version_id}"`

- [ ] **Step 5.2: Tests (8)**

1. happy: N bound elements → N hints + N links
2. skip unbound: bound_source_id IS NULL element ignored
3. preserve manual: existing hint with std_derived_link_id IS NULL not touched
4. upsert: same binding re-derive → UPDATE hint (not duplicate)
5. stale flow: v1 active, v2 deletes element → v1 link.status='stale' + hint.derived_status='stale'
6. value_constraint mapping: trigger_keywords includes bound_column + name_zh
7. error isolation: one bad element (FK violation on bound_source_id) → result.failed +1, others continue
8. UNIQUE (scope_ref, hint_kind, hint_text_zh) handled via ON CONFLICT

- [ ] **Step 5.3: Commit**

---

## Task 6: derivation runner + outbox handler integration

**Files:**
- Create: `data_agent/standards_platform/derivation/runner.py`
- Modify: `data_agent/standards_platform/handlers.py` (add elif branches)
- Create: `data_agent/standards_platform/tests/test_derivation_runner.py`

- [ ] **Step 6.1: runner.py**

```python
from .strategies.semantic_hint import SemanticHintStrategy

_REGISTRY: dict[str, "DerivationStrategy | None"] = {
    'to_semantic_hint': SemanticHintStrategy(),
    'to_synonym': None, 'to_value_semantics': None,
    'to_qc_rule': None, 'to_defect_code': None, 'to_data_model': None,
}

def get_strategy_status() -> list[dict]: ...
def dispatch(*, version_id, by_user='system', strategies=None) -> dict:
    # Per spec §6.4 乐观发布: catch each strategy individually.
    # Return {name: {ok: bool, new, staled, failed, failures (10 first), error?}}
```

- [ ] **Step 6.2: Wire into outbox dispatch**

Edit `data_agent/standards_platform/handlers.py:dispatch()` — add `elif et == "version_released"` branch calling `derivation.runner.dispatch(version_id=p["version_id"])`. Also add `elif et == "derivation_requested"` for direct strategy invocation (from rerun handler when async needed).

- [ ] **Step 6.3: Tests (4)**

1. dispatch runs all active strategies
2. dispatch with strategies=[name] filters
3. one strategy raises → result['ok']=false but other strategies still run (use mock failing strategy)
4. handlers.dispatch routes 'version_released' → runner correctly

- [ ] **Step 6.4: Commit**

---

## Task 7: Publishing handlers + 4 endpoints

**Files:**
- Modify: `data_agent/api/standards_routes.py` (add 4 routes + handlers)
- Test: `data_agent/standards_platform/tests/test_publish_handler.py`

- [ ] **Step 7.1: Add handlers**

```python
async def publish_version_handler(request)        # POST /api/std/publish/versions/{vid}
async def publish_fork_handler(request)           # POST /api/std/publish/fork
async def publish_list_versions_handler(request)  # GET  /api/std/publish/versions
async def publish_timeline_handler(request)       # GET  /api/std/publish/timeline/{vid}
```

All admin-write use `_require_admin_or_403`. Bodies: `{}` for publish, `{source_version_id, new_label}` for fork. Returns per spec §5.1.

- [ ] **Step 7.2: Register routes** (after Wave 4 review routes block):

```python
Route("/api/std/publish/versions/{version_id}", endpoint=publish_version_handler, methods=["POST"]),
Route("/api/std/publish/fork", endpoint=publish_fork_handler, methods=["POST"]),
Route("/api/std/publish/versions", endpoint=publish_list_versions_handler, methods=["GET"]),
Route("/api/std/publish/timeline/{version_id}", endpoint=publish_timeline_handler, methods=["GET"]),
```

- [ ] **Step 7.3: Tests (7)**

publish happy / non-approved-409 / non-admin-403 / fork happy / fork non-released-409 / fork dup-label-409 / list versions filter

- [ ] **Step 7.4: Commit**

---

## Task 8: Derivation handlers + 4 endpoints

**Files:**
- Modify: `data_agent/api/standards_routes.py`
- Test: `data_agent/standards_platform/tests/test_derive_handler.py`

- [ ] **Step 8.1-3: Handlers + routes + 6 tests**

```python
async def derive_strategies_handler(request)   # GET  /api/std/derive/strategies
async def derive_links_handler(request)         # GET  /api/std/derive/links
async def derive_rerun_handler(request)         # POST /api/std/derive/rerun/{vid}  admin
async def derive_status_handler(request)        # GET  /api/std/derive/status/{vid}
```

derive_rerun synchronously calls `runner.dispatch(version_id, by_user=username)` (NOT outbox enqueue — user wants immediate result).

Tests: list strategies (active + coming_soon mix), list_links filter combinations, rerun happy, rerun non-released-409, rerun non-admin-403, status aggregation by strategy.

- [ ] **Step 8.4: Commit**

---

## Task 9: Drafting gate extension — _block_if_not_drafting

**Files:**
- Modify: `data_agent/api/standards_routes.py` (replace Wave 4 _block_if_reviewing)
- Test: extend `data_agent/standards_platform/tests/test_api_drafting.py`

- [ ] **Step 9.1: Replace helper**

Find Wave 4's `_block_if_reviewing` in standards_routes.py. Replace with `_block_if_not_drafting` from `publishing.guards`. Update all callers (lock_clause, save_clause_route).

- [ ] **Step 9.2: Add gate to citation_insert + lock_break**

These two endpoints don't currently gate version status. Add `_block_if_not_drafting(version_id)` after auth check. lock_break must check **even for admin** (released is immutable).

- [ ] **Step 9.3: Tests (+3)**

Append to test_api_drafting.py:
1. PUT /clauses on released → 409 'version released, immutable'
2. POST /citation/insert on released → 409
3. POST /clauses/{cid}/lock/break on released by admin → 409

- [ ] **Step 9.4: Commit**

---

## Task 10: Frontend — SDK + PublishSubTab + DeriveSubTab + StandardsTab wiring

**Files:**
- Modify: `frontend/src/components/datapanel/standards/standardsApi.ts` (append SDK)
- Create: `frontend/src/components/datapanel/standards/PublishSubTab.tsx`
- Create: `frontend/src/components/datapanel/standards/publish/{VersionPickerPane, PublishActionPane, PublishTimeline, ForkDialog}.tsx`
- Create: `frontend/src/components/datapanel/standards/DeriveSubTab.tsx`
- Create: `frontend/src/components/datapanel/standards/derive/{StrategyPane, LinkTable, DeriveStatusSummary, RerunButton}.tsx`
- Modify: `frontend/src/components/datapanel/StandardsTab.tsx` (enable publish + derive sub-tabs, mount components, share selectedVersionId state)

- [ ] **Step 10.1: SDK types + 8 functions**

Append to standardsApi.ts: PublishedVersion / PublishEvent / Strategy / DerivedLink / DerivationStatus types + 8 fetch wrappers (publishVersion, forkVersion, listPublishedVersions, getPublishTimeline, listDeriveStrategies, listDeriveLinks, rerunDerivation, getDeriveStatus).

- [ ] **Step 10.2: PublishSubTab + 4 sub-components**

3-column grid: VersionPickerPane (20%) | PublishActionPane (50%) | PublishTimeline (30%). Per spec §5.2 mockup.

- [ ] **Step 10.3: DeriveSubTab + 4 sub-components**

3-column grid: StrategyPane (20%) | LinkTable (60%) | DeriveStatusSummary+RerunButton (20%). Per spec §5.3.

- [ ] **Step 10.4: StandardsTab wiring**

Replace Wave 4's `enabled = {ingest, analyze, draft, review}` with `{ingest, analyze, draft, review, publish, derive}`. Mount PublishSubTab + DeriveSubTab; share `selectedVersionId` state across them.

- [ ] **Step 10.5: Verify build**

```powershell
cd frontend; npm run build
```
Expected: exit 0.

- [ ] **Step 10.6: Commit**

---

## Task 11: Regression gate + push

- [ ] **Step 11.1: Run full standards_platform suite**

```powershell
$env:PYTHONPATH="D:\adk"
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/ --tb=short
```
Expected: ≥ 200 passed (151 from Wave 4 baseline + ~50 new). One pre-existing failure (`test_handlers.py::test_extract_requested_routes_to_extract_then_enqueues_structure`) remains — unrelated.

- [ ] **Step 11.2: npm build**

- [ ] **Step 11.3: Manual browser smoke (user)**

1. Login admin/admin123 → 数据标准 tab
2. Use a version that has reached 'approved' (走 Wave 4 round close-approved) — or manually UPDATE std_document_version SET status='approved' for testing
3. 发布 sub-tab → 选 version → [发布]
4. Verify std_document_version.status='released' + std_publish_event row + std_outbox 'version_released' row + agent_semantic_hints rows with std_derived_link_id NOT NULL
5. 派生 sub-tab → 选 released version → 看 LinkTable 里有 active 行
6. 起草 sub-tab → 试编辑 → expect 409 banner
7. 发布 sub-tab → [Fork v1.1] → 看新 draft version 出现，内容复制完整
8. SQL verify:
```sql
SELECT v.status, e.event_type, e.actor_user_id
  FROM std_document_version v
  LEFT JOIN std_publish_event e ON e.document_version_id = v.id
 WHERE v.status = 'released' OR v.supersedes_version_id IS NOT NULL
 ORDER BY v.updated_at DESC LIMIT 5;
```

- [ ] **Step 11.4: Push**

```powershell
git push origin feat/v12-extensible-platform
```

---

## Done criteria

- 9-10 commits land on `feat/v12-extensible-platform` (after the spec commit `c27478d`)
- `pytest data_agent/standards_platform/` ≥ 200 green
- npm build OK
- Manual browser smoke succeeds
- Memory handoff entry written after merge / push

---

## Notes for implementer

This plan is **expanded fully for Tasks 1-3.2** with ready-to-paste code. Tasks 3.3+ are written as **structured task summaries** with file paths, key signatures, test counts, and explicit commit messages — but not fully expanded. This is intentional: the schemas are now well-documented (see "Spec → Actual DB Reality" at the plan top), and an implementer or fresh subagent can read each task summary plus the actual DB columns to fill in implementation details with minimal additional research.

**Recommended impl mode**: subagent-driven. Dispatch a fresh subagent per task with:
1. The plan file
2. The spec file
3. The "Spec → Actual DB Reality" section as required reading
4. Wave 4 conftest fixtures + test_api_standards helpers as references

Each subagent should write the test, run it red, write impl, run it green, then commit. Two-stage review (spec compliance + code quality) per Wave 4 pattern.

**Pre-write verification per task**: before each task, the implementer should run a small Python script to inspect actual schema if uncertain (see Wave 4 lesson: fresh_clause uses 'draft' not 'drafting'). The "Spec → Actual DB Reality" table at top covers known divergences.
