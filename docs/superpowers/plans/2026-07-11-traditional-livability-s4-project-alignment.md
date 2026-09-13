# Traditional Livability S4 Project Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an evidence-bounded S4 workflow for assessing multi-use project GFA schedules on real Heping and Banzhu planning parcels.

**Architecture:** A project-input module validates and audits multi-use GFA schedules. A pure S4 engine orchestrates existing S1 demand evidence, S6 semantic/spatial evidence and parcel-direct relationships without duplicating their logic. FastAPI exposes server-snapshot-only resources and analysis endpoints, and an independent React panel supports dynamic project uses, evidence review and engine-generated map layers.

**Tech Stack:** Python 3.11, pytest, FastAPI, GeoPandas/Shapely through existing S6 contracts, React, TypeScript, Leaflet/Vite.

---

## File Structure

- Create `data_agent/uwm/traditional_livability_s4_project.py`: validate project/use input, GFA, identities, audit fields and digest.
- Create `data_agent/uwm/traditional_livability_s4.py`: orchestrate semantic, parcel, S1 and S6 evidence and GFA summaries.
- Modify `data_agent/api/uwm_traditional_livability_routes.py`: expose S4 resources/analyze using validated S1/S6 snapshots.
- Create `frontend/src/components/datapanel/TraditionalLivabilityS4Panel.tsx`: dynamic multi-use project interface and map output.
- Modify `frontend/src/components/datapanel/TraditionalLivabilityTab.tsx`: mount the S4 panel.
- Add focused unit, route, frontend and real-data verification coverage.

### Task 1: Validate and Audit Project GFA Input

**Files:**
- Create: `data_agent/uwm/traditional_livability_s4_project.py`
- Create: `data_agent/test_traditional_livability_s4_project.py`

- [ ] **Step 1: Write failing tests**

Require valid multi-use normalization, stable IDs, exact raw/normalized audit fields, canonical SHA-256 digest, authenticated actor override support and total GFA reconciliation. Reject empty project name, empty uses, duplicate use IDs, zero/negative/NaN/infinite/non-numeric GFA and non-object use rows.

```python
def test_valid_project_preserves_gfa_and_audit_contract():
    result = validate_s4_project_request(project_request(), actor_id="planner-01")
    assert result["valid"] is True
    assert result["total_gfa_m2"] == 7000.0
    assert sum(row["gfa_m2"] for row in result["uses"]) == result["total_gfa_m2"]
    assert result["actor_id"] == "planner-01"
    assert result["content_digest"].startswith("sha256:")


def test_invalid_gfa_fails_closed():
    for value in (0, -1, float("nan"), float("inf"), "bad"):
        assert validate_s4_project_request(project_request(gfa=value), actor_id="planner")["valid"] is False
```

- [ ] **Step 2: Verify RED**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s4_project.py`

Expected: module import failure.

- [ ] **Step 3: Implement minimal project contract**

Define schema `uwm.traditional_livability.s4_project_request.v1`, strict JSON canonicalization, stable server-generated IDs when absent, duplicate detection, finite-positive GFA validation and immutable output. GFA shares are computed only after all rows validate.

- [ ] **Step 4: Verify GREEN**

Run the focused test and expect PASS.

- [ ] **Step 5: Commit**

Run: `git add data_agent/uwm/traditional_livability_s4_project.py data_agent/test_traditional_livability_s4_project.py && git commit -m "feat: validate S4 project GFA schedules"`

### Task 2: Implement the S4 Evidence-Orchestration Engine

**Files:**
- Create: `data_agent/uwm/traditional_livability_s4.py`
- Create: `data_agent/test_traditional_livability_s4.py`

- [ ] **Step 1: Write failing engine tests**

Cover:

- one S6 semantic/spatial analysis per use on the selected parcel;
- parcel-direct evidence separated from 150 m evidence;
- S1 `not_assessed` never becoming `demand_supported`;
- authoritative S1 gap becoming demand support only with matching area/class/standard evidence;
- nearby same-class objects without capacity rules becoming review-only;
- no compatibility rule preventing formal encroachment/duplicate conclusions;
- conflicting evidence producing `mixed_evidence_review_required` without weighted cancellation;
- unresolved semantics producing `unresolved_review_required`;
- exact GFA totals/shares across statuses;
- formal alignment disabled under current blockers;
- output detached and strict-JSON-safe.

```python
def test_s1_not_assessed_is_background_only():
    result = assess_s4_project(
        project=valid_project(),
        s1_snapshot=s1_not_assessed(),
        s6_resources=s6_resource_fixture(),
        facility_dictionary=unavailable_facility_dictionary(),
        compatibility_matrix=unavailable_compatibility_matrix(),
    )
    assert result["use_assessments"][0]["demand_evidence"]["status"] == "demand_not_assessed"
    assert result["project_summary"]["formal_alignment_enabled"] is False


