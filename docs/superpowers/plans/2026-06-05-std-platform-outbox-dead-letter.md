# Standards Platform Outbox Dead-Letter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an admin-only Standards Platform outbox dead-letter panel and retry API so failed `std_outbox` events can be inspected and retried without SQL.

**Architecture:** Add a focused backend repository module (`outbox_admin.py`) for event listing/counting/retry state transitions, expose admin-only `/api/std/outbox/*` routes in the existing standards route module, then add typed frontend SDK wrappers plus an `OutboxDeadLetterPanel` embedded in `DeriveSubTab`. Existing worker and at-least-once delivery semantics remain unchanged.

**Tech Stack:** Python 3.13, PostgreSQL, SQLAlchemy `text()`, Starlette routes/TestClient, pytest, React 18, TypeScript, Vite.

---

## Scope Check

This plan implements only the v25.4 P4 first slice from
`docs/superpowers/specs/2026-06-05-std-platform-outbox-dead-letter-design.md`.
It does not implement batch rollback, cross-standard impact graph, review
workflow templates, payload editing, or event deletion.

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `data_agent/standards_platform/outbox_admin.py` | Create | Admin-safe list/count/retry operations for `std_outbox` |
| `data_agent/standards_platform/tests/test_outbox_admin.py` | Create | DB-level behavior tests for list/count/retry |
| `data_agent/api/standards_routes.py` | Modify | Add admin-only routes and route handlers |
| `data_agent/standards_platform/tests/test_api_outbox_admin.py` | Create | REST auth, validation, and response tests |
| `frontend/src/components/datapanel/standards/standardsApi.ts` | Modify | Add typed outbox SDK wrappers |
| `frontend/src/components/datapanel/standards/derive/OutboxDeadLetterPanel.tsx` | Create | Admin UI for event list, details, retry |
| `frontend/src/components/datapanel/standards/DeriveSubTab.tsx` | Modify | Mount panel under derive status controls |
| `docs/roadmap.md` | Modify | Mark v25.4 first P4 slice complete after verification |

---

## Task 1: Backend Repository - Outbox Admin Operations

**Files:**
- Create: `data_agent/standards_platform/tests/test_outbox_admin.py`
- Create: `data_agent/standards_platform/outbox_admin.py`

- [ ] **Step 1: Write the failing repository tests**

Create `data_agent/standards_platform/tests/test_outbox_admin.py`:

