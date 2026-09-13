# Traditional Livability S6 to S1 Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the evidence-bound traditional LIV 2.0 workflow from a confirmed S6 out-of-taxonomy facility proposal to an S1 FP/FPP baseline-versus-proposal assessment.

**Architecture:** Add immutable handoff and metric-profile contracts, split FP/FPP evaluation into focused pure modules, orchestrate deterministic baseline/proposal snapshot comparison in an actor-owned service, and expose the workflow through the existing traditional livability API and S6 panel. Every component fails closed on missing authority, fields, versions or inventory completeness and never labels static recomputation as UWM.

**Tech Stack:** Python 3.11, pytest, Shapely/PyProj, FastAPI-style routes, React/TypeScript, existing map-update GeoJSON contract.

---

### Task 1: Add S6-to-S1 Handoff Contract

**Files:**
- Create: `data_agent/uwm/traditional_livability_s6_s1_handoff.py`
- Create: `data_agent/test_traditional_livability_s6_s1_handoff.py`

- [ ] **Step 1: Write failing canonical-contract tests**

Cover stable digest generation, required source S6 fields, normalized proposal geometry, semantic confirmation binding, dictionary/profile references, deep input detachment and deterministic blocker ordering.

```python
def test_handoff_digest_is_stable_for_equivalent_mapping_order():
    left = build_s6_s1_handoff(**handoff_inputs(order="forward"))
    right = build_s6_s1_handoff(**handoff_inputs(order="reverse"))
    assert left["source_s6_analysis_digest"] == right["source_s6_analysis_digest"]
    assert left["handoff_id"] == right["handoff_id"]


def test_changed_proposal_invalidates_confirmation_binding():
    payload = handoff_inputs()
    payload["s6_analysis"]["request"]["facility_name"] = "changed"
    result = build_s6_s1_handoff(**payload)
    assert result["ready_for_s1"] is False
    assert "stale_or_mismatched_human_confirmation" in result["validation_blockers"]
```

- [ ] **Step 2: Run the contract test to verify RED**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s6_s1_handoff.py`

Expected: FAIL because the module is absent.

- [ ] **Step 3: Implement the immutable handoff builder**

Define:

```python
SCHEMA = "uwm.traditional_livability.s6_s1_handoff.v1"

def canonical_payload_digest(payload: Mapping[str, Any]) -> str:
    ...

def build_s6_s1_handoff(
    *,
    s6_analysis: Mapping[str, Any],
    metric_profiles: Mapping[str, Any],
    actor_id: str,
    created_at: str,
) -> dict[str, Any]:
    ...
```

Reuse the repository canonical JSON normalization pattern. Bind the actor server-side, validate confirmation evidence against the exact normalized proposal and selected candidate, include source bundle and authority versions, and return `ready_for_s1=false` rather than inventing a profile.

- [ ] **Step 4: Run focused S6 contract regressions**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s6_s1_handoff.py data_agent/test_traditional_livability_s6_semantics.py data_agent/test_traditional_livability_s6.py`

Expected: PASS.

- [ ] **Step 5: Commit the handoff contract**

Run: `git add data_agent/uwm/traditional_livability_s6_s1_handoff.py data_agent/test_traditional_livability_s6_s1_handoff.py && git commit -m "feat: bind S6 proposals to S1 handoffs"`

### Task 2: Add Versioned S1 Metric Profiles

**Files:**
- Create: `data_agent/uwm/traditional_livability_s1_profiles.py`
- Create: `data_agent/test_traditional_livability_s1_profiles.py`

- [ ] **Step 1: Write failing profile validation tests**

Cover FP-only, FPP-only and dual profiles; authority metadata; content digest; allowed comparators and units; required source fields; metre-based service radius validation; network method prerequisites; synthesis-matrix references; duplicate class rejection and unavailable profile contracts.

```python
def test_dual_profile_requires_matrix_reference():
    result = validate_s1_metric_profile(dual_profile(matrix_id=None))
    assert result["status"] == "invalid"
    assert "synthesis_matrix_reference_required" in result["blockers"]


def test_s6_screening_distance_is_not_a_profile_default():
    result = unavailable_s1_metric_profiles()
    assert "service_radius_m" not in result
```

- [ ] **Step 2: Run the profile tests to verify RED**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s1_profiles.py`

Expected: FAIL because profile validation is absent.

- [ ] **Step 3: Implement fail-closed profile and matrix loaders**

Define schemas:

```python
PROFILE_SCHEMA = "uwm.traditional_livability.s1_metric_profile.v1"
MATRIX_SCHEMA = "uwm.traditional_livability.s1_synthesis_matrix.v1"
```

Accept only explicitly supplied profiles. Validate source metadata and content digest using the existing canonical digest helper. Return stable unavailable/invalid contracts; do not synthesize a 43-class standard catalog.

- [ ] **Step 4: Run profile and existing S1 tests**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s1_profiles.py data_agent/test_traditional_livability_s1.py`