def test_conflicting_evidence_is_not_numerically_cancelled():
    result = assess_s4_project(
        project=valid_project(),
        s1_snapshot=s1_authoritative_gap_fixture(),
        s6_resources=s6_resource_fixture(parcel_risk=True),
        facility_dictionary=authoritative_dictionary_fixture(),
        compatibility_matrix=authoritative_conflict_matrix_fixture(),
    )
    assert result["use_assessments"][0]["status"] == "mixed_evidence_review_required"
    assert "weighted_score" not in result
```

- [ ] **Step 2: Verify RED**

Run the focused test; expect missing module.

- [ ] **Step 3: Implement pure orchestration**

Define `SCHEMA = "uwm.traditional_livability.s4_project_assessment.v1"` and:

```python
def assess_s4_project(
    *,
    project: Mapping[str, Any],
    s1_snapshot: Mapping[str, Any],
    s6_resources: Mapping[str, Any],
    facility_dictionary: Mapping[str, Any],
    compatibility_matrix: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the evidence-bounded S4 project assessment."""
```

Reuse `analyze_s6_facility_proposal`; do not copy its buffer/compatibility logic. Extract the target-parcel hit as parcel-direct evidence and remaining hits as neighbourhood evidence. Match S1 metrics only by confirmed class and administrative evidence. Produce compact per-use evidence, GFA summary, project blockers, claim boundary and merged/capped engine GeoJSON.

Status precedence: insufficient input/evidence → `insufficient_evidence`; unresolved class → `unresolved_review_required`; material support plus risk → `mixed_evidence_review_required`; potential parcel resource risk → `potential_encroachment_review_required`; nearby supply without decisive rule → `nearby_supply_review_required`; authoritative demand support without material risk → `provisionally_supported`.

- [ ] **Step 4: Verify GREEN and dependencies**

Run S4, S6, semantic, dictionary and S1 tests; expect zero failures.

- [ ] **Step 5: Commit**

Run: `git add data_agent/uwm/traditional_livability_s4.py data_agent/test_traditional_livability_s4.py && git commit -m "feat: orchestrate S4 project alignment evidence"`

### Task 3: Expose S4 Resources and Analyze APIs

**Files:**
- Modify: `data_agent/api/uwm_traditional_livability_routes.py`
- Modify: `data_agent/test_uwm_traditional_livability_routes.py`

- [ ] **Step 1: Write failing route tests**

Require backend/frontend registrations:

```text
GET  /api/uwm/traditional-livability/s4/resources
POST /api/uwm/traditional-livability/s4/analyze
```

Test authentication; resources include real selectable parcels, minimal dictionary classes, S1/S6 readiness and blockers; missing/invalid/digest-tampered required snapshots return 503. Analyze overwrites actor identity with authenticated username, rejects invalid GFA/parcel/cross-area requests with 400, and returns 200 for valid evidence-limited analysis. Assert no Downloads/shapefile access or persistence.

- [ ] **Step 2: Verify RED**

Run route tests filtered by `s4`; expect missing routes.

- [ ] **Step 3: Implement thin endpoints**

Reuse existing validated S1/S6 loaders and authority envelope. Add no new source-path resolver. Run loading and analysis with `asyncio.to_thread`. Use production `validation_blockers` to determine HTTP 400 and snapshot exceptions for 503.

- [ ] **Step 4: Verify GREEN and route regression**

Run the complete traditional-livability route test; expect S1/S4/S6/S7 PASS.

- [ ] **Step 5: Commit**

Run: `git add data_agent/api/uwm_traditional_livability_routes.py data_agent/test_uwm_traditional_livability_routes.py && git commit -m "feat: expose Fulu S4 project APIs"`

### Task 4: Build the Interactive S4 Project Panel

**Files:**
- Create: `frontend/src/components/datapanel/TraditionalLivabilityS4Panel.tsx`
- Modify: `frontend/src/components/datapanel/TraditionalLivabilityTab.tsx`
- Modify: `data_agent/test_uwm_traditional_livability_frontend_contract.py`

- [ ] **Step 1: Write failing frontend contract tests**

Require both endpoints and strings/behaviours:

```text
S4 项目宜居性评估
项目名称
项目说明
规划地块
新增业态
业态名称
原始业态类型
用途说明
GFA
GFA 证据构成
地块直接关系
150 米空间初筛
需求未评估
初步对齐分析，需人工复核
```

Require dynamic add/remove use rows, finite-positive client validation, backend-compatible confirmation fields, authenticated actor not hard-coded, engine-only map layers and separate unresolved planning/facility evidence. Prohibit `审批通过`, `禁止建设`, `合理建设规模`, `GFA即容量`, `步行服务区` and unqualified formal alignment claims.

- [ ] **Step 2: Verify RED**

Run frontend contract filtered by `s4`; expect missing panel.

- [ ] **Step 3: Implement two-column panel**

Load resources independently, manage dynamic use rows with stable client keys, submit exact backend fields, show per-use and GFA summaries, evidence channels, blockers and max claim. Queue only engine GeoJSON:
+
+- target project parcel;
+- 150 m screening range;
+- parcel-contained resources;
+- nearby facilities;
+- nearby planning resources;
+- unresolved objects.

Use stale-response/unmount guards and preserve S6 point-selection lifecycle untouched.

- [ ] **Step 4: Verify GREEN and build**

Run frontend contract and `npm run build`; expect PASS with only existing warnings.

- [ ] **Step 5: Commit**

Run: `git add frontend/src/components/datapanel/TraditionalLivabilityS4Panel.tsx frontend/src/components/datapanel/TraditionalLivabilityTab.tsx data_agent/test_uwm_traditional_livability_frontend_contract.py && git commit -m "feat: add Fulu S4 project assessment panel"`

### Task 5: Verify S4 with Real Two-Village Data

**Files:**
- Create: `docs/reports/traditional_livability_s4_fulu_verification_2026-07-11.md`

- [ ] **Step 1: Use the real validated S1/S6 snapshots**

Use `/private/tmp/traditional_livability_s6_fulu_real` and the Phase 1A S1 snapshot. Select at least one real parcel in each village. Submit at least two different multi-use schedules with finite GFA values; examples are verification inputs, not embedded product defaults.

- [ ] **Step 2: Verify evidence and GFA conservation**

Assert every use includes semantic, parcel, S1 and S6 evidence; project GFA equals the sum of use GFA and status-group totals; no absent standard becomes demand support; no absent compatibility rule becomes formal duplicate/encroachment; no formal alignment is emitted under current blockers.

- [ ] **Step 3: Write the report**

Record parcels, submitted schedules, runtime, per-use statuses, GFA shares, spatial hit counts, inventory completeness, authority readiness and non-claims. State that results are preliminary evidence analyses, not approvals.

- [ ] **Step 4: Run focused regression and frontend build**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_traditional_livability_s4_project.py \
  data_agent/test_traditional_livability_s4.py \
  data_agent/test_traditional_livability_facility_dictionary.py \
  data_agent/test_traditional_livability_s6_semantics.py \
  data_agent/test_traditional_livability_s6_fulu_adapter.py \
  data_agent/test_traditional_livability_s6.py \
  data_agent/test_build_traditional_livability_s6_fulu.py \
  data_agent/test_uwm_traditional_livability_routes.py \
  data_agent/test_uwm_traditional_livability_frontend_contract.py \
  data_agent/test_traditional_livability_s1.py \
  data_agent/test_traditional_livability_s7.py
cd frontend && npm run build
```

Expected: zero failures and successful Vite build.

- [ ] **Step 5: Commit**

Run: `git add docs/reports/traditional_livability_s4_fulu_verification_2026-07-11.md && git commit -m "test: verify Fulu S4 project alignment"`

## Plan Self-Review

- **Spec coverage:** Task 1 covers project/GFA audit; Task 2 covers four evidence channels, status precedence and GFA conservation; Task 3 covers authenticated fail-closed APIs; Task 4 covers dynamic UI and map; Task 5 verifies real data and claims.
- **Reuse boundary:** S4 calls S6 semantics/spatial analysis and consumes S1; it does not copy taxonomy, buffer or compatibility logic.
- **Evidence boundary:** Missing FP/FPP, capacity or compatibility standards cannot become formal demand, duplication, encroachment or alignment conclusions.
- **Scope boundary:** Only Heping/Banzhu real parcels are executable; no Chongqing-wide claim and no UWM transition prediction.
- **Placeholder scan:** No unspecified standards, fixed demo projects, subjective weights or implementation placeholders remain.
- **Dependency order:** Project validation precedes engine; engine precedes APIs; APIs precede UI; real verification is last.