```python
"""Tests for admin outbox dead-letter operations."""
from __future__ import annotations

from datetime import datetime, timezone
import uuid

import pytest
from sqlalchemy import text

from data_agent.standards_platform import outbox as ob
from data_agent.standards_platform import outbox_admin


@pytest.fixture
def clean_outbox(engine):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM std_outbox"))
    yield engine
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM std_outbox"))


def _event(payload: dict | None = None, event_type: str = "derive_requested") -> str:
    return ob.enqueue(event_type, payload or {"version_id": str(uuid.uuid4())})


def _set_status(engine, event_id: str, status: str, *, attempts: int = 0,
                last_error: str | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE std_outbox "
            "SET status=:s, attempts=:a, last_error=:e, next_attempt_at=now() "
            "WHERE id=:i"
        ), {"s": status, "a": attempts, "e": last_error, "i": event_id})


def _row(engine, event_id: str):
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT status, attempts, last_error, next_attempt_at "
            "FROM std_outbox WHERE id=:i"
        ), {"i": event_id}).mappings().first()


def test_list_events_filters_failed_newest_first(clean_outbox):
    old_id = _event({"order": "old"}, "extract_requested")
    new_id = _event({"order": "new"}, "derive_requested")
    pending_id = _event({"order": "pending"}, "embed_requested")
    _set_status(clean_outbox, old_id, "failed", attempts=5, last_error="old")
    _set_status(clean_outbox, new_id, "failed", attempts=5, last_error="new")
    _set_status(clean_outbox, pending_id, "pending")

    events = outbox_admin.list_events(status="failed", limit=10, offset=0)

    assert [e["id"] for e in events] == [new_id, old_id]
    assert events[0]["event_type"] == "derive_requested"
    assert events[0]["payload"] == {"order": "new"}
    assert events[0]["last_error"] == "new"


def test_list_events_filters_by_event_type(clean_outbox):
    keep_id = _event({"kind": "keep"}, "derive_requested")
    skip_id = _event({"kind": "skip"}, "extract_requested")
    _set_status(clean_outbox, keep_id, "failed", attempts=5)
    _set_status(clean_outbox, skip_id, "failed", attempts=5)

    events = outbox_admin.list_events(
        status="failed", event_type="derive_requested", limit=10, offset=0
    )

    assert [e["id"] for e in events] == [keep_id]


def test_get_counts_includes_zero_statuses(clean_outbox):
    failed_id = _event()
    _set_status(clean_outbox, failed_id, "failed", attempts=5)

    counts = outbox_admin.get_counts()

    assert counts["failed"] == 1
    assert counts["pending"] == 0
    assert counts["in_flight"] == 0
    assert counts["done"] == 0


def test_retry_failed_event_resets_to_pending(clean_outbox):
    event_id = _event({"retry": "failed"})
    _set_status(clean_outbox, event_id, "failed", attempts=5, last_error="boom")

    result = outbox_admin.retry_event(event_id, by_user="admin")
    row = _row(clean_outbox, event_id)

    assert result == {"id": event_id, "status": "retried"}
    assert row["status"] == "pending"
    assert row["attempts"] == 5
    assert row["last_error"] == "boom"
    assert row["next_attempt_at"] <= datetime.now(timezone.utc)


def test_retry_in_flight_event_resets_to_pending(clean_outbox):
    event_id = _event({"retry": "in_flight"})
    _set_status(clean_outbox, event_id, "in_flight", attempts=2, last_error="stuck")

    result = outbox_admin.retry_event(event_id, by_user="admin")
    row = _row(clean_outbox, event_id)

    assert result == {"id": event_id, "status": "retried"}
    assert row["status"] == "pending"
    assert row["attempts"] == 2


def test_retry_done_event_is_skipped(clean_outbox):
    event_id = _event({"retry": "done"})
    _set_status(clean_outbox, event_id, "done", attempts=0)

    result = outbox_admin.retry_event(event_id, by_user="admin")
    row = _row(clean_outbox, event_id)

    assert result == {
        "id": event_id,
        "status": "skipped",
        "reason": "status done is not retryable",
    }
    assert row["status"] == "done"


def test_retry_missing_event_is_skipped(clean_outbox):
    missing_id = str(uuid.uuid4())

    result = outbox_admin.retry_event(missing_id, by_user="admin")

    assert result == {
        "id": missing_id,
        "status": "skipped",
        "reason": "not found",
    }


def test_retry_events_returns_mixed_results(clean_outbox):
    failed_id = _event({"bulk": "failed"})
    done_id = _event({"bulk": "done"})
    missing_id = str(uuid.uuid4())
    _set_status(clean_outbox, failed_id, "failed", attempts=5)
    _set_status(clean_outbox, done_id, "done")

    result = outbox_admin.retry_events(
        [failed_id, done_id, missing_id], by_user="admin"
    )

    assert result["retried"] == [{"id": failed_id, "status": "retried"}]
    assert result["skipped"] == [
        {"id": done_id, "status": "skipped",
         "reason": "status done is not retryable"},
        {"id": missing_id, "status": "skipped", "reason": "not found"},
    ]
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_outbox_admin.py -v
```

Expected: FAIL during import with `ImportError` or `ModuleNotFoundError` for
`data_agent.standards_platform.outbox_admin`.

- [ ] **Step 3: Write minimal repository implementation**

Create `data_agent/standards_platform/outbox_admin.py`:

```python
"""Admin operations for Standards Platform std_outbox events."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from data_agent.db_engine import get_engine

_STATUSES = ("pending", "in_flight", "done", "failed")
_RETRYABLE = {"failed", "in_flight"}


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "hex"):
        return str(value)
    return value


def _event_mapping(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "event_type": row["event_type"],
        "payload": row["payload"] or {},
        "created_at": _json_safe(row["created_at"]),
        "processed_at": _json_safe(row["processed_at"]),
        "attempts": row["attempts"],
        "last_error": row["last_error"],
        "next_attempt_at": _json_safe(row["next_attempt_at"]),
        "status": row["status"],
    }


def list_events(*, status: str | None = None,
                event_type: str | None = None,
                limit: int = 50,
                offset: int = 0) -> list[dict]:
    if limit < 1 or limit > 200:
        raise ValueError("limit must be between 1 and 200")
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if status is not None and status not in _STATUSES:
        raise ValueError("invalid status")

    where = []
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if status:
        where.append("status=:status")
        params["status"] = status
    if event_type:
        where.append("event_type=:event_type")
        params["event_type"] = event_type
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, event_type, payload, created_at, processed_at, "
            "attempts, last_error, next_attempt_at, status "
            f"FROM std_outbox {where_sql} "
            "ORDER BY created_at DESC, id DESC "
            "LIMIT :limit OFFSET :offset"
        ), params).mappings().all()
    return [_event_mapping(dict(row)) for row in rows]


def get_counts() -> dict[str, int]:
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(
            "SELECT status, COUNT(*) AS n FROM std_outbox GROUP BY status"
        )).mappings().all()
    counts = {status: 0 for status in _STATUSES}
    for row in rows:
        counts[row["status"]] = int(row["n"])
    return counts


def retry_event(event_id: str, *, by_user: str) -> dict:
    eng = get_engine()
    with eng.begin() as conn:
        row = conn.execute(text(
            "SELECT id, status FROM std_outbox WHERE id=:i FOR UPDATE"
        ), {"i": event_id}).mappings().first()
        if row is None:
            return {"id": event_id, "status": "skipped", "reason": "not found"}
        current_status = row["status"]
        if current_status not in _RETRYABLE:
            return {
                "id": event_id,
                "status": "skipped",
                "reason": f"status {current_status} is not retryable",
            }
        conn.execute(text(
            "UPDATE std_outbox "
            "SET status='pending', next_attempt_at=now() "
            "WHERE id=:i"
        ), {"i": event_id})
    return {"id": event_id, "status": "retried"}


def retry_events(event_ids: list[str], *, by_user: str) -> dict:
    retried: list[dict] = []
    skipped: list[dict] = []
    seen: set[str] = set()
    for event_id in event_ids:
        if event_id in seen:
            skipped.append({
                "id": event_id,
                "status": "skipped",
                "reason": "duplicate id",
            })
            continue
        seen.add(event_id)
        result = retry_event(event_id, by_user=by_user)
        if result["status"] == "retried":
            retried.append(result)
        else:
            skipped.append(result)
    return {"retried": retried, "skipped": skipped}
```

- [ ] **Step 4: Run repository tests to verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_outbox_admin.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add data_agent\standards_platform\outbox_admin.py data_agent\standards_platform\tests\test_outbox_admin.py
git commit -m "feat(std-platform): add outbox admin retry repository"
```

---

## Task 2: Backend API - Admin Routes

**Files:**
- Create: `data_agent/standards_platform/tests/test_api_outbox_admin.py`
- Modify: `data_agent/api/standards_routes.py`

- [ ] **Step 1: Write failing API tests**

Create `data_agent/standards_platform/tests/test_api_outbox_admin.py`:

```python
"""API tests for Standards Platform outbox admin routes."""
from __future__ import annotations

from unittest.mock import patch

from data_agent.standards_platform.tests.test_api_standards import (
    _auth_user,
    _client,
)


def test_list_outbox_events_requires_auth(monkeypatch):
    monkeypatch.setattr(
        "data_agent.api.helpers._get_user_from_request", lambda r: None
    )

    resp = _client().get("/api/std/outbox/events")

    assert resp.status_code == 401


def test_list_outbox_events_admin_only(monkeypatch):
    _auth_user(monkeypatch, role="standard_editor")

    resp = _client().get("/api/std/outbox/events")

    assert resp.status_code == 403


