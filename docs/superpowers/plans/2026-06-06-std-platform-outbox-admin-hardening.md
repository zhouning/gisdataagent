# Standards Platform Outbox Admin Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the outbox dead-letter admin slice with durable retry audit, a safe bulk retry cap, and visible retry result feedback.

**Architecture:** Keep the existing outbox admin repository/API/UI split. Add audit persistence inside `outbox_admin.retry_event()` for successful retries, add API-level bulk size validation before repository dispatch, and add a compact frontend retry message without changing worker behavior.

**Tech Stack:** Python 3.13, PostgreSQL, SQLAlchemy `text()`, Starlette TestClient, pytest, React 18, TypeScript, Vite.

---

## Scope Check

This plan implements only the hardening follow-up from
`docs/superpowers/specs/2026-06-06-std-platform-outbox-admin-hardening-design.md`.
It does not implement payload editing, delete/purge, worker retry policy
changes, batch rollback, review-template visualization, or cross-standard impact
graph work.

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `data_agent/standards_platform/outbox_admin.py` | Modify | Write durable audit rows for successful admin retry |
| `data_agent/standards_platform/tests/test_outbox_admin.py` | Modify | Repository audit behavior tests |
| `data_agent/api/standards_routes.py` | Modify | Bulk retry maximum-size validation |
| `data_agent/standards_platform/tests/test_api_outbox_admin.py` | Modify | API cap tests |
| `frontend/src/components/datapanel/standards/derive/OutboxDeadLetterPanel.tsx` | Modify | Retry result summary message |

---

## Task 1: Repository Retry Audit

**Files:**
- Modify: `data_agent/standards_platform/tests/test_outbox_admin.py`
- Modify: `data_agent/standards_platform/outbox_admin.py`

- [ ] **Step 1: Write failing audit tests**

Append these tests near the existing retry tests in
`data_agent/standards_platform/tests/test_outbox_admin.py`:

```python
def _audit_count(engine, *, event_id: str, action: str = "std_outbox.retry") -> int:
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT COUNT(*) FROM agent_audit_log "
            "WHERE action=:a AND details->>'event_id'=:i"
        ), {"a": action, "i": event_id}).scalar()


def test_retry_failed_event_writes_audit(clean_outbox):
    event_id = _event({"retry": "audit"})
    _set_status(clean_outbox, event_id, "failed", attempts=5, last_error="boom")

    result = outbox_admin.retry_event(event_id, by_user="admin")

    assert result == {"id": event_id, "status": "retried"}
    with clean_outbox.connect() as conn:
        row = conn.execute(text(
            "SELECT username, action, details "
            "FROM agent_audit_log "
            "WHERE action='std_outbox.retry' "
            "AND details->>'event_id'=:i "
            "ORDER BY created_at DESC "
            "LIMIT 1"
        ), {"i": event_id}).mappings().first()
    assert row is not None
    assert row["username"] == "admin"
    assert row["details"]["event_id"] == event_id
    assert row["details"]["event_type"] == "derivation_requested"
    assert row["details"]["previous_status"] == "failed"


def test_retry_done_event_does_not_write_audit(clean_outbox):
    event_id = _event({"retry": "no-audit"})
    _set_status(clean_outbox, event_id, "done", attempts=0)
    before = _audit_count(clean_outbox, event_id=event_id)

    result = outbox_admin.retry_event(event_id, by_user="admin")

    assert result["status"] == "skipped"
    assert _audit_count(clean_outbox, event_id=event_id) == before
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_outbox_admin.py -v --basetemp .pytest_harden_task1_tmp
```

Expected: `test_retry_failed_event_writes_audit` fails because no
`agent_audit_log` row is written.

- [ ] **Step 3: Implement durable audit**

Modify `data_agent/standards_platform/outbox_admin.py`:

1. Add `import json`.
2. Change the locked row query in `retry_event()` to select `event_type`:

```python
row = conn.execute(text(
    "SELECT event_type, status FROM std_outbox WHERE id=:id FOR UPDATE"
), {"id": str(event_uuid)}).mappings().first()
```

3. After the `UPDATE std_outbox ...` statement, insert the audit row in the
same transaction:

```python
audit_details = {
    "event_id": event_id_str,
    "event_type": str(row["event_type"]),
    "previous_status": status,
}
conn.execute(text(
    "INSERT INTO agent_audit_log (username, action, details) "
    "VALUES (:u, 'std_outbox.retry', CAST(:d AS jsonb))"
), {"u": by_user, "d": json.dumps(audit_details, ensure_ascii=False)})
```

Do not write audit rows for missing, malformed, duplicate, `pending`, or `done`
events.

- [ ] **Step 4: Run repository tests to verify GREEN**

Run:

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_outbox_admin.py -v --basetemp .pytest_harden_task1_tmp
```

Expected: all repository outbox admin tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add data_agent\standards_platform\outbox_admin.py data_agent\standards_platform\tests\test_outbox_admin.py
git commit -m "feat(std-platform): audit outbox admin retries"
```

---

## Task 2: API Bulk Retry Cap

**Files:**
- Modify: `data_agent/standards_platform/tests/test_api_outbox_admin.py`
- Modify: `data_agent/api/standards_routes.py`

