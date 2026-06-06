# Standards Platform Market Catalog + Diff Implementation Plan

> **For agentic workers:** Implement task-by-task. Use TDD for backend tasks.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Start P5 with a released-standards market catalog and deterministic
version diff.

**Architecture:** Reuse existing released `std_document_version` rows as market
items. Build asset counts and version diff from current standards tables. Add
one frontend sub-tab. No migration in this slice.

**Tech Stack:** Python 3.13, PostgreSQL, SQLAlchemy `text()`, Starlette
TestClient, pytest, React 18, TypeScript, Vite.

---

## Scope Check

This plan implements only the P5 market catalog + diff first slice from
`docs/superpowers/specs/2026-06-06-std-platform-market-catalog-diff-design.md`.
It does not add subscription tables, organization ACLs, billing, ratings, or a
market approval workflow.

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `data_agent/standards_platform/market/__init__.py` | Create | Market package |
| `data_agent/standards_platform/market/catalog.py` | Create | Catalog + diff repository |
| `data_agent/standards_platform/tests/test_market_catalog.py` | Create | Repository tests |
| `data_agent/api/standards_routes.py` | Modify | Market REST endpoints |
| `data_agent/standards_platform/tests/test_api_market.py` | Create | API tests |
| `frontend/src/components/datapanel/standards/standardsApi.ts` | Modify | Typed SDK |
| `frontend/src/components/datapanel/standards/MarketSubTab.tsx` | Create | Market UI |
| `frontend/src/components/datapanel/StandardsTab.tsx` | Modify | Add Market tab |
| `docs/roadmap.md` | Modify | Mark P5 first slice complete |

---

## Task 1: Design Documents

**Files:**
- Create:
  `docs/superpowers/specs/2026-06-06-std-platform-market-catalog-diff-design.md`
- Create:
  `docs/superpowers/plans/2026-06-06-std-platform-market-catalog-diff.md`

- [ ] **Step 1: Add design spec and implementation plan**
- [ ] **Step 2: Commit**

```powershell
git add docs\superpowers\specs\2026-06-06-std-platform-market-catalog-diff-design.md docs\superpowers\plans\2026-06-06-std-platform-market-catalog-diff.md
git commit -m "docs(std-platform): add market catalog diff design"
```

---

## Task 2: Market Repository

**Files:**
- Create: `data_agent/standards_platform/market/__init__.py`
- Create: `data_agent/standards_platform/market/catalog.py`
- Create: `data_agent/standards_platform/tests/test_market_catalog.py`

- [ ] **Step 1: Write failing repository tests**

Cover:

1. catalog lists only `released` versions
2. catalog supports query filter and pagination
3. catalog includes asset counts
4. diff reports added/removed/changed/unchanged for clauses and data elements
5. missing source/target version raises `LookupError`

- [ ] **Step 2: Run tests to verify RED**

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_market_catalog.py -v --basetemp .pytest_market_task1_tmp
```

Expected: import/module failure because `standards_platform.market` does not
exist.

- [ ] **Step 3: Implement repository**

Create:

- `list_market_standards(query=None, limit=50, offset=0) -> dict`
- `version_diff(source_version_id, target_version_id) -> dict`

Implementation notes:

- catalog reads `released` versions only
- count assets through subqueries against standards tables
- cap `limit` in API, repository assumes valid numbers
- diff natural keys:
  - clause: `clause_no` else `ordinal_path`
  - data element: `code`
  - term: `term_code`
  - value domain: `code`
- compare stable content fields with a deterministic JSON hash

- [ ] **Step 4: Run repository tests to verify GREEN**
- [ ] **Step 5: Commit**

```powershell
git add data_agent\standards_platform\market data_agent\standards_platform\tests\test_market_catalog.py
git commit -m "feat(std-platform): add market catalog repository"
```

---

## Task 3: Market API

**Files:**
- Modify: `data_agent/api/standards_routes.py`
- Create: `data_agent/standards_platform/tests/test_api_market.py`

- [ ] **Step 1: Write failing API tests**

Cover:

1. unauthenticated catalog/diff requests get `401`
2. invalid limit/offset returns `400`
3. catalog happy path returns items
4. diff missing required IDs returns `400`
5. diff missing version returns `404`
6. diff happy path returns summary and changes

- [ ] **Step 2: Run API tests to verify RED**

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_api_market.py -v --basetemp .pytest_market_task2_tmp
```

