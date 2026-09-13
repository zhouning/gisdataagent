# Traditional Livability S7 Fulu Primary School Siting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver fail-closed parcel-level primary-school siting for the Heping and Banzhu village planning samples, using residential-land-area demand proxies and projected straight-line distance allocation.

**Architecture:** A Fulu planning adapter normalizes two village planning databases into boundaries, demand, candidates and exclusions. A pure S7 engine runs deterministic greedy allocation on projected centroid distances. An offline builder writes a snapshot that a fail-closed API and analysis-led two-column UI consume. No result can call the proxy a walking/network service area or assert capacity, compliance or future policy benefit.

**Tech Stack:** Python 3.11, GeoPandas, pyogrio, Shapely, pandas, Starlette, React/TypeScript, pytest, Vite.

---

### Task 1: Normalize Fulu Planning Data

**Files:**
- Create: `data_agent/uwm/traditional_livability_s7_fulu_adapter.py`
- Create: `data_agent/test_traditional_livability_s7_fulu_adapter.py`

- [ ] **Step 1: Write failing adapter tests**

Create temporary GeoPackage layers (`GHFW`, `JQDLTB`, `TDGHDL`) for Heping and Banzhu. Require:

```python
payload = load_fulu_s7_planning_inputs(source_root)
assert payload["schema"] == "uwm.traditional_livability.s7_fulu_planning_inputs.v1"
assert {row["planning_area_id"] for row in payload["planning_areas"]} == {"fulu_heping", "fulu_banzhu"}
assert payload["demand_parcels"][0]["demand_proxy"] == "residential_land_area_m2"
assert payload["candidate_parcels"][0]["suitability_score"] == 3
assert payload["excluded_parcels"][0]["exclusion_reason"] == "cultivated_land"
```

Also assert a missing layer returns `ready=False` and `missing_required_source:<area>:<layer>`.

- [ ] **Step 2: Verify RED**

Run: `pytest -q data_agent/test_traditional_livability_s7_fulu_adapter.py`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement the adapter**

Implement `inspect_fulu_s7_planning_sources(source_root: Path)` and `load_fulu_s7_planning_inputs(source_root: Path)`. Use verified village paths; calculate centroids/areas in source projected CRS. Demand is Heping `2121`/`宅基地（村居住用地）` and Banzhu `2121`/`村居住用地`. Candidates are `2123`/`村公共服务用地` (3), `2124`/`村混合用地` (2), `214`/`其他独立建设用地` (1). Map all other parcels to controlled reasons: cultivated, garden, forest, water, road, mining, facilities-agriculture, natural-reservation, other-land-use or invalid-area. Retain source IDs, working CRS, projected centroid and WGS84 display centroid.

- [ ] **Step 4: Verify GREEN**

Run: `pytest -q data_agent/test_traditional_livability_s7_fulu_adapter.py`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add data_agent/uwm/traditional_livability_s7_fulu_adapter.py data_agent/test_traditional_livability_s7_fulu_adapter.py && git commit -m "feat: add Fulu S7 planning adapter"`

### Task 2: Classify Existing Local Schools

**Files:**
- Modify: `data_agent/uwm/traditional_livability_s7_fulu_adapter.py`
- Modify: `data_agent/test_traditional_livability_s7_fulu_adapter.py`

- [ ] **Step 1: Write failing school-locality tests**

Pass primary-school facilities inside Heping, inside Banzhu, outside both and without coordinates. Require statuses `locally_verified_current_supply`, `locally_verified_current_supply`, `outside_planning_area_reference`, and `unlocatable_reference`; only local supply is eligible for baseline coverage.

- [ ] **Step 2: Verify RED**

Run: `pytest -q data_agent/test_traditional_livability_s7_fulu_adapter.py -k school`

Expected: FAIL because the classifier is absent.

- [ ] **Step 3: Implement the classifier**

Implement `classify_primary_school_supply(*, facility_product, planning_inputs)`. Read only exact class `education.primary_school`; transform WGS84 points into each planning-area CRS for containment; preserve facility source IDs.

- [ ] **Step 4: Verify GREEN**

Run: `pytest -q data_agent/test_traditional_livability_s7_fulu_adapter.py -k school`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add data_agent/uwm/traditional_livability_s7_fulu_adapter.py data_agent/test_traditional_livability_s7_fulu_adapter.py && git commit -m "feat: classify S7 local school supply"`