Expected: PASS.

- [ ] **Step 5: Commit profile contracts**

Run: `git add data_agent/uwm/traditional_livability_s1_profiles.py data_agent/test_traditional_livability_s1_profiles.py && git commit -m "feat: validate S1 FP FPP profiles"`

### Task 3: Implement the S1 FP Evaluator

**Files:**
- Create: `data_agent/uwm/traditional_livability_s1_fp.py`
- Create: `data_agent/test_traditional_livability_s1_fp.py`

- [ ] **Step 1: Write failing FP evaluator tests**

Cover authoritative Euclidean service radius, demand geometry coverage, administrative-subunit presence, unsupported network service-area profiles, invalid CRS, incomplete demand geometry, proposal insertion, backend GeoJSON evidence and explicit proof that 150 metres is not used unless the profile states 150 metres.

```python
def test_fp_uses_profile_radius_not_s6_screening_radius():
    result = evaluate_fp(
        facilities=facility_fixture(),
        demand_units=demand_fixture(),
        profile=fp_profile(service_radius_m=800),
    )
    assert result["method_parameters"]["service_radius_m"] == 800
    assert result["method_parameters"]["service_radius_m"] != 150


def test_network_fp_without_authoritative_network_is_unresolved():
    result = evaluate_fp(
        facilities=facility_fixture(),
        demand_units=demand_fixture(),
        profile=network_fp_profile(),
    )
    assert result["status"] == "unresolved"
    assert "authoritative_network_missing" in result["blockers"]
```

- [ ] **Step 2: Run the FP tests to verify RED**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s1_fp.py`

Expected: FAIL because the evaluator is absent.

- [ ] **Step 3: Implement deterministic FP evaluation**

Transform source geometries into the profile distance CRS, calculate only the declared method, return numerator/denominator geometry references and display GeoJSON, and cap claims when demand or facility inventory is incomplete.

- [ ] **Step 4: Run FP and geometry regressions**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s1_fp.py data_agent/test_traditional_livability_s6.py data_agent/test_traditional_livability_s7.py`

Expected: PASS.

- [ ] **Step 5: Commit FP evaluation**

Run: `git add data_agent/uwm/traditional_livability_s1_fp.py data_agent/test_traditional_livability_s1_fp.py && git commit -m "feat: evaluate authoritative S1 FP metrics"`

### Task 4: Implement the S1 FPP Evaluator and 2×2 Synthesis

**Files:**
- Create: `data_agent/uwm/traditional_livability_s1_fpp.py`
- Create: `data_agent/uwm/traditional_livability_s1_synthesis.py`
- Create: `data_agent/test_traditional_livability_s1_fpp.py`
- Create: `data_agent/test_traditional_livability_s1_synthesis.py`

- [ ] **Step 1: Write failing FPP and synthesis tests**

Cover facility count, per-population rate, total area, capacity-per-population, missing proposal area/capacity, comparator directions, gap calculation, FP/FPP matrix outcomes and missing/invalid matrix behaviour.

```python
def test_proposal_without_capacity_does_not_change_capacity_metric():
    result = evaluate_fpp(
        facilities=facilities_with_proposal(capacity=None),
        population_units=population_fixture(),
        profile=capacity_profile(),
    )
    assert result["status"] == "unresolved"
    assert "facility_capacity_missing" in result["blockers"]


def test_dual_dimensions_require_validated_matrix():
    result = synthesize_s1_dimensions(fp=meets(), fpp=does_not_meet(), matrix=unavailable_matrix())
    assert result["status"] == "unresolved"
    assert "authoritative_synthesis_matrix_missing" in result["blockers"]
```

- [ ] **Step 2: Run the tests to verify RED**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s1_fpp.py data_agent/test_traditional_livability_s1_synthesis.py`

Expected: FAIL because the modules are absent.

- [ ] **Step 3: Implement metric-specific FPP and matrix synthesis**

Do not reinterpret legacy count diagnostics as authority. Evaluate exactly one metric definition per dimension result, preserve missing fields, and synthesize only validated `meets`/`does_not_meet` pairs declared by the matrix.

- [ ] **Step 4: Run FPP, synthesis and legacy S1 regressions**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s1_fpp.py data_agent/test_traditional_livability_s1_synthesis.py data_agent/test_traditional_livability_s1.py`

Expected: PASS.

- [ ] **Step 5: Commit FPP and synthesis**