Expected: `404 Not Found` because market routes do not exist.

- [ ] **Step 3: Implement API**

Modify `data_agent/api/standards_routes.py`:

- import `market.catalog as _market_catalog`
- add `market_list_standards_handler(request)`
- add `market_diff_handler(request)`
- validate `limit`, `offset`
- cap `limit` at `100`
- catch `LookupError` as `404`
- register routes:
  - `/api/std/market/standards`
  - `/api/std/market/diff`

- [ ] **Step 4: Run API tests to verify GREEN**
- [ ] **Step 5: Commit**

```powershell
git add data_agent\api\standards_routes.py data_agent\standards_platform\tests\test_api_market.py
git commit -m "feat(std-platform): expose market catalog API"
```

---

## Task 4: Frontend Market Sub-Tab

**Files:**
- Modify: `frontend/src/components/datapanel/standards/standardsApi.ts`
- Create: `frontend/src/components/datapanel/standards/MarketSubTab.tsx`
- Modify: `frontend/src/components/datapanel/StandardsTab.tsx`

- [ ] **Step 1: Add typed SDK**

Add:

- `MarketStandardItem`
- `MarketCatalogResponse`
- `MarketDiffChange`
- `MarketDiffResponse`
- `listMarketStandards(params?)`
- `getMarketDiff(sourceVersionId, targetVersionId)`

- [ ] **Step 2: Create `MarketSubTab`**

Render:

- released standards list with search
- asset count chips
- selected market item detail
- source/target version IDs
- diff summary and changes table
- button to select a market version as current active version

- [ ] **Step 3: Register in `StandardsTab`**

Add sub-tab key `market` and label `市场`.

- [ ] **Step 4: Run frontend build**

```powershell
cd frontend
npm run build
```

- [ ] **Step 5: Commit**

```powershell
cd ..
git add frontend\src\components\datapanel\standards\standardsApi.ts frontend\src\components\datapanel\standards\MarketSubTab.tsx frontend\src\components\datapanel\StandardsTab.tsx
git commit -m "feat(std-platform-fe): add standards market tab"
```

---

## Task 5: Regression and Roadmap

**Files:**
- Modify: `docs/roadmap.md`

- [ ] **Step 1: Run focused backend tests**

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_market_catalog.py data_agent\standards_platform\tests\test_api_market.py -q --basetemp .pytest_market_focus_tmp
```

- [ ] **Step 2: Run full Standards Platform regression**

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform -q --basetemp .pytest_market_full_tmp
```

- [ ] **Step 3: Run frontend build**

```powershell
cd frontend
npm run build
```

- [ ] **Step 4: Update roadmap**

Update header to `v25.8` and mark P5 first slice:

```markdown
## v25.8 — Standards Platform P5 Market Catalog + Diff First Slice (已完成, 2026-06-06)

- [x] **Market catalog repository/API** — released 标准版本市场目录，带文档元数据、标签、owner 和资产计数。
- [x] **Version diff API/UI** — 支持两个版本按 clause/data_element/term/value_domain 自然键做 added/removed/changed/unchanged diff。
- [x] **Market UI** — StandardsTab 新增「市场」子页，可搜索 released 标准、选择市场版本并查看 diff。
```

- [ ] **Step 5: Commit roadmap**

```powershell
git add docs\roadmap.md
git commit -m "docs(roadmap): mark std-platform market catalog slice complete"
```

- [ ] **Step 6: Final status check**

```powershell
git status --short --branch --untracked-files=no
```
