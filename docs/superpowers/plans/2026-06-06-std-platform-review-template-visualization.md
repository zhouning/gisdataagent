# Standards Platform Review Template Visualization Implementation Plan

> **For agentic workers:** Implement task-by-task. Use TDD for backend tasks.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only visualization of the default standards review
workflow in `ReviewSubTab`.

**Architecture:** Build a deterministic review-template read model from
existing review/version/reference/comment tables. Expose it through one read
API and render a compact panel above the existing review workspace. No new
migration or workflow behavior.

**Tech Stack:** Python 3.13, PostgreSQL, SQLAlchemy `text()`, Starlette
TestClient, pytest, React 18, TypeScript, Vite.

---

## Scope Check

This plan implements only the first P4 审定流模板可视化 slice from
`docs/superpowers/specs/2026-06-06-std-platform-review-template-visualization-design.md`.
It does not add editable templates, serial approval stages, a graph library, or
new database tables.

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `data_agent/standards_platform/review/template_repo.py` | Create | Default review-template read model |
| `data_agent/standards_platform/tests/test_review_template.py` | Create | Repository tests |
| `data_agent/api/standards_routes.py` | Modify | Review-template REST endpoint |
| `data_agent/standards_platform/tests/test_api_review_template.py` | Create | API tests |
| `frontend/src/components/datapanel/standards/standardsApi.ts` | Modify | Typed SDK |
| `frontend/src/components/datapanel/standards/review/ReviewTemplatePanel.tsx` | Create | Read-only template panel |
| `frontend/src/components/datapanel/standards/ReviewSubTab.tsx` | Modify | Mount and refresh panel |
| `docs/roadmap.md` | Modify | Mark P4 complete |

---

## Task 1: Design Documents

**Files:**
- Create:
  `docs/superpowers/specs/2026-06-06-std-platform-review-template-visualization-design.md`
- Create:
  `docs/superpowers/plans/2026-06-06-std-platform-review-template-visualization.md`

- [ ] **Step 1: Add design spec and implementation plan**
- [ ] **Step 2: Commit**

```powershell
git add docs\superpowers\specs\2026-06-06-std-platform-review-template-visualization-design.md docs\superpowers\plans\2026-06-06-std-platform-review-template-visualization.md
git commit -m "docs(std-platform): add review template visualization design"
```

---

## Task 2: Repository Review Template

**Files:**
- Create: `data_agent/standards_platform/review/template_repo.py`
- Create: `data_agent/standards_platform/tests/test_review_template.py`

- [ ] **Step 1: Write failing repository tests**

Cover:

1. draft version with no round marks draft active and later steps pending
2. review version with an open round and pending refs marks audit blocked
3. review version with refs approved and open comments marks comments blocked
4. review version with all gates clear marks close round active
5. approved version marks all review steps done

- [ ] **Step 2: Run tests to verify RED**

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_review_template.py -v --basetemp .pytest_review_template_task1_tmp
```

Expected: import/module failure because `review.template_repo` does not exist.

- [ ] **Step 3: Implement repository**

Create `default_review_template(version_id: str) -> dict`:

- read version metadata
- raise `LookupError("version not found")` for missing version
- find open round and latest round
- count reference statuses for clauses under the version
- count open/resolved comments for the open round if present, otherwise latest
  round
- compute six step statuses: `draft`, `start_review`, `audit_references`,
  `resolve_comments`, `close_round`, `approved`
- return `steps`, ordered `edges`, and `summary`

- [ ] **Step 4: Run repository tests to verify GREEN**
- [ ] **Step 5: Commit**

```powershell
git add data_agent\standards_platform\review\template_repo.py data_agent\standards_platform\tests\test_review_template.py
git commit -m "feat(std-platform): add review template repository"
```

---

## Task 3: Review Template API

**Files:**
- Modify: `data_agent/api/standards_routes.py`
- Create: `data_agent/standards_platform/tests/test_api_review_template.py`

- [ ] **Step 1: Write failing API tests**

Cover:

1. unauthenticated request gets `401`
2. missing version gets `404 {"error": "version not found"}`
3. happy path returns `template_id`, `version_id`, `steps`, and `summary`
4. route works beside existing `/api/std/reviews/rounds`

- [ ] **Step 2: Run API tests to verify RED**

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_api_review_template.py -v --basetemp .pytest_review_template_task2_tmp
```

