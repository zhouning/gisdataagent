# Standards Platform Wave 4 — Review Sub-Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the parent spec's 「审定」 stage as a new ReviewSubTab — two-tier review (per-reference audit + document-level single-reviewer round) with a `standard_reviewer` role, two new tables, 7 REST endpoints, gating on round closure, and a 5-component frontend.

**Architecture:** New `data_agent/standards_platform/review/` module (round_repo + comment_repo + gating + handlers). Migration 078 adds `std_review_round` and `std_review_comment` tables with strict CHECKs and a UNIQUE-while-open index. The role string flows through existing infra (`standards_routes.py:_REVIEWER_ROLES` already includes `standard_reviewer`). New ReviewSubTab on the standards tab uses 4-column layout and 5 sub-components, threading `userRole` from `App.tsx`.

**Tech Stack:** PostgreSQL 16 + PostGIS (UUID, CHECK), Python 3.13 + SQLAlchemy 2 + Starlette, pytest fixtures (Wave 3 conftest), React 18 + TypeScript + Vite.

**Spec:** `docs/superpowers/specs/2026-05-17-std-platform-wave4-review-subtab-design.md`

**Branch:** `feat/v12-extensible-platform` (continue, current HEAD: `adff2f6` after spec commit)

---

## Pre-flight

- [ ] **Step 0.1: Confirm baseline + clean staged state**

Run:
```powershell
cd D:\adk
git status --short data_agent/ frontend/src/components/datapanel/standards/
git log --oneline -3
```
Expected: HEAD is `adff2f6` (Wave 4 spec). NO files in `data_agent/standards_platform/` or `frontend/src/components/datapanel/standards/` should appear in `git status` — earlier session had stale staged changes that were reset. If any appear, run `git reset HEAD <file>` and `git checkout HEAD -- <file>` to clean before starting Task 1.

- [ ] **Step 0.2: Confirm DB has Wave 3 migrations 076 + 077 applied**

Run:
```powershell
.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv('data_agent/.env'); from sqlalchemy import text; from data_agent.db_engine import get_engine; e=get_engine(); rows=e.connect().execute(text(\"SELECT column_name FROM information_schema.columns WHERE table_name='std_reference' AND column_name IN ('verification_status','target_data_element_id','target_term_id') ORDER BY column_name\")).fetchall(); print([r[0] for r in rows])"
```
Expected: `['target_data_element_id', 'target_term_id', 'verification_status']` — confirms Wave 3 schema is live. If empty, STOP — Wave 3 migrations must be applied first.

- [ ] **Step 0.3: Confirm `_REVIEWER_ROLES` is already wired**

Run:
```powershell
grep -n "_REVIEWER_ROLES\|standard_reviewer" data_agent/api/standards_routes.py
```
Expected: `_REVIEWER_ROLES = {"admin", ..., "standard_reviewer"}` at line ~27. If missing, STOP — this prerequisite from Wave 1/2 is not in place.

---

## Task 1: Migration 078 — review_round + review_comment tables

**Files:**
- Create: `data_agent/migrations/078_std_review_tables.sql`
- Create: `data_agent/standards_platform/tests/test_migration_078.py`

- [ ] **Step 1.1: Write the migration**

Create `data_agent/migrations/078_std_review_tables.sql`:

```sql
-- 078: review_round + review_comment for the review stage
--      (parent spec §4.2.6).

CREATE TABLE IF NOT EXISTS std_review_round (
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

CREATE UNIQUE INDEX IF NOT EXISTS idx_std_review_round_one_open_per_version
    ON std_review_round(document_version_id) WHERE status = 'open';

CREATE INDEX IF NOT EXISTS idx_std_review_round_reviewer
    ON std_review_round(reviewer_user_id, status);

CREATE TABLE IF NOT EXISTS std_review_comment (
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

CREATE INDEX IF NOT EXISTS idx_std_review_comment_round_clause
    ON std_review_comment(round_id, clause_id);

CREATE INDEX IF NOT EXISTS idx_std_review_comment_open
    ON std_review_comment(round_id) WHERE resolution = 'open';
```

- [ ] **Step 1.2: Apply the migration locally**

Run:
```powershell
$env:PYTHONPATH="D:\adk"
.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv('data_agent/.env'); from sqlalchemy import text; from data_agent.db_engine import get_engine; sql=open('data_agent/migrations/078_std_review_tables.sql','r',encoding='utf-8').read(); e=get_engine(); conn=e.connect(); conn.execute(text(sql)); conn.commit(); print('OK')"
```
Expected: `OK`.

- [ ] **Step 1.3: Verify tables exist with the right shape**

Run:
```powershell
.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv('data_agent/.env'); from sqlalchemy import text; from data_agent.db_engine import get_engine; e=get_engine(); cols={t: [r[0] for r in e.connect().execute(text(f\"SELECT column_name FROM information_schema.columns WHERE table_name='{t}' ORDER BY column_name\")).fetchall()] for t in ('std_review_round','std_review_comment')}; print(cols)"
```
Expected: each table dict has all expected columns including `parent_comment_id`, `resolution`, `outcome`.

- [ ] **Step 1.4: Write the migration test**

Create `data_agent/standards_platform/tests/test_migration_078.py`:

```python
"""Schema-level checks for migration 078 (std_review_round + std_review_comment)."""
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


def _seed_doc_version(eng):
    """Create throwaway doc + version, return (doc_id, version_id)."""
    doc_id = str(uuid.uuid4())
    ver_id = str(uuid.uuid4())
    with eng.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_document (id, doc_code, title, source_type, "
            "status, owner_user_id) VALUES (:i, :c, 't', 'draft', "
            "'ingested', 'admin')"
        ), {"i": doc_id, "c": f"T-078-{doc_id[:6]}"})
        conn.execute(text(
            "INSERT INTO std_document_version (id, document_id, "
            "version_label, status, semver_major) VALUES (:i, :d, 'v1.0', "
            "'drafting', 1)"
        ), {"i": ver_id, "d": doc_id})
    return doc_id, ver_id


def test_review_round_columns_exist():
    eng = _get_engine_or_skip()
    with eng.connect() as c:
        cols = {r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='std_review_round'"
        )).fetchall()}
    assert {"id", "document_version_id", "reviewer_user_id",
            "initiated_by", "initiated_at", "closed_at",
            "status", "outcome"}.issubset(cols)


def test_review_comment_columns_exist():
    eng = _get_engine_or_skip()
    with eng.connect() as c:
        cols = {r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='std_review_comment'"
        )).fetchall()}
    assert {"id", "round_id", "clause_id", "parent_comment_id",
            "author_user_id", "body_md", "resolution",
            "created_at", "resolved_at", "resolved_by"}.issubset(cols)


def test_round_status_check_rejects_invalid():
    eng = _get_engine_or_skip()
    doc_id, ver_id = _seed_doc_version(eng)
    try:
        with pytest.raises(IntegrityError):
            with eng.begin() as conn:
                conn.execute(text(
                    "INSERT INTO std_review_round (id, document_version_id, "
                    "reviewer_user_id, initiated_by, status) VALUES "
                    "(:i, :v, 'rev', 'admin', 'bogus')"
                ), {"i": str(uuid.uuid4()), "v": ver_id})
    finally:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                         {"i": doc_id})


def test_round_outcome_consistency_check():
    """status=closed without outcome must be rejected."""
    eng = _get_engine_or_skip()
    doc_id, ver_id = _seed_doc_version(eng)
    try:
        with pytest.raises(IntegrityError):
            with eng.begin() as conn:
                conn.execute(text(
                    "INSERT INTO std_review_round (id, document_version_id, "
                    "reviewer_user_id, initiated_by, status, closed_at) "
                    "VALUES (:i, :v, 'rev', 'admin', 'closed', now())"
                ), {"i": str(uuid.uuid4()), "v": ver_id})
    finally:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                         {"i": doc_id})


def test_one_open_round_per_version():
    """UNIQUE partial index must reject a 2nd open round on same version."""
    eng = _get_engine_or_skip()
    doc_id, ver_id = _seed_doc_version(eng)
    r1 = str(uuid.uuid4())
    try:
        with eng.begin() as conn:
            conn.execute(text(
                "INSERT INTO std_review_round (id, document_version_id, "
                "reviewer_user_id, initiated_by) VALUES (:i, :v, 'rev1', 'admin')"
            ), {"i": r1, "v": ver_id})
        with pytest.raises(IntegrityError):
            with eng.begin() as conn:
                conn.execute(text(
                    "INSERT INTO std_review_round (id, document_version_id, "
                    "reviewer_user_id, initiated_by) VALUES (:i, :v, 'rev2', 'admin')"
                ), {"i": str(uuid.uuid4()), "v": ver_id})
    finally:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                         {"i": doc_id})


def test_comment_body_nonempty_check():
    """Whitespace-only body_md must be rejected."""
    eng = _get_engine_or_skip()
    doc_id, ver_id = _seed_doc_version(eng)
    cid = str(uuid.uuid4())
    rid = str(uuid.uuid4())
    try:
        with eng.begin() as conn:
            conn.execute(text(
                "INSERT INTO std_clause (id, document_id, document_version_id, "
                "ordinal_path, clause_no, kind, body_md) VALUES (:i, :d, :v, "
                "CAST('1' AS ltree), '1', 'clause', 'hello')"
            ), {"i": cid, "d": doc_id, "v": ver_id})
            conn.execute(text(
                "INSERT INTO std_review_round (id, document_version_id, "
                "reviewer_user_id, initiated_by) VALUES (:i, :v, 'rev', 'admin')"
            ), {"i": rid, "v": ver_id})
        with pytest.raises(IntegrityError):
            with eng.begin() as conn:
                conn.execute(text(
                    "INSERT INTO std_review_comment (id, round_id, clause_id, "
                    "author_user_id, body_md) VALUES (:i, :r, :c, 'rev', '   ')"
                ), {"i": str(uuid.uuid4()), "r": rid, "c": cid})
    finally:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                         {"i": doc_id})
```