### Task 3: Implement Greedy Distance-Proxy Allocation

**Files:**
- Create: `data_agent/uwm/traditional_livability_s7.py`
- Create: `data_agent/test_traditional_livability_s7.py`

- [ ] **Step 1: Write failing allocation tests**

Build projected synthetic demand/candidate fixtures. Require the greatest new proxy area wins; repeated coverage loses; remaining ties use suitability, candidate area, then parcel ID:

```python
result = build_s7_primary_school_siting(..., coverage_distance_m=1500, max_sites=2)
assert result["schema"] == "uwm.traditional_livability.s7_siting.v1"
assert result["assumptions"]["distance_cost_provider"] == "projected_straight_line_distance_proxy"
assert result["selected_sites"][0]["parcel_id"] == "candidate-best"
assert result["selected_sites"][0]["newly_covered_proxy_area_m2"] == 4000
```

Require no candidates to return `recommendation_status="no_recommendation"` plus `candidate_policy_no_eligible_parcels`; zero/negative threshold raises `ValueError`; serialized result does not include walking time.

- [ ] **Step 2: Verify RED**

Run: `pytest -q data_agent/test_traditional_livability_s7.py`

Expected: FAIL because engine module does not exist.

- [ ] **Step 3: Implement the pure engine**

Implement `build_s7_primary_school_siting(*, siting_id, created_at, planning_inputs, school_supply, coverage_distance_m, max_sites)`. Calculate Euclidean metres only within same planning area and CRS. Baseline coverage uses only local schools. Per round rank `(-new_area, repeated_area, -suitability, -candidate_area, parcel_id)`. Return filter funnel, demand summary, all ranked candidates, selections, unserved area, WGS84 `geometry_payload` with `distance_proxy_circle_radius_m`, blockers and claim boundary.

- [ ] **Step 4: Verify GREEN**

Run: `pytest -q data_agent/test_traditional_livability_s7.py`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add data_agent/uwm/traditional_livability_s7.py data_agent/test_traditional_livability_s7.py && git commit -m "feat: add S7 primary school allocation"`

### Task 4: Build Offline Snapshot and API

**Files:**
- Create: `scripts/build_traditional_livability_s7_fulu.py`
- Create: `data_agent/test_build_traditional_livability_s7_fulu.py`
- Modify: `data_agent/api/uwm_traditional_livability_routes.py`
- Modify: `data_agent/test_uwm_traditional_livability_routes.py`

- [ ] **Step 1: Write failing tests**

Require the builder to atomically write `uwm_traditional_livability_s7.json` without absolute paths. Missing sources must return `ready=False` and write no S7 snapshot. Require authenticated `GET /api/uwm/traditional-livability/s7` to read valid snapshot and return 503 with `s7_snapshot_missing`/`s7_snapshot_schema_invalid` otherwise.

- [ ] **Step 2: Verify RED**

Run: `pytest -q data_agent/test_build_traditional_livability_s7_fulu.py && pytest -q data_agent/test_uwm_traditional_livability_routes.py -k s7`

Expected: FAIL because builder and route are absent.

- [ ] **Step 3: Implement snapshot flow**

Script flags are `--source-root`, `--facility-product`, `--output`, `--coverage-distance-m` default `1500`, `--max-sites` default `3`. It invokes Tasks 1–3 and records scope `fulu_heping_and_banzhu_planning_samples_only`. Route resolves only `UWM_TRADITIONAL_LIVABILITY_S7_PATH` or controlled output; it never reads Downloads or runs GIS work in GET.

- [ ] **Step 4: Verify GREEN**

Run: `pytest -q data_agent/test_build_traditional_livability_s7_fulu.py && pytest -q data_agent/test_uwm_traditional_livability_routes.py -k s7`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add scripts/build_traditional_livability_s7_fulu.py data_agent/test_build_traditional_livability_s7_fulu.py data_agent/api/uwm_traditional_livability_routes.py data_agent/test_uwm_traditional_livability_routes.py && git commit -m "feat: expose Fulu S7 siting snapshot"`

### Task 5: Render Analysis-Led S7 UI

