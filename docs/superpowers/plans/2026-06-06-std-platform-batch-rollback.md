# Standards Platform Batch Rollback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an admin-only batch rollback workflow for Standards Platform derivations.

**Architecture:** Reuse the existing `link_repo.rollback_version()` single-version semantics and add a small batch coordinator, then expose it through an admin API, typed frontend SDK, and a compact Derive-side operations panel. Each version rollback remains independently transactional; the batch API aggregates results instead of creating an all-or-nothing transaction.

**Tech Stack:** Python 3.13, PostgreSQL, SQLAlchemy `text()`, Starlette TestClient, pytest, React 18, TypeScript, Vite.

---

## Scope Check

This plan implements only the first P4 batch rollback slice from
`docs/superpowers/specs/2026-06-06-std-platform-batch-rollback-design.md`.
It does not add impact preview, a cross-document version picker, physical row
deletion, payload purge, or worker/outbox behavior changes.

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `data_agent/standards_platform/derivation/link_repo.py` | Modify | Batch rollback coordinator |
| `data_agent/standards_platform/tests/test_rollback_and_impact.py` | Modify | Repository batch rollback tests |
| `data_agent/api/standards_routes.py` | Modify | Batch rollback REST endpoint |
| `data_agent/standards_platform/tests/test_api_batch_rollback.py` | Create | API auth/validation/delegation tests |
| `frontend/src/components/datapanel/standards/standardsApi.ts` | Modify | Typed rollback SDK wrappers |
| `frontend/src/components/datapanel/standards/derive/BatchRollbackPanel.tsx` | Create | Admin batch rollback panel |
| `frontend/src/components/datapanel/standards/DeriveSubTab.tsx` | Modify | Mount batch rollback panel |
| `docs/roadmap.md` | Modify | Mark P4 batch rollback first slice complete |

---

## Task 1: Repository Batch Rollback

**Files:**
- Modify: `data_agent/standards_platform/tests/test_rollback_and_impact.py`
- Modify: `data_agent/standards_platform/derivation/link_repo.py`

- [ ] **Step 1: Write failing repository tests**

Append these tests after `test_rollback_empty_when_nothing_active` in
`data_agent/standards_platform/tests/test_rollback_and_impact.py`:

```python
def test_rollback_versions_returns_mixed_results(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _seed_bound_element(engine, ver_id, obligation="mandatory")
    SemanticHintStrategy().run(version_id=ver_id, by_user="admin")
    QcRuleStrategy().run(version_id=ver_id, by_user="admin")
    missing_id = str(uuid.uuid4())
    try:
        result = link_repo.rollback_versions(
            version_ids=[ver_id, ver_id, missing_id, "not-a-uuid"],
            by_user="admin",
            reason="batch test",
        )

        assert result["rolled_back"][0]["version_id"] == ver_id
        assert result["rolled_back"][0]["status"] == "rolled_back"
        assert "to_semantic_hint" in result["rolled_back"][0]["by_strategy"]
        assert "to_qc_rule" in result["rolled_back"][0]["by_strategy"]
        assert result["skipped"] == [
            {"version_id": ver_id, "reason": "duplicate id"},
            {"version_id": missing_id, "reason": "not found"},
            {"version_id": "not-a-uuid", "reason": "not found"},
        ]

        with engine.connect() as c:
            statuses = [r[0] for r in c.execute(text(
                "SELECT status FROM std_derived_link "
                "WHERE source_version_id=:v"
            ), {"v": ver_id}).fetchall()]
        assert statuses and all(s == "superseded" for s in statuses)
    finally:
        _cleanup_all(engine, doc_id)


def test_rollback_versions_reports_no_active_links(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    try:
        result = link_repo.rollback_versions(
            version_ids=[ver_id],
            by_user="admin",
            reason="batch no-op",
        )

        assert result == {
            "rolled_back": [
                {"version_id": ver_id, "status": "no_active_links",
                 "by_strategy": {}}
            ],
            "skipped": [],
        }
    finally:
        _cleanup_all(engine, doc_id)
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_rollback_and_impact.py -v --basetemp .pytest_batch_rb_task1_tmp
```

Expected: fail with `AttributeError` because `link_repo.rollback_versions`
does not exist.

