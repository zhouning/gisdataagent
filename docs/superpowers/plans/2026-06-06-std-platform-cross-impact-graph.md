# Standards Platform Cross-Standard Impact Graph Implementation Plan

> **For agentic workers:** Implement task-by-task. Use TDD for backend tasks.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only version-level cross-standard impact graph first slice.

**Architecture:** Build a graph response from existing storage:
`std_derived_link`, `std_reference`, and `deduper.find_similar_clauses()`.
Expose it through a read API and render a compact summary/list in
`AnalyzeSubTab`. No new migration or graph persistence.

**Tech Stack:** Python 3.13, PostgreSQL, SQLAlchemy `text()`, Starlette
TestClient, pytest, React 18, TypeScript, Vite.

---

## Scope Check

This plan implements only the first P4 cross-standard impact graph slice from
`docs/superpowers/specs/2026-06-06-std-platform-cross-impact-graph-design.md`.
It does not add a graph layout engine, recursive multi-hop traversal, rollback
preview, graph editing, or new database tables.

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `data_agent/standards_platform/analysis/impact_graph.py` | Create | Version impact graph builder |
| `data_agent/standards_platform/tests/test_cross_impact_graph.py` | Create | Repository graph tests |
| `data_agent/api/standards_routes.py` | Modify | Version impact graph REST endpoint |
| `data_agent/standards_platform/tests/test_api_cross_impact_graph.py` | Create | API tests |
| `frontend/src/components/datapanel/standards/standardsApi.ts` | Modify | Typed graph SDK |
| `frontend/src/components/datapanel/standards/AnalyzeSubTab.tsx` | Modify | Compact graph summary/list |
| `docs/roadmap.md` | Modify | Mark first slice complete |

---

## Task 1: Repository Cross-Impact Graph

**Files:**
- Create: `data_agent/standards_platform/analysis/impact_graph.py`
- Create: `data_agent/standards_platform/tests/test_cross_impact_graph.py`

- [ ] **Step 1: Write failing repository tests**

Cover:

1. graph contains a version root node and derivation edge from
   `std_derived_link`
2. graph contains a cross-version `references` edge from `std_reference`
3. graph includes `similar_clause` edges when `deduper.find_similar_clauses()`
   returns hits
4. graph excludes similar edges when `include_similar=False`

Use existing `engine` and `fresh_clause` fixtures where possible. For
cross-version reference tests, seed a second document/version/clause and delete
the second document in `finally`.

- [ ] **Step 2: Run tests to verify RED**

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_cross_impact_graph.py -v --basetemp .pytest_cross_impact_task1_tmp
```

Expected: import/module failure because `analysis.impact_graph` does not exist.

- [ ] **Step 3: Implement graph builder**

Create `data_agent/standards_platform/analysis/impact_graph.py`:

- `version_impact_graph(version_id, include_similar=True, min_similarity=0.8,
  top_k=20) -> dict`
- local `add_node()` helper dedupes nodes by graph ID
- local `edge_summary()` helper computes `by_edge_type`,
  `cross_version_edge_count`, `node_count`, `edge_count`
- query version metadata via `std_document_version JOIN std_document`
- return an empty graph shape with root version node for existing versions with
  no edges
- derivation edges from `std_derived_link`
- reference edges from `std_reference` rows whose source clause belongs to the
  version
- similar edges via `deduper.find_similar_clauses()`

- [ ] **Step 4: Run repository tests to verify GREEN**

Run the same focused repository command.

- [ ] **Step 5: Commit**

```powershell
git add data_agent\standards_platform\analysis\impact_graph.py data_agent\standards_platform\tests\test_cross_impact_graph.py
git commit -m "feat(std-platform): add cross-standard impact graph repository"
```

---

## Task 2: Cross-Impact Graph API

**Files:**
- Modify: `data_agent/api/standards_routes.py`
- Create: `data_agent/standards_platform/tests/test_api_cross_impact_graph.py`

- [ ] **Step 1: Write failing API tests**

Cover:

1. unauthenticated request gets `401`
2. missing version gets `404 {"error": "version not found"}`
3. invalid `top_k` or `min_similarity` gets `400`
4. happy path delegates to `_impact_graph.version_impact_graph()`
5. route is static and not shadowed by `/api/std/impact/{kind}/{source_id}`

- [ ] **Step 2: Run API tests to verify RED**

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_api_cross_impact_graph.py -v --basetemp .pytest_cross_impact_task2_tmp
```