- [ ] **Step 1.5: Run migration tests**

Run:
```powershell
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_migration_078.py -v
```
Expected: 6 passed.

- [ ] **Step 1.6: Commit**

```powershell
git add data_agent/migrations/078_std_review_tables.sql data_agent/standards_platform/tests/test_migration_078.py
git commit -m "feat(std-platform): migration 078 -- std_review_round + std_review_comment tables"
```

---

## Task 2: Repository layer + gating

**Files:**
- Create: `data_agent/standards_platform/review/__init__.py`
- Create: `data_agent/standards_platform/review/round_repo.py`
- Create: `data_agent/standards_platform/review/comment_repo.py`
- Create: `data_agent/standards_platform/review/gating.py`
- Create: `data_agent/standards_platform/tests/test_review_repo.py`

- [ ] **Step 2.1: Create the package init**

Create `data_agent/standards_platform/review/__init__.py`:

```python
"""Review stage — round + comment + gating logic.

Wave 4 of standards platform. See spec
docs/superpowers/specs/2026-05-17-std-platform-wave4-review-subtab-design.md
"""
```

- [ ] **Step 2.2: Implement round_repo**

Create `data_agent/standards_platform/review/round_repo.py`:

```python
"""CRUD on std_review_round."""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import text

from ...db_engine import get_engine


def create_round(*, document_version_id: str, reviewer_user_id: str,
                 initiated_by: str) -> str:
    """Insert a new open round + flip version.status to 'reviewing' atomically.

    Caller must verify version.status == 'drafting' first (handler concern).
    Returns the new round_id.
    """
    rid = str(uuid.uuid4())
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text("""
            INSERT INTO std_review_round
                (id, document_version_id, reviewer_user_id, initiated_by)
            VALUES (:i, :v, :r, :ib)
        """), {"i": rid, "v": document_version_id,
                "r": reviewer_user_id, "ib": initiated_by})
        conn.execute(text("""
            UPDATE std_document_version SET status='reviewing'
             WHERE id=:v AND status='drafting'
        """), {"v": document_version_id})
    return rid


def get_round(round_id: str) -> Optional[dict]:
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(text(
            "SELECT id, document_version_id, reviewer_user_id, initiated_by, "
            "initiated_at, closed_at, status, outcome "
            "FROM std_review_round WHERE id=:i"
        ), {"i": round_id}).mappings().first()
    return dict(row) if row else None


def list_rounds(*, version_id: Optional[str] = None,
                reviewer_user_id: Optional[str] = None,
                status: Optional[str] = None) -> list[dict]:
    eng = get_engine()
    where = []
    params = {}
    if version_id:
        where.append("document_version_id=:v"); params["v"] = version_id
    if reviewer_user_id:
        where.append("reviewer_user_id=:r"); params["r"] = reviewer_user_id
    if status:
        where.append("status=:s"); params["s"] = status
    sql = ("SELECT id, document_version_id, reviewer_user_id, initiated_by, "
           "initiated_at, closed_at, status, outcome FROM std_review_round")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY initiated_at DESC"
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def get_open_round_for_version(version_id: str) -> Optional[dict]:
    """Return the single open round for a version, if any."""
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(text(
            "SELECT id, document_version_id, reviewer_user_id, initiated_by, "
            "initiated_at, closed_at, status, outcome "
            "FROM std_review_round WHERE document_version_id=:v AND status='open'"
        ), {"v": version_id}).mappings().first()
    return dict(row) if row else None


def close_round(*, round_id: str, outcome: str) -> dict:
    """Close the round, flip version.status accordingly.

    outcome: 'approved' → version.status='approved'.
             'rejected' → version.status='drafting'.
    Caller is responsible for gating check (gating.check_close_gating)
    when outcome='approved'. Uses SELECT ... FOR UPDATE on the round
    to prevent concurrent close.

    Returns: {round_id, status, outcome, version_status}.
    """
    if outcome not in ("approved", "rejected"):
        raise ValueError(f"invalid outcome: {outcome}")
    target_version_status = "approved" if outcome == "approved" else "drafting"
    eng = get_engine()
    with eng.begin() as conn:
        row = conn.execute(text(
            "SELECT document_version_id, status FROM std_review_round "
            "WHERE id=:i FOR UPDATE"
        ), {"i": round_id}).first()
        if row is None:
            raise LookupError("round not found")
        if row[0] is None:
            raise ValueError("round has no version")
        if row[1] == "closed":
            raise ValueError("round already closed")
        version_id = str(row[0])
        conn.execute(text(
            "UPDATE std_review_round SET status='closed', "
            "outcome=:o, closed_at=now() WHERE id=:i"
        ), {"o": outcome, "i": round_id})
        conn.execute(text(
            "UPDATE std_document_version SET status=:s WHERE id=:v"
        ), {"s": target_version_status, "v": version_id})
    return {"round_id": round_id, "status": "closed", "outcome": outcome,
            "version_status": target_version_status}
```

- [ ] **Step 2.3: Implement comment_repo**

Create `data_agent/standards_platform/review/comment_repo.py`:

```python
"""CRUD on std_review_comment."""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import text

from ...db_engine import get_engine


def create_comment(*, round_id: str, clause_id: str,
                   author_user_id: str, body_md: str,
                   parent_comment_id: Optional[str] = None) -> str:
    cid = str(uuid.uuid4())
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text("""
            INSERT INTO std_review_comment
                (id, round_id, clause_id, parent_comment_id,
                 author_user_id, body_md)
            VALUES (:i, :r, :c, :p, :a, :b)
        """), {"i": cid, "r": round_id, "c": clause_id,
                "p": parent_comment_id, "a": author_user_id,
                "b": body_md})
    return cid


def list_comments(*, round_id: str,
                  clause_id: Optional[str] = None) -> list[dict]:
    sql = ("SELECT id, round_id, clause_id, parent_comment_id, "
           "author_user_id, body_md, resolution, created_at, "
           "resolved_at, resolved_by FROM std_review_comment "
           "WHERE round_id=:r")
    params = {"r": round_id}
    if clause_id:
        sql += " AND clause_id=:c"
        params["c"] = clause_id
    sql += " ORDER BY created_at ASC"
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def get_comment(comment_id: str) -> Optional[dict]:
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(text(
            "SELECT id, round_id, clause_id, parent_comment_id, "
            "author_user_id, body_md, resolution, created_at, "
            "resolved_at, resolved_by FROM std_review_comment WHERE id=:i"
        ), {"i": comment_id}).mappings().first()
    return dict(row) if row else None


def resolve_comment(*, comment_id: str, resolution: str,
                    resolver_user_id: str) -> None:
    if resolution not in ("accepted", "rejected", "duplicate"):
        raise ValueError(f"invalid resolution: {resolution}")
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text("""
            UPDATE std_review_comment
               SET resolution=:r, resolved_by=:u, resolved_at=now()
             WHERE id=:i
        """), {"r": resolution, "u": resolver_user_id, "i": comment_id})
```

- [ ] **Step 2.4: Implement gating**

Create `data_agent/standards_platform/review/gating.py`:

```python
"""Close-round gating: pure SQL counts of pending refs + open comments."""
from __future__ import annotations

from sqlalchemy import text

from ...db_engine import get_engine


def check_close_gating(*, round_id: str, version_id: str) -> dict:
    """Return {pending_refs, open_comments, blocking}.

    blocking = True when at least one is > 0.
    Used by both /close-precheck endpoint and the close handler when
    outcome='approved'.
    """
    eng = get_engine()
    with eng.connect() as conn:
        pending = conn.execute(text("""
            SELECT count(*) FROM std_reference r
            JOIN std_clause c ON c.id = r.source_clause_id
            WHERE c.document_version_id = :v
              AND r.verification_status = 'pending'
        """), {"v": version_id}).scalar() or 0
        open_c = conn.execute(text("""
            SELECT count(*) FROM std_review_comment
             WHERE round_id = :r AND resolution = 'open'
        """), {"r": round_id}).scalar() or 0
    return {
        "pending_refs": int(pending),
        "open_comments": int(open_c),
        "blocking": int(pending) + int(open_c) > 0,
    }
```

- [ ] **Step 2.5: Write repo + gating tests**

Create `data_agent/standards_platform/tests/test_review_repo.py`:

```python
"""Unit tests for review/{round_repo,comment_repo,gating}."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from data_agent.standards_platform.review import (
    round_repo, comment_repo, gating,
)


def test_create_round_flips_version_to_reviewing(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    rid = round_repo.create_round(
        document_version_id=ver_id,
        reviewer_user_id="rev1",
        initiated_by="admin")
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT status FROM std_document_version WHERE id=:v"
            ), {"v": ver_id}).first()
        assert row[0] == "reviewing"
        r = round_repo.get_round(rid)
        assert r["status"] == "open"
        assert r["reviewer_user_id"] == "rev1"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_close_round_approved_flips_version_to_approved(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    rid = round_repo.create_round(
        document_version_id=ver_id,
        reviewer_user_id="rev1",
        initiated_by="admin")
    try:
        out = round_repo.close_round(round_id=rid, outcome="approved")
        assert out["version_status"] == "approved"
        with engine.connect() as conn:
            v = conn.execute(text(
                "SELECT status FROM std_document_version WHERE id=:v"
            ), {"v": ver_id}).first()[0]
            r = conn.execute(text(
                "SELECT status, outcome FROM std_review_round WHERE id=:i"
            ), {"i": rid}).first()
        assert v == "approved"
        assert r[0] == "closed" and r[1] == "approved"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_close_round_rejected_flips_version_to_drafting(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    rid = round_repo.create_round(
        document_version_id=ver_id,
        reviewer_user_id="rev1",
        initiated_by="admin")
    try:
        out = round_repo.close_round(round_id=rid, outcome="rejected")
        assert out["version_status"] == "drafting"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_close_already_closed_round_raises(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    rid = round_repo.create_round(
        document_version_id=ver_id,
        reviewer_user_id="rev1",
        initiated_by="admin")
    try:
        round_repo.close_round(round_id=rid, outcome="approved")
        with pytest.raises(ValueError, match="already closed"):
            round_repo.close_round(round_id=rid, outcome="approved")
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_create_comment_with_parent(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    rid = round_repo.create_round(
        document_version_id=ver_id,
        reviewer_user_id="rev1",
        initiated_by="admin")
    try:
        c1 = comment_repo.create_comment(
            round_id=rid, clause_id=cid,
            author_user_id="rev1", body_md="hello")
        c2 = comment_repo.create_comment(
            round_id=rid, clause_id=cid,
            author_user_id="rev1", body_md="reply",
            parent_comment_id=c1)
        comments = comment_repo.list_comments(round_id=rid, clause_id=cid)
        assert len(comments) == 2
        assert any(c["parent_comment_id"] and str(c["parent_comment_id"]) == c1
                   for c in comments)
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_resolve_comment_sets_resolved_metadata(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    rid = round_repo.create_round(
        document_version_id=ver_id,
        reviewer_user_id="rev1",
        initiated_by="admin")
    try:
        comm_id = comment_repo.create_comment(
            round_id=rid, clause_id=cid,
            author_user_id="rev1", body_md="please fix")
        comment_repo.resolve_comment(
            comment_id=comm_id, resolution="accepted",
            resolver_user_id="rev1")
        c = comment_repo.get_comment(comm_id)
        assert c["resolution"] == "accepted"
        assert c["resolved_by"] == "rev1"
        assert c["resolved_at"] is not None
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_gating_open_comment_blocks(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    rid = round_repo.create_round(
        document_version_id=ver_id,
        reviewer_user_id="rev1",
        initiated_by="admin")
    try:
        comment_repo.create_comment(
            round_id=rid, clause_id=cid,
            author_user_id="rev1", body_md="todo")
        g = gating.check_close_gating(round_id=rid, version_id=ver_id)
        assert g["open_comments"] >= 1
        assert g["blocking"] is True
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_gating_pending_ref_blocks(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    rid = round_repo.create_round(
        document_version_id=ver_id,
        reviewer_user_id="rev1",
        initiated_by="admin")
    ref_id = str(uuid.uuid4())
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO std_reference (id, source_clause_id, target_kind, "
                "target_clause_id, citation_text) VALUES "
                "(:i, :s, 'std_clause', :s, 'cite')"
            ), {"i": ref_id, "s": cid})
        g = gating.check_close_gating(round_id=rid, version_id=ver_id)
        assert g["pending_refs"] >= 1
        assert g["blocking"] is True
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})
```

- [ ] **Step 2.6: Run repo tests**

Run:
```powershell
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_review_repo.py -v
```
Expected: 8 passed.

- [ ] **Step 2.7: Commit**

```powershell
git add data_agent/standards_platform/review/__init__.py data_agent/standards_platform/review/round_repo.py data_agent/standards_platform/review/comment_repo.py data_agent/standards_platform/review/gating.py data_agent/standards_platform/tests/test_review_repo.py
git commit -m "feat(std-platform): review repo + gating layer (round_repo, comment_repo, gating)"
```

---

## Task 3: REST handlers — round endpoints

**Files:**
- Modify: `data_agent/api/standards_routes.py` (add 3 round handlers + register routes)
- Test: `data_agent/standards_platform/tests/test_review_round_handler.py` (new)

- [ ] **Step 3.1: Add round handlers + helper**

Open `data_agent/api/standards_routes.py`. After the existing `_require_editor_or_403` (line ~36) add:

```python
def _require_admin_or_403(role: str | None) -> JSONResponse | None:
    if role != "admin":
        return JSONResponse({"error": "Forbidden — admin only"}, status_code=403)
    return None
```

At the end of the file (just before `standards_routes = [` at line ~403) add:

```python
# ---------------------------------------------------------------------------
# Wave 4: Review stage handlers
# ---------------------------------------------------------------------------

from ..standards_platform.review import (
    round_repo as _round_repo,
    comment_repo as _comment_repo,
    gating as _gating,
)


def _round_or_404(round_id: str):
    r = _round_repo.get_round(round_id)
    if r is None:
        return None, JSONResponse({"error": "round not found"}, status_code=404)
    return r, None


def _require_round_reviewer_or_403(round_dict, username, role):
    """Allow if user is admin OR is the round's reviewer."""
    if role == "admin":
        return None
    if round_dict["reviewer_user_id"] == username:
        return None
    return JSONResponse({"error": "not the assigned reviewer"},
                        status_code=403)


async def review_round_start(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    forbid = _require_admin_or_403(role)
    if forbid: return forbid
    body = await request.json()
    version_id = body.get("document_version_id")
    reviewer = body.get("reviewer_user_id")
    if not version_id or not reviewer:
        return JSONResponse({"error": "document_version_id and reviewer_user_id required"},
                            status_code=400)
    eng = get_engine()
    with eng.connect() as conn:
        v = conn.execute(text(
            "SELECT status FROM std_document_version WHERE id=:i"
        ), {"i": version_id}).first()
    if v is None:
        return JSONResponse({"error": "version not found"}, status_code=404)
    if v[0] != "drafting":
        return JSONResponse({"error": "version status must be drafting",
                              "current_status": v[0]}, status_code=409)
    if _round_repo.get_open_round_for_version(version_id) is not None:
        existing = _round_repo.get_open_round_for_version(version_id)
        return JSONResponse({"error": "round already open for this version",
                              "round_id": str(existing["id"])}, status_code=409)
    rid = _round_repo.create_round(
        document_version_id=version_id,
        reviewer_user_id=reviewer,
        initiated_by=username)
    return JSONResponse({"round_id": rid}, status_code=201)


async def review_round_list(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    p = request.query_params
    rounds = _round_repo.list_rounds(
        version_id=p.get("version_id"),
        reviewer_user_id=p.get("reviewer_user_id"),
        status=p.get("status"))
    return JSONResponse({"rounds": [
        {"id": str(r["id"]),
         "document_version_id": str(r["document_version_id"]),
         "reviewer_user_id": r["reviewer_user_id"],
         "initiated_by": r["initiated_by"],
         "initiated_at": r["initiated_at"].isoformat() if r["initiated_at"] else None,
         "closed_at": r["closed_at"].isoformat() if r["closed_at"] else None,
         "status": r["status"],
         "outcome": r["outcome"]} for r in rounds]})


async def review_round_close_precheck(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    rid = request.path_params["round_id"]
    r, err404 = _round_or_404(rid)
    if err404: return err404
    forbid = _require_round_reviewer_or_403(r, username, role)
    if forbid: return forbid
    g = _gating.check_close_gating(round_id=rid,
                                   version_id=str(r["document_version_id"]))
    return JSONResponse(g)


async def review_round_close(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    rid = request.path_params["round_id"]
    r, err404 = _round_or_404(rid)
    if err404: return err404
    forbid = _require_round_reviewer_or_403(r, username, role)
    if forbid: return forbid
    body = await request.json()
    outcome = body.get("outcome")
    if outcome not in ("approved", "rejected"):
        return JSONResponse({"error": "outcome must be 'approved' or 'rejected'"},
                            status_code=400)
    if r["status"] == "closed":
        return JSONResponse({"error": "round already closed"}, status_code=409)
    if outcome == "approved":
        g = _gating.check_close_gating(round_id=rid,
                                       version_id=str(r["document_version_id"]))
        if g["blocking"]:
            return JSONResponse({"error": "cannot close: gating not satisfied",
                                  "pending_refs": g["pending_refs"],
                                  "open_comments": g["open_comments"]},
                                  status_code=409)
    try:
        out = _round_repo.close_round(round_id=rid, outcome=outcome)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    return JSONResponse(out)
```

- [ ] **Step 3.2: Register the round routes**

In `data_agent/api/standards_routes.py`, find `standards_routes = [` (line ~403). After the `Route("/api/std/citation/insert", ...)` entry, add before the closing `]`:

```python
    Route("/api/std/reviews/rounds",
          endpoint=review_round_start, methods=["POST"]),
    Route("/api/std/reviews/rounds",
          endpoint=review_round_list, methods=["GET"]),
    Route("/api/std/reviews/rounds/{round_id}/close-precheck",
          endpoint=review_round_close_precheck, methods=["GET"]),
    Route("/api/std/reviews/rounds/{round_id}/close",
          endpoint=review_round_close, methods=["POST"]),
```

- [ ] **Step 3.3: Write round handler tests**

Create `data_agent/standards_platform/tests/test_review_round_handler.py`:

```python
"""API tests for /api/std/reviews/rounds/* endpoints."""
from __future__ import annotations

import uuid

from sqlalchemy import text

from data_agent.standards_platform.tests.test_api_standards import (
    _client, _auth_user,
)


def test_start_round_happy(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    resp = _client().post("/api/std/reviews/rounds", json={
        "document_version_id": ver_id,
        "reviewer_user_id": "rev1",
    })
    assert resp.status_code == 201, resp.text
    rid = resp.json()["round_id"]
    try:
        with engine.connect() as conn:
            v = conn.execute(text(
                "SELECT status FROM std_document_version WHERE id=:v"
            ), {"v": ver_id}).first()
        assert v[0] == "reviewing"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_start_round_when_version_not_drafting(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE std_document_version SET status='approved' WHERE id=:v"
        ), {"v": ver_id})
    _auth_user(monkeypatch, username="admin", role="admin")
    resp = _client().post("/api/std/reviews/rounds", json={
        "document_version_id": ver_id, "reviewer_user_id": "rev1"})
    assert resp.status_code == 409
    assert resp.json()["current_status"] == "approved"


def test_start_round_when_open_round_exists(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    r1 = _client().post("/api/std/reviews/rounds", json={
        "document_version_id": ver_id, "reviewer_user_id": "rev1"}).json()["round_id"]
    try:
        resp = _client().post("/api/std/reviews/rounds", json={
            "document_version_id": ver_id, "reviewer_user_id": "rev2"})
        assert resp.status_code == 409
        assert resp.json()["round_id"] == r1
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": r1})


def test_list_rounds_filter_by_reviewer(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _client().post("/api/std/reviews/rounds", json={
        "document_version_id": ver_id, "reviewer_user_id": "rev-X"}).json()["round_id"]
    try:
        resp = _client().get("/api/std/reviews/rounds?reviewer_user_id=rev-X")
        assert resp.status_code == 200
        rounds = resp.json()["rounds"]
        assert any(r["id"] == rid for r in rounds)
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_close_round_approved_happy(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _client().post("/api/std/reviews/rounds", json={
        "document_version_id": ver_id, "reviewer_user_id": "admin"}).json()["round_id"]
    try:
        resp = _client().post(f"/api/std/reviews/rounds/{rid}/close",
                              json={"outcome": "approved"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["version_status"] == "approved"
        with engine.connect() as conn:
            v = conn.execute(text(
                "SELECT status FROM std_document_version WHERE id=:v"
            ), {"v": ver_id}).first()
        assert v[0] == "approved"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_close_round_rejected_happy(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _client().post("/api/std/reviews/rounds", json={
        "document_version_id": ver_id, "reviewer_user_id": "admin"}).json()["round_id"]
    try:
        resp = _client().post(f"/api/std/reviews/rounds/{rid}/close",
                              json={"outcome": "rejected"})
        assert resp.status_code == 200
        assert resp.json()["version_status"] == "drafting"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_close_round_gating_blocks_when_pending_ref(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _client().post("/api/std/reviews/rounds", json={
        "document_version_id": ver_id, "reviewer_user_id": "admin"}).json()["round_id"]
    ref_id = str(uuid.uuid4())
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO std_reference (id, source_clause_id, target_kind, "
                "target_clause_id, citation_text) VALUES "
                "(:i, :s, 'std_clause', :s, 'cite')"
            ), {"i": ref_id, "s": cid})
        resp = _client().post(f"/api/std/reviews/rounds/{rid}/close",
                              json={"outcome": "approved"})
        assert resp.status_code == 409
        assert resp.json()["pending_refs"] >= 1
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_close_round_by_non_reviewer_403(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _client().post("/api/std/reviews/rounds", json={
        "document_version_id": ver_id, "reviewer_user_id": "rev1"}).json()["round_id"]
    try:
        # Switch identity to non-reviewer
        _auth_user(monkeypatch, username="someone_else", role="standard_reviewer")
        resp = _client().post(f"/api/std/reviews/rounds/{rid}/close",
                              json={"outcome": "approved"})
        assert resp.status_code == 403
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})
```

- [ ] **Step 3.4: Run tests**

Run:
```powershell
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_review_round_handler.py -v
```
Expected: 8 passed.

- [ ] **Step 3.5: Commit**

```powershell
git add data_agent/api/standards_routes.py data_agent/standards_platform/tests/test_review_round_handler.py
git commit -m "feat(std-platform): review round handlers (start/list/close-precheck/close)"
```

---

## Task 4: REST handlers — comment + reference endpoints

**Files:**
- Modify: `data_agent/api/standards_routes.py` (add 3 comment handlers + 1 reference handler + register routes)
- Test: `data_agent/standards_platform/tests/test_review_comment_handler.py` (new)
- Test: `data_agent/standards_platform/tests/test_review_reference_handler.py` (new)

- [ ] **Step 4.1: Add comment + reference handlers**

In `data_agent/api/standards_routes.py`, just before `standards_routes = [` add:

```python
async def review_comment_list(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    rid = request.path_params["round_id"]
    r, err404 = _round_or_404(rid)
    if err404: return err404
    clause_id = request.query_params.get("clause_id")
    comments = _comment_repo.list_comments(round_id=rid, clause_id=clause_id)
    return JSONResponse({"comments": [
        {"id": str(c["id"]), "round_id": str(c["round_id"]),
         "clause_id": str(c["clause_id"]),
         "parent_comment_id": str(c["parent_comment_id"]) if c["parent_comment_id"] else None,
         "author_user_id": c["author_user_id"], "body_md": c["body_md"],
         "resolution": c["resolution"],
         "created_at": c["created_at"].isoformat() if c["created_at"] else None,
         "resolved_at": c["resolved_at"].isoformat() if c["resolved_at"] else None,
         "resolved_by": c["resolved_by"]} for c in comments]})


async def review_comment_post(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    rid = request.path_params["round_id"]
    r, err404 = _round_or_404(rid)
    if err404: return err404
    forbid = _require_round_reviewer_or_403(r, username, role)
    if forbid: return forbid
    if r["status"] == "closed":
        return JSONResponse({"error": "round closed"}, status_code=409)
    body = await request.json()
    clause_id = body.get("clause_id")
    body_md = (body.get("body_md") or "").strip()
    parent = body.get("parent_comment_id")
    if not clause_id:
        return JSONResponse({"error": "clause_id required"}, status_code=400)
    if not body_md:
        return JSONResponse({"error": "body_md is required"}, status_code=400)
    if parent:
        p = _comment_repo.get_comment(parent)
        if p is None or str(p["round_id"]) != rid:
            return JSONResponse({"error": "parent must belong to same round"},
                                status_code=400)
    cid = _comment_repo.create_comment(
        round_id=rid, clause_id=clause_id,
        author_user_id=username, body_md=body_md,
        parent_comment_id=parent)
    return JSONResponse({"comment_id": cid}, status_code=201)


async def review_comment_resolve(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    comm_id = request.path_params["comment_id"]
    c = _comment_repo.get_comment(comm_id)
    if c is None:
        return JSONResponse({"error": "comment not found"}, status_code=404)
    r, err404 = _round_or_404(str(c["round_id"]))
    if err404: return err404
    forbid = _require_round_reviewer_or_403(r, username, role)
    if forbid: return forbid
    if r["status"] == "closed":
        return JSONResponse({"error": "round closed"}, status_code=409)
    body = await request.json()
    resolution = body.get("resolution")
    if resolution not in ("accepted", "rejected", "duplicate"):
        return JSONResponse({"error": "resolution must be accepted/rejected/duplicate"},
                            status_code=400)
    _comment_repo.resolve_comment(
        comment_id=comm_id, resolution=resolution,
        resolver_user_id=username)
    return JSONResponse({"comment_id": comm_id, "resolution": resolution})


async def review_reference_patch_status(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    ref_id = request.path_params["ref_id"]
    body = await request.json()
    new_status = body.get("verification_status")
    rid = body.get("round_id")
    if new_status not in ("approved", "rejected"):
        return JSONResponse({"error": "verification_status must be approved or rejected"},
                            status_code=400)
    if not rid:
        return JSONResponse({"error": "round_id required"}, status_code=400)
    r, err404 = _round_or_404(rid)
    if err404: return err404
    forbid = _require_round_reviewer_or_403(r, username, role)
    if forbid: return forbid
    if r["status"] == "closed":
        return JSONResponse({"error": "round closed"}, status_code=409)
    eng = get_engine()
    with eng.connect() as conn:
        ref_row = conn.execute(text(
            "SELECT r.id, c.document_version_id "
            "FROM std_reference r "
            "JOIN std_clause c ON c.id = r.source_clause_id "
            "WHERE r.id=:i"
        ), {"i": ref_id}).first()
    if ref_row is None:
        return JSONResponse({"error": "reference not found"}, status_code=404)
    if str(ref_row[1]) != str(r["document_version_id"]):
        return JSONResponse({"error": "reference not in round"}, status_code=404)
    with eng.begin() as conn:
        conn.execute(text("""
            UPDATE std_reference
               SET verification_status=:s,
                   verified_by=:u, verified_at=now()
             WHERE id=:i
        """), {"s": new_status, "u": username, "i": ref_id})
        row = conn.execute(text(
            "SELECT verification_status, verified_by, verified_at "
            "FROM std_reference WHERE id=:i"
        ), {"i": ref_id}).first()
    return JSONResponse({"ref_id": ref_id,
                         "verification_status": row[0],
                         "verified_by": row[1],
                         "verified_at": row[2].isoformat() if row[2] else None})
```

- [ ] **Step 4.2: Register the comment + reference routes**

In `data_agent/api/standards_routes.py`'s `standards_routes = [...]` list, after the `Route("/api/std/reviews/rounds/{round_id}/close", ...)` entry, add:

```python
    Route("/api/std/reviews/rounds/{round_id}/comments",
          endpoint=review_comment_list, methods=["GET"]),
    Route("/api/std/reviews/rounds/{round_id}/comments",
          endpoint=review_comment_post, methods=["POST"]),
    Route("/api/std/reviews/comments/{comment_id}/resolve",
          endpoint=review_comment_resolve, methods=["POST"]),
    Route("/api/std/reviews/references/{ref_id}/status",
          endpoint=review_reference_patch_status, methods=["PATCH"]),
```

- [ ] **Step 4.3: Write comment handler tests**

Create `data_agent/standards_platform/tests/test_review_comment_handler.py`:

```python
"""API tests for /api/std/reviews/.../comments + resolve."""
from __future__ import annotations

from sqlalchemy import text

from data_agent.standards_platform.tests.test_api_standards import (
    _client, _auth_user,
)


def _start_round(client, version_id, reviewer="admin"):
    return client.post("/api/std/reviews/rounds", json={
        "document_version_id": version_id,
        "reviewer_user_id": reviewer}).json()["round_id"]


def test_post_comment_happy(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _start_round(_client(), ver_id)
    try:
        resp = _client().post(f"/api/std/reviews/rounds/{rid}/comments",
                              json={"clause_id": cid, "body_md": "needs work"})
        assert resp.status_code == 201, resp.text
        cmts = _client().get(f"/api/std/reviews/rounds/{rid}/comments").json()["comments"]
        assert any(c["body_md"] == "needs work" for c in cmts)
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_post_threaded_reply(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _start_round(_client(), ver_id)
    try:
        c1 = _client().post(f"/api/std/reviews/rounds/{rid}/comments",
                            json={"clause_id": cid, "body_md": "q?"}).json()["comment_id"]
        resp = _client().post(f"/api/std/reviews/rounds/{rid}/comments",
                              json={"clause_id": cid, "body_md": "reply!",
                                    "parent_comment_id": c1})
        assert resp.status_code == 201
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_resolve_comment(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _start_round(_client(), ver_id)
    try:
        c1 = _client().post(f"/api/std/reviews/rounds/{rid}/comments",
                            json={"clause_id": cid, "body_md": "foo"}).json()["comment_id"]
        resp = _client().post(f"/api/std/reviews/comments/{c1}/resolve",
                              json={"resolution": "accepted"})
        assert resp.status_code == 200
        assert resp.json()["resolution"] == "accepted"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_post_comment_empty_body_400(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _start_round(_client(), ver_id)
    try:
        resp = _client().post(f"/api/std/reviews/rounds/{rid}/comments",
                              json={"clause_id": cid, "body_md": "   "})
        assert resp.status_code == 400
        assert "body_md" in resp.json()["error"]
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_post_comment_parent_in_different_round_400(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    rid1 = _start_round(_client(), ver_id)
    try:
        # close round 1 then start round 2, putting a parent in round 1
        c_in_r1 = _client().post(f"/api/std/reviews/rounds/{rid1}/comments",
                                 json={"clause_id": cid, "body_md": "in r1"}).json()["comment_id"]
        _client().post(f"/api/std/reviews/comments/{c_in_r1}/resolve",
                       json={"resolution": "accepted"})
        _client().post(f"/api/std/reviews/rounds/{rid1}/close",
                       json={"outcome": "rejected"})  # back to drafting
        rid2 = _start_round(_client(), ver_id)
        try:
            resp = _client().post(f"/api/std/reviews/rounds/{rid2}/comments",
                                  json={"clause_id": cid, "body_md": "x",
                                        "parent_comment_id": c_in_r1})
            assert resp.status_code == 400
            assert "parent" in resp.json()["error"]
        finally:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                             {"i": rid2})
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid1})


def test_post_comment_non_reviewer_403(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _start_round(_client(), ver_id, reviewer="rev1")
    try:
        _auth_user(monkeypatch, username="someone", role="standard_reviewer")
        resp = _client().post(f"/api/std/reviews/rounds/{rid}/comments",
                              json={"clause_id": cid, "body_md": "x"})
        assert resp.status_code == 403
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})
```

- [ ] **Step 4.4: Write reference handler tests**

Create `data_agent/standards_platform/tests/test_review_reference_handler.py`:

```python
"""API tests for PATCH /api/std/reviews/references/{ref_id}/status."""
from __future__ import annotations

import uuid

from sqlalchemy import text

from data_agent.standards_platform.tests.test_api_standards import (
    _client, _auth_user,
)


def _seed_pending_ref(engine, clause_id):
    ref_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_reference (id, source_clause_id, target_kind, "
            "target_clause_id, citation_text) VALUES "
            "(:i, :s, 'std_clause', :s, 'cite')"
        ), {"i": ref_id, "s": clause_id})
    return ref_id


def _start_round(client, version_id, reviewer="admin"):
    return client.post("/api/std/reviews/rounds", json={
        "document_version_id": version_id,
        "reviewer_user_id": reviewer}).json()["round_id"]


def test_patch_ref_approved(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    ref_id = _seed_pending_ref(engine, cid)
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _start_round(_client(), ver_id)
    try:
        resp = _client().patch(f"/api/std/reviews/references/{ref_id}/status",
                               json={"verification_status": "approved",
                                     "round_id": rid})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["verification_status"] == "approved"
        assert body["verified_by"] == "admin"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_patch_ref_rejected(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    ref_id = _seed_pending_ref(engine, cid)
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _start_round(_client(), ver_id)
    try:
        resp = _client().patch(f"/api/std/reviews/references/{ref_id}/status",
                               json={"verification_status": "rejected",
                                     "round_id": rid})
        assert resp.status_code == 200
        assert resp.json()["verification_status"] == "rejected"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_patch_ref_pending_400(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    ref_id = _seed_pending_ref(engine, cid)
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _start_round(_client(), ver_id)
    try:
        resp = _client().patch(f"/api/std/reviews/references/{ref_id}/status",
                               json={"verification_status": "pending",
                                     "round_id": rid})
        assert resp.status_code == 400
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_patch_ref_non_reviewer_403(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    ref_id = _seed_pending_ref(engine, cid)
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _start_round(_client(), ver_id, reviewer="rev1")
    try:
        _auth_user(monkeypatch, username="someone", role="standard_reviewer")
        resp = _client().patch(f"/api/std/reviews/references/{ref_id}/status",
                               json={"verification_status": "approved",
                                     "round_id": rid})
        assert resp.status_code == 403
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_patch_ref_closed_round_409(monkeypatch, engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    ref_id = _seed_pending_ref(engine, cid)
    _auth_user(monkeypatch, username="admin", role="admin")
    rid = _start_round(_client(), ver_id)
    try:
        # approve the ref first so we can close cleanly
        _client().patch(f"/api/std/reviews/references/{ref_id}/status",
                        json={"verification_status": "approved", "round_id": rid})
        _client().post(f"/api/std/reviews/rounds/{rid}/close",
                       json={"outcome": "approved"})
        # now attempt patch on closed round
        # need a 2nd ref to flip
        ref2 = _seed_pending_ref(engine, cid)
        resp = _client().patch(f"/api/std/reviews/references/{ref2}/status",
                               json={"verification_status": "rejected",
                                     "round_id": rid})
        assert resp.status_code == 409
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})
```

- [ ] **Step 4.5: Run all review handler tests**

Run:
```powershell
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_review_comment_handler.py data_agent/standards_platform/tests/test_review_reference_handler.py -v
```
Expected: 6 + 5 = 11 passed.

- [ ] **Step 4.6: Commit**

```powershell
git add data_agent/api/standards_routes.py data_agent/standards_platform/tests/test_review_comment_handler.py data_agent/standards_platform/tests/test_review_reference_handler.py
git commit -m "feat(std-platform): review comment + reference patch handlers"
```

---

## Task 5: Drafting endpoint gate (block when version='reviewing')

**Files:**
- Modify: `data_agent/api/standards_routes.py` (add gate to drafting handlers)
- Test: `data_agent/standards_platform/tests/test_api_drafting.py` (extend)

- [ ] **Step 5.1: Add the gate helper**

In `data_agent/api/standards_routes.py`, near `_require_admin_or_403` (added in Task 3), add:

```python
def _block_if_reviewing(version_id: str) -> JSONResponse | None:
    """Returns a 409 JSONResponse if the version is in 'reviewing' status."""
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(text(
            "SELECT status FROM std_document_version WHERE id=:i"
        ), {"i": version_id}).first()
    if row is None:
        return None  # downstream will 404
    if row[0] == "reviewing":
        return JSONResponse({"error": "version is under review, drafting blocked"},
                            status_code=409)
    return None
```

- [ ] **Step 5.2: Add the gate to clause update handler**

Find the PUT handler for `/api/std/clauses/{clause_id}` (search for `Route("/api/std/clauses/{clause_id}",` and follow to the handler — likely named `update_clause` or similar). At the start of that handler, after `_auth_or_401` and editor-role checks, add:

```python
    # Wave 4: block drafting writes when version is in review
    eng = get_engine()
    with eng.connect() as conn:
        ver = conn.execute(text(
            "SELECT document_version_id FROM std_clause WHERE id=:i"
        ), {"i": clause_id}).first()
    if ver:
        forbid = _block_if_reviewing(str(ver[0]))
        if forbid: return forbid
```

Apply the same block to the lock acquire handler (`Route("/api/std/clauses/{clause_id}/lock"`) before it tries to set the lock.

- [ ] **Step 5.3: Write the failing test**

In `data_agent/standards_platform/tests/test_api_drafting.py`, append:

```python
def test_drafting_blocked_when_version_in_review(monkeypatch, engine, fresh_clause):
    """Wave 4: drafting endpoints return 409 when version.status='reviewing'."""
    cid, doc_id, ver_id = fresh_clause
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE std_document_version SET status='reviewing' WHERE id=:v"
        ), {"v": ver_id})
    _auth_user(monkeypatch, username="admin", role="admin")
    resp = _client().put(f"/api/std/clauses/{cid}",
                         json={"body_md": "trying to edit"})
    assert resp.status_code == 409
    assert "review" in resp.json().get("error", "").lower()
```

- [ ] **Step 5.4: Run test to verify pass**

Run:
```powershell
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_api_drafting.py::test_drafting_blocked_when_version_in_review -v
```
Expected: PASS.

- [ ] **Step 5.5: Run the full test_api_drafting.py to ensure no regression**

Run:
```powershell
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_api_drafting.py -v
```
Expected: all tests pass (existing + 1 new).

- [ ] **Step 5.6: Commit**

```powershell
git add data_agent/api/standards_routes.py data_agent/standards_platform/tests/test_api_drafting.py
git commit -m "feat(std-platform): block drafting writes when version is under review"
```

---

## Task 6: Auth — accept standard_reviewer role + admin dashboard option

**Files:**
- Modify: `data_agent/auth.py:193-238` (register_user accepts role param)
- Modify: `frontend/src/components/AdminDashboard.tsx:213-215` (add new role options)
- Test: `data_agent/test_auth.py` (find or create)

- [ ] **Step 6.1: Check whether test_auth.py exists**

Run:
```powershell
ls data_agent/test_auth.py
```
If missing, the test in Step 6.4 creates it.

- [ ] **Step 6.2: Update register_user to accept role**