Run: `git add data_agent/uwm/traditional_livability_s1_fpp.py data_agent/uwm/traditional_livability_s1_synthesis.py data_agent/test_traditional_livability_s1_fpp.py data_agent/test_traditional_livability_s1_synthesis.py && git commit -m "feat: evaluate and synthesize S1 FPP metrics"`

### Task 5: Orchestrate Baseline and Proposed S1 Snapshots

**Files:**
- Create: `data_agent/uwm/traditional_livability_s1_comparison.py`
- Create: `data_agent/test_traditional_livability_s1_comparison.py`

- [ ] **Step 1: Write failing comparison tests**

Cover handoff validation, class and administrative filtering, proposed-record insertion, baseline/proposal independence, changed FP/FPP values, unchanged unresolved dimensions, bundle/profile version equality, backend map layers and static-analysis claim wording.

```python
def test_comparison_is_static_and_not_a_world_model_rollout():
    result = compare_s1_baseline_and_proposal(**comparison_inputs())
    assert result["method"] == "deterministic_static_proposal_comparison"
    assert result["claim_boundary"]["uwm_rollout"] is False
    assert result["claim_boundary"]["future_adaptation_assessed"] is False


def test_baseline_input_is_not_mutated_by_proposal_insertion():
    product = facility_product_fixture()
    before = deepcopy(product)
    compare_s1_baseline_and_proposal(facility_product=product, **other_inputs())
    assert product == before
```

- [ ] **Step 2: Run the comparison test to verify RED**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s1_comparison.py`

Expected: FAIL because comparison orchestration is absent.

- [ ] **Step 3: Implement baseline/proposal orchestration**

Build two detached snapshots, call only the profile-declared FP/FPP evaluators, synthesize when allowed, calculate stable deltas, include all unresolved reasons and return map evidence solely from engine outputs.

- [ ] **Step 4: Run all focused traditional S1/S6 tests**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s1*.py data_agent/test_traditional_livability_s6*.py`

Expected: PASS.

- [ ] **Step 5: Commit snapshot comparison**

Run: `git add data_agent/uwm/traditional_livability_s1_comparison.py data_agent/test_traditional_livability_s1_comparison.py && git commit -m "feat: compare S1 baseline and proposal snapshots"`

### Task 6: Add Actor-Owned Handoff Service and APIs

**Files:**
- Create: `data_agent/uwm/traditional_livability_s6_s1_service.py`
- Modify: `data_agent/api/uwm_traditional_livability_routes.py`
- Modify: `data_agent/frontend_api.py`
- Create: `data_agent/test_traditional_livability_s6_s1_service.py`
- Modify: `data_agent/test_uwm_traditional_livability_routes.py`

- [ ] **Step 1: Write failing service and route tests**

Cover handoff creation, actor binding, 404 cross-user reads, stale digest 409, unavailable profile 409, successful execution, route registration and error payload stability.

```python
def test_other_actor_cannot_read_or_execute_handoff(client, actor_headers):
    handoff_id = create_handoff(client, actor_headers("alice"))["handoff_id"]
    assert client.get(f"/api/uwm/traditional-livability/s6/handoffs/{handoff_id}", headers=actor_headers("bob")).status_code == 404
    assert client.post(f"/api/uwm/traditional-livability/s6/handoffs/{handoff_id}/execute-s1", headers=actor_headers("bob")).status_code == 404
```

- [ ] **Step 2: Run service and route tests to verify RED**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s6_s1_service.py data_agent/test_uwm_traditional_livability_routes.py`

Expected: FAIL because the routes and service are absent.

- [ ] **Step 3: Implement the service and endpoints**

Follow the existing UWM S2 actor-owned run pattern without importing UWM semantics. Keep storage process-local, validate all versions on execution and return 404 without existence leakage.

- [ ] **Step 4: Run API and adjacent route regressions**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s6_s1_service.py data_agent/test_uwm_traditional_livability_routes.py data_agent/test_uwm_livability_s2_routes.py`

Expected: PASS.

- [ ] **Step 5: Commit service and APIs**

Run: `git add data_agent/uwm/traditional_livability_s6_s1_service.py data_agent/api/uwm_traditional_livability_routes.py data_agent/frontend_api.py data_agent/test_traditional_livability_s6_s1_service.py data_agent/test_uwm_traditional_livability_routes.py && git commit -m "feat: expose S6 to S1 handoff APIs"`

### Task 7: Complete the S6 Panel Workflow

**Files:**
- Modify: `frontend/src/components/datapanel/TraditionalLivabilityS6Panel.tsx`
- Modify: `data_agent/test_uwm_traditional_livability_frontend_contract.py`

- [ ] **Step 1: Write failing frontend contract assertions**