- [ ] **Step 3: Implement `rollback_versions()`**

Modify `data_agent/standards_platform/derivation/link_repo.py`:

1. Change the typing import:

```python
from typing import Iterable, Optional
```

2. Add this helper below `rollback_version()`:

```python
def rollback_versions(*, version_ids: Iterable[str],
                      by_user: str = "system",
                      reason: Optional[str] = None) -> dict:
    """Rollback multiple versions independently, preserving input order."""
    rolled_back: list[dict] = []
    skipped: list[dict] = []
    seen: set[str] = set()
    eng = get_engine()

    for raw_id in version_ids:
        version_id = str(raw_id)
        try:
            normalized_id = str(uuid.UUID(version_id))
        except ValueError:
            skipped.append({"version_id": version_id, "reason": "not found"})
            continue

        if normalized_id in seen:
            skipped.append({"version_id": version_id, "reason": "duplicate id"})
            continue
        seen.add(normalized_id)

        with eng.connect() as conn:
            exists = conn.execute(text(
                "SELECT 1 FROM std_document_version WHERE id=:i"
            ), {"i": normalized_id}).first()
        if exists is None:
            skipped.append({"version_id": version_id, "reason": "not found"})
            continue

        summary = rollback_version(
            version_id=normalized_id,
            by_user=by_user,
            reason=reason,
        )
        rolled_back.append({
            "version_id": normalized_id,
            "status": "rolled_back" if summary else "no_active_links",
            "by_strategy": summary,
        })

    return {"rolled_back": rolled_back, "skipped": skipped}
```

- [ ] **Step 4: Run repository tests to verify GREEN**

Run:

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_rollback_and_impact.py -v --basetemp .pytest_batch_rb_task1_tmp
```

Expected: all rollback/impact tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add data_agent\standards_platform\derivation\link_repo.py data_agent\standards_platform\tests\test_rollback_and_impact.py
git commit -m "feat(std-platform): add batch derivation rollback repository"
```

---

## Task 2: Batch Rollback API

**Files:**
- Create: `data_agent/standards_platform/tests/test_api_batch_rollback.py`
- Modify: `data_agent/api/standards_routes.py`

- [ ] **Step 1: Write failing API tests**

Create `data_agent/standards_platform/tests/test_api_batch_rollback.py`:

```python
"""API tests for Standards Platform batch rollback."""
from __future__ import annotations

from unittest.mock import patch

from data_agent.standards_platform.tests.test_api_standards import (
    _auth_user,
    _client,
)


def test_batch_rollback_requires_auth(monkeypatch):
    monkeypatch.setattr(
        "data_agent.api.helpers._get_user_from_request", lambda r: None
    )

    resp = _client().post("/api/std/derive/rollback",
                          json={"version_ids": ["v1"]})

    assert resp.status_code == 401


def test_batch_rollback_admin_only(monkeypatch):
    _auth_user(monkeypatch, role="standard_editor")

    resp = _client().post("/api/std/derive/rollback",
                          json={"version_ids": ["v1"]})

    assert resp.status_code == 403


def test_batch_rollback_rejects_malformed_json(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")

    resp = _client().post(
        "/api/std/derive/rollback",
        content="{not-json",
        headers={"content-type": "application/json"},
    )

    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid JSON body"


def test_batch_rollback_rejects_empty_ids(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")

    resp = _client().post("/api/std/derive/rollback",
                          json={"version_ids": []})

    assert resp.status_code == 400
    assert resp.json()["error"] == "version_ids must be a non-empty list"


def test_batch_rollback_rejects_non_string_ids(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")

    resp = _client().post("/api/std/derive/rollback",
                          json={"version_ids": ["v1", 2]})

    assert resp.status_code == 400
    assert resp.json()["error"] == "version_ids must contain non-empty strings"


def test_batch_rollback_rejects_too_many_ids(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")
    version_ids = [f"v-{i}" for i in range(51)]

    resp = _client().post("/api/std/derive/rollback",
                          json={"version_ids": version_ids})

    assert resp.status_code == 400
    assert resp.json()["error"] == "version_ids must contain at most 50 ids"


def test_batch_rollback_admin_delegates(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")
    result = {
        "rolled_back": [{"version_id": "v1", "status": "rolled_back",
                         "by_strategy": {}}],
        "skipped": [{"version_id": "v2", "reason": "not found"}],
    }
    with patch(
        "data_agent.api.standards_routes._link_repo.rollback_versions",
        return_value=result,
    ) as rollback:
        resp = _client().post(
            "/api/std/derive/rollback",
            json={"version_ids": ["v1", "v2"], "reason": "ops rollback"},
        )

    assert resp.status_code == 200
    assert resp.json() == result
    rollback.assert_called_once_with(
        version_ids=["v1", "v2"],
        by_user="admin",
        reason="ops rollback",
    )


def test_batch_rollback_default_reason(monkeypatch):
    _auth_user(monkeypatch, username="admin", role="admin")
    result = {"rolled_back": [], "skipped": []}
    with patch(
        "data_agent.api.standards_routes._link_repo.rollback_versions",
        return_value=result,
    ) as rollback:
        resp = _client().post("/api/std/derive/rollback",
                              json={"version_ids": ["v1"]})

    assert resp.status_code == 200
    rollback.assert_called_once_with(
        version_ids=["v1"],
        by_user="admin",
        reason="batch rollback by admin",
    )
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_api_batch_rollback.py -v --basetemp .pytest_batch_rb_task2_tmp
```