**Files:**
- Create: `frontend/src/components/datapanel/TraditionalLivabilityS7Panel.tsx`
- Modify: `frontend/src/components/datapanel/TraditionalLivabilityTab.tsx`
- Modify: `data_agent/test_uwm_traditional_livability_frontend_contract.py`

- [ ] **Step 1: Write failing frontend contract tests**

Require `/api/uwm/traditional-livability/s7`, `福禄镇和平村与斑竹村`, `住宅用地面积代理`, `距离代理覆盖范围`, `候选过滤漏斗`, `新增覆盖面积`, `重复覆盖面积`, `candidate_policy_no_eligible_parcels`; prohibit `步行服务区` and `15分钟步行`.

- [ ] **Step 2: Verify RED**

Run: `pytest -q data_agent/test_uwm_traditional_livability_frontend_contract.py`

Expected: FAIL because the panel is absent.

- [ ] **Step 3: Implement selected A layout**

Create independent load/error state. Left column shows scope, proxy, threshold, funnel, ranked candidates, selections, blockers and claim boundary. Right map action queues only `小学候选地块`, `住宅用地需求代理`, `距离代理覆盖范围`, `排除地块` via `window.__handleMapUpdate`. Unavailable state says unavailable and emits no recommendation.

- [ ] **Step 4: Verify GREEN and build**

Run: `pytest -q data_agent/test_uwm_traditional_livability_frontend_contract.py && cd frontend && npm run build`

Expected: PASS and Vite exits 0.

- [ ] **Step 5: Commit**

Run: `git add frontend/src/components/datapanel/TraditionalLivabilityS7Panel.tsx frontend/src/components/datapanel/TraditionalLivabilityTab.tsx data_agent/test_uwm_traditional_livability_frontend_contract.py && git commit -m "feat: show Fulu S7 school siting analysis"`

### Task 6: Verify with Real Data

**Files:**
- Create: `docs/reports/traditional_livability_s7_fulu_verification_2026-07-10.md`

- [ ] **Step 1: Run the real builder**

Run: `python scripts/build_traditional_livability_s7_fulu.py --source-root /private/tmp/planning_sample_audit/规划院提供数据样例及Demo系统功能演示建议/01数据样例 --facility-product /private/tmp/traditional_livability_phase1a_final2/uwm_traditional_livability_facility_product.json --output /private/tmp/traditional_livability_s7_fulu_real --coverage-distance-m 1500 --max-sites 3`

- [ ] **Step 2: Inspect public claims**

Assert output scope is two samples; provider is projected proxy; metrics use `proxy_area_m2`; no walking-time wording or absolute source root exists; filter funnel and no-recommendation state are factual.

- [ ] **Step 3: Write verification report**

Record runtime, counts, funnel, proxy area, local-school count, result status, sampling, blockers and non-claims. State selected parcels are analytical rankings under a proxy, not approved school sites.

- [ ] **Step 4: Run focused regression**

Run: `pytest -q data_agent/test_traditional_livability_facility_product.py data_agent/test_traditional_livability_source_adapter.py data_agent/test_traditional_livability_s1.py data_agent/test_traditional_livability_s7_fulu_adapter.py data_agent/test_traditional_livability_s7.py data_agent/test_build_traditional_livability_phase1a.py data_agent/test_build_traditional_livability_s7_fulu.py data_agent/test_uwm_traditional_livability_routes.py data_agent/test_uwm_traditional_livability_analysis.py data_agent/test_uwm_traditional_livability_frontend_contract.py`

Expected: PASS with zero failures.

- [ ] **Step 5: Commit**

Run: `git add docs/reports/traditional_livability_s7_fulu_verification_2026-07-10.md && git commit -m "test: verify Fulu S7 school siting"`

## Plan Self-Review

- **Spec coverage:** Tasks 1–2 implement source and supply contracts; Task 3 covers filtering and allocation; Task 4 is reproducible/fail-closed; Task 5 implements selected UI; Task 6 verifies real data and regressions.
- **Placeholder scan:** No fallback points, automatic candidate relaxation, unspecified standards or walking-time claims are allowed.
- **Type consistency:** `planning_inputs`, `school_supply`, `build_s7_primary_school_siting`, `geometry_payload`, `coverage_distance_m`, and the snapshot schema are defined before their consumers.
