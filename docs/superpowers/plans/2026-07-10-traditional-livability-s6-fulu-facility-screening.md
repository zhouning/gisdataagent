# Traditional Livability S6 Fulu Facility Screening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-bounded S6 workflow that classifies out-of-taxonomy facility proposals conservatively and performs real 150-metre dual-channel spatial screening in Heping and Banzhu villages.

**Architecture:** A versioned dictionary/compatibility loader supplies authoritative evidence when available; a Fulu resource adapter builds planning and facility snapshots offline; a pure S6 engine performs semantic resolution and projected screening without reading source archives at request time. FastAPI exposes fail-closed resource and analysis contracts, while an independent React panel supports point/parcel input and evidence-separated map output.

**Tech Stack:** Python 3.11, pytest, GeoPandas, Shapely, pyogrio, FastAPI, React, TypeScript, Leaflet/Vite.

---

## File Structure

- Create `data_agent/uwm/traditional_livability_facility_dictionary.py`: validate external taxonomy and compatibility-rule payloads without inventing missing authority.
- Create `data_agent/uwm/traditional_livability_s6_semantics.py`: return traceable authoritative, suggested or unresolved class candidates and validate human confirmation.
- Create `data_agent/uwm/traditional_livability_s6_fulu_adapter.py`: load two-village planning layers, preserve status evidence and build planning/current-facility screening resources.
- Create `data_agent/uwm/traditional_livability_s6.py`: validate requests, project geometries, run 150 m dual-channel screening and bound claims.
- Create `scripts/build_traditional_livability_s6_fulu.py`: offline resource/dictionary build with atomic JSON outputs and manifest.
- Modify `data_agent/api/uwm_traditional_livability_routes.py`: load S6 snapshots and expose resources, dictionary and analyze endpoints.
- Create `frontend/src/components/datapanel/TraditionalLivabilityS6Panel.tsx`: interactive S6 form, results and map layers.
- Modify `frontend/src/components/datapanel/TraditionalLivabilityTab.tsx`: mount the independent S6 panel.
- Add focused unit, builder, route and frontend contract tests plus a real-data verification report.

### Task 1: Authoritative Dictionary and Compatibility Contracts

**Files:**
- Create: `data_agent/uwm/traditional_livability_facility_dictionary.py`
- Create: `data_agent/test_traditional_livability_facility_dictionary.py`

- [ ] **Step 1: Write failing dictionary validation tests**

Cover these exact cases:

```python
def test_load_dictionary_preserves_authority_and_exact_class_count():
    payload = dictionary_fixture(class_count=43)
    result = validate_facility_dictionary(payload)
    assert result["ready"] is True
    assert result["authoritative_complete_43_class_dictionary"] is True
    assert result["class_count"] == 43
    assert result["production_blockers"] == []


def test_missing_dictionary_never_promotes_internal_taxonomy():
    result = unavailable_facility_dictionary()
    assert result["ready"] is False
    assert result["status"] == "dictionary_unavailable"
    assert "authoritative_43_class_facility_dictionary_missing" in result["production_blockers"]


def test_compatibility_rule_requires_provenance_and_stable_rule_id():
    result = validate_compatibility_matrix(matrix_fixture(rule_id=""))
    assert result["ready"] is False
    assert "compatibility_rule_id_missing" in result["validation_errors"]
```

Also reject duplicate class IDs, aliases pointing to unknown classes, unsupported relationship values and payloads claiming completeness with a count other than 43.

- [ ] **Step 2: Run tests to verify RED**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_facility_dictionary.py`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement the minimal validated contracts**

Define:

```python
DICTIONARY_SCHEMA = "uwm.traditional_livability.facility_dictionary.v1"
COMPATIBILITY_SCHEMA = "uwm.traditional_livability.facility_compatibility.v1"
ALLOWED_RELATIONSHIPS = {"conflict", "compatible"}