Expected: fail with `404 Not Found` for `/api/std/derive/rollback`.

- [ ] **Step 3: Implement the API route**

Modify `data_agent/api/standards_routes.py`:

1. Add near existing constants:

```python
_MAX_BATCH_ROLLBACK_IDS = 50
```

2. Add this handler after `derive_rollback_handler()`:

```python
async def derive_batch_rollback_handler(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    forbid = _require_admin_or_403(role)
    if forbid: return forbid
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    version_ids = body.get("version_ids") if isinstance(body, dict) else None
    if not isinstance(version_ids, list) or not version_ids:
        return JSONResponse(
            {"error": "version_ids must be a non-empty list"},
            status_code=400,
        )
    if len(version_ids) > _MAX_BATCH_ROLLBACK_IDS:
        return JSONResponse(
            {"error": "version_ids must contain at most 50 ids"},
            status_code=400,
        )
    if any(not isinstance(version_id, str) or not version_id
           for version_id in version_ids):
        return JSONResponse(
            {"error": "version_ids must contain non-empty strings"},
            status_code=400,
        )
    reason = body.get("reason") or f"batch rollback by {username}"
    result = _link_repo.rollback_versions(
        version_ids=version_ids,
        by_user=username,
        reason=reason,
    )
    return JSONResponse(result)
```

3. Register the route near the existing rollback route, with the static route
before `rollback/{version_id}`:

```python
    Route("/api/std/derive/rollback",
          endpoint=derive_batch_rollback_handler, methods=["POST"]),
    Route("/api/std/derive/rollback/{version_id}",
          endpoint=derive_rollback_handler, methods=["POST"]),
```

- [ ] **Step 4: Run API tests to verify GREEN**

Run:

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_api_batch_rollback.py -v --basetemp .pytest_batch_rb_task2_tmp
```

Expected: all batch rollback API tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add data_agent\api\standards_routes.py data_agent\standards_platform\tests\test_api_batch_rollback.py
git commit -m "feat(std-platform): expose batch derivation rollback API"
```

---

## Task 3: Frontend SDK

**Files:**
- Modify: `frontend/src/components/datapanel/standards/standardsApi.ts`

- [ ] **Step 1: Add typed SDK wrappers**

Modify `frontend/src/components/datapanel/standards/standardsApi.ts` near the
derive SDK exports:

```typescript
export type RollbackByStrategy = Record<string, {
  links_marked: number;
  downstream_marked: number;
  target_tables: string[];
}>;

export interface RollbackVersionResult {
  version_id: string;
  by_strategy: RollbackByStrategy;
}

export interface BatchRollbackItem {
  version_id: string;
  status: "rolled_back" | "no_active_links";
  by_strategy: RollbackByStrategy;
}

export interface BatchRollbackSkipped {
  version_id: string;
  reason: string;
}

export interface BatchRollbackResult {
  rolled_back: BatchRollbackItem[];
  skipped: BatchRollbackSkipped[];
}

export const rollbackDerivations = (versionId: string, reason?: string) =>
  fetch(`/api/std/derive/rollback/${versionId}`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({reason: reason ?? null}),
  }).then(j<RollbackVersionResult>);

export const rollbackDerivationsBatch = (
  versionIds: string[],
  reason?: string,
) =>
  fetch("/api/std/derive/rollback", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({version_ids: versionIds, reason: reason ?? null}),
  }).then(j<BatchRollbackResult>);
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
git add frontend\src\components\datapanel\standards\standardsApi.ts
git commit -m "feat(std-platform-fe): add batch rollback SDK"
```