In `data_agent/auth.py`, replace lines 193-238 (the `register_user` function) with:

```python
_VALID_ROLES = {"viewer", "analyst", "admin",
                "standard_editor", "standard_reviewer"}


def register_user(username: str, password: str, display_name: str = "",
                   email: str = "", role: str = "analyst") -> dict:
    """Register a new user with the given role (default 'analyst').

    Returns: {"status": "success", "message": "..."} or {"status": "error", "message": "..."}
    """
    if not username or not password:
        return {"status": "error", "message": t("auth.username_empty")}

    if not re.match(r'^[a-zA-Z0-9_]{3,30}$', username):
        return {"status": "error", "message": t("auth.username_format")}

    if len(password) < 8:
        return {"status": "error", "message": t("auth.password_length")}
    if not re.search(r'[a-zA-Z]', password) or not re.search(r'\d', password):
        return {"status": "error", "message": t("auth.password_complexity")}

    if email and not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return {"status": "error", "message": t("auth.email_format")}

    if role not in _VALID_ROLES:
        return {"status": "error", "message": f"invalid role: {role}"}

    engine = get_engine()
    if not engine:
        return {"status": "error", "message": t("auth.db_unavailable")}

    try:
        with engine.connect() as conn:
            exists = conn.execute(text(
                f"SELECT 1 FROM {T_APP_USERS} WHERE username = :u"
            ), {"u": username}).fetchone()
            if exists:
                return {"status": "error", "message": t("auth.username_exists")}

            pw_hash = _make_password_hash(password)
            conn.execute(text(
                f"INSERT INTO {T_APP_USERS} "
                "(username, password_hash, display_name, email, role, auth_provider) "
                "VALUES (:u, :p, :d, :e, :r, 'password')"
            ), {"u": username, "p": pw_hash, "d": display_name or username,
                "e": email or "", "r": role})
            conn.commit()
            return {"status": "success", "message": t("auth.register_success")}
    except Exception as e:
        return {"status": "error", "message": t("auth.register_failed", error=str(e))}
```

- [ ] **Step 6.3: Update AdminDashboard role options**

In `frontend/src/components/AdminDashboard.tsx`, find the `<select className="role-select"` block (around line 211-215) and replace the option list:

**Before:**
```tsx
                    <option value="admin">admin</option>
                    <option value="analyst">analyst</option>
                    <option value="viewer">viewer</option>
```

**After:**
```tsx
                    <option value="admin">admin</option>
                    <option value="analyst">analyst</option>
                    <option value="viewer">viewer</option>
                    <option value="standard_editor">standard_editor</option>
                    <option value="standard_reviewer">standard_reviewer</option>
```

- [ ] **Step 6.4: Write the auth test**

If `data_agent/test_auth.py` exists, append. Otherwise create it:

```python
"""Auth tests."""
from __future__ import annotations

from unittest.mock import patch

from data_agent.auth import _VALID_ROLES, register_user


def test_valid_roles_includes_standard_reviewer():
    """Wave 4: standard_reviewer is a recognized role."""
    assert "standard_reviewer" in _VALID_ROLES
    assert "standard_editor" in _VALID_ROLES


def test_register_user_rejects_invalid_role():
    """register_user should return error for unknown role."""
    out = register_user("testuser_w4", "Password123", role="bogus_role")
    assert out["status"] == "error"
    assert "invalid role" in out["message"]
```

- [ ] **Step 6.5: Run the auth test**

Run:
```powershell
.venv\Scripts\python.exe -m pytest data_agent/test_auth.py -v
```
Expected: PASS.

- [ ] **Step 6.6: Commit**

```powershell
git add data_agent/auth.py frontend/src/components/AdminDashboard.tsx data_agent/test_auth.py
git commit -m "feat(auth): standard_reviewer + standard_editor roles in register_user + AdminDashboard"
```

---

## Task 7: Frontend SDK additions

**Files:**
- Modify: `frontend/src/components/datapanel/standards/standardsApi.ts` (append types + 8 functions)

- [ ] **Step 7.1: Add types and SDK functions**

At the bottom of `frontend/src/components/datapanel/standards/standardsApi.ts`, append:

```typescript
// ===========================================================================
// Wave 4: Review stage SDK
// ===========================================================================

export type ReviewRound = {
  id: string;
  document_version_id: string;
  reviewer_user_id: string;
  initiated_by: string;
  initiated_at: string | null;
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
  created_at: string | null;
  resolved_at: string | null;
  resolved_by: string | null;
};

export type GatingPrecheck = {
  pending_refs: number;
  open_comments: number;
  blocking: boolean;
};

export const startReviewRound = (versionId: string, reviewerUserId: string) =>
  fetch("/api/std/reviews/rounds", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({document_version_id: versionId,
                          reviewer_user_id: reviewerUserId}),
  }).then(j<{round_id: string}>);

export const listReviewRounds = (params: {version_id?: string;
                                            reviewer_user_id?: string;
                                            status?: string} = {}) => {
  const q = new URLSearchParams(params as Record<string,string>).toString();
  return fetch(`/api/std/reviews/rounds?${q}`)
    .then(j<{rounds: ReviewRound[]}>);
};

export const closeReviewPrecheck = (roundId: string) =>
  fetch(`/api/std/reviews/rounds/${roundId}/close-precheck`)
    .then(j<GatingPrecheck>);

export const closeReviewRound = (roundId: string,
                                 outcome: 'approved' | 'rejected') =>
  fetch(`/api/std/reviews/rounds/${roundId}/close`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({outcome}),
  }).then(j<{round_id: string; status: string;
              outcome: string; version_status: string}>);

export const listReviewComments = (roundId: string, clauseId?: string) => {
  const q = clauseId ? `?clause_id=${clauseId}` : "";
  return fetch(`/api/std/reviews/rounds/${roundId}/comments${q}`)
    .then(j<{comments: ReviewComment[]}>);
};

export const postReviewComment = (roundId: string, clauseId: string,
                                   bodyMd: string,
                                   parentCommentId?: string) =>
  fetch(`/api/std/reviews/rounds/${roundId}/comments`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({clause_id: clauseId, body_md: bodyMd,
                          parent_comment_id: parentCommentId ?? null}),
  }).then(j<{comment_id: string}>);

export const resolveReviewComment = (commentId: string,
                                      resolution: 'accepted' | 'rejected' | 'duplicate') =>
  fetch(`/api/std/reviews/comments/${commentId}/resolve`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({resolution}),
  }).then(j<{comment_id: string; resolution: string}>);

export const patchReferenceStatus = (refId: string, roundId: string,
                                      status: 'approved' | 'rejected') =>
  fetch(`/api/std/reviews/references/${refId}/status`, {
    method: "PATCH",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({verification_status: status, round_id: roundId}),
  }).then(j<{ref_id: string; verification_status: string;
              verified_by: string; verified_at: string}>);
```

- [ ] **Step 7.2: Verify TS compiles**

Run:
```powershell
cd frontend
npm run build
cd ..
```
Expected: exit 0. (No new component yet — this just adds SDK types/functions.)

- [ ] **Step 7.3: Commit**

```powershell
git add frontend/src/components/datapanel/standards/standardsApi.ts
git commit -m "feat(std-platform-fe): standardsApi -- review SDK (types + 8 functions)"
```

---

## Task 8: ReviewSubTab + 5 sub-components

**Files:**
- Create: `frontend/src/components/datapanel/standards/ReviewSubTab.tsx`
- Create: `frontend/src/components/datapanel/standards/review/RoundSelector.tsx`
- Create: `frontend/src/components/datapanel/standards/review/ClauseAuditList.tsx`
- Create: `frontend/src/components/datapanel/standards/review/ReferenceAuditCard.tsx`
- Create: `frontend/src/components/datapanel/standards/review/CommentThread.tsx`
- Create: `frontend/src/components/datapanel/standards/review/CloseRoundDialog.tsx`

- [ ] **Step 8.1: Create RoundSelector**

Create `frontend/src/components/datapanel/standards/review/RoundSelector.tsx`:

```tsx
import React, { useEffect, useState } from "react";
import { ReviewRound, listReviewRounds, startReviewRound } from "../standardsApi";

interface Props {
  versionId: string | null;
  isAdmin: boolean;
  onSelect: (round: ReviewRound | null) => void;
}

export default function RoundSelector({versionId, isAdmin, onSelect}: Props) {
  const [rounds, setRounds] = useState<ReviewRound[]>([]);
  const [reviewerInput, setReviewerInput] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = () => {
    if (!versionId) return;
    listReviewRounds({version_id: versionId}).then(r => setRounds(r.rounds));
  };

  useEffect(refresh, [versionId]);

  const start = async () => {
    if (!versionId || !reviewerInput.trim()) return;
    setBusy(true);
    try {
      await startReviewRound(versionId, reviewerInput.trim());
      setReviewerInput("");
      refresh();
    } catch (e: any) {
      alert(`启动失败: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{padding: 8, borderRight: "1px solid #eee"}}>
      <h4>审定 Rounds</h4>
      {rounds.length === 0 && <div style={{color: "#888"}}>暂无</div>}
      {rounds.map(r => (
        <button key={r.id} onClick={() => onSelect(r)}
                style={{display: "block", width: "100%", textAlign: "left",
                        padding: 6, marginBottom: 4,
                        background: r.status === "open" ? "#fffceb" : "#f0f0f0",
                        border: "1px solid #ccc", borderRadius: 4}}>
          <div style={{fontSize: 12}}>
            {r.status} {r.outcome ? `(${r.outcome})` : ""}
          </div>
          <div style={{fontSize: 11, color: "#666"}}>
            reviewer: {r.reviewer_user_id}
          </div>
        </button>
      ))}
      {isAdmin && versionId && (
        <div style={{marginTop: 12, paddingTop: 12, borderTop: "1px dashed #ccc"}}>
          <input value={reviewerInput}
                 onChange={e => setReviewerInput(e.target.value)}
                 placeholder="reviewer username"
                 style={{width: "100%", padding: 4, boxSizing: "border-box"}}/>
          <button onClick={start} disabled={busy || !reviewerInput.trim()}
                  style={{marginTop: 4, width: "100%", padding: 6,
                          background: "#0a7", color: "#fff",
                          border: "none", borderRadius: 4,
                          cursor: busy ? "wait" : "pointer"}}>
            启动审定
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 8.2: Create ClauseAuditList**

Create `frontend/src/components/datapanel/standards/review/ClauseAuditList.tsx`:

```tsx
import React, { useEffect, useState } from "react";
import { StdClause, getVersionClauses } from "../standardsApi";

interface Props {
  versionId: string;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export default function ClauseAuditList({versionId, selectedId, onSelect}: Props) {
  const [clauses, setClauses] = useState<StdClause[]>([]);

  useEffect(() => {
    getVersionClauses(versionId).then(r => setClauses(r.clauses));
  }, [versionId]);

  return (
    <div style={{padding: 8, borderRight: "1px solid #eee", overflow: "auto"}}>
      <h4>条款</h4>
      {clauses.map(c => (
        <button key={c.id} onClick={() => onSelect(c.id)}
                style={{display: "block", width: "100%", textAlign: "left",
                        padding: 6, marginBottom: 2,
                        background: selectedId === c.id ? "#cef" : "transparent",
                        border: "1px solid #ddd", borderRadius: 4,
                        fontSize: 12}}>
          {c.clause_no || c.ordinal_path} {c.heading || ""}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 8.3: Create ReferenceAuditCard**

Create `frontend/src/components/datapanel/standards/review/ReferenceAuditCard.tsx`:

```tsx
import React, { useState } from "react";
import { patchReferenceStatus } from "../standardsApi";

interface ReferenceRow {
  id: string;
  citation_text: string;
  verification_status: 'pending' | 'approved' | 'rejected';
  target_kind: string;
}

interface Props {
  reference: ReferenceRow;
  roundId: string;
  onUpdated: () => void;
}

export default function ReferenceAuditCard({reference, roundId, onUpdated}: Props) {
  const [busy, setBusy] = useState(false);

  const decide = async (status: 'approved' | 'rejected') => {
    setBusy(true);
    try {
      await patchReferenceStatus(reference.id, roundId, status);
      onUpdated();
    } catch (e: any) {
      alert(`更新失败: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  const badge = {pending: "🟠 待审", approved: "🟢 已通过",
                  rejected: "🔴 已驳回"}[reference.verification_status];

  return (
    <div style={{padding: 8, marginBottom: 6,
                  border: "1px solid #ddd", borderRadius: 4}}>
      <div style={{fontSize: 11, color: "#666"}}>
        {badge} · {reference.target_kind}
      </div>
      <div style={{fontSize: 12, margin: "4px 0"}}>
        {reference.citation_text}
      </div>
      {reference.verification_status === "pending" && (
        <div style={{display: "flex", gap: 6}}>
          <button onClick={() => decide("approved")} disabled={busy}
                  style={{flex: 1, padding: 4, background: "#0a7",
                          color: "#fff", border: "none", borderRadius: 3}}>
            通过
          </button>
          <button onClick={() => decide("rejected")} disabled={busy}
                  style={{flex: 1, padding: 4, background: "#c33",
                          color: "#fff", border: "none", borderRadius: 3}}>
            驳回
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 8.4: Create CommentThread**

Create `frontend/src/components/datapanel/standards/review/CommentThread.tsx`:

```tsx
import React, { useEffect, useState } from "react";
import { ReviewComment, listReviewComments, postReviewComment,
         resolveReviewComment } from "../standardsApi";

interface Props {
  roundId: string;
  clauseId: string;
  isReviewer: boolean;
}

export default function CommentThread({roundId, clauseId, isReviewer}: Props) {
  const [comments, setComments] = useState<ReviewComment[]>([]);
  const [draft, setDraft] = useState("");
  const [replyTo, setReplyTo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = () => {
    listReviewComments(roundId, clauseId).then(r => setComments(r.comments));
  };
  useEffect(refresh, [roundId, clauseId]);

  const post = async () => {
    if (!draft.trim()) return;
    setBusy(true);
    try {
      await postReviewComment(roundId, clauseId, draft.trim(),
                              replyTo ?? undefined);
      setDraft("");
      setReplyTo(null);
      refresh();
    } catch (e: any) {
      alert(`发表失败: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  const resolve = async (id: string,
                         resolution: 'accepted' | 'rejected' | 'duplicate') => {
    try {
      await resolveReviewComment(id, resolution);
      refresh();
    } catch (e: any) {
      alert(`解决失败: ${e.message}`);
    }
  };

  return (
    <div style={{padding: 8}}>
      <h4>评论 ({comments.filter(c => c.resolution === "open").length} 未决)</h4>
      {comments.map(c => (
        <div key={c.id}
             style={{padding: 6, marginBottom: 4,
                      marginLeft: c.parent_comment_id ? 16 : 0,
                      background: c.resolution === "open" ? "#fff8e8" : "#f5f5f5",
                      border: "1px solid #ddd", borderRadius: 4}}>
          <div style={{fontSize: 11, color: "#666"}}>
            {c.author_user_id} · {c.resolution}
          </div>
          <div style={{fontSize: 12, whiteSpace: "pre-wrap"}}>{c.body_md}</div>
          {isReviewer && c.resolution === "open" && (
            <div style={{display: "flex", gap: 4, marginTop: 4}}>
              <button onClick={() => resolve(c.id, "accepted")}
                      style={{fontSize: 11}}>✓ 接受</button>
              <button onClick={() => resolve(c.id, "rejected")}
                      style={{fontSize: 11}}>✗ 拒绝</button>
              <button onClick={() => resolve(c.id, "duplicate")}
                      style={{fontSize: 11}}>= 重复</button>
              <button onClick={() => setReplyTo(c.id)}
                      style={{fontSize: 11}}>↳ 回复</button>
            </div>
          )}
        </div>
      ))}
      {isReviewer && (
        <div style={{marginTop: 8}}>
          {replyTo && (
            <div style={{fontSize: 11, color: "#666"}}>
              回复: {replyTo.slice(0, 8)}…{" "}
              <button onClick={() => setReplyTo(null)}>取消</button>
            </div>
          )}
          <textarea value={draft} onChange={e => setDraft(e.target.value)}
                    placeholder="评论内容…"
                    rows={3} style={{width: "100%", boxSizing: "border-box"}}/>
          <button onClick={post} disabled={busy || !draft.trim()}
                  style={{padding: 6, background: "#0a7", color: "#fff",
                          border: "none", borderRadius: 4}}>
            发表
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 8.5: Create CloseRoundDialog**

Create `frontend/src/components/datapanel/standards/review/CloseRoundDialog.tsx`:

```tsx
import React, { useEffect, useState } from "react";
import { GatingPrecheck, closeReviewPrecheck, closeReviewRound } from "../standardsApi";

interface Props {
  roundId: string;
  isReviewer: boolean;
  onClosed: () => void;
}

export default function CloseRoundDialog({roundId, isReviewer, onClosed}: Props) {
  const [pre, setPre] = useState<GatingPrecheck | null>(null);
  const [outcome, setOutcome] = useState<'approved' | 'rejected'>("approved");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    closeReviewPrecheck(roundId).then(setPre).catch(() => setPre(null));
  }, [roundId]);

  const submit = async () => {
    setBusy(true);
    try {
      await closeReviewRound(roundId, outcome);
      onClosed();
    } catch (e: any) {
      alert(`关闭失败: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{padding: 8, borderLeft: "1px solid #eee"}}>
      <h4>关闭审定</h4>
      {pre && (
        <div style={{fontSize: 12, marginBottom: 8}}>
          <div>待审引用: {pre.pending_refs}</div>
          <div>未决评论: {pre.open_comments}</div>
          <div style={{color: pre.blocking ? "#c33" : "#0a7"}}>
            {pre.blocking ? "⛔ 阻塞中" : "✓ 通过"}
          </div>
        </div>
      )}
      {isReviewer && (
        <>
          <div style={{margin: "8px 0"}}>
            <label style={{display: "block"}}>
              <input type="radio" checked={outcome === "approved"}
                     onChange={() => setOutcome("approved")}/> 通过
            </label>
            <label style={{display: "block"}}>
              <input type="radio" checked={outcome === "rejected"}
                     onChange={() => setOutcome("rejected")}/> 驳回
            </label>
          </div>
          <button onClick={submit}
                  disabled={busy || (outcome === "approved" && !!pre?.blocking)}
                  style={{width: "100%", padding: 6, background: "#0a7",
                          color: "#fff", border: "none", borderRadius: 4}}>
            关闭 Round
          </button>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 8.6: Create ReviewSubTab**

Create `frontend/src/components/datapanel/standards/ReviewSubTab.tsx`:

```tsx
import React, { useEffect, useState } from "react";
import { ReviewRound } from "./standardsApi";
import RoundSelector from "./review/RoundSelector";
import ClauseAuditList from "./review/ClauseAuditList";
import ReferenceAuditCard from "./review/ReferenceAuditCard";
import CommentThread from "./review/CommentThread";
import CloseRoundDialog from "./review/CloseRoundDialog";

interface Props {
  versionId: string | null;
  userRole: string;
  username: string;
}

interface ReferenceRow {
  id: string;
  citation_text: string;
  verification_status: 'pending' | 'approved' | 'rejected';
  target_kind: string;
}

export default function ReviewSubTab({versionId, userRole, username}: Props) {
  const [round, setRound] = useState<ReviewRound | null>(null);
  const [clauseId, setClauseId] = useState<string | null>(null);
  const [refs, setRefs] = useState<ReferenceRow[]>([]);
  const [refsTick, setRefsTick] = useState(0);

  const isAdmin = userRole === "admin";
  const isReviewer = round !== null && (
    userRole === "admin" || round.reviewer_user_id === username
  );

  useEffect(() => {
    if (!round || !clauseId) { setRefs([]); return; }
    fetch(`/api/std/clauses/${clauseId}/references`)
      .then(r => r.ok ? r.json() : {references: []})
      .then(j => setRefs(j.references || []))
      .catch(() => setRefs([]));
  }, [round, clauseId, refsTick]);

  if (!versionId) {
    return <div style={{padding: 24, color: "#888"}}>
      请先在「分析」选择一个文档版本
    </div>;
  }

  const pendingCount = refs.filter(r => r.verification_status === "pending").length;

  return (
    <div style={{display: "grid",
                  gridTemplateColumns: "20% 25% 35% 20%",
                  height: "100%"}}>
      <RoundSelector versionId={versionId} isAdmin={isAdmin}
                     onSelect={setRound}/>
      {round ? (
        <>
          <ClauseAuditList versionId={versionId}
                            selectedId={clauseId}
                            onSelect={setClauseId}/>
          <div style={{padding: 8, overflow: "auto"}}>
            {clauseId && (
              <>
                <h4>引用 ({pendingCount} 待审)</h4>
                {refs.length === 0 && <div style={{color:"#888"}}>无引用</div>}
                {refs.map(r => (
                  <ReferenceAuditCard
                    key={r.id} reference={r} roundId={round.id}
                    onUpdated={() => setRefsTick(t => t + 1)}/>
                ))}
                <CommentThread roundId={round.id} clauseId={clauseId}
                               isReviewer={isReviewer}/>
              </>
            )}
          </div>
          <CloseRoundDialog roundId={round.id} isReviewer={isReviewer}
                            onClosed={() => setRound(null)}/>
        </>
      ) : (
        <div style={{gridColumn: "2 / 5", padding: 24, color: "#888"}}>
          请选择一个 round
        </div>
      )}
    </div>
  );
}
```

Note: ReviewSubTab depends on `GET /api/std/clauses/{id}/references` returning `{references: [...]}`. The existing standards routes already include this endpoint per Wave 1; if it returns a different shape than expected, the .catch falls back to empty list (no crash).

- [ ] **Step 8.7: Verify TS compiles**

Run:
```powershell
cd frontend
npm run build
cd ..
```
Expected: exit 0.

- [ ] **Step 8.8: Commit**

```powershell
git add frontend/src/components/datapanel/standards/ReviewSubTab.tsx frontend/src/components/datapanel/standards/review/
git commit -m "feat(std-platform-fe): ReviewSubTab + 5 review sub-components"
```

---

## Task 9: Wire ReviewSubTab into StandardsTab + thread userRole

**Files:**
- Modify: `frontend/src/components/datapanel/StandardsTab.tsx` (enable review tab + import ReviewSubTab)
- Modify: `frontend/src/components/datapanel/DataPanel.tsx` (or whichever parent threads userRole — pass it to StandardsTab)
- Modify: `frontend/src/App.tsx:262` (pass username + role to DataPanel)

- [ ] **Step 9.1: Find DataPanel and inspect userRole flow**

Run:
```powershell
grep -rn "DataPanel\|StandardsTab" frontend/src/ | head -10
```
Identify the parent that mounts `StandardsTab` and how `userRole` is currently passed.

- [ ] **Step 9.2: Update StandardsTab to accept userRole + username**

Replace `frontend/src/components/datapanel/StandardsTab.tsx` with:

```tsx
import React, { useState } from "react";
import IngestSubTab from "./standards/IngestSubTab";
import AnalyzeSubTab from "./standards/AnalyzeSubTab";
import DraftSubTab from "./standards/DraftSubTab";
import ReviewSubTab from "./standards/ReviewSubTab";

type Sub = "ingest" | "analyze" | "draft" | "review" | "publish" | "derive";

interface Props {
  userRole?: string;
  username?: string;
}

export default function StandardsTab({userRole = "", username = ""}: Props) {
  const [sub, setSub] = useState<Sub>("ingest");
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const isAdmin = userRole === "admin";
  const enabled: Set<Sub> = new Set(["ingest", "analyze", "draft", "review"]);

  return (
    <div style={{display:"flex", flexDirection:"column", height:"100%"}}>
      <div style={{display:"flex", gap:8, padding:8, borderBottom:"1px solid #eee"}}>
        {(["ingest","analyze","draft","review","publish","derive"] as Sub[]).map(k => (
          <button key={k}
            onClick={()=>setSub(k)}
            disabled={!enabled.has(k)}
            style={{padding:"4px 10px",
              background: sub===k ? "#0a7" : "transparent",
              color: sub===k ? "#fff" : "#444",
              border:"1px solid #ccc", borderRadius:4,
              opacity: enabled.has(k) ? 1 : 0.4,
              cursor: enabled.has(k) ? "pointer" : "not-allowed"}}>
            {({ingest:"采集", analyze:"分析", draft:"起草",
               review:"审定", publish:"发布", derive:"派生"} as Record<Sub,string>)[k]}
          </button>
        ))}
      </div>
      <div style={{flex:1, overflow:"auto"}}>
        {sub==="ingest" &&
          <IngestSubTab onPickVersion={(vid)=>{
            setSelectedVersionId(vid);
            setSub("analyze");
          }} />}
        {sub==="analyze" &&
          <AnalyzeSubTab versionId={selectedVersionId}/>}
        {sub==="draft" &&
          <DraftSubTab versionId={selectedVersionId} isAdmin={isAdmin} />}
        {sub==="review" &&
          <ReviewSubTab versionId={selectedVersionId}
                         userRole={userRole} username={username}/>}
      </div>
    </div>
  );
}
```

- [ ] **Step 9.3: Thread userRole + username through DataPanel**

Find DataPanel and ensure it passes `userRole` and `username` to `<StandardsTab>`. Inspect:

```powershell
grep -n "StandardsTab\|userRole\|user.username" frontend/src/components/DataPanel.tsx 2>$null; if ($LASTEXITCODE -ne 0) { Write-Host "DataPanel.tsx not found at this path; locate it via:"; grep -rln "StandardsTab" frontend/src }
```

If `DataPanel.tsx` already accepts `userRole`, just add `username` and forward both into `<StandardsTab userRole={userRole} username={username}/>`. If only `userRole` exists, add `username` to the props.

If `App.tsx` does not currently pass `username` to `<DataPanel>`, add it:

In `frontend/src/App.tsx` around line 262, replace:
```tsx
<DataPanel dataFile={dataFile} userRole={userRole} />
```
with:
```tsx
<DataPanel dataFile={dataFile} userRole={userRole} username={user?.identifier || ""} />
```

And update DataPanel's props/interface accordingly.

- [ ] **Step 9.4: Verify build**

Run:
```powershell
cd frontend
npm run build
cd ..
```
Expected: exit 0.

- [ ] **Step 9.5: Commit**

```powershell
git add frontend/src/components/datapanel/StandardsTab.tsx frontend/src/components/datapanel/DataPanel.tsx frontend/src/App.tsx
git commit -m "feat(std-platform-fe): wire ReviewSubTab into StandardsTab + thread userRole/username"
```

(If only StandardsTab needed changing because DataPanel/App already had the role threaded, the git add will simply skip the unchanged files — that's fine.)

---

## Task 10: Regression gate

- [ ] **Step 10.1: Run full standards_platform suite**

Run:
```powershell
cd D:\adk
$env:PYTHONPATH="D:\adk"
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/ -v --tb=short
```
Expected: ≥ 145 passed (117 existing from Wave 3 + ~28 new). The single pre-existing `test_handlers.py::test_extract_requested_routes_to_extract_then_enqueues_structure` failure remains.

- [ ] **Step 10.2: Run auth tests**

Run:
```powershell
.venv\Scripts\python.exe -m pytest data_agent/test_auth.py -v
```
Expected: PASS (1+ tests).

- [ ] **Step 10.3: Run full project suite**

Run:
```powershell
.venv\Scripts\python.exe -m pytest data_agent/ --ignore=data_agent/test_knowledge_agent.py -q --tb=no
```
Expected: same green count as before this PR + the new tests; the 81 pre-existing failures remain.

- [ ] **Step 10.4: Run frontend build**

Run:
```powershell
cd frontend
npm run build
cd ..
```
Expected: exit 0.

- [ ] **Step 10.5: Manual browser smoke (user)**

Hand off to user with this script:

1. Restart chainlit if needed: `.\scripts\restart_chainlit.ps1`
2. Login as admin/admin123. DataPanel → 数据标准 → 采集 → upload a docx → wait for processing.
3. → 分析 → pick a version. → 起草 → insert 2-3 citations. Save.
4. → 审定 → 「启动审定」 → reviewer = "admin" (self). Verify status = open + version becomes `reviewing`.
5. Try → 起草 → edit clause → expect 409 banner.
6. Back to 审定 → click each clause → see references → approve/reject each.
7. Post a comment on a clause → reply to it → resolve it.
8. Footer: 「关闭审定」 → precheck shows blocking? Fix remaining items. Outcome=approved → close.
9. SQL verify:
   ```sql
   SELECT v.status, r.status, r.outcome, r.closed_at
     FROM std_document_version v
     JOIN std_review_round r ON r.document_version_id = v.id
    ORDER BY r.closed_at DESC NULLS LAST LIMIT 1;
   ```
   Expected: `v.status='approved'`, `r.status='closed'`, `r.outcome='approved'`, `closed_at` non-null.

- [ ] **Step 10.6: Push branch**

```powershell
git push origin feat/v12-extensible-platform
```

---

## Done criteria

- 9 commits land on `feat/v12-extensible-platform` covering Tasks 1-9.
- `pytest data_agent/standards_platform/` ≥ 145 green (28 new tests added).
- Auth + drafting + frontend regression checks all pass.
- Manual browser smoke (Step 10.5) succeeds.
- MEMORY.md handoff entry written separately after merge / push.

