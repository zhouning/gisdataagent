# Traditional Livability Phase 1A Facility/S1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible Chongqing facility data product and a fail-closed LIV 2.0 S1 facility supply/gap assessment without inventing FP/FPP standards.

**Architecture:** A source adapter reads the customer-provided GDB/XLSX files from a configured read-only root and normalizes them into a versioned facility/population product. A pure S1 engine consumes that product plus optional external standards, returns inventory and normalized supply metrics, and only emits compliance judgements when an authoritative standard is present. Existing traditional-livability ranking remains available but gains a separate S1 API section rather than being relabelled as S1.

**Tech Stack:** Python 3.11, pyogrio, pandas, Shapely/GeoPandas, Starlette, pytest, React/TypeScript.

---

### Task 1: Facility Data Product Contract

**Files:**
- Create: `data_agent/uwm/traditional_livability_facility_product.py`
- Create: `data_agent/test_traditional_livability_facility_product.py`

- [ ] **Step 1: Write failing contract tests**

Create tests that pass small in-memory POI, AOI and population rows into `build_facility_data_product(...)` and assert:

```python
assert product["schema"] == "uwm.traditional_livability.facility_product.v1"
assert product["geography"]["executed_area"] == "重庆市"
assert product["facilities"][0]["canonical_class"] == "education.primary_school"
assert product["facilities"][0]["mapping_status"] == "mapped_internal_taxonomy"
assert product["population_units"][0]["population_basis"] == "resident_population_2021"
assert product["claim_boundary"]["authoritative_fp_fpp_available"] is False
assert product["production_blockers"]
```

Also test that unknown categories become `canonical_class="unmapped"`, retain raw classifications and never receive a guessed class.

- [ ] **Step 2: Verify tests fail**

Run: `pytest -q data_agent/test_traditional_livability_facility_product.py`

Expected: FAIL because the module and builder do not exist.

- [ ] **Step 3: Implement the pure product builder**

Implement:

```python
def build_facility_data_product(
    *,
    product_id: str,
    created_at: str,
    poi_rows: list[dict[str, Any]],
    aoi_rows: list[dict[str, Any]],
    population_rows: list[dict[str, Any]],
    source_manifest: list[dict[str, Any]],
) -> dict[str, Any]: ...
```

Use a versioned, explicit internal mapping table for initial education, health, parks, culture, sport, public safety, government/community and transport classes. Preserve `raw_primary_class`, `raw_secondary_class`, `raw_tertiary_class`, `source_record_id`, `source_dataset_id`, `admin_code`, coordinates, and geometry type. Deduplicate only identical source-dataset/source-record IDs; do not spatially merge POI and AOI in Phase 1A.

- [ ] **Step 4: Verify tests pass**

Run: `pytest -q data_agent/test_traditional_livability_facility_product.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add data_agent/uwm/traditional_livability_facility_product.py data_agent/test_traditional_livability_facility_product.py
git commit -m "feat: add traditional livability facility product"
```

### Task 2: Local Source Adapter and Manifest

**Files:**
- Create: `data_agent/uwm/traditional_livability_source_adapter.py`
- Create: `data_agent/test_traditional_livability_source_adapter.py`

- [ ] **Step 1: Write failing adapter tests**

Use temporary GeoPackage/Excel fixtures and assert `inspect_traditional_livability_sources(root)` reports paths relative to the configured root, SHA-256, layer, feature count, CRS, geometry type and fields. Assert missing required sources produce `ready=False` and named blockers rather than an exception disguised as readiness.

- [ ] **Step 2: Verify tests fail**

Run: `pytest -q data_agent/test_traditional_livability_source_adapter.py`

Expected: FAIL because the adapter does not exist.

- [ ] **Step 3: Implement inspection and bounded loading**

Implement:

```python
def inspect_traditional_livability_sources(source_root: Path) -> dict[str, Any]: ...

def load_traditional_livability_source_rows(
    source_root: Path,
    *,
    max_poi_features: int | None = None,
    max_aoi_features: int | None = None,
) -> dict[str, list[dict[str, Any]]]: ...
```

Recognize the verified relative suffixes for the Gaode POI GDB, Baidu AOI GDB, population XLSX, OSM roads and current-land-use GDB. Do not embed `/Users/zhouning` in public payloads. Sampling limits must be reported in the manifest and force `complete_inventory=False`.

- [ ] **Step 4: Verify tests pass**

Run: `pytest -q data_agent/test_traditional_livability_source_adapter.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add data_agent/uwm/traditional_livability_source_adapter.py data_agent/test_traditional_livability_source_adapter.py
git commit -m "feat: add livability source adapter"
```

### Task 3: S1 Facility Supply Assessment

**Files:**
- Create: `data_agent/uwm/traditional_livability_s1.py`
- Create: `data_agent/test_traditional_livability_s1.py`

- [ ] **Step 1: Write failing S1 tests**

Build a small product with two administrative units and assert the engine reports facility count, facilities per 10,000 residents, mapped/unmapped counts and missing-capacity blockers. Without standards, assert `compliance_status="not_assessed"`, `gap_to_standard=None`, and no “达标/不达标” claim. With an explicitly authoritative standard row, assert the numeric gap and standard provenance are returned.

- [ ] **Step 2: Verify tests fail**

Run: `pytest -q data_agent/test_traditional_livability_s1.py`