---

## Task 4: Frontend Batch Rollback Panel

**Files:**
- Create: `frontend/src/components/datapanel/standards/derive/BatchRollbackPanel.tsx`
- Modify: `frontend/src/components/datapanel/standards/DeriveSubTab.tsx`

- [ ] **Step 1: Create the panel**

Create `frontend/src/components/datapanel/standards/derive/BatchRollbackPanel.tsx`:

```typescript
import React, { useMemo, useState } from "react";
import {
  rollbackDerivationsBatch,
  BatchRollbackResult,
} from "../standardsApi";

interface Props {
  versionId: string | null;
  onRollbackComplete: () => void;
}

const parseIds = (value: string) => Array.from(new Set(
  value.split(/[\s,;]+/).map(v => v.trim()).filter(Boolean),
));

const summarizeStrategies = (item: BatchRollbackResult["rolled_back"][number]) =>
  Object.entries(item.by_strategy)
    .map(([strategy, summary]) => `${strategy}: ${summary.links_marked}`)
    .join("; ") || item.status;

export default function BatchRollbackPanel({
  versionId,
  onRollbackComplete,
}: Props) {
  const [idsText, setIdsText] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BatchRollbackResult | null>(null);

  const versionIds = useMemo(() => parseIds(idsText), [idsText]);

  const addCurrent = () => {
    if (!versionId) return;
    const next = Array.from(new Set([...versionIds, versionId]));
    setIdsText(next.join("\n"));
    setError(null);
  };

  const rollback = async () => {
    if (versionIds.length === 0) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const r = await rollbackDerivationsBatch(
        versionIds,
        reason.trim() || undefined,
      );
      setResult(r);
      onRollbackComplete();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{
      marginTop: 12, padding: 8, border: "1px solid #ddd",
      borderRadius: 4, background: "#fafafa", fontSize: 11,
    }}>
      <div style={{display: "flex", justifyContent: "space-between",
                   gap: 8, alignItems: "center", marginBottom: 6}}>
        <div style={{fontSize: 12, fontWeight: 500}}>批量回滚</div>
        <button
          type="button"
          onClick={addCurrent}
          disabled={!versionId || busy}
          style={{fontSize: 11, padding: "3px 7px",
                  border: "1px solid #ccc", borderRadius: 3,
                  background: "#fff"}}>
          加入当前版本
        </button>
      </div>

      <textarea
        value={idsText}
        onChange={e => setIdsText(e.currentTarget.value)}
        placeholder="version id，每行或逗号分隔"
        rows={4}
        disabled={busy}
        style={{width: "100%", boxSizing: "border-box", fontSize: 11,
                padding: 6, border: "1px solid #ccc", borderRadius: 3,
                resize: "vertical", minHeight: 74}}
      />
      <input
        value={reason}
        onChange={e => setReason(e.currentTarget.value)}
        placeholder="reason"
        disabled={busy}
        style={{width: "100%", boxSizing: "border-box", marginTop: 6,
                fontSize: 11, padding: 5, border: "1px solid #ccc",
                borderRadius: 3}}
      />
      <button
        type="button"
        onClick={rollback}
        disabled={busy || versionIds.length === 0}
        style={{width: "100%", marginTop: 6, padding: "5px 8px",
                fontSize: 11, border: "none", borderRadius: 4,
                background: versionIds.length ? "#a50" : "#ddd",
                color: "#fff",
                cursor: busy || versionIds.length === 0
                  ? "not-allowed" : "pointer"}}>
        {busy ? "回滚中..." : `回滚 ${versionIds.length} 个版本`}
      </button>

      {error && (
        <div role="alert" style={{marginTop: 6, color: "#c33",
                                  overflowWrap: "anywhere"}}>
          {error}
        </div>
      )}
      {result && (
        <div role="status" style={{marginTop: 8}}>
          <div style={{color: "#075", marginBottom: 4}}>
            rolled_back {result.rolled_back.length} / skipped {result.skipped.length}
          </div>
          <div style={{maxHeight: 180, overflow: "auto",
                       borderTop: "1px solid #e6e6e6"}}>
            {result.rolled_back.map(item => (
              <div key={`ok-${item.version_id}`}
                   style={{padding: "5px 0", borderBottom: "1px solid #eee"}}>
                <div style={{fontFamily: "monospace", overflowWrap: "anywhere"}}>
                  {item.version_id}
                </div>
                <div style={{color: item.status === "rolled_back" ? "#075" : "#777"}}>
                  {summarizeStrategies(item)}
                </div>
              </div>
            ))}
            {result.skipped.map(item => (
              <div key={`skip-${item.version_id}`}
                   style={{padding: "5px 0", borderBottom: "1px solid #eee"}}>
                <div style={{fontFamily: "monospace", overflowWrap: "anywhere"}}>
                  {item.version_id}
                </div>
                <div style={{color: "#a33"}}>{item.reason}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Mount the panel**

Modify `frontend/src/components/datapanel/standards/DeriveSubTab.tsx`:

1. Add import:

```typescript
import BatchRollbackPanel from "./derive/BatchRollbackPanel";
```

2. Mount it for admins after `RerunButton` and before the outbox panel:

```tsx
        {isAdmin && (
          <BatchRollbackPanel
            versionId={versionId}
            onRollbackComplete={() => setRefreshTick(t => t + 1)}
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
git add frontend\src\components\datapanel\standards\DeriveSubTab.tsx frontend\src\components\datapanel\standards\derive\BatchRollbackPanel.tsx
git commit -m "feat(std-platform-fe): add batch rollback panel"
```

---

## Task 5: Regression and Roadmap

**Files:**
- Modify: `docs/roadmap.md`

- [ ] **Step 1: Run focused backend tests**

Run:

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_rollback_and_impact.py data_agent\standards_platform\tests\test_api_batch_rollback.py -q --basetemp .pytest_batch_rb_focus_tmp
```

Expected: all focused rollback tests PASS.

- [ ] **Step 2: Run full Standards Platform regression**

Run:

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform -q --basetemp .pytest_batch_rb_full_tmp
```

Expected: all tests PASS, with existing skip/warnings only.

- [ ] **Step 3: Run frontend build**

Run:

```powershell
cd frontend
npm run build
```

Expected: build exits 0.

- [ ] **Step 4: Update roadmap**

Modify `docs/roadmap.md`:

1. Update header:

```markdown
**Last updated**: 2026-06-06 &nbsp;|&nbsp; **Current version**: v25.5 &nbsp;|&nbsp; **Next**: P4 remaining (Standards Platform 审定流模板可视化 / 跨标准影响图谱) &nbsp;|&nbsp; **ADK**: v1.27.2
```

2. Insert after the v25.4 section:

```markdown
## v25.5 — Standards Platform P4 Batch Rollback First Slice (已完成, 2026-06-06)

- [x] **Batch rollback repository/API** — 新增 `link_repo.rollback_versions()` 与 admin-only `POST /api/std/derive/rollback`，复用单版本 rollback 语义，支持 duplicate/missing/malformed ID 跳过与最多 50 个版本的批量请求。
- [x] **Batch rollback UI** — 在 `DeriveSubTab` 增加 admin-only 批量回滚运维面板，可加入当前版本或粘贴多个 version id，显示 rolled_back / skipped 汇总与逐版本结果。
- [x] **测试覆盖** — 新增 repository + API focused tests；`pytest data_agent/standards_platform -q` 与 `npm run build` 通过。

> P4 仍未完成的主线：审定流模板可视化、跨标准影响图谱。
```

- [ ] **Step 5: Commit roadmap**

```powershell
git add docs\roadmap.md
git commit -m "docs(roadmap): mark std-platform batch rollback slice complete"
```

- [ ] **Step 6: Final status check**

Run:

```powershell
git status --short --branch --untracked-files=no
```

Expected: no tracked changes.