- [ ] **Step 1: Write failing API cap tests**

Append these tests near the existing bulk retry validation tests in
`data_agent/standards_platform/tests/test_api_outbox_admin.py`:

```python
def test_retry_outbox_events_rejects_too_many_ids(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")
    event_ids = [f"evt-{i}" for i in range(201)]

    resp = _client().post(
        "/api/std/outbox/events/retry",
        json={"event_ids": event_ids},
    )

    assert resp.status_code == 400
    assert resp.json()["error"] == "event_ids must contain at most 200 ids"


def test_retry_outbox_events_accepts_max_ids(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")
    event_ids = [f"evt-{i}" for i in range(200)]
    result = {"retried": [], "skipped": []}
    with patch(
        "data_agent.api.standards_routes._outbox_admin.retry_events",
        return_value=result,
    ) as retry:
        resp = _client().post(
            "/api/std/outbox/events/retry",
            json={"event_ids": event_ids},
        )

    assert resp.status_code == 200
    assert resp.json() == result
    retry.assert_called_once_with(event_ids, by_user="admin")
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_api_outbox_admin.py -v --basetemp .pytest_harden_task2_tmp
```

Expected: `test_retry_outbox_events_rejects_too_many_ids` fails because 201 IDs
are currently accepted.

- [ ] **Step 3: Implement the API cap**

Modify `data_agent/api/standards_routes.py`:

1. Add the constant near role constants:

```python
_MAX_OUTBOX_RETRY_IDS = 200
```

2. In `retry_outbox_events()`, after the existing non-empty list check and before
the string-item check, add:

```python
    if len(event_ids) > _MAX_OUTBOX_RETRY_IDS:
        return JSONResponse(
            {"error": "event_ids must contain at most 200 ids"},
            status_code=400,
        )
```

- [ ] **Step 4: Run API tests to verify GREEN**

Run:

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_api_outbox_admin.py -v --basetemp .pytest_harden_task2_tmp
```

Expected: all outbox admin API tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add data_agent\api\standards_routes.py data_agent\standards_platform\tests\test_api_outbox_admin.py
git commit -m "feat(std-platform): cap outbox bulk retry size"
```

---

## Task 3: Frontend Retry Result Summary

**Files:**
- Modify: `frontend/src/components/datapanel/standards/derive/OutboxDeadLetterPanel.tsx`

- [ ] **Step 1: Add retry summary behavior**

Modify `OutboxDeadLetterPanel.tsx`:

1. Add a message state next to the existing `error` state:

```typescript
const [retryMessage, setRetryMessage] = useState<string | null>(null);
```

2. Add helper functions near `formatPayload`:

```typescript
const summarizeSkipped = (
  skipped: {id: string; reason?: string}[],
  max = 3,
) => {
  if (skipped.length === 0) return "";
  const reasons = skipped.slice(0, max)
    .map(s => `${s.id.slice(0, 8)}: ${s.reason ?? "skipped"}`);
  const suffix = skipped.length > max ? `; +${skipped.length - max}` : "";
  return ` (${reasons.join("; ")}${suffix})`;
};
```

3. Clear retry message when changing filters or starting a retry:

```typescript
setRetryMessage(null);
```

4. In `retryOne`, use the SDK response:

```typescript
const r = await retryOutboxEvent(event.id);
if (r.result.status === "retried") {
  setRetryMessage("已重试 1 条事件");
} else {
  setRetryMessage(`未重试: ${r.result.reason ?? "skipped"}`);
}
```

5. In `retrySelected`, use the SDK response:

```typescript
const r = await retryOutboxEvents(ids);
const skippedNote = summarizeSkipped(r.skipped);
setRetryMessage(
  `重试完成: retried ${r.retried.length}, skipped ${r.skipped.length}${skippedNote}`,
);
```

6. Render the message below the error block:

```tsx
{retryMessage && (
  <div
    role="status"
    style={{
      marginBottom: 8, color: "#075", lineHeight: 1.35,
      overflowWrap: "anywhere",
    }}>
    {retryMessage}
  </div>
)}
```

- [ ] **Step 2: Run frontend build**

Run:

```powershell
cd frontend
npm run build
```

Expected: build exits 0.

- [ ] **Step 3: Commit**

```powershell
cd ..
git add frontend\src\components\datapanel\standards\derive\OutboxDeadLetterPanel.tsx
git commit -m "feat(std-platform-fe): show outbox retry results"
```

---

## Task 4: Regression Verification

**Files:**
- No source changes expected.

- [ ] **Step 1: Run focused backend tests**

Run:

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_outbox_admin.py data_agent\standards_platform\tests\test_api_outbox_admin.py -q --basetemp .pytest_harden_focus_tmp
```

Expected: all tests PASS.

- [ ] **Step 2: Run full Standards Platform regression**

Run:

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform -q --basetemp .pytest_harden_full_tmp
```

Expected: all tests PASS, with existing skip/warnings only.

- [ ] **Step 3: Run frontend build**

Run:

```powershell
cd frontend
npm run build
```

Expected: build exits 0, with existing Vite warnings only.

- [ ] **Step 4: Final status check**

Run:

```powershell
git status --short --branch --untracked-files=no
```

Expected: no tracked file changes.