Expected: FAIL because the S1 engine does not exist.

- [ ] **Step 3: Implement deterministic assessment**

Implement:

```python
def build_s1_facility_assessment(
    *,
    assessment_id: str,
    created_at: str,
    facility_product: dict[str, Any],
    standards: list[dict[str, Any]] | None = None,
) -> dict[str, Any]: ...
```

Standards must contain `canonical_class`, `metric`, `threshold`, `unit`, `authority`, `effective_date`, and `evidence_level="authoritative"`. Reject other standards from compliance calculations and list them under `rejected_standards`. Aggregate only population units with explicit administrative-code matches; report unmatched facilities separately.

- [ ] **Step 4: Verify tests pass**

Run: `pytest -q data_agent/test_traditional_livability_s1.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add data_agent/uwm/traditional_livability_s1.py data_agent/test_traditional_livability_s1.py
git commit -m "feat: add S1 facility supply assessment"
```

### Task 4: S1 API Integration

**Files:**
- Modify: `data_agent/api/uwm_traditional_livability_routes.py`
- Modify: `data_agent/test_uwm_traditional_livability_routes.py`

- [ ] **Step 1: Write failing route tests**

Assert authenticated `GET /api/uwm/traditional-livability/s1` returns the S1 schema when `UWM_TRADITIONAL_LIVABILITY_SOURCE_ROOT` points to valid fixtures. Assert missing sources return HTTP 503 with `ready=False`, blockers, and no fabricated assessment.

- [ ] **Step 2: Verify tests fail**

Run: `pytest -q data_agent/test_uwm_traditional_livability_routes.py`

Expected: FAIL because the S1 route is absent.

- [ ] **Step 3: Add the fail-closed endpoint**

Register `GET /api/uwm/traditional-livability/s1`. Resolve source root exclusively from `UWM_TRADITIONAL_LIVABILITY_SOURCE_ROOT`; do not silently fall back to the developer Downloads directory. Build the manifest, product and assessment in a worker thread. Preserve the existing ranking and map routes unchanged.

- [ ] **Step 4: Verify tests pass**

Run: `pytest -q data_agent/test_uwm_traditional_livability_routes.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add data_agent/api/uwm_traditional_livability_routes.py data_agent/test_uwm_traditional_livability_routes.py
git commit -m "feat: expose traditional livability S1 assessment"
```

### Task 5: Traditional Livability S1 UI

**Files:**
- Modify: `frontend/src/components/datapanel/TraditionalLivabilityTab.tsx`
- Modify: `data_agent/test_uwm_traditional_livability_frontend_contract.py`

- [ ] **Step 1: Write failing frontend contract tests**

Assert the component requests `/api/uwm/traditional-livability/s1`, renders facility inventory, per-10,000-resident metrics, mapping quality, rejected/missing standards and production blockers, and does not contain unconditional compliance wording.

- [ ] **Step 2: Verify tests fail**

Run: `pytest -q data_agent/test_uwm_traditional_livability_frontend_contract.py`

Expected: FAIL because the S1 UI is absent.

- [ ] **Step 3: Add an S1 section**

Keep the existing current-state ranking section. Add a separately labelled “S1 设施供需评估” section with loading, unavailable/503 and ready states. Display executed geography as 重庆, source completeness, standard availability and claim boundary. Never translate `not_assessed` as “不达标”.

- [ ] **Step 4: Verify tests and build pass**

Run:

```bash
pytest -q data_agent/test_uwm_traditional_livability_frontend_contract.py
cd frontend && npm run build
```

Expected: pytest PASS and Vite build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/datapanel/TraditionalLivabilityTab.tsx data_agent/test_uwm_traditional_livability_frontend_contract.py
git commit -m "feat: show S1 facility assessment in livability tab"
```

### Task 6: Real-Data Verification and Report

**Files:**
- Create: `scripts/build_traditional_livability_phase1a.py`
- Create: `data_agent/test_build_traditional_livability_phase1a.py`
- Create: `docs/reports/traditional_livability_phase1a_verification_2026-07-10.md`

- [ ] **Step 1: Write failing CLI tests**

Assert the CLI accepts `--source-root` and `--output`, refuses missing required sources with non-zero exit status, and writes manifest/product/S1 JSON files for valid fixtures without absolute source paths in public payloads.

- [ ] **Step 2: Verify tests fail**

Run: `pytest -q data_agent/test_build_traditional_livability_phase1a.py`

Expected: FAIL because the script does not exist.

- [ ] **Step 3: Implement the reproducible builder**

Use the source adapter, product builder and S1 engine. Add optional `--max-poi-features` and `--max-aoi-features` flags; sampled runs must remain visibly incomplete. Write JSON atomically and never overwrite source data.

- [ ] **Step 4: Run focused and broad verification**

Run the new test files, existing traditional-livability tests, the real-data builder against the audited extraction, and the frontend build. Record exact counts, runtime, sampling/completeness, unmapped categories, absent FP/FPP standards and all blockers in the verification report.

- [ ] **Step 5: Commit**

```bash
git add scripts/build_traditional_livability_phase1a.py data_agent/test_build_traditional_livability_phase1a.py docs/reports/traditional_livability_phase1a_verification_2026-07-10.md
git commit -m "test: verify traditional livability phase1a"
```