Expected: `404 Not Found` because the route does not exist.

- [ ] **Step 3: Implement API**

Modify `data_agent/api/standards_routes.py`:

- import `template_repo as _template_repo`
- add `review_template_get(request)`
- call `_auth_or_401()`
- catch `LookupError` and return `404 {"error": "version not found"}`
- register `Route("/api/std/reviews/template/{version_id}", ...)`

- [ ] **Step 4: Run API tests to verify GREEN**
- [ ] **Step 5: Commit**

```powershell
git add data_agent\api\standards_routes.py data_agent\standards_platform\tests\test_api_review_template.py
git commit -m "feat(std-platform): expose review template API"
```

---

## Task 4: Frontend SDK and Review UI

**Files:**
- Modify: `frontend/src/components/datapanel/standards/standardsApi.ts`
- Create:
  `frontend/src/components/datapanel/standards/review/ReviewTemplatePanel.tsx`
- Modify: `frontend/src/components/datapanel/standards/ReviewSubTab.tsx`

- [ ] **Step 1: Add typed SDK**

Add:

- `ReviewTemplateStepStatus`
- `ReviewTemplateStep`
- `ReviewTemplateEdge`
- `ReviewTemplateSummary`
- `ReviewTemplate`
- `getReviewTemplate(versionId)`

- [ ] **Step 2: Create `ReviewTemplatePanel`**

Render:

- summary chips
- six ordered steps
- role and status badge per step
- blocked message from `summary.blocking`
- loading/error/empty states

- [ ] **Step 3: Mount in `ReviewSubTab`**

- place the panel above the existing four-column grid
- refresh on `versionId`, selected round change, reference update tick, and
  close-round tick
- preserve the existing review columns and operations

- [ ] **Step 4: Run frontend build**

```powershell
cd frontend
npm run build
```

- [ ] **Step 5: Commit**

```powershell
cd ..
git add frontend\src\components\datapanel\standards\standardsApi.ts frontend\src\components\datapanel\standards\review\ReviewTemplatePanel.tsx frontend\src\components\datapanel\standards\ReviewSubTab.tsx
git commit -m "feat(std-platform-fe): show review template panel"
```

---

## Task 5: Regression and Roadmap

**Files:**
- Modify: `docs/roadmap.md`

- [ ] **Step 1: Run focused backend tests**

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_review_template.py data_agent\standards_platform\tests\test_api_review_template.py -q --basetemp .pytest_review_template_focus_tmp
```

- [ ] **Step 2: Run full Standards Platform regression**

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform -q --basetemp .pytest_review_template_full_tmp
```

- [ ] **Step 3: Run frontend build**

```powershell
cd frontend
npm run build
```

- [ ] **Step 4: Update roadmap**

Update header to `v25.7` and mark P4 complete:

```markdown
## v25.7 — Standards Platform P4 Review Template Visualization First Slice (已完成, 2026-06-06)

- [x] **Review template repository/API** — 新增只读默认审定流模板，按现有 version / round / reference / comment 状态计算步骤、角色、门禁与摘要。
- [x] **Review UI** — 在 `ReviewSubTab` 顶部增加审定流模板面板，展示 draft → review → audit → comments → close → approved 的流程状态。
- [x] **测试覆盖** — 新增 repository + API focused tests；`pytest data_agent/standards_platform -q` 与 `npm run build` 通过。

> P4 三项（审定流模板可视化、批量回滚、跨标准影响图谱）全部完成。
```

- [ ] **Step 5: Commit roadmap**

```powershell
git add docs\roadmap.md
git commit -m "docs(roadmap): mark std-platform review template slice complete"
```

- [ ] **Step 6: Final status check**

```powershell
git status --short --branch --untracked-files=no
```
