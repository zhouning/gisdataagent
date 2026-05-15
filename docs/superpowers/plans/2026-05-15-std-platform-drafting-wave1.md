# Standards Platform — Drafting Wave 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the 起草 (drafting) sub-tab MVP — a TipTap WYSIWYG editor for `std_clause.body_md` with 15-minute clause-level optimistic concurrency lock, lazy checksum backfill, optimistic save via `If-Match`, and admin force-break with audit-log.

**Architecture:** New `data_agent/standards_platform/drafting/editor_session.py` exposes 5 transactional functions wrapped in raw SQL on `std_clause`. Five new routes appended to `data_agent/api/standards_routes.py` map two custom exceptions (`LockError`, `ConflictError`) to HTTP 409/410/423. Frontend adds `DraftSubTab` (3-column layout) with TipTap StarterKit + marked + turndown for Markdown round-trip. No DB migration — `std_clause` already has `lock_holder`, `lock_expires_at`, `checksum`, `body_md`, `body_html`, `updated_by`.

**Tech Stack:** Python 3.13 + SQLAlchemy raw SQL + Starlette routes + pytest + React 18 + TipTap 2.x + marked 12 + turndown 7 + TypeScript.

**Spec:** `docs/superpowers/specs/2026-05-15-std-platform-drafting-wave1-design.md`

---

## File Structure

**Backend (created)**
- `data_agent/standards_platform/drafting/__init__.py`
- `data_agent/standards_platform/drafting/editor_session.py` — five functions + two exceptions + `compute_checksum`
- `data_agent/standards_platform/tests/test_editor_session.py` — 12 unit tests
- `data_agent/standards_platform/tests/test_api_drafting.py` — 5 API tests

**Backend (modified)**
- `data_agent/api/standards_routes.py` — append 5 endpoints + role check helpers

**Frontend (created)**
- `frontend/src/components/datapanel/standards/DraftSubTab.tsx` — 3-column layout host
- `frontend/src/components/datapanel/standards/draft/ClauseTree.tsx` — left, list of clauses, click to select
- `frontend/src/components/datapanel/standards/draft/ClauseEditor.tsx` — center, TipTap, lock state machine, save
- `frontend/src/components/datapanel/standards/draft/ClauseMeta.tsx` — right, read-only metadata

**Frontend (modified)**
- `frontend/src/components/datapanel/standards/standardsApi.ts` — add 5 fetch functions + `StdClauseDetail` type
- `frontend/src/components/datapanel/StandardsTab.tsx` — remove `"draft"` from disabled set + plumb selectedVersionId
- `frontend/package.json` — `@tiptap/react`, `@tiptap/starter-kit`, `@tiptap/extension-placeholder`, `@tiptap/extension-link`, `marked`, `turndown`

---
## Task 1: Create `drafting` package skeleton + `compute_checksum`

**Files:**
- Create: `data_agent/standards_platform/drafting/__init__.py`
- Create: `data_agent/standards_platform/drafting/editor_session.py`
- Create: `data_agent/standards_platform/tests/test_editor_session.py`

- [ ] **Step 1: Write the failing checksum test**

Create `data_agent/standards_platform/tests/test_editor_session.py`:

```python
"""Unit tests for editor_session."""
from __future__ import annotations

import pytest
from data_agent.standards_platform.drafting.editor_session import compute_checksum


def test_compute_checksum_is_stable():
    assert compute_checksum("hello") == compute_checksum("hello")


def test_compute_checksum_changes_with_content():
    assert compute_checksum("hello") != compute_checksum("hello!")


def test_compute_checksum_returns_16_hex():
    c = compute_checksum("any content")
    assert len(c) == 16
    int(c, 16)  # must be valid hex
```

