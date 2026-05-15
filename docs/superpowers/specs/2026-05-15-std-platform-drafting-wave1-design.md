# Standards Platform — Drafting Wave 1 Design

**Date:** 2026-05-15
**Branch:** `feat/v12-extensible-platform`
**Status:** design — ready for implementation plan
**Parent spec:** `docs/superpowers/specs/2026-05-13-data-standard-lifecycle-platform-design.md`
**Scope:** P1 「起草」 sub-tab, first of three waves

## 0. Why this spec is small

The full P1 「起草」 sub-project in the parent spec covers a TipTap WYSIWYG
editor, clause-level concurrent locking, a three-source citation assistant,
AI drafting suggestions, and a consistency checker — easily a 7‑9 day, 30+
task piece of work with high blocker risk if shipped in one go. We split it
into three waves and brainstorm each separately so progress stays demoable:

| Wave | Theme | This spec | ETA |
|---|---|---|---|
| 1 | Editor skeleton + concurrent lock | ✅ | 2–3 days |
| 2 | Citation assistant (pgvector + KB + web) | future | 3–4 days |
| 3 | AI drafting suggestions | future | 2 days |

Consistency-checking moves to the future 「审定」 sub-tab per the user's
2026-05-15 brainstorming decision.

## 1. Scope of Wave 1

**Delivered**

- A new `DraftSubTab` under `数据标准 → 起草`. Three columns: clause tree
  (left, reuses analyze data) / TipTap WYSIWYG body editor (center) /
  clause meta panel (right, read-only).
- Clause-level optimistic concurrent edit lock per spec §6.3:
  - `acquire_lock` with 15‑minute TTL
  - 30 s client heartbeat to extend TTL
  - Optimistic save with `If-Match: <checksum>` for conflict detection
  - Explicit release on tab close / clause switch
  - Admin force-break with audit-log entry
- Five new REST endpoints under `/api/std/clauses/{id}/*`.
- TipTap as a frontend dependency (full install per user decision).
- New role gate: `editor = {admin, analyst, standard_editor}` already
  defined in the parent spec.

**Explicitly NOT in this wave**

- Creating, deleting, or restructuring clauses
- Citation insertion, AI suggestions, consistency rules
- Three-way merge UI on checksum conflict (return 409 + server snapshot;
  user picks "view server / cancel")
- Real-time collaborative editing (OT / CRDT)
- Undo history beyond what TipTap provides in-memory

## 2. Architecture

### 2.1 Backend (new under `data_agent/standards_platform/drafting/`)

```
drafting/
├── __init__.py
└── editor_session.py     # 5 functions, raw SQL, transaction-wrapped
```

`editor_session.py` interface:

```python
class LockError(Exception):
    """Raised when the caller cannot hold or no longer holds the lock.
    Carries .holder and .expires_at when applicable."""

class ConflictError(Exception):
    """Raised on optimistic concurrency conflict.
    Carries .server_checksum and .server_body_md."""

def acquire_lock(clause_id: str, user_id: str, *, ttl_minutes: int = 15) -> dict
def heartbeat(clause_id: str, user_id: str, *, ttl_minutes: int = 15) -> dict
def release_lock(clause_id: str, user_id: str) -> None
def save_clause(clause_id: str, user_id: str, *,
                if_match_checksum: str,
                body_md: str, body_html: str | None) -> dict
def break_lock(clause_id: str, admin_user_id: str) -> dict
```

Each function opens its own `with eng.begin() as conn:` transaction and
issues parameterised raw SQL (project convention). Errors propagate via
the two custom exceptions; the route layer maps them to HTTP status codes.

### 2.2 Backend routes (appended to `data_agent/api/standards_routes.py`)

| Method | Path | Role | Calls |
|---|---|---|---|
| POST | `/api/std/clauses/{id}/lock` | editor | `acquire_lock` |
| POST | `/api/std/clauses/{id}/heartbeat` | editor | `heartbeat` |
| POST | `/api/std/clauses/{id}/lock/release` | editor | `release_lock` |
| PUT | `/api/std/clauses/{id}` | editor | `save_clause` |
| POST | `/api/std/clauses/{id}/lock/break` | admin | `break_lock` |