def test_list_outbox_events_returns_events_and_counts(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")
    event = {
        "id": "evt-1",
        "event_type": "derive_requested",
        "status": "failed",
        "attempts": 5,
        "last_error": "boom",
        "payload": {"version_id": "v1"},
        "created_at": "2026-06-05T00:00:00+00:00",
        "processed_at": None,
        "next_attempt_at": "2026-06-05T00:00:00+00:00",
    }
    with patch("data_agent.api.standards_routes._outbox_admin.list_events",
               return_value=[event]) as list_events, \
         patch("data_agent.api.standards_routes._outbox_admin.get_counts",
               return_value={"pending": 0, "in_flight": 0,
                             "done": 0, "failed": 1}):
        resp = _client().get(
            "/api/std/outbox/events?status=failed&event_type=derive_requested"
        )

    assert resp.status_code == 200
    assert resp.json() == {
        "events": [event],
        "counts": {"pending": 0, "in_flight": 0, "done": 0, "failed": 1},
    }
    list_events.assert_called_once_with(
        status="failed", event_type="derive_requested", limit=50, offset=0
    )


def test_list_outbox_events_rejects_invalid_limit(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")

    resp = _client().get("/api/std/outbox/events?limit=0")

    assert resp.status_code == 400
    assert resp.json()["error"] == "limit must be between 1 and 200"


def test_retry_outbox_event_admin_only(monkeypatch):
    _auth_user(monkeypatch, role="standard_editor")

    resp = _client().post("/api/std/outbox/events/evt-1/retry")

    assert resp.status_code == 403


def test_retry_outbox_event_returns_result(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")
    with patch("data_agent.api.standards_routes._outbox_admin.retry_event",
               return_value={"id": "evt-1", "status": "retried"}) as retry:
        resp = _client().post("/api/std/outbox/events/evt-1/retry")

    assert resp.status_code == 200
    assert resp.json() == {"result": {"id": "evt-1", "status": "retried"}}
    retry.assert_called_once_with("evt-1", by_user="admin")


def test_retry_outbox_events_bulk(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")
    result = {
        "retried": [{"id": "evt-1", "status": "retried"}],
        "skipped": [{"id": "evt-2", "status": "skipped",
                     "reason": "status done is not retryable"}],
    }
    with patch("data_agent.api.standards_routes._outbox_admin.retry_events",
               return_value=result) as retry:
        resp = _client().post(
            "/api/std/outbox/events/retry",
            json={"event_ids": ["evt-1", "evt-2"]},
        )

    assert resp.status_code == 200
    assert resp.json() == result
    retry.assert_called_once_with(["evt-1", "evt-2"], by_user="admin")


def test_retry_outbox_events_rejects_empty_bulk(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")

    resp = _client().post("/api/std/outbox/events/retry", json={"event_ids": []})

    assert resp.status_code == 400
    assert resp.json()["error"] == "event_ids must be a non-empty list"
```

- [ ] **Step 2: Run API tests to verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_api_outbox_admin.py -v
```

Expected: tests fail with `404 Not Found` for `/api/std/outbox/events` and
patch failures for `_outbox_admin` until the route module is updated.

- [ ] **Step 3: Add API route implementation**

Modify `data_agent/api/standards_routes.py`.

Add this import near the existing standards_platform imports:

```python
from ..standards_platform import outbox_admin as _outbox_admin
```

Replace `outbox_status()` with:

```python
async def outbox_status(request: Request):
    user, username, role, err = _require_admin(request)
    if err:
        return err
    return JSONResponse({"counts": _outbox_admin.get_counts()})
```

Add these handlers after `outbox_status()`:

```python
def _parse_int_param(request: Request, name: str, default: int) -> int:
    raw = request.query_params.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise ValueError(f"{name} must be an integer") from e


async def outbox_events(request: Request):
    user, username, role, err = _require_admin(request)
    if err:
        return err
    try:
        limit = _parse_int_param(request, "limit", 50)
        offset = _parse_int_param(request, "offset", 0)
        events = _outbox_admin.list_events(
            status=request.query_params.get("status"),
            event_type=request.query_params.get("event_type"),
            limit=limit,
            offset=offset,
        )
        counts = _outbox_admin.get_counts()
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"events": events, "counts": counts})


async def outbox_retry_event(request: Request):
    user, username, role, err = _require_admin(request)
    if err:
        return err
    event_id = request.path_params["event_id"]
    result = _outbox_admin.retry_event(event_id, by_user=username)
    return JSONResponse({"result": result})


async def outbox_retry_events(request: Request):
    user, username, role, err = _require_admin(request)
    if err:
        return err
    body = await request.json()
    event_ids = body.get("event_ids")
    if not isinstance(event_ids, list) or not event_ids:
        return JSONResponse(
            {"error": "event_ids must be a non-empty list"},
            status_code=400,
        )
    if not all(isinstance(event_id, str) and event_id for event_id in event_ids):
        return JSONResponse(
            {"error": "event_ids must contain non-empty strings"},
            status_code=400,
        )
    result = _outbox_admin.retry_events(event_ids, by_user=username)
    return JSONResponse(result)
```

Add these routes immediately after the existing outbox status route:

```python
    Route("/api/std/outbox/events", endpoint=outbox_events, methods=["GET"]),
    Route("/api/std/outbox/events/retry",
          endpoint=outbox_retry_events, methods=["POST"]),
    Route("/api/std/outbox/events/{event_id}/retry",
          endpoint=outbox_retry_event, methods=["POST"]),
```

- [ ] **Step 4: Run API tests to verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_api_outbox_admin.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run existing status route regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_api_standards.py::test_outbox_status_admin_only -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add data_agent\api\standards_routes.py data_agent\standards_platform\tests\test_api_outbox_admin.py
git commit -m "feat(std-platform): expose outbox dead-letter admin routes"
```

---

## Task 3: Frontend SDK - Typed Outbox Wrappers

**Files:**
- Modify: `frontend/src/components/datapanel/standards/standardsApi.ts`

- [ ] **Step 1: Add SDK types and wrappers**

Append this section near the existing Wave 5/8 SDK exports in
`frontend/src/components/datapanel/standards/standardsApi.ts`:

```typescript
// ---------- P4: outbox dead-letter operations ----------

export type OutboxStatus = "pending" | "in_flight" | "done" | "failed";

export interface OutboxEvent {
  id: string;
  event_type: string;
  payload: Record<string, any>;
  created_at: string | null;
  processed_at: string | null;
  attempts: number;
  last_error: string | null;
  next_attempt_at: string | null;
  status: OutboxStatus;
}

export type OutboxCounts = Record<OutboxStatus, number>;

export interface OutboxRetryResult {
  id: string;
  status: "retried" | "skipped";
  reason?: string;
}

export const listOutboxEvents = (
  params: {status?: OutboxStatus; event_type?: string;
           limit?: number; offset?: number} = {},
) => {
  const filtered: Record<string,string> = {};
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") filtered[k] = String(v);
  }
  const q = new URLSearchParams(filtered).toString();
  return fetch(`/api/std/outbox/events${q ? `?${q}` : ""}`)
    .then(j<{events: OutboxEvent[]; counts: OutboxCounts}>);
};

export const retryOutboxEvent = (eventId: string) =>
  fetch(`/api/std/outbox/events/${eventId}/retry`, {method: "POST"})
    .then(j<{result: OutboxRetryResult}>);

export const retryOutboxEvents = (eventIds: string[]) =>
  fetch("/api/std/outbox/events/retry", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({event_ids: eventIds}),
  }).then(j<{retried: OutboxRetryResult[]; skipped: OutboxRetryResult[]}>);
```

- [ ] **Step 2: Run frontend build to verify wrappers compile**

Run:

```powershell
cd frontend
npm run build
```

Expected: build exits 0.

- [ ] **Step 3: Commit**

```powershell
cd ..
git add frontend\src\components\datapanel\standards\standardsApi.ts
git commit -m "feat(std-platform-fe): add outbox admin SDK wrappers"
```

---

## Task 4: Frontend UI - Dead-Letter Panel

**Files:**
- Create: `frontend/src/components/datapanel/standards/derive/OutboxDeadLetterPanel.tsx`
- Modify: `frontend/src/components/datapanel/standards/DeriveSubTab.tsx`

- [ ] **Step 1: Create the panel component**

Create
`frontend/src/components/datapanel/standards/derive/OutboxDeadLetterPanel.tsx`:

```typescript
import React, { useEffect, useMemo, useState } from "react";
import {
  listOutboxEvents,
  retryOutboxEvent,
  retryOutboxEvents,
  OutboxEvent,
  OutboxStatus,
  OutboxCounts,
} from "../standardsApi";

interface Props {
  refreshTick: number;
  onRetryComplete: () => void;
}

const emptyCounts: OutboxCounts = {
  pending: 0,
  in_flight: 0,
  done: 0,
  failed: 0,
};

const retryable = (event: OutboxEvent) =>
  event.status === "failed" || event.status === "in_flight";

const short = (value: string | null, max = 90) => {
  if (!value) return "";
  return value.length > max ? `${value.slice(0, max)}...` : value;
};

export default function OutboxDeadLetterPanel({
  refreshTick,
  onRetryComplete,
}: Props) {
  const [status, setStatus] = useState<OutboxStatus>("failed");
  const [events, setEvents] = useState<OutboxEvent[]>([]);
  const [counts, setCounts] = useState<OutboxCounts>(emptyCounts);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [localTick, setLocalTick] = useState(0);

  useEffect(() => {
    setBusy(true);
    setError(null);
    listOutboxEvents({status, limit: 50})
      .then(r => {
        setEvents(r.events);
        setCounts({...emptyCounts, ...r.counts});
        setSelected(new Set());
      })
      .catch(e => setError(String(e)))
      .finally(() => setBusy(false));
  }, [status, refreshTick, localTick]);

  const retryableSelected = useMemo(() => {
    const byId = new Map(events.map(e => [e.id, e]));
    return Array.from(selected).filter(id => {
      const event = byId.get(id);
      return event ? retryable(event) : false;
    });
  }, [events, selected]);

  const toggle = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const retryOne = async (eventId: string) => {
    setBusy(true);
    setError(null);
    try {
      await retryOutboxEvent(eventId);
      setLocalTick(t => t + 1);
      onRetryComplete();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const retrySelected = async () => {
    if (!retryableSelected.length) return;
    setBusy(true);
    setError(null);
    try {
      await retryOutboxEvents(retryableSelected);
      setLocalTick(t => t + 1);
      onRetryComplete();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{marginTop: 12, padding: 8, border: "1px solid #ddd",
                 borderRadius: 4, background: "#fff"}}>
      <div style={{display: "flex", justifyContent: "space-between",
                   alignItems: "center", gap: 8}}>
        <div style={{fontSize: 12, fontWeight: 600}}>Outbox dead-letter</div>
        <button
          onClick={() => setLocalTick(t => t + 1)}
          disabled={busy}
          style={{fontSize: 11, padding: "3px 8px"}}>
          Refresh
        </button>
      </div>

      <div style={{display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8}}>
        {(["failed", "pending", "in_flight", "done"] as OutboxStatus[]).map(s => (
          <button
            key={s}
            onClick={() => setStatus(s)}
            style={{
              fontSize: 11,
              padding: "3px 7px",
              border: "1px solid #ccc",
              borderRadius: 4,
              background: status === s ? "#333" : "#fff",
              color: status === s ? "#fff" : "#333",
              cursor: "pointer",
            }}>
            {s} {counts[s] ?? 0}
          </button>
        ))}
      </div>

      {error && (
        <div style={{marginTop: 8, color: "#c33", fontSize: 11}}>{error}</div>
      )}

      <button
        onClick={retrySelected}
        disabled={busy || retryableSelected.length === 0}
        style={{marginTop: 8, width: "100%", padding: "5px 8px",
                fontSize: 12}}>
        Retry selected ({retryableSelected.length})
      </button>

      <div style={{marginTop: 8, maxHeight: 280, overflow: "auto"}}>
        {events.length === 0 && (
          <div style={{fontSize: 11, color: "#888", padding: 8}}>
            No outbox events for this filter.
          </div>
        )}
        {events.map(event => (
          <div key={event.id}
               style={{borderTop: "1px solid #eee", padding: "7px 0"}}>
            <div style={{display: "grid",
                         gridTemplateColumns: "18px 1fr auto",
                         gap: 6, alignItems: "start"}}>
              <input
                type="checkbox"
                checked={selected.has(event.id)}
                disabled={!retryable(event)}
                onChange={() => toggle(event.id)}
              />
              <button
                onClick={() => setExpanded(
                  expanded === event.id ? null : event.id
                )}
                style={{border: 0, background: "transparent", padding: 0,
                        textAlign: "left", cursor: "pointer"}}>
                <div style={{fontSize: 11, fontWeight: 600}}>
                  {event.event_type}
                </div>
                <div style={{fontSize: 10, color: "#666"}}>
                  {event.status} · attempts {event.attempts}
                </div>
                {event.last_error && (
                  <div style={{fontSize: 10, color: "#c33"}}>
                    {short(event.last_error)}
                  </div>
                )}
              </button>
              <button
                onClick={() => retryOne(event.id)}
                disabled={busy || !retryable(event)}
                style={{fontSize: 10, padding: "3px 6px"}}>
                Retry
              </button>
            </div>
            {expanded === event.id && (
              <div style={{marginTop: 6, padding: 6, background: "#fafafa",
                           border: "1px solid #eee", borderRadius: 4}}>
                <div style={{fontSize: 10, color: "#666"}}>
                  id: {event.id}
                </div>
                <div style={{fontSize: 10, color: "#666"}}>
                  next: {event.next_attempt_at || "-"}
                </div>
                <pre style={{fontSize: 10, maxHeight: 120, overflow: "auto",
                             whiteSpace: "pre-wrap"}}>
                  {JSON.stringify(event.payload, null, 2)}
                </pre>
                {event.last_error && (
                  <pre style={{fontSize: 10, maxHeight: 120,
                               overflow: "auto", whiteSpace: "pre-wrap",
                               color: "#c33"}}>
                    {event.last_error}
                  </pre>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Mount the panel in DeriveSubTab**

Modify `frontend/src/components/datapanel/standards/DeriveSubTab.tsx`.

Add import:

```typescript
import OutboxDeadLetterPanel from "./derive/OutboxDeadLetterPanel";
```

Add this block after `RerunButton`:

```typescript
        {isAdmin && (
          <OutboxDeadLetterPanel
            refreshTick={refreshTick}
            onRetryComplete={() => setRefreshTick(t => t + 1)}
          />
        )}
```

- [ ] **Step 3: Run frontend build**

Run:

```powershell
cd frontend
npm run build
```

Expected: build exits 0.

- [ ] **Step 4: Commit**

```powershell
cd ..
git add frontend\src\components\datapanel\standards\DeriveSubTab.tsx frontend\src\components\datapanel\standards\derive\OutboxDeadLetterPanel.tsx
git commit -m "feat(std-platform-fe): add outbox dead-letter panel"
```

---

## Task 5: Regression Sweep and Roadmap Update

**Files:**
- Modify: `docs/roadmap.md`

- [ ] **Step 1: Run focused backend tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_outbox_admin.py data_agent\standards_platform\tests\test_api_outbox_admin.py -q
```

Expected: all tests PASS.

- [ ] **Step 2: Run Standards Platform regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\standards_platform -q
```

Expected: all tests PASS, with any existing skip unchanged.

- [ ] **Step 3: Run frontend build**

Run:

```powershell
cd frontend
npm run build
cd ..
```

Expected: build exits 0.

- [ ] **Step 4: Update roadmap**

Modify `docs/roadmap.md` near the current v25.x Standards Platform section and
add:

```markdown
## v25.4 — Standards Platform P4 First Slice (已完成, 2026-06-05)

- [x] **Outbox dead-letter UI** — 在 `DeriveSubTab` 增加 admin-only outbox 运维面板，可查看 `failed` / `pending` / `in_flight` / `done` 事件、展开 payload 与 last_error，并支持单条与批量 retry。
- [x] **Outbox admin API** — 新增 `GET /api/std/outbox/events`、`POST /api/std/outbox/events/{id}/retry`、`POST /api/std/outbox/events/retry`；保留 worker at-least-once 语义，不删除或编辑事件 payload。
- [x] **测试覆盖** — 新增 outbox repository + API focused tests；`pytest data_agent/standards_platform -q` 与 `npm run build` 通过。

> P4 仍未完成的主线：审定流模板可视化、批量回滚、跨标准影响图谱。
```

- [ ] **Step 5: Commit roadmap**

```powershell
git add docs\roadmap.md
git commit -m "docs(roadmap): mark std-platform outbox dead-letter slice complete"
```

- [ ] **Step 6: Final status check**

Run:

```powershell
git status --short
```

Expected: only pre-existing unrelated files remain modified or untracked.

---

## Implementation Notes

- Do not alter `outbox.claim_batch()`, `outbox.fail()`, or worker retry timing in
  this slice.
- Do not reset `attempts` or clear `last_error` during retry; preserving them is
  useful operational context.
- Do not make the panel visible to non-admin roles.
- Keep table payload rendering scrollable so large event payloads do not resize
  the entire right-side derive panel.
- Existing uncommitted NL2SQL changes in the worktree are unrelated to this
  plan. Do not stage or modify them.