def validate_facility_dictionary(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the normalized dictionary, validation errors and blockers."""

def unavailable_facility_dictionary() -> dict[str, Any]:
    """Return the explicit no-authoritative-dictionary contract."""

def validate_compatibility_matrix(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return normalized authoritative compatibility rules."""

def unavailable_compatibility_matrix() -> dict[str, Any]:
    """Return the explicit no-authoritative-rule contract."""
```

Return normalized classes, alias and keyword indexes, source metadata, digest, validation errors and blockers. Do not import or copy the Phase 1A internal class map into the authoritative payload.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_facility_dictionary.py`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add data_agent/uwm/traditional_livability_facility_dictionary.py data_agent/test_traditional_livability_facility_dictionary.py && git commit -m "feat: add authoritative facility dictionary contracts"`

### Task 2: Conservative S6 Semantic Resolution

**Files:**
- Create: `data_agent/uwm/traditional_livability_s6_semantics.py`
- Create: `data_agent/test_traditional_livability_s6_semantics.py`

- [ ] **Step 1: Write failing semantic-resolution tests**

```python
def test_exact_authoritative_alias_can_confirm_class():
    result = resolve_s6_facility_semantics(
        facility_name="社区传统市集",
        raw_facility_type="传统市集",
        use_description="固定室内市场",
        dictionary=authoritative_dictionary_fixture(alias="传统市集"),
    )
    assert result["resolution_status"] == "authoritative_confirmed"
    assert result["candidates"][0]["match_method"] == "authoritative_alias_exact"


def test_internal_match_is_suggestion_only():
    result = resolve_s6_facility_semantics(
        facility_name="流动食品车",
        raw_facility_type="食品车",
        use_description="临时餐饮服务",
        dictionary=unavailable_facility_dictionary(),
    )
    assert result["resolution_status"] == "suggested_review_required"
    assert result["candidates"][0]["authority_level"] == "internal_suggestion"
    assert result["confirmed_standard_class_id"] is None


def test_human_confirmation_is_request_scoped_and_auditable():
    confirmation = validate_human_confirmation({
        "actor_id": "reviewer-001",
        "confirmed_at": "2026-07-10T08:00:00Z",
        "selected_standard_class_id": "facility.market",
        "original_input_digest": "sha256:fixture",
        "dictionary_version": "liv-2.0-fixture-v1",
    }, dictionary=authoritative_dictionary_fixture(class_id="facility.market"))
    assert confirmation["valid"] is True
    assert confirmation["mutates_authoritative_dictionary"] is False
```

Require an actor ID, confirmation timestamp, selected class present in the loaded dictionary, original input digest and dictionary version. Unknown or incomplete input returns `unresolved`.

- [ ] **Step 2: Verify RED**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s6_semantics.py`

Expected: FAIL because the resolver is absent.

- [ ] **Step 3: Implement deterministic resolution**

Implement normalized exact alias lookup, controlled keyword lookup, narrowly scoped internal suggestions, candidate evidence and request-scoped confirmation validation. Confidence values are labels such as `exact`, `controlled_rule` and `weak_suggestion`, never probabilities. No LLM call is added.

- [ ] **Step 4: Verify GREEN**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s6_semantics.py`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add data_agent/uwm/traditional_livability_s6_semantics.py data_agent/test_traditional_livability_s6_semantics.py && git commit -m "feat: add conservative S6 semantic resolution"`

### Task 3: Build the Two-Village Screening Resource Adapter

**Files:**
- Create: `data_agent/uwm/traditional_livability_s6_fulu_adapter.py`
- Create: `data_agent/test_traditional_livability_s6_fulu_adapter.py`

- [ ] **Step 1: Write failing planning-resource tests**

Use temporary GeoDataFrames for both CRS paths and assert:

```python
def test_resource_adapter_preserves_source_status_without_guessing_reserved():
    payload = build_fulu_s6_resources(
        source_root=planning_fixture_root,
        facility_product=facility_product_fixture(),
    )
    resource = payload["planning_resources"][0]
    assert resource["planning_status"] == "status_unknown"
    assert resource["planning_status_evidence"] is None


def test_resource_adapter_keeps_area_specific_distance_crs():
    payload = build_fulu_s6_resources(
        source_root=planning_fixture_root,
        facility_product=facility_product_fixture(),
    )
    assert {row["planning_area_id"] for row in payload["planning_areas"]} == {"fulu_heping", "fulu_banzhu"}
    assert all(row["distance_crs"] for row in payload["planning_areas"])


def test_unmapped_facilities_are_retained_for_screening():
    payload = attach_facility_resources(planning_inputs, facility_product_fixture())
    assert payload["current_facilities"][0]["mapping_status"] == "unmapped"
```

Also require stable source IDs, raw land-use fields, WGS84 display geometry, metric geometry serialization, source manifest references and `complete_inventory` propagation.

- [ ] **Step 2: Verify RED**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s6_fulu_adapter.py`

Expected: FAIL because the adapter is absent.

- [ ] **Step 3: Implement the adapter using verified S7 source rules**

Reuse `ASSET_SPECS`, boundary handling and per-village CRS behavior from `traditional_livability_s7_fulu_adapter.py` without importing S7 allocation behavior. Read `GHFW`, `JQDLTB` and `TDGHDL`; construct planning resources from explicit code/name rules; use `status_unknown` unless a real source field states current/planned/reserved status. Attach only facilities spatially associated with each village boundary and preserve mapped/unmapped objects.

- [ ] **Step 4: Verify GREEN and S7 regression**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s6_fulu_adapter.py data_agent/test_traditional_livability_s7_fulu_adapter.py`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add data_agent/uwm/traditional_livability_s6_fulu_adapter.py data_agent/test_traditional_livability_s6_fulu_adapter.py && git commit -m "feat: build Fulu S6 screening resources"`

### Task 4: Implement the Projected Dual-Channel S6 Engine

**Files:**
- Create: `data_agent/uwm/traditional_livability_s6.py`
- Create: `data_agent/test_traditional_livability_s6.py`

- [ ] **Step 1: Write failing engine tests**

Test point and parcel modes separately:

```python
def test_point_mode_returns_separate_planning_and_facility_hits():
    result = analyze_s6_facility_proposal(
        request=point_request(),
        resources=resource_fixture(),
        dictionary=unavailable_facility_dictionary(),
        compatibility=unavailable_compatibility_matrix(),
    )
    assert result["screening"]["distance_m"] == 150
    assert result["screening"]["provider"] == "projected_planar_buffer"
    assert result["planning_resource_hits"]
    assert result["current_facility_hits"]


def test_spatial_hits_without_rules_require_review():
    result = analyze_s6_facility_proposal(
        request=point_request(),
        resources=resource_fixture(),
        dictionary=unavailable_facility_dictionary(),
        compatibility=unavailable_compatibility_matrix(),
    )
    assert result["status"] == "potential_conflict_review_required"
    assert result["max_claim_level"] == "spatial_screening_only"


def test_authoritative_rule_is_required_for_confirmed_conflict():
    result = analyze_s6_facility_proposal(
        request=confirmed_point_request(class_id="facility.market"),
        resources=resource_fixture(),
        dictionary=authoritative_dictionary_fixture(class_id="facility.market"),
        compatibility=matrix_with_conflict_rule(),
    )
    assert result["status"] == "confirmed_conflict"
    assert result["applied_rule_ids"] == ["RULE-001"]
```

Also test `confirmed_compatible`, sampled-inventory no-hit limitations, unresolved objects, invalid coordinates, unknown parcel, cross-area parcel rejection, missing geometry, class-confirmation requirements and S1 handoff readiness.

- [ ] **Step 2: Verify RED**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s6.py`

Expected: FAIL because the engine is absent.

- [ ] **Step 3: Implement pure analysis functions**

Define:

```python
SCHEMA = "uwm.traditional_livability.s6_analysis.v1"
SCREENING_DISTANCE_M = 150.0

def validate_s6_request(
    payload: Mapping[str, Any], resources: Mapping[str, Any]
) -> dict[str, Any]:
    """Return a normalized request or exact validation blockers."""

def analyze_s6_facility_proposal(
    *,
    request: Mapping[str, Any],
    resources: Mapping[str, Any],
    dictionary: Mapping[str, Any],
    compatibility: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the evidence-bounded S6 analysis contract."""
```

Transform point inputs from EPSG:4326 into the selected area's distance CRS. Parcel mode buffers the actual parcel geometry. Use Shapely intersections/distance in metres, return polygon intersection area where available, keep channels separate and generate display GeoJSON only from engine outputs. Do not cross planning areas.

Status precedence must be deterministic: invalid/missing evidence → `insufficient_evidence`; applicable authoritative conflict → `confirmed_conflict`; applicable authoritative compatible rules with no conflict → `confirmed_compatible`; any hit without decisive rules → `potential_conflict_review_required`; otherwise → `no_screening_hit` with completeness warning.

- [ ] **Step 4: Verify GREEN**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s6.py`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add data_agent/uwm/traditional_livability_s6.py data_agent/test_traditional_livability_s6.py && git commit -m "feat: add projected S6 conflict screening engine"`

### Task 5: Add the Offline Builder and Snapshot Validation

**Files:**
- Create: `scripts/build_traditional_livability_s6_fulu.py`
- Create: `data_agent/test_build_traditional_livability_s6_fulu.py`

- [ ] **Step 1: Write failing builder tests**

Require the builder to:

- fail closed when required planning sources or the facility product are absent;
- build `uwm_traditional_livability_s6_resources.json` atomically;
- optionally load dictionary and compatibility JSON inputs;
- produce unavailable contracts rather than fabricated defaults when those inputs are omitted;
- record exact scope `fulu_heping_and_banzhu_planning_samples_only`;
- omit absolute source-root paths from public output while retaining relative paths and hashes;
- propagate facility inventory completeness and unresolved counts.

- [ ] **Step 2: Verify RED**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_build_traditional_livability_s6_fulu.py`

Expected: FAIL because the builder is absent.

- [ ] **Step 3: Implement the builder and CLI**

CLI contract:

```text
--source-root PATH                 required
--facility-product PATH            required
--output PATH                      required
--facility-dictionary PATH         optional
--compatibility-matrix PATH        optional
```

Write the resource snapshot, normalized dictionary status and compatibility status into the controlled output directory using temporary files plus `os.replace`. Return exit code 2 on missing required spatial/facility inputs and exit code 0 when spatial screening is ready even if authoritative dictionary/rules are unavailable.

- [ ] **Step 4: Verify GREEN**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_build_traditional_livability_s6_fulu.py`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add scripts/build_traditional_livability_s6_fulu.py data_agent/test_build_traditional_livability_s6_fulu.py && git commit -m "feat: build Fulu S6 runtime snapshots"`

### Task 6: Expose Fail-Closed S6 Runtime APIs

**Files:**
- Modify: `data_agent/api/uwm_traditional_livability_routes.py`
- Modify: `data_agent/test_uwm_traditional_livability_routes.py`

- [ ] **Step 1: Write failing route and loader tests**

Require these methods and paths in both backend and frontend route lists:

```text
GET  /api/uwm/traditional-livability/s6/resources
GET  /api/uwm/traditional-livability/s6/dictionary
POST /api/uwm/traditional-livability/s6/analyze
```

Test `UWM_TRADITIONAL_LIVABILITY_S6_PATH`, schema validation and HTTP 503 for missing/unreadable/invalid resource snapshots. Test that dictionary unavailability returns HTTP 200 with blockers, while analyze uses only loaded server snapshots and rejects malformed/cross-area requests without touching Downloads or shapefiles.

- [ ] **Step 2: Verify RED**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_uwm_traditional_livability_routes.py -k s6`

Expected: FAIL because the S6 routes are absent.

- [ ] **Step 3: Implement loaders and endpoints**

Add `S6_RESOURCE_SCHEMA`, `S6SnapshotUnavailable`, `_resolve_s6_path()`, `_load_s6_snapshot()` and thin endpoint functions. Execute file loading and analysis with `asyncio.to_thread`. The POST endpoint delegates to `analyze_s6_facility_proposal` and never persists user classification as authority.

- [ ] **Step 4: Verify GREEN and existing route regression**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_uwm_traditional_livability_routes.py`

Expected: PASS for S1, S7 and S6.

- [ ] **Step 5: Commit**

Run: `git add data_agent/api/uwm_traditional_livability_routes.py data_agent/test_uwm_traditional_livability_routes.py && git commit -m "feat: expose Fulu S6 screening APIs"`

### Task 7: Add the Interactive S6 Panel and Map Layers

**Files:**
- Create: `frontend/src/components/datapanel/TraditionalLivabilityS6Panel.tsx`
- Modify: `frontend/src/components/datapanel/TraditionalLivabilityTab.tsx`
- Modify: `data_agent/test_uwm_traditional_livability_frontend_contract.py`

- [ ] **Step 1: Write failing frontend contract tests**

Require all three S6 endpoints and these strings/behaviors:

```text
S6 超范围设施评估
地图点选
规划地块
设施名称
原始类型
用途说明
150 米空间初筛范围
规划资源命中
现状设施命中
语义未解析对象
潜在冲突、需人工复核
采样库存
__handleMapUpdate
```

Prohibit unqualified UI claims `禁止建设`, `审批通过`, `法定退界`, `安全距离` and `步行服务区`. Require a visible dictionary/rule-unavailable state and no silent automatic confirmation.

- [ ] **Step 2: Verify RED**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_uwm_traditional_livability_frontend_contract.py -k s6`

Expected: FAIL because the panel is absent.

- [ ] **Step 3: Implement the independent two-column panel**

Load resources and dictionary status independently. Support active planning area, point/parcel mode, parcel selector, required text fields, semantic candidate review, request-scoped confirmation and POST analysis. Map point selection must use the project's existing map interaction contract; if no reusable callback exists, expose a narrowly scoped custom event rather than modifying global map behavior broadly.

Queue only engine-produced GeoJSON layers through `window.__handleMapUpdate`:

- `拟建设施位置或目标地块`;
- `150 米空间初筛范围`;
- `命中规划资源地块`;
- `命中现状设施`;
- `语义未解析设施`.

Show separate hit tables, rule IDs, source evidence, inventory completeness, blockers and `max_claim_level`.

- [ ] **Step 4: Verify GREEN and production build**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_uwm_traditional_livability_frontend_contract.py && cd frontend && npm run build`

Expected: contract tests PASS and Vite exits 0. Existing chunk-size warnings may remain but no new build error is permitted.

- [ ] **Step 5: Commit**

Run: `git add frontend/src/components/datapanel/TraditionalLivabilityS6Panel.tsx frontend/src/components/datapanel/TraditionalLivabilityTab.tsx data_agent/test_uwm_traditional_livability_frontend_contract.py && git commit -m "feat: add interactive Fulu S6 screening panel"`

### Task 8: Verify with Real Planning and Facility Data

**Files:**
- Create: `docs/reports/traditional_livability_s6_fulu_verification_2026-07-10.md`

- [ ] **Step 1: Build the real two-village resource snapshot**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python \
  scripts/build_traditional_livability_s6_fulu.py \
  --source-root '/private/tmp/planning_sample_audit/规划院提供数据样例及Demo系统功能演示建议/01数据样例' \
  --facility-product /private/tmp/traditional_livability_phase1a_final2/uwm_traditional_livability_facility_product.json \
  --output /private/tmp/traditional_livability_s6_fulu_real
```

Expected: exit 0; spatial resources ready; dictionary and compatibility statuses explicitly unavailable unless real authoritative files have been supplied.

- [ ] **Step 2: Execute representative non-fixed analyses**

Run at least one point-mode request and one parcel-mode request in each village using objects discovered from the built snapshot. Assert the buffer is 150 m, the distance CRS matches the active village, cross-village requests fail, channels are separate, unresolved facilities remain visible and no missing rule produces a confirmed conflict.

- [ ] **Step 3: Audit public claims and write the verification report**

Record actual planning-resource counts, current-facility counts, unmapped counts, inventory completeness, per-village CRS, point/parcel outcomes, runtime and blockers. State explicitly that proximity hits are screening evidence, the source does not justify guessing reserved status, and results are not approvals or statutory-distance findings.

- [ ] **Step 4: Run focused regression and frontend build**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_traditional_livability_facility_product.py \
  data_agent/test_traditional_livability_facility_dictionary.py \
  data_agent/test_traditional_livability_s6_semantics.py \
  data_agent/test_traditional_livability_s6_fulu_adapter.py \
  data_agent/test_traditional_livability_s6.py \
  data_agent/test_build_traditional_livability_s6_fulu.py \
  data_agent/test_uwm_traditional_livability_routes.py \
  data_agent/test_uwm_traditional_livability_frontend_contract.py \
  data_agent/test_traditional_livability_s1.py \
  data_agent/test_traditional_livability_s7_fulu_adapter.py \
  data_agent/test_traditional_livability_s7.py \
  data_agent/test_build_traditional_livability_s7_fulu.py
cd frontend && npm run build
```

Expected: zero pytest failures and Vite exits 0.

- [ ] **Step 5: Commit**

Run: `git add docs/reports/traditional_livability_s6_fulu_verification_2026-07-10.md && git commit -m "test: verify Fulu S6 facility screening"`

## Plan Self-Review

- **Spec coverage:** Tasks 1–2 cover authoritative dictionary, compatibility and human-confirmed semantics; Task 3 covers two-village planning/current-facility evidence; Task 4 covers point/parcel modes, 150 m projected screening, status precedence and S1 handoff; Tasks 5–6 enforce offline/fail-closed runtime behavior; Task 7 implements the confirmed interaction and map design; Task 8 verifies real data and claims.
- **Evidence boundary:** No task permits internal or LLM suggestions to become authoritative. Proximity without a cited rule cannot produce `confirmed_conflict` or `confirmed_compatible`; unknown planning status stays `status_unknown`; sampled inventory limits no-hit claims.
- **Scope boundary:** All executable data remains limited to Heping and Banzhu planning samples. No task expands the result to Chongqing-wide coverage or modifies UWM behavior.
- **Placeholder scan:** The plan contains no TBD/TODO implementation gaps. Optional authoritative inputs have explicit unavailable contracts and are not replaced with fabricated data.
- **Type and dependency order:** Dictionary contracts precede semantics; resource products precede the engine; the engine and builder precede APIs; APIs precede the UI; real-data verification is last.