Exception → HTTP mapping:

| Exception | Status | Body |
|---|---|---|
| `LockError` from `acquire_lock` | 423 Locked | `{holder, expires_at}` |
| `LockError` from `heartbeat` / `save_clause` | 410 Gone | `{message}` |
| `ConflictError` from `save_clause` | 409 Conflict | `{server_checksum, server_body_md}` |
| Non-editor role | 403 Forbidden | `{error}` |

### 2.3 Frontend (new under `frontend/src/components/datapanel/standards/draft/`)

```
standards/
├── StandardsTab.tsx              # remove "draft" from disabled list
├── DraftSubTab.tsx               # three-column layout
├── draft/
│   ├── ClauseTree.tsx            # left, reuses getVersionClauses
│   ├── ClauseEditor.tsx          # center, TipTap + lock indicator + Save
│   └── ClauseMeta.tsx            # right, read-only metadata
└── standardsApi.ts               # +5 fetch functions
```

### 2.4 New npm dependencies

- `@tiptap/react@^2`
- `@tiptap/starter-kit@^2`
- `@tiptap/extension-placeholder@^2`
- `@tiptap/extension-link@^2`
- `marked@^12` — Markdown → HTML on initial load
- `turndown@^7` — HTML → Markdown on save

Mention / collaboration / AI extensions are deferred to waves 2/3.

### 2.5 No database migration

`std_clause` already has `lock_holder`, `lock_expires_at`, `checksum`,
`body_md`, `body_html`, `updated_at`, `updated_by`. The audit table
`agent_audit_log` (migration 007) has `username`, `action`, `details
jsonb`. No schema change needed.

## 3. Key data flows

### 3.1 Enter draft view

```
User selects version in 分析 → 起草 tab
  GET /api/std/versions/{vid}/clauses     (existing P0 endpoint)
  → render left tree by ordinal_path
  → right + center empty placeholder
```

### 3.2 Click clause → acquire lock → edit

```
Click clause C
  POST /api/std/clauses/C/lock           {}
    Server (single SQL, atomic):
      UPDATE std_clause
         SET lock_holder=:u,
             lock_expires_at=now() + interval '15 min',
             checksum = COALESCE(checksum, :computed)   -- lazy backfill
       WHERE id=:c
         AND (lock_holder IS NULL
              OR lock_holder=:u
              OR lock_expires_at < now())
       RETURNING checksum, body_md, body_html, lock_expires_at
    rowcount == 0 → LockError (held by someone else, not expired)
                    Re-SELECT to fetch current holder for the 423 body.
    rowcount == 1 → 200 + {checksum, body_md, body_html, expires_at,
                            lock_token: user_id}
  
  Client:
    Populate TipTap with body_md
    setInterval(30_000, heartbeat)
```

### 3.3 Heartbeat

```
Every 30 s:
  POST /api/std/clauses/C/heartbeat       {lock_token}
    UPDATE std_clause
       SET lock_expires_at = now() + interval '15 min'
     WHERE id=:c AND lock_holder=:u
     RETURNING lock_expires_at
    rowcount == 0 → LockError → 410 → client clears interval,
                                      disables editor, shows "锁丢失"
```

### 3.4 Save

```
Click Save (or Ctrl+S):
  PUT /api/std/clauses/C
    Headers: If-Match: <checksum_baseline>
    Body: {lock_token, body_md, body_html}
    Server transaction:
      row = SELECT checksum, lock_holder, lock_expires_at
              FROM std_clause WHERE id=:c FOR UPDATE
      IF row.checksum != if_match
         → ConflictError(row.checksum, row.body_md) → 409
      IF row.lock_holder != user OR row.lock_expires_at < now()
         → LockError → 410
      new_checksum = sha256(body_md)[:16]
      UPDATE std_clause
         SET body_md=:b, body_html=:h, checksum=:new_chk,
             updated_at=now(), updated_by=:u
       WHERE id=:c
       RETURNING checksum, updated_at
    → 200 + {checksum, updated_at}

  Client: update baseline checksum, mark editor dirty=false
```