- [ ] **Step 2: Run test, verify ImportError failure**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_editor_session.py -q
```

Expected: 3 errors with `ModuleNotFoundError: No module named 'data_agent.standards_platform.drafting'`.

- [ ] **Step 3: Create empty package init**

`data_agent/standards_platform/drafting/__init__.py`:

```python
"""Drafting subsystem — clause-level optimistic editing with locks."""
```

- [ ] **Step 4: Implement `compute_checksum` and exceptions**

`data_agent/standards_platform/drafting/editor_session.py`:

```python
"""Clause editor session — acquire/heartbeat/release/save/break_lock.

All five operations open their own transaction on the singleton engine
returned by data_agent.db_engine.get_engine() and emit raw SQL against
std_clause and agent_audit_log.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import text

from ...db_engine import get_engine
from ...observability import get_logger

logger = get_logger("standards_platform.drafting.editor_session")


class LockError(Exception):
    """Raised when the caller cannot hold or no longer holds the lock."""

    def __init__(self, message: str, *, holder: str | None = None,
                 expires_at: Any | None = None):
        super().__init__(message)
        self.holder = holder
        self.expires_at = expires_at


class ConflictError(Exception):
    """Optimistic concurrency conflict on save (If-Match mismatch)."""

    def __init__(self, server_checksum: str, server_body_md: str):
        super().__init__("checksum mismatch")
        self.server_checksum = server_checksum
        self.server_body_md = server_body_md


def compute_checksum(body_md: str) -> str:
    """Truncated SHA-256 hex of the markdown body. 16 chars = 64 bits."""
    return hashlib.sha256(body_md.encode("utf-8")).hexdigest()[:16]
```

- [ ] **Step 5: Run tests, verify pass**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_editor_session.py -q
```

Expected: `3 passed`.

- [ ] **Step 6: Commit**

```
git add data_agent/standards_platform/drafting/ data_agent/standards_platform/tests/test_editor_session.py
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "feat(std-platform): drafting package skeleton + compute_checksum"
```

---
## Task 2: Test fixtures — temp document/version/clause helpers

**Files:**
- Modify: `data_agent/standards_platform/tests/test_editor_session.py`

- [ ] **Step 1: Add fixtures at the top of the test file**

Insert after the imports block:

```python
import uuid
from sqlalchemy import text as _sql
from data_agent.db_engine import get_engine

@pytest.fixture
def db():
    eng = get_engine()
    if eng is None:
        pytest.skip("DB engine unavailable")
    return eng


@pytest.fixture
def clause_row(db):
    """Insert a throwaway document/version/clause and yield (clause_id, vid).
    Clean up at teardown via document CASCADE."""
    doc_id = str(uuid.uuid4())
    ver_id = str(uuid.uuid4())
    clause_id = str(uuid.uuid4())
    with db.begin() as conn:
        conn.execute(_sql("""
            INSERT INTO std_document (id, doc_code, title, source_type, status,
                                       owner_user_id)
            VALUES (:i, :c, :t, 'draft', 'ingested', 'test')
        """), {"i": doc_id, "c": f"T-EDIT-{doc_id[:6]}", "t": "test-edit"})
        conn.execute(_sql("""
            INSERT INTO std_document_version (id, document_id, version_label,
                                               status)
            VALUES (:i, :d, 'v1.0', 'draft')
        """), {"i": ver_id, "d": doc_id})
        conn.execute(_sql("""
            INSERT INTO std_clause (id, document_id, document_version_id,
                                     ordinal_path, clause_no, kind, body_md)
            VALUES (:i, :d, :v, CAST('1' AS ltree), '1', 'clause',
                    'initial body')
        """), {"i": clause_id, "d": doc_id, "v": ver_id})
    yield clause_id, ver_id, doc_id
    with db.begin() as conn:
        conn.execute(_sql("DELETE FROM std_document WHERE id=:d"),
                     {"d": doc_id})
```

- [ ] **Step 2: Smoke-test the fixture**

Append:

```python
def test_clause_fixture_round_trips(db, clause_row):
    cid, _vid, _did = clause_row
    with db.connect() as c:
        row = c.execute(_sql(
            "SELECT body_md FROM std_clause WHERE id=:i"
        ), {"i": cid}).first()
    assert row is not None
    assert row[0] == "initial body"
```

- [ ] **Step 3: Run, verify pass**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_editor_session.py -q
```

Expected: `4 passed`.

- [ ] **Step 4: Commit**

```
git add data_agent/standards_platform/tests/test_editor_session.py
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "test(std-platform): clause_row fixture for editor_session tests"
```

---

## Task 3: Implement `acquire_lock` (4 test variants)

**Files:**
- Modify: `data_agent/standards_platform/drafting/editor_session.py`
- Modify: `data_agent/standards_platform/tests/test_editor_session.py`

- [ ] **Step 1: Write 4 failing tests**

Append to `test_editor_session.py`:

```python
from datetime import datetime, timezone, timedelta
from data_agent.standards_platform.drafting.editor_session import (
    LockError, acquire_lock,
)


def _holder(db, cid):
    with db.connect() as c:
        return c.execute(_sql(
            "SELECT lock_holder, lock_expires_at FROM std_clause WHERE id=:i"
        ), {"i": cid}).first()


def test_acquire_lock_when_unlocked(db, clause_row):
    cid, _vid, _did = clause_row
    out = acquire_lock(cid, "alice")
    assert out["body_md"] == "initial body"
    assert out["checksum"]              # backfilled
    holder, exp = _holder(db, cid)
    assert holder == "alice"
    assert exp > datetime.now(timezone.utc) + timedelta(minutes=14)


def test_acquire_lock_when_held_by_other(db, clause_row):
    cid, _vid, _did = clause_row
    acquire_lock(cid, "alice")
    with pytest.raises(LockError) as exc:
        acquire_lock(cid, "bob")
    assert exc.value.holder == "alice"


def test_acquire_lock_when_expired_steals(db, clause_row):
    cid, _vid, _did = clause_row
    acquire_lock(cid, "alice")
    with db.begin() as c:
        c.execute(_sql(
            "UPDATE std_clause SET lock_expires_at = now() - interval '1 min' "
            "WHERE id=:i"
        ), {"i": cid})
    out = acquire_lock(cid, "bob")
    assert out["checksum"]
    holder, _exp = _holder(db, cid)
    assert holder == "bob"


def test_acquire_lock_same_user_renews(db, clause_row):
    cid, _vid, _did = clause_row
    acquire_lock(cid, "alice")
    out = acquire_lock(cid, "alice")
    assert out["body_md"] == "initial body"
    holder, _ = _holder(db, cid)
    assert holder == "alice"
```

- [ ] **Step 2: Run, verify 4 failures**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_editor_session.py::test_acquire_lock_when_unlocked -q
```

Expected: `ImportError: cannot import name 'acquire_lock'`.

- [ ] **Step 3: Implement `acquire_lock`**

Append to `editor_session.py`:

```python
_DEFAULT_TTL_MIN = 15


def acquire_lock(clause_id: str, user_id: str,
                 *, ttl_minutes: int = _DEFAULT_TTL_MIN) -> dict:
    """Atomically acquire or renew the edit lock on a clause.

    On first acquire of a clause whose checksum is NULL (P0 backfill case),
    we lazily compute and persist the checksum from the current body_md.
    """
    eng = get_engine()
    if eng is None:
        raise RuntimeError("DB engine unavailable")
    with eng.begin() as conn:
        row = conn.execute(text("""
            SELECT body_md, checksum FROM std_clause WHERE id=:c FOR UPDATE
        """), {"c": clause_id}).first()
        if row is None:
            raise LookupError(f"clause {clause_id} not found")
        body_md = row.body_md or ""
        checksum = row.checksum or compute_checksum(body_md)

        updated = conn.execute(text(f"""
            UPDATE std_clause
               SET lock_holder=:u,
                   lock_expires_at=now() + (:ttl || ' minutes')::interval,
                   checksum=:chk
             WHERE id=:c
               AND (lock_holder IS NULL
                    OR lock_holder=:u
                    OR lock_expires_at < now())
            RETURNING body_md, body_html, checksum, lock_expires_at
        """), {"c": clause_id, "u": user_id, "ttl": str(ttl_minutes),
               "chk": checksum}).first()
        if updated is None:
            held = conn.execute(text(
                "SELECT lock_holder, lock_expires_at FROM std_clause "
                "WHERE id=:c"
            ), {"c": clause_id}).first()
            raise LockError("clause is locked by another user",
                            holder=held.lock_holder if held else None,
                            expires_at=held.lock_expires_at if held else None)
        return {
            "body_md": updated.body_md or "",
            "body_html": updated.body_html,
            "checksum": updated.checksum,
            "lock_expires_at": updated.lock_expires_at,
            "lock_token": user_id,
        }
```

- [ ] **Step 4: Run all tests, verify pass**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_editor_session.py -q
```

Expected: `8 passed`.

- [ ] **Step 5: Commit**

```
git add data_agent/standards_platform/drafting/editor_session.py data_agent/standards_platform/tests/test_editor_session.py
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "feat(std-platform): acquire_lock with lazy checksum backfill"
```

---
## Task 4: Implement `heartbeat` (2 tests)

**Files:**
- Modify: `data_agent/standards_platform/drafting/editor_session.py`
- Modify: `data_agent/standards_platform/tests/test_editor_session.py`

- [ ] **Step 1: Write 2 failing tests**

Append:

```python
from data_agent.standards_platform.drafting.editor_session import heartbeat
import time


def test_heartbeat_extends_expiry(db, clause_row):
    cid, _vid, _did = clause_row
    first = acquire_lock(cid, "alice")
    time.sleep(1)
    second = heartbeat(cid, "alice")
    assert second["lock_expires_at"] > first["lock_expires_at"]


def test_heartbeat_lost_lock_raises(db, clause_row):
    cid, _vid, _did = clause_row
    with pytest.raises(LockError):
        heartbeat(cid, "alice")
```

- [ ] **Step 2: Run, verify 2 failures**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_editor_session.py::test_heartbeat_extends_expiry -q
```

Expected: `ImportError`.

- [ ] **Step 3: Implement `heartbeat`**

Append to `editor_session.py`:

```python
def heartbeat(clause_id: str, user_id: str,
              *, ttl_minutes: int = _DEFAULT_TTL_MIN) -> dict:
    """Extend the lock TTL. Raises LockError if lock no longer held."""
    eng = get_engine()
    if eng is None:
        raise RuntimeError("DB engine unavailable")
    with eng.begin() as conn:
        row = conn.execute(text("""
            UPDATE std_clause
               SET lock_expires_at = now() + (:ttl || ' minutes')::interval
             WHERE id=:c
               AND lock_holder=:u
               AND (lock_expires_at IS NULL OR lock_expires_at >= now())
            RETURNING lock_expires_at
        """), {"c": clause_id, "u": user_id, "ttl": str(ttl_minutes)}).first()
        if row is None:
            raise LockError("lock no longer held")
        return {"lock_expires_at": row.lock_expires_at}
```

- [ ] **Step 4: Run all tests, verify pass**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_editor_session.py -q
```

Expected: `10 passed`.

- [ ] **Step 5: Commit**

```
git add data_agent/standards_platform/drafting/editor_session.py data_agent/standards_platform/tests/test_editor_session.py
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "feat(std-platform): heartbeat for clause lock TTL extension"
```

---

## Task 5: Implement `save_clause` (3 tests)

**Files:**
- Modify: `data_agent/standards_platform/drafting/editor_session.py`
- Modify: `data_agent/standards_platform/tests/test_editor_session.py`

- [ ] **Step 1: Write 3 failing tests**

Append:

```python
from data_agent.standards_platform.drafting.editor_session import (
    save_clause, ConflictError,
)


def test_save_clause_happy_path(db, clause_row):
    cid, _vid, _did = clause_row
    a = acquire_lock(cid, "alice")
    out = save_clause(cid, "alice",
                      if_match_checksum=a["checksum"],
                      body_md="updated body", body_html="<p>updated body</p>")
    assert out["checksum"] != a["checksum"]
    with db.connect() as c:
        row = c.execute(_sql(
            "SELECT body_md, body_html, updated_by FROM std_clause WHERE id=:i"
        ), {"i": cid}).first()
    assert row.body_md == "updated body"
    assert row.body_html == "<p>updated body</p>"
    assert row.updated_by == "alice"


def test_save_clause_checksum_mismatch_raises_conflict(db, clause_row):
    cid, _vid, _did = clause_row
    acquire_lock(cid, "alice")
    with pytest.raises(ConflictError) as exc:
        save_clause(cid, "alice",
                    if_match_checksum="0000000000000000",
                    body_md="x", body_html=None)
    assert exc.value.server_body_md == "initial body"


def test_save_clause_lost_lock_raises(db, clause_row):
    cid, _vid, _did = clause_row
    a = acquire_lock(cid, "alice")
    with db.begin() as c:
        c.execute(_sql(
            "UPDATE std_clause SET lock_holder=NULL WHERE id=:i"
        ), {"i": cid})
    with pytest.raises(LockError):
        save_clause(cid, "alice",
                    if_match_checksum=a["checksum"],
                    body_md="x", body_html=None)
```

- [ ] **Step 2: Run, verify 3 failures**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_editor_session.py::test_save_clause_happy_path -q
```

Expected: `ImportError`.

- [ ] **Step 3: Implement `save_clause`**

Append to `editor_session.py`:

```python
def save_clause(clause_id: str, user_id: str, *,
                if_match_checksum: str,
                body_md: str, body_html: str | None) -> dict:
    """Optimistic save. Verifies If-Match checksum and lock ownership."""
    eng = get_engine()
    if eng is None:
        raise RuntimeError("DB engine unavailable")
    with eng.begin() as conn:
        row = conn.execute(text("""
            SELECT checksum, body_md, lock_holder, lock_expires_at
              FROM std_clause WHERE id=:c FOR UPDATE
        """), {"c": clause_id}).first()
        if row is None:
            raise LookupError(f"clause {clause_id} not found")
        if row.checksum != if_match_checksum:
            raise ConflictError(server_checksum=row.checksum or "",
                                server_body_md=row.body_md or "")
        if (row.lock_holder != user_id
                or row.lock_expires_at is None
                or row.lock_expires_at < _now_utc()):
            raise LockError("lock no longer held")
        new_chk = compute_checksum(body_md)
        updated = conn.execute(text("""
            UPDATE std_clause
               SET body_md=:b, body_html=:h, checksum=:k,
                   updated_at=now(), updated_by=:u
             WHERE id=:c
            RETURNING checksum, updated_at
        """), {"c": clause_id, "u": user_id, "b": body_md,
               "h": body_html, "k": new_chk}).first()
        return {"checksum": updated.checksum, "updated_at": updated.updated_at}
```

Insert helper near the top of the file (after imports):

```python
from datetime import datetime, timezone


def _now_utc():
    return datetime.now(timezone.utc)
```

- [ ] **Step 4: Run all tests, verify pass**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_editor_session.py -q
```

Expected: `13 passed`.

- [ ] **Step 5: Commit**

```
git add data_agent/standards_platform/drafting/editor_session.py data_agent/standards_platform/tests/test_editor_session.py
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "feat(std-platform): save_clause with optimistic concurrency"
```

---
## Task 6: Implement `release_lock` (1 test, idempotent)

**Files:**
- Modify: `data_agent/standards_platform/drafting/editor_session.py`
- Modify: `data_agent/standards_platform/tests/test_editor_session.py`

- [ ] **Step 1: Write failing test**

Append:

```python
from data_agent.standards_platform.drafting.editor_session import release_lock


def test_release_lock_idempotent(db, clause_row):
    cid, _vid, _did = clause_row
    acquire_lock(cid, "alice")
    release_lock(cid, "alice")
    release_lock(cid, "alice")  # second call: no-op, no exception
    holder, _ = _holder(db, cid)
    assert holder is None
```

- [ ] **Step 2: Run, verify failure**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_editor_session.py::test_release_lock_idempotent -q
```

Expected: `ImportError`.

- [ ] **Step 3: Implement `release_lock`**

Append:

```python
def release_lock(clause_id: str, user_id: str) -> None:
    """Idempotent release. No-op if user no longer holds the lock."""
    eng = get_engine()
    if eng is None:
        return
    with eng.begin() as conn:
        conn.execute(text("""
            UPDATE std_clause
               SET lock_holder=NULL, lock_expires_at=NULL
             WHERE id=:c AND lock_holder=:u
        """), {"c": clause_id, "u": user_id})
```

- [ ] **Step 4: Run all tests, verify pass**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_editor_session.py -q
```

Expected: `14 passed`.

- [ ] **Step 5: Commit**

```
git add data_agent/standards_platform/drafting/editor_session.py data_agent/standards_platform/tests/test_editor_session.py
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "feat(std-platform): idempotent release_lock"
```

---

## Task 7: Implement `break_lock` with audit log (1 test)

**Files:**
- Modify: `data_agent/standards_platform/drafting/editor_session.py`
- Modify: `data_agent/standards_platform/tests/test_editor_session.py`

- [ ] **Step 1: Write failing test**

Append:

```python
from data_agent.standards_platform.drafting.editor_session import break_lock


def test_break_lock_writes_audit(db, clause_row):
    cid, _vid, _did = clause_row
    acquire_lock(cid, "alice")
    out = break_lock(cid, "admin_user")
    assert out["previous_holder"] == "alice"
    holder, _ = _holder(db, cid)
    assert holder is None
    with db.connect() as c:
        n = c.execute(_sql(
            "SELECT COUNT(*) FROM agent_audit_log "
            "WHERE username=:u AND action='std_clause.lock.break' "
            "AND details->>'clause_id'=:c "
            "AND details->>'previous_holder'='alice'"
        ), {"u": "admin_user", "c": cid}).scalar()
    assert n >= 1
```

- [ ] **Step 2: Run, verify failure**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_editor_session.py::test_break_lock_writes_audit -q
```

Expected: `ImportError`.

- [ ] **Step 3: Implement `break_lock`**

Append:

```python
def break_lock(clause_id: str, admin_user_id: str) -> dict:
    """Admin force-break of a clause lock. Writes agent_audit_log entry."""
    eng = get_engine()
    if eng is None:
        raise RuntimeError("DB engine unavailable")
    with eng.begin() as conn:
        row = conn.execute(text(
            "SELECT lock_holder FROM std_clause WHERE id=:c FOR UPDATE"
        ), {"c": clause_id}).first()
        if row is None:
            raise LookupError(f"clause {clause_id} not found")
        previous_holder = row.lock_holder
        conn.execute(text(
            "UPDATE std_clause SET lock_holder=NULL, lock_expires_at=NULL "
            "WHERE id=:c"
        ), {"c": clause_id})
        meta = {"clause_id": clause_id, "previous_holder": previous_holder}
        conn.execute(text(
            "INSERT INTO agent_audit_log (username, action, details) "
            "VALUES (:u, 'std_clause.lock.break', CAST(:m AS jsonb))"
        ), {"u": admin_user_id, "m": json.dumps(meta)})
        logger.info("clause %s lock broken by %s (was held by %s)",
                    clause_id, admin_user_id, previous_holder)
        return {"previous_holder": previous_holder}
```

- [ ] **Step 4: Run all tests, verify pass**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_editor_session.py -q
```

Expected: `15 passed`.

- [ ] **Step 5: Add lazy-checksum coverage test**

Append:

```python
def test_lazy_checksum_on_first_acquire(db, clause_row):
    cid, _vid, _did = clause_row
    # P0 inserts may have NULL checksum; ensure backfill happens
    with db.begin() as c:
        c.execute(_sql("UPDATE std_clause SET checksum=NULL WHERE id=:i"),
                  {"i": cid})
    out = acquire_lock(cid, "alice")
    assert out["checksum"]
    with db.connect() as c:
        chk = c.execute(_sql(
            "SELECT checksum FROM std_clause WHERE id=:i"
        ), {"i": cid}).scalar()
    assert chk == compute_checksum("initial body")
```

- [ ] **Step 6: Run, verify pass**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_editor_session.py -q
```

Expected: `16 passed`.

- [ ] **Step 7: Commit**

```
git add data_agent/standards_platform/drafting/editor_session.py data_agent/standards_platform/tests/test_editor_session.py
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "feat(std-platform): break_lock with audit log + lazy checksum coverage"
```

---
## Task 8: Wire 5 REST routes into `standards_routes.py`

**Files:**
- Modify: `data_agent/api/standards_routes.py`

- [ ] **Step 1: Read current end of file to find the route table**

```
grep -n "Route(" data_agent/api/standards_routes.py | tail -15
```

Expected output: route list near the end with `routes = [...]` followed by `Route("/api/std/...")` entries.

- [ ] **Step 2: Add imports + role helper at top**

After the existing import block (around the `_EDITOR_ROLES` constant), add:

```python
from ..standards_platform.drafting import editor_session as _editor


def _require_editor_or_403(role: str | None) -> JSONResponse | None:
    if role not in _EDITOR_ROLES:
        return JSONResponse({"error": "Forbidden — editor role required"},
                            status_code=403)
    return None
```

- [ ] **Step 3: Add 5 route handler functions**

Append above the `routes = [...]` list:

```python
async def lock_clause(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    forbid = _require_editor_or_403(role)
    if forbid: return forbid
    cid = request.path_params["clause_id"]
    try:
        out = _editor.acquire_lock(cid, username)
    except _editor.LockError as e:
        return JSONResponse({"error": "Locked",
                             "holder": e.holder,
                             "expires_at": e.expires_at.isoformat()
                                if e.expires_at else None},
                            status_code=423)
    out["lock_expires_at"] = out["lock_expires_at"].isoformat()
    return JSONResponse(out)


async def heartbeat_clause(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    forbid = _require_editor_or_403(role)
    if forbid: return forbid
    cid = request.path_params["clause_id"]
    try:
        out = _editor.heartbeat(cid, username)
    except _editor.LockError:
        return JSONResponse({"error": "Lock lost"}, status_code=410)
    out["lock_expires_at"] = out["lock_expires_at"].isoformat()
    return JSONResponse(out)


async def release_clause_lock(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    forbid = _require_editor_or_403(role)
    if forbid: return forbid
    cid = request.path_params["clause_id"]
    _editor.release_lock(cid, username)
    return JSONResponse({"ok": True})


async def save_clause_route(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    forbid = _require_editor_or_403(role)
    if forbid: return forbid
    cid = request.path_params["clause_id"]
    if_match = request.headers.get("if-match", "")
    body = await request.json()
    try:
        out = _editor.save_clause(cid, username,
                                  if_match_checksum=if_match,
                                  body_md=body.get("body_md", ""),
                                  body_html=body.get("body_html"))
    except _editor.ConflictError as e:
        return JSONResponse({"error": "Conflict",
                             "server_checksum": e.server_checksum,
                             "server_body_md": e.server_body_md},
                            status_code=409)
    except _editor.LockError:
        return JSONResponse({"error": "Lock lost"}, status_code=410)
    out["updated_at"] = out["updated_at"].isoformat()
    return JSONResponse(out)


async def break_clause_lock(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    if role != "admin":
        return JSONResponse({"error": "Forbidden — admin only"},
                            status_code=403)
    cid = request.path_params["clause_id"]
    out = _editor.break_lock(cid, username)
    return JSONResponse(out)
```

- [ ] **Step 4: Append 5 routes to the `routes` list**

Inside the `routes = [...]` literal, before the closing `]`:

```python
    Route("/api/std/clauses/{clause_id}/lock",
          endpoint=lock_clause, methods=["POST"]),
    Route("/api/std/clauses/{clause_id}/heartbeat",
          endpoint=heartbeat_clause, methods=["POST"]),
    Route("/api/std/clauses/{clause_id}/lock/release",
          endpoint=release_clause_lock, methods=["POST"]),
    Route("/api/std/clauses/{clause_id}",
          endpoint=save_clause_route, methods=["PUT"]),
    Route("/api/std/clauses/{clause_id}/lock/break",
          endpoint=break_clause_lock, methods=["POST"]),
```

- [ ] **Step 5: Smoke check via Python — module imports cleanly**

```
.venv\Scripts\python.exe -c "from data_agent.api.standards_routes import routes; print(len(routes))"
```

Expected: number prints (was 12, now 17).

- [ ] **Step 6: Run all unit tests still pass**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_editor_session.py -q
```

Expected: `16 passed`.

- [ ] **Step 7: Commit**

```
git add data_agent/api/standards_routes.py
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "feat(std-platform): 5 drafting REST routes (lock/heartbeat/release/save/break)"
```

---

## Task 9: API integration tests

**Files:**
- Create: `data_agent/standards_platform/tests/test_api_drafting.py`

- [ ] **Step 1: Write 5 failing API tests**

```python
"""API smoke tests for drafting endpoints."""
from __future__ import annotations

import json
import uuid

import pytest
from starlette.testclient import TestClient

from data_agent.standards_platform.drafting.editor_session import (
    acquire_lock, compute_checksum,
)
from data_agent.standards_platform.tests.test_api_standards import (
    _client, _seed_doc as _seed_clause_doc,  # reuse if available
)


def _seed_clause():
    """Insert a throwaway clause and return clause_id."""
    from data_agent.db_engine import get_engine
    from sqlalchemy import text
    eng = get_engine()
    doc_id = str(uuid.uuid4()); ver_id = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    with eng.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_document (id, doc_code, title, source_type, "
            "status, owner_user_id) VALUES (:i, :c, 't', 'draft', "
            "'ingested', 'admin')"
        ), {"i": doc_id, "c": f"T-API-{doc_id[:6]}"})
        conn.execute(text(
            "INSERT INTO std_document_version (id, document_id, "
            "version_label, status) VALUES (:i, :d, 'v1.0', 'draft')"
        ), {"i": ver_id, "d": doc_id})
        conn.execute(text(
            "INSERT INTO std_clause (id, document_id, document_version_id, "
            "ordinal_path, clause_no, kind, body_md) VALUES (:i, :d, :v, "
            "CAST('1' AS ltree), '1', 'clause', 'hello')"
        ), {"i": cid, "d": doc_id, "v": ver_id})
    return cid, doc_id


@pytest.fixture
def fresh_clause():
    cid, did = _seed_clause()
    yield cid
    from data_agent.db_engine import get_engine
    from sqlalchemy import text
    with get_engine().begin() as c:
        c.execute(text("DELETE FROM std_document WHERE id=:d"), {"d": did})


def test_post_lock_returns_200(fresh_clause):
    r = _client().post(f"/api/std/clauses/{fresh_clause}/lock",
                       headers={"X-Test-User": "admin",
                                "X-Test-Role": "admin"})
    assert r.status_code == 200
    body = r.json()
    assert body["body_md"] == "hello"
    assert body["checksum"]


def test_post_lock_returns_423_when_held(fresh_clause):
    acquire_lock(fresh_clause, "alice")
    r = _client().post(f"/api/std/clauses/{fresh_clause}/lock",
                       headers={"X-Test-User": "admin",
                                "X-Test-Role": "admin"})
    assert r.status_code == 423
    assert r.json()["holder"] == "alice"


def test_put_clause_save_happy(fresh_clause):
    a = acquire_lock(fresh_clause, "admin")
    r = _client().put(f"/api/std/clauses/{fresh_clause}",
                      headers={"X-Test-User": "admin",
                               "X-Test-Role": "admin",
                               "If-Match": a["checksum"]},
                      json={"body_md": "new", "body_html": "<p>new</p>"})
    assert r.status_code == 200
    assert r.json()["checksum"] != a["checksum"]


def test_put_clause_returns_409_on_checksum_mismatch(fresh_clause):
    acquire_lock(fresh_clause, "admin")
    r = _client().put(f"/api/std/clauses/{fresh_clause}",
                      headers={"X-Test-User": "admin",
                               "X-Test-Role": "admin",
                               "If-Match": "0000000000000000"},
                      json={"body_md": "x", "body_html": None})
    assert r.status_code == 409
    assert r.json()["server_body_md"] == "hello"


def test_post_break_admin_only(fresh_clause):
    acquire_lock(fresh_clause, "alice")
    # As an analyst -> 403
    r = _client().post(f"/api/std/clauses/{fresh_clause}/lock/break",
                       headers={"X-Test-User": "u", "X-Test-Role": "analyst"})
    assert r.status_code == 403
    # As admin -> 200
    r = _client().post(f"/api/std/clauses/{fresh_clause}/lock/break",
                       headers={"X-Test-User": "admin",
                                "X-Test-Role": "admin"})
    assert r.status_code == 200
    assert r.json()["previous_holder"] == "alice"
```

- [ ] **Step 2: Verify `_client()` fixture exists in test_api_standards.py**

```
grep -n "def _client" data_agent/standards_platform/tests/test_api_standards.py
```

If missing, create a `_client()` factory in this new file that returns a `TestClient` with the auth-bypass `X-Test-User`/`X-Test-Role` middleware already used by P0 tests. Otherwise, reuse.

- [ ] **Step 3: Run, verify all 5 pass**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_api_drafting.py -q
```

Expected: `5 passed`.

- [ ] **Step 4: Run full standards_platform test suite**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/ -q
```

Expected: previous P0 count + 16 unit + 5 API = no regressions.

- [ ] **Step 5: Commit**

```
git add data_agent/standards_platform/tests/test_api_drafting.py
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "test(std-platform): 5 API smoke tests for drafting endpoints"
```

---
## Task 10: Install TipTap + Markdown deps and extend `standardsApi.ts`

**Files:**
- Modify: `frontend/package.json` (via npm install)
- Modify: `frontend/src/components/datapanel/standards/standardsApi.ts`

- [ ] **Step 1: Install npm deps**

```
cd D:\adk\frontend
npm install @tiptap/react@^2 @tiptap/starter-kit@^2 @tiptap/extension-placeholder@^2 @tiptap/extension-link@^2 marked@^12 turndown@^7
npm install --save-dev @types/turndown
```

Expected: `package.json` and `package-lock.json` updated, no errors.

- [ ] **Step 2: Append types and 5 fetch functions to `standardsApi.ts`**

```typescript
export interface StdClauseDetail extends StdClause {
  body_html?: string | null;
  checksum: string;
}

export interface AcquireLockResponse {
  body_md: string;
  body_html: string | null;
  checksum: string;
  lock_expires_at: string;     // ISO
  lock_token: string;
}

export interface LockedError {
  holder: string | null;
  expires_at: string | null;
}

export interface ConflictDetail {
  server_checksum: string;
  server_body_md: string;
}

export const acquireLock = async (clauseId: string)
    : Promise<AcquireLockResponse | { status: 423, body: LockedError }> => {
  const r = await fetch(`/api/std/clauses/${clauseId}/lock`, {method: "POST"});
  if (r.status === 423) return {status: 423, body: await r.json()};
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};

export const heartbeat = async (clauseId: string)
    : Promise<{lock_expires_at: string} | {status: 410}> => {
  const r = await fetch(`/api/std/clauses/${clauseId}/heartbeat`, {method: "POST"});
  if (r.status === 410) return {status: 410};
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};

export const releaseLock = async (clauseId: string): Promise<void> => {
  await fetch(`/api/std/clauses/${clauseId}/lock/release`, {method: "POST"});
};

export const saveClause = async (clauseId: string, ifMatch: string,
                                  bodyMd: string, bodyHtml: string)
    : Promise<{checksum: string, updated_at: string}
              | {status: 409, body: ConflictDetail}
              | {status: 410}> => {
  const r = await fetch(`/api/std/clauses/${clauseId}`, {
    method: "PUT",
    headers: {"Content-Type": "application/json", "If-Match": ifMatch},
    body: JSON.stringify({body_md: bodyMd, body_html: bodyHtml}),
  });
  if (r.status === 409) return {status: 409, body: await r.json()};
  if (r.status === 410) return {status: 410};
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};

export const breakLock = async (clauseId: string)
    : Promise<{previous_holder: string | null}> => {
  const r = await fetch(`/api/std/clauses/${clauseId}/lock/break`,
                        {method: "POST"});
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};
```

- [ ] **Step 3: Verify TypeScript compiles**

```
cd D:\adk\frontend
npx tsc --noEmit -p .
```

Expected: 0 errors.

- [ ] **Step 4: Commit**

```
git add frontend/package.json frontend/package-lock.json frontend/src/components/datapanel/standards/standardsApi.ts
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "feat(std-platform): install TipTap deps + 5 drafting fetch functions"
```

---

## Task 11: `ClauseMeta.tsx` (read-only right panel)

**Files:**
- Create: `frontend/src/components/datapanel/standards/draft/ClauseMeta.tsx`

- [ ] **Step 1: Write the component**

```tsx
import React from "react";
import { StdClause } from "../standardsApi";

interface Props {
  clause: StdClause | null;
  lockExpiresAt?: string | null;
  lastSavedAt?: string | null;
}

export default function ClauseMeta({clause, lockExpiresAt, lastSavedAt}: Props) {
  if (!clause) {
    return <div style={{padding: 12, color: "#888"}}>请选择左侧条款</div>;
  }
  return (
    <div style={{padding: 12, fontSize: 13, lineHeight: 1.6}}>
      <h4 style={{marginTop: 0}}>条款元信息</h4>
      <div><b>编号:</b> {clause.clause_no || "-"}</div>
      <div><b>标题:</b> {clause.heading || "-"}</div>
      <div><b>类型:</b> {clause.kind}</div>
      <div><b>路径:</b> <code>{clause.ordinal_path}</code></div>
      <hr style={{margin: "12px 0", border: 0, borderTop: "1px solid #eee"}}/>
      {lockExpiresAt && (
        <div><b>锁过期:</b> {new Date(lockExpiresAt).toLocaleTimeString()}</div>
      )}
      {lastSavedAt && (
        <div><b>上次保存:</b> {new Date(lastSavedAt).toLocaleString()}</div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify TS compiles**

```
cd D:\adk\frontend
npx tsc --noEmit -p .
```

Expected: 0 errors.

- [ ] **Step 3: Commit**

```
git add frontend/src/components/datapanel/standards/draft/ClauseMeta.tsx
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "feat(std-platform): ClauseMeta read-only metadata panel"
```

---

## Task 12: `ClauseTree.tsx` (left, clickable list)

**Files:**
- Create: `frontend/src/components/datapanel/standards/draft/ClauseTree.tsx`

- [ ] **Step 1: Write the component**

```tsx
import React, { useEffect, useState } from "react";
import { getVersionClauses, StdClause } from "../standardsApi";

interface Props {
  versionId: string;
  selectedId: string | null;
  onSelect: (c: StdClause) => void;
}

export default function ClauseTree({versionId, selectedId, onSelect}: Props) {
  const [items, setItems] = useState<StdClause[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getVersionClauses(versionId)
      .then(r => setItems(r.clauses))
      .catch(e => setErr(String(e)));
  }, [versionId]);

  if (err) return <div style={{padding: 12, color: "red"}}>{err}</div>;

  return (
    <div style={{padding: 8, overflow: "auto", height: "100%"}}>
      <h4 style={{marginTop: 0}}>条款（{items.length}）</h4>
      <ul style={{listStyle: "none", padding: 0, margin: 0}}>
        {items.map(c => (
          <li key={c.id}
              onClick={() => onSelect(c)}
              style={{
                padding: "6px 8px",
                cursor: "pointer",
                background: c.id === selectedId ? "#e6f7ee" : "transparent",
                borderLeft: c.id === selectedId ? "3px solid #0a7" : "3px solid transparent",
                fontSize: 13,
              }}>
            <b>{c.clause_no || "?"}</b>{" "}
            <span style={{color: "#666"}}>{c.heading || "(无标题)"}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 2: Verify TS compiles**

```
npx tsc --noEmit -p .
```

Expected: 0 errors.

- [ ] **Step 3: Commit**

```
git add frontend/src/components/datapanel/standards/draft/ClauseTree.tsx
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "feat(std-platform): ClauseTree left-pane component"
```

---
## Task 13: `ClauseEditor.tsx` (TipTap + lock state machine)

**Files:**
- Create: `frontend/src/components/datapanel/standards/draft/ClauseEditor.tsx`

- [ ] **Step 1: Write the component**

```tsx
import React, { useEffect, useRef, useState } from "react";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import Link from "@tiptap/extension-link";
import { marked } from "marked";
import TurndownService from "turndown";
import {
  acquireLock, heartbeat, releaseLock, saveClause, breakLock,
  StdClause, ConflictDetail,
} from "../standardsApi";

interface Props {
  clause: StdClause | null;
  isAdmin: boolean;
  onLockChange: (expiresAt: string | null) => void;
  onSaved: (when: string) => void;
}

type State =
  | { kind: "idle" }
  | { kind: "acquiring" }
  | { kind: "editing"; checksum: string; lockExpiresAt: string }
  | { kind: "lockedByOther"; holder: string | null; expiresAt: string | null }
  | { kind: "lost" }
  | { kind: "conflict"; server: ConflictDetail };

const turndown = new TurndownService();

export default function ClauseEditor({clause, isAdmin, onLockChange, onSaved}: Props) {
  const [state, setState] = useState<State>({kind: "idle"});
  const heartbeatRef = useRef<number | null>(null);

  const editor = useEditor({
    extensions: [StarterKit, Placeholder.configure({placeholder: "开始编写条款内容…"}), Link],
    editable: state.kind === "editing",
    content: "",
  }, [clause?.id]);

  // Keep editable in sync with state
  useEffect(() => {
    editor?.setEditable(state.kind === "editing");
  }, [editor, state.kind]);

  // Acquire lock when clause changes
  useEffect(() => {
    if (!clause || !editor) {
      setState({kind: "idle"});
      return;
    }
    setState({kind: "acquiring"});
    acquireLock(clause.id).then(r => {
      if ("status" in r && r.status === 423) {
        setState({kind: "lockedByOther",
                  holder: r.body.holder, expiresAt: r.body.expires_at});
        onLockChange(null);
        return;
      }
      const ok = r as Exclude<typeof r, {status: 423}>;
      const html = marked.parse(ok.body_md) as string;
      editor.commands.setContent(html, false);
      setState({kind: "editing", checksum: ok.checksum, lockExpiresAt: ok.lock_expires_at});
      onLockChange(ok.lock_expires_at);
      heartbeatRef.current = window.setInterval(async () => {
        const h = await heartbeat(clause.id);
        if ("status" in h && h.status === 410) {
          if (heartbeatRef.current) clearInterval(heartbeatRef.current);
          setState({kind: "lost"});
          onLockChange(null);
        } else if ("lock_expires_at" in h) {
          onLockChange(h.lock_expires_at);
        }
      }, 30_000);
    });
    return () => {
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
      if (clause) releaseLock(clause.id);
      onLockChange(null);
    };
  }, [clause?.id, editor]);

  const onSave = async () => {
    if (!clause || !editor || state.kind !== "editing") return;
    const html = editor.getHTML();
    const md = turndown.turndown(html);
    const r = await saveClause(clause.id, state.checksum, md, html);
    if ("status" in r && r.status === 409) {
      setState({kind: "conflict", server: r.body});
    } else if ("status" in r && r.status === 410) {
      setState({kind: "lost"});
      onLockChange(null);
    } else if ("checksum" in r) {
      setState({kind: "editing", checksum: r.checksum,
                lockExpiresAt: state.lockExpiresAt});
      onSaved(r.updated_at);
    }
  };

  const onForceBreak = async () => {
    if (!clause) return;
    await breakLock(clause.id);
    // Re-acquire
    setState({kind: "idle"});
    setTimeout(() => setState({kind: "acquiring"}), 100);
  };

  if (!clause) {
    return <div style={{padding: 24, color: "#888"}}>请从左侧选择条款开始编辑</div>;
  }

  return (
    <div style={{display: "flex", flexDirection: "column", height: "100%"}}>
      <div style={{padding: 8, background: state.kind === "editing" ? "#e6f7ee" :
                                          state.kind === "lockedByOther" ? "#fff3cd" :
                                          state.kind === "lost" ? "#fde2e2" : "#f4f4f4",
                   fontSize: 13, borderBottom: "1px solid #ddd"}}>
        {state.kind === "acquiring" && "🔄 正在获取锁…"}
        {state.kind === "editing" && `🟢 已加锁，${new Date(state.lockExpiresAt).toLocaleTimeString()} 后过期`}
        {state.kind === "lockedByOther" && (
          <span>
            🟡 被 <b>{state.holder}</b> 锁定中
            {isAdmin && <button onClick={onForceBreak} style={{marginLeft: 8}}>强制破锁</button>}
          </span>
        )}
        {state.kind === "lost" && "🔴 锁丢失，重新选择条款以继续"}
        {state.kind === "conflict" && "⚠️ 服务端版本已变化，下方按钮重置后再编辑"}
      </div>
      <div style={{flex: 1, overflow: "auto", padding: 12, background: "#fff"}}>
        <EditorContent editor={editor} />
      </div>
      <div style={{padding: 8, borderTop: "1px solid #ddd", display: "flex", gap: 8}}>
        <button onClick={onSave} disabled={state.kind !== "editing"}>保存</button>
        {state.kind === "conflict" && (
          <>
            <span style={{color: "#a60"}}>服务端版本：{state.server.server_body_md.slice(0, 60)}…</span>
            <button onClick={() => setState({kind: "idle"})}>关闭</button>
          </>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify TS compiles**

```
npx tsc --noEmit -p .
```

Expected: 0 errors.

- [ ] **Step 3: Commit**

```
git add frontend/src/components/datapanel/standards/draft/ClauseEditor.tsx
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "feat(std-platform): ClauseEditor with TipTap + lock state machine"
```

---
## Task 14: `DraftSubTab.tsx` + enable in `StandardsTab.tsx`

**Files:**
- Create: `frontend/src/components/datapanel/standards/DraftSubTab.tsx`
- Modify: `frontend/src/components/datapanel/StandardsTab.tsx`

- [ ] **Step 1: Write `DraftSubTab.tsx`**

```tsx
import React, { useState } from "react";
import ClauseTree from "./draft/ClauseTree";
import ClauseEditor from "./draft/ClauseEditor";
import ClauseMeta from "./draft/ClauseMeta";
import { StdClause } from "./standardsApi";

interface Props {
  versionId: string | null;
  isAdmin: boolean;
}

export default function DraftSubTab({versionId, isAdmin}: Props) {
  const [selected, setSelected] = useState<StdClause | null>(null);
  const [lockExp, setLockExp] = useState<string | null>(null);
  const [lastSaved, setLastSaved] = useState<string | null>(null);

  if (!versionId) {
    return <div style={{padding: 24, color: "#888"}}>
      请先在「分析」选择一个文档版本
    </div>;
  }

  return (
    <div style={{display: "grid",
                 gridTemplateColumns: "25% 50% 25%",
                 height: "100%"}}>
      <div style={{borderRight: "1px solid #eee"}}>
        <ClauseTree versionId={versionId}
                    selectedId={selected?.id ?? null}
                    onSelect={setSelected}/>
      </div>
      <div style={{borderRight: "1px solid #eee"}}>
        <ClauseEditor clause={selected}
                      isAdmin={isAdmin}
                      onLockChange={setLockExp}
                      onSaved={setLastSaved}/>
      </div>
      <div>
        <ClauseMeta clause={selected}
                    lockExpiresAt={lockExp}
                    lastSavedAt={lastSaved}/>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Modify `StandardsTab.tsx`**

Find the line:

```tsx
type Sub = "ingest" | "analyze" | "draft" | "review" | "publish" | "derive";
```

Replace the disabled set and the conditional renderers:

```tsx
import DraftSubTab from "./standards/DraftSubTab";

// ... inside the component, alongside the existing sub-tab conditionals:

// Update the disabled prop:
disabled={k!=="ingest" && k!=="analyze" && k!=="draft"}

// Update opacity / cursor checks similarly to include "draft".

// Add the conditional renderer:
{sub==="draft" &&
  <DraftSubTab versionId={selectedVersionId} isAdmin={true /* TODO: real role */} />}
```

(For Wave 1 we hardcode `isAdmin=true` since admin is the default seeded user; Wave 2 will read from session context.)

- [ ] **Step 3: Verify TS + build**

```
cd D:\adk\frontend
npm run build
```

Expected: exit 0, new bundle hash printed.

- [ ] **Step 4: Commit**

```
git add frontend/src/components/datapanel/standards/DraftSubTab.tsx frontend/src/components/datapanel/StandardsTab.tsx
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "feat(std-platform): DraftSubTab three-column layout + enable in StandardsTab"
```

---

## Task 15: Manual E2E verification

**Files:** none — runtime verification only.

- [ ] **Step 1: Restart Chainlit so it picks up route changes**

```
Get-WmiObject Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like "*chainlit*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
$env:PYTHONPATH = "D:\adk"
$env:NO_PROXY = "119.3.175.198,localhost,127.0.0.1"
cd D:\adk
Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList "-m","chainlit","run","data_agent/app.py","-w" -RedirectStandardOutput "D:\adk\chainlit_stdout.log" -RedirectStandardError "D:\adk\chainlit_stderr.log" -NoNewWindow
```

Wait until log shows `app is available` (~15s).

- [ ] **Step 2: Verify route count via curl (no auth)**

```
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/std/clauses/00000000-0000-0000-0000-000000000000/lock -X POST
```

Expected: `401` (unauth — route exists).

- [ ] **Step 3: Browser checklist**

1. Hard refresh `http://localhost:8000` (Ctrl+Shift+R), login `admin` / `admin123`
2. DataPanel → 数据标准 → 分析 → 选 GBT+21010 → 进入分析
3. 切到「起草」sub-tab — 应该看到三列布局，左侧 9 条 RT.x clauses
4. 点 RT.1 — 编辑器加载 body_md，状态条绿色「已加锁」，右侧元信息显示
5. 修改内容，点「保存」 — 状态条更新「上次保存」时间
6. 开隐身窗口，admin 登录，进入同一 clause — 状态条黄色「被 admin 锁定中」+「强制破锁」按钮
7. 在隐身窗口点「强制破锁」，回到主窗口刷新 clause — 状态条红色「锁丢失」
8. 验证 audit log:
   ```
   .venv\Scripts\python.exe -c "from data_agent.db_engine import get_engine; from sqlalchemy import text; eng=get_engine(); print(eng.connect().execute(text(\"SELECT username, action, details FROM agent_audit_log WHERE action='std_clause.lock.break' ORDER BY created_at DESC LIMIT 3\")).fetchall())"
   ```
   Expected: at least 1 row showing `action='std_clause.lock.break'`.

- [ ] **Step 4: Run full pytest sweep, no regressions**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/ -q
```

Expected: all green. (P0: ~50 tests + new 16 unit + 5 API.)

- [ ] **Step 5: Update memory**

Append to `C:\Users\zn198\.claude\projects\D--adk\memory\MEMORY.md` a one-line entry under «最新状态» pointing to a new file `std_platform_drafting_wave1_20260515.md` summarising delivery and open follow-ups (Wave 2 citation assistant, Wave 3 AI suggestions, real role plumbing for `isAdmin`).

- [ ] **Step 6: Final commit + push**

```
cd D:\adk
git status --short
git push origin feat/v12-extensible-platform
```

Expected: clean tree (only memory + maybe scratch files), push succeeds.

---

## Done Criteria Recap

- [ ] All 15 tasks committed in order
- [ ] `pytest data_agent/standards_platform/` green
- [ ] `npm run build` exit 0
- [ ] 8-step browser E2E passes
- [ ] `agent_audit_log` shows force-break entry
- [ ] Memory updated, branch pushed