Expected: `404 Not Found` because `/api/std/impact/versions/{version_id}` does
not exist.

- [ ] **Step 3: Implement API**

Modify `data_agent/api/standards_routes.py`:

- import `analysis.impact_graph as _impact_graph`
- add helper parsing for float/bool if local patterns do not already exist
- add `derive_version_impact_graph_handler(request)`
- validate version existence with `std_document_version`
- query params:
  - `include_similar`: default true; false when `0`, `false`, or `False`
  - `min_similarity`: default `0.8`
  - `top_k`: default `20`; reject non-int; cap above 100 to 100
- register `Route("/api/std/impact/versions/{version_id}", ...)` before
  `Route("/api/std/impact/{kind}/{source_id}", ...)`

- [ ] **Step 4: Run API tests to verify GREEN**

Run the same focused API command.

- [ ] **Step 5: Commit**

```powershell
git add data_agent\api\standards_routes.py data_agent\standards_platform\tests\test_api_cross_impact_graph.py
git commit -m "feat(std-platform): expose cross-standard impact graph API"
```

---

## Task 3: Frontend Graph SDK and Analyze UI

**Files:**
- Modify: `frontend/src/components/datapanel/standards/standardsApi.ts`
- Modify: `frontend/src/components/datapanel/standards/AnalyzeSubTab.tsx`

- [ ] **Step 1: Add typed SDK**

Add:

- `ImpactGraphNode`
- `ImpactGraphEdge`
- `ImpactGraphSummary`
- `ImpactGraphResult`
- `getVersionImpactGraph(versionId, params?)`

Endpoint:

```typescript
GET /api/std/impact/versions/${versionId}
```

with optional `include_similar`, `min_similarity`, `top_k`.

- [ ] **Step 2: Update AnalyzeSubTab**

Keep the current clause/data-element/term/similar sections and add:

- impact graph state: loading/error/result
- load graph on `versionId` changes
- summary row for node/edge counts and edge type counts
- scrollable edge list grouped visually by `edge_type`
- compact text-only first slice; no force graph/canvas

- [ ] **Step 3: Run frontend build**

```powershell
cd frontend
npm run build
```

- [ ] **Step 4: Commit**

```powershell
cd ..
git add frontend\src\components\datapanel\standards\standardsApi.ts frontend\src\components\datapanel\standards\AnalyzeSubTab.tsx
git commit -m "feat(std-platform-fe): show cross-standard impact graph"
```

---

## Task 4: Regression and Roadmap

**Files:**
- Modify: `docs/roadmap.md`

- [ ] **Step 1: Run focused backend tests**

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_cross_impact_graph.py data_agent\standards_platform\tests\test_api_cross_impact_graph.py -q --basetemp .pytest_cross_impact_focus_tmp
```

- [ ] **Step 2: Run full Standards Platform regression**

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform -q --basetemp .pytest_cross_impact_full_tmp
```

- [ ] **Step 3: Run frontend build**

```powershell
cd frontend
npm run build
```

- [ ] **Step 4: Update roadmap**

Update header:

```markdown
**Last updated**: 2026-06-06 &nbsp;|&nbsp; **Current version**: v25.6 &nbsp;|&nbsp; **Next**: P4 remaining (Standards Platform 审定流模板可视化) &nbsp;|&nbsp; **ADK**: v1.27.2
```

Insert after v25.5:

```markdown
## v25.6 — Standards Platform P4 Cross-Standard Impact Graph First Slice (已完成, 2026-06-06)

- [x] **Version impact graph repository/API** — 新增版本级影响图谱聚合，统一派生链、引用关系与相似条款边，输出 nodes/edges/summary。
- [x] **Analyze UI** — 在 `AnalyzeSubTab` 增加跨标准影响图谱摘要与边列表，展示 derives / references / similar_clause 关系和跨版本边计数。
- [x] **测试覆盖** — 新增 repository + API focused tests；`pytest data_agent/standards_platform -q` 与 `npm run build` 通过。

> P4 仍未完成的主线：审定流模板可视化。
```

- [ ] **Step 5: Commit roadmap**

```powershell
git add docs\roadmap.md
git commit -m "docs(roadmap): mark std-platform cross-impact graph slice complete"
```

- [ ] **Step 6: Final status check**

```powershell
git status --short --branch --untracked-files=no
```