### 3.5 Release

```
On clause switch / tab close / Esc:
  POST /api/std/clauses/C/lock/release    {lock_token}
    UPDATE std_clause
       SET lock_holder=NULL, lock_expires_at=NULL
     WHERE id=:c AND lock_holder=:u
  (idempotent, never errors)
  
  Browser-close case: best-effort via navigator.sendBeacon();
  if it fails, the 15-minute TTL handles cleanup.
```

### 3.6 Admin force-break

```
Admin sees "Locked by user_A until 14:32" → click "Force break"
  POST /api/std/clauses/C/lock/break
    role check: admin only
    Transaction:
      old_holder = SELECT lock_holder FROM std_clause
                    WHERE id=:c FOR UPDATE
      UPDATE std_clause SET lock_holder=NULL, lock_expires_at=NULL
       WHERE id=:c
      INSERT INTO agent_audit_log (username, action, details)
        VALUES (:admin, 'std_clause.lock.break',
                CAST(:meta AS jsonb))
        where meta = {clause_id, previous_holder: old_holder}
    → 200 + {previous_holder}
```

## 4. Checksum strategy

```python
import hashlib
def compute_checksum(body_md: str) -> str:
    return hashlib.sha256(body_md.encode("utf-8")).hexdigest()[:16]
```

64-bit truncated hash — collision probability is negligible at human-edit
scale and matches the existing `std_clause.checksum TEXT` column nicely.

P0 inserted clauses with `checksum = NULL`. We **lazy-backfill on first
`acquire_lock`** (see §3.2): if `checksum IS NULL`, compute and store in
the same UPDATE. No migration, no big bang.

## 5. Frontend behaviour

### 5.1 Component layout

```
DraftSubTab
├── (left, 25%)   ClauseTree
│                    – flat list of clauses ordered by ordinal_path
│                    – click highlights selected, calls onSelect(clauseId)
│
├── (center, 50%) ClauseEditor
│                    – lock-status bar at top:
│                        green  "已加锁，14:59 后过期"
│                        red    "未持有锁 / 锁丢失" (editor disabled)
│                        amber  "正在加载…"
│                    – TipTap editor body
│                    – footer: [Save] [Release & Close] [last-saved time]
│
└── (right, 25%)  ClauseMeta
                     read-only: clause_no, heading, kind,
                                source_origin, updated_by, updated_at
```

### 5.2 Lock state machine (client)

```
idle ──click──► acquiring ──200──► editing ──save──► editing
                  │                    │
                  └───423──► locked-by-other
                  └───403──► not-editor
                  
editing ──heartbeat-410──► lost
        ──save-409──► conflict-modal ──[view server]/[cancel]──► editing
        ──save-200──► editing (new baseline)
        ──release──► idle
```

### 5.3 TipTap configuration and Markdown round-trip

- `StarterKit` (bold, italic, lists, headings, blockquote, code, history)
- `Placeholder` ("开始编写条款内容…")
- `Link` (manual URL insertion)
- Editable bound to lock-state: when not in `editing`, `editor.setEditable(false)`

TipTap is HTML-native; `std_clause` stores Markdown in `body_md` as the
canonical form. Round-trip:

- **Load**: `body_md → marked.parse() → HTML → editor.commands.setContent()`
- **Save**: `editor.getHTML() → turndown → body_md` AND `editor.getHTML() → body_html`

Both fields are sent on save so the backend can serve either form to
later consumers (the analyze sub-tab already renders `body_md` via
`react-markdown`). The lossy edge cases (tables, footnotes, raw HTML
blocks) are listed in §8.

## 6. Testing strategy

### 6.1 Unit tests (new file)

`data_agent/standards_platform/tests/test_editor_session.py` — 12 cases:

1. `test_acquire_lock_when_unlocked`
2. `test_acquire_lock_when_held_by_other`
3. `test_acquire_lock_when_expired_steals`
4. `test_acquire_lock_same_user_renews`
5. `test_heartbeat_extends_expiry`
6. `test_heartbeat_lost_lock_raises`
7. `test_save_clause_happy_path`
8. `test_save_clause_checksum_mismatch_raises_conflict`
9. `test_save_clause_lost_lock_raises`
10. `test_release_lock_idempotent`
11. `test_break_lock_writes_audit`
12. `test_lazy_checksum_on_first_acquire`

### 6.2 API tests

`data_agent/standards_platform/tests/test_api_drafting.py` — 5 cases,
one per endpoint, asserting status codes and JSON shape. Reuses the
`_client()` fixture from `test_api_standards.py`.

### 6.3 Frontend

No automated UI tests in this wave. Manual checklist:

1. admin login → GBT 21010 → 起草 sub-tab loads
2. Click RT.1 → editor loads body_md, status bar green
3. Edit & Save → status bar updates, no errors
4. Second admin in incognito → same clause → 423 with holder info
5. `UPDATE std_clause SET lock_expires_at = now() WHERE id=…` →
   second admin retries → success (steal expired lock)
6. In window A, devtools changes the checksum value the editor holds,
   then Save → 409 with server snapshot in response
7. Admin clicks Force-break → `agent_audit_log` has a new row with
   action='std_clause.lock.break'

### 6.4 Regression

Full `pytest data_agent/` must remain at 211 passed (P0 baseline) + 17
new = 228 expected. `npm run build` must exit 0.

## 7. Done criteria

- [ ] 5 routes mounted, smoke-tested via curl with admin cookie
- [ ] 12 unit tests + 5 API tests pass
- [ ] `npm run build` clean
- [ ] DraftSubTab visible (not disabled) in 数据标准 tab
- [ ] Manual checklist §6.3 all 7 steps pass
- [ ] `agent_audit_log` shows a force-break entry

## 8. Risks and limits

| Risk | Mitigation |
|---|---|
| TipTap bundle ≈ 150 KB gz on top of an already ≈ 1 MB main bundle | Accepted. Code-split deferred to wave 2 |
| User closes browser without `release` request | 15-min TTL self-heals; `acquire` clears expired locks |
| Same user opens two tabs on the same clause | Same-user `acquire` renews the lock, but the second save still hits 409 because the first save changed checksum. Acceptable UX |
| `body_md` >100 KB | TEXT column has no hard limit; client shows warning above 100 KB |
| AnalyzeSubTab cache after save | Existing tab re-fetches on remount; no cross-tab live invalidation |
| Markdown ↔ HTML round-trip data loss for TipTap-unsupported MD | Accept some normalisation. Original raw still in `std_clause.source_origin`. Known lossy: GFM tables (StarterKit lacks the table extension in this wave), footnotes, raw HTML blocks. If a clause body contains these, the editor will display the source as-is via `<p>` paragraphs and the user can choose not to save. Wave 2/3 may add `@tiptap/extension-table` if needed |

## 9. Out of scope (deferred)

- Clause creation / deletion / re-ordering
- Three-way merge UI on 409
- Citation insertion `[[ref:id]]` (wave 2)
- LLM drafting suggestions (wave 3)
- Consistency rules (审定 sub-tab)
- Real-time collaborative cursors
- Per-clause comment threads (审定 sub-tab)

## 10. Implementation order

Suggested for the writing-plans step:

1. `editor_session.py` skeleton + `compute_checksum`
2. Unit tests 1–4 (lock acquire variants) → green
3. Unit tests 5–6 (heartbeat) → green
4. Unit tests 7–9 (save) → green
5. Unit tests 10–12 (release / break / lazy checksum) → green
6. Add 5 routes to `standards_routes.py`
7. API tests → green
8. `npm install` TipTap deps
9. `standardsApi.ts` +5 fetch functions
10. `ClauseMeta.tsx` (simplest, read-only)
11. `ClauseTree.tsx`
12. `ClauseEditor.tsx` (most complex, owns lock state machine)
13. `DraftSubTab.tsx` (layout + version-id plumbing)
14. Enable `"draft"` in StandardsTab.tsx
15. `npm run build` + manual E2E