Assert the panel contains explicit labels and API paths for `S1交接就绪度`, `生成S1交接`, `执行S1评估`, `FP`, `FPP`, `基线`, `拟建静态快照`, `传统静态分析` and unresolved blockers. Assert it does not label the comparison as UWM rollout.

- [ ] **Step 2: Run the frontend contract test to verify RED**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_uwm_traditional_livability_frontend_contract.py`

Expected: FAIL because the workflow controls are absent.

- [ ] **Step 3: Implement handoff and S1 result UI**

Reset confirmation and handoff whenever any semantic or spatial input changes. Display profile authority, dimensions, blockers, baseline/proposal values, combined result and backend-provided map evidence. Keep current S6 screening tables intact.

- [ ] **Step 4: Run frontend contract and production build**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_uwm_traditional_livability_frontend_contract.py data_agent/test_uwm_traditional_livability_routes.py`

Run: `npm run build` from `frontend/`.

Expected: tests PASS and Vite production build succeeds; existing loaders.gl/chunk-size warnings may remain.

- [ ] **Step 5: Commit the frontend workflow**

Run: `git add frontend/src/components/datapanel/TraditionalLivabilityS6Panel.tsx data_agent/test_uwm_traditional_livability_frontend_contract.py && git commit -m "feat: complete S6 to S1 livability workflow"`

### Task 8: Build and Verify the Real Fulu Product

**Files:**
- Create: `scripts/build_traditional_livability_s6_s1_fulu.py`
- Create: `scripts/verify_traditional_livability_s6_s1_fulu.py`
- Create: `data_agent/test_build_traditional_livability_s6_s1_fulu.py`
- Create: `data_agent/test_verify_traditional_livability_s6_s1_fulu.py`
- Create: `docs/reports/traditional_livability_s6_s1_fulu_verification_2026-07-11.md`

- [ ] **Step 1: Write failing product and verification tests**

Require bundle-consistent dictionary/profile/resource/facility products, one Heping and one Banzhu proposal, real blocker reporting, zero fabricated population/area/capacity fields, stable digests and explicit sampled-inventory claim limits.

- [ ] **Step 2: Run product tests to verify RED**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_build_traditional_livability_s6_s1_fulu.py data_agent/test_verify_traditional_livability_s6_s1_fulu.py`

Expected: FAIL because builders and reports are absent.

- [ ] **Step 3: Implement real-data build and verification scripts**

Reuse existing Fulu S6 resources and facility products. Import only locally available authoritative profiles; when none are available, produce a verified `profile_unavailable` handoff blocker rather than an invented compliance result. Record actual counts, bundle digests, proposal IDs, computed metrics and unresolved dimensions.

- [ ] **Step 4: Run complete focused verification**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_traditional_livability_s1*.py \
  data_agent/test_traditional_livability_s6*.py \
  data_agent/test_build_traditional_livability_s6_s1_fulu.py \
  data_agent/test_verify_traditional_livability_s6_s1_fulu.py \
  data_agent/test_traditional_livability_s7*.py \
  data_agent/test_uwm_livability_s2*.py
```

Run: `npm run build` from `frontend/`.

Expected: all focused tests PASS and frontend production build succeeds.

- [ ] **Step 5: Commit real verification artifacts**

Run: `git add scripts/build_traditional_livability_s6_s1_fulu.py scripts/verify_traditional_livability_s6_s1_fulu.py data_agent/test_build_traditional_livability_s6_s1_fulu.py data_agent/test_verify_traditional_livability_s6_s1_fulu.py docs/reports/traditional_livability_s6_s1_fulu_verification_2026-07-11.md && git commit -m "test: verify real S6 to S1 Fulu workflow"`

### Task 9: Final Regression and Evidence Audit

**Files:**
- Modify only files required by verified failures in this feature scope.

- [ ] **Step 1: Run diff and contract checks**

Run: `git diff --check`

Run: `rg -n "forecast|rollout|world model|UWM" frontend/src/components/datapanel/TraditionalLivabilityS6Panel.tsx data_agent/uwm/traditional_livability_s1_*.py data_agent/uwm/traditional_livability_s6_s1_*.py`

Expected: no wording that presents static S1 comparison as UWM or future prediction.

- [ ] **Step 2: Run focused backend suite**

Run the Task 8 focused pytest command.

Expected: PASS.

- [ ] **Step 3: Run frontend production build**

Run: `npm run build` from `frontend/`.

Expected: build succeeds.

- [ ] **Step 4: Audit source and claim boundaries**

Confirm the real verification report lists every missing authoritative profile, population, facility inventory, area, capacity or network field and contains no fabricated replacement values.

- [ ] **Step 5: Commit only necessary final corrections**

If corrections were required, stage only feature-owned files and commit with `fix: harden S6 to S1 evidence boundaries`. If no corrections were required, do not create an empty commit.
