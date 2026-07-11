# Traditional Livability S1-Gated S7 Siting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent S7 from presenting conditional primary-school candidate rankings as authoritative site recommendations unless a compatible S1 assessment proves a positive facility need.

**Architecture:** Add immutable S1→S7 demand-gate and geography-crosswalk contracts, keep the current S7 engine as a pure conditional geometry-ranking primitive, and place a gate-aware orchestrator above it. Expose authoritative, conditional and no-siting modes through the existing traditional livability API and panel, with real Fulu data verified as unresolved need plus conditional ranking only.

**Tech Stack:** Python 3.11, pytest, existing deterministic S1/S7 products, Starlette routes, React/TypeScript, existing map-update GeoJSON contract.

---

### Task 1: Add the S1→S7 Geography Crosswalk Contract

**Files:**
- Create: `data_agent/uwm/traditional_livability_s1_s7_crosswalk.py`
- Create: `data_agent/test_traditional_livability_s1_s7_crosswalk.py`

- [ ] **Step 1: Write failing crosswalk validation tests**

Cover schema, source metadata, effective date, unique S1/S7 pairs, relationship type, content digest, missing-area detection, deep detachment and deterministic ordering.

```python
def test_crosswalk_requires_every_requested_s7_area():
    result = validate_s1_s7_crosswalk(
        crosswalk_fixture(rows=[row("bishan", "fulu_heping")]),
        s1_geography_id="bishan",
        requested_s7_area_ids=["fulu_heping", "fulu_banzhu"],
    )
    assert result["status"] == "invalid"
    assert "s7_area_crosswalk_missing:fulu_banzhu" in result["blockers"]
```

- [ ] **Step 2: Run the crosswalk test to verify RED**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s1_s7_crosswalk.py`

Expected: FAIL because the module is absent.

- [ ] **Step 3: Implement the versioned crosswalk validator**

Define schema `uwm.traditional_livability.s1_s7_geography_crosswalk.v1`. Reuse the canonical content-digest helper, accept only explicit relationship rows, and fail closed for missing requested areas or duplicate/conflicting mappings.

- [ ] **Step 4: Run focused validation tests**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s1_s7_crosswalk.py data_agent/test_traditional_livability_s7_fulu_adapter.py`

Expected: PASS.

- [ ] **Step 5: Commit the crosswalk contract**

Run: `git add data_agent/uwm/traditional_livability_s1_s7_crosswalk.py data_agent/test_traditional_livability_s1_s7_crosswalk.py && git commit -m "feat: validate S1 to S7 geography crosswalks"`

### Task 2: Implement the S7 Demand Gate

**Files:**
- Create: `data_agent/uwm/traditional_livability_s7_demand_gate.py`
- Create: `data_agent/test_traditional_livability_s7_demand_gate.py`

- [ ] **Step 1: Write failing gate-state tests**

Cover authoritative positive count gap, authoritative zero/negative gap, missing profile/matrix/population/capacity, sampled inventory, class mismatch, facility-bundle mismatch, stale assessment timestamp and crosswalk blockers.

```python
def test_positive_authoritative_count_gap_confirms_need():
    gate = build_s7_demand_gate(**gate_inputs(gap_type="facility_count_gap", gap_value=2.2))
    assert gate["state"] == "authoritative_need_confirmed"
    assert gate["required_site_count"] == 3


def test_sampled_inventory_keeps_need_unresolved():
    gate = build_s7_demand_gate(**gate_inputs(complete_inventory=False))
    assert gate["state"] == "need_unresolved"
    assert "facility_inventory_incomplete" in gate["blockers"]
```

- [ ] **Step 2: Run gate tests to verify RED**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s7_demand_gate.py`

Expected: FAIL because the gate is absent.

- [ ] **Step 3: Implement immutable demand-gate construction**

Define schema `uwm.traditional_livability.s7_demand_gate.v1`. Bind class, geography, S1 assessment/profile/matrix, facility bundle and S7 planning product digests. Calculate `required_site_count` only for a positive authoritative count gap. Keep area/capacity closure unavailable without proposal attributes.

- [ ] **Step 4: Run gate, S1 and profile regressions**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s7_demand_gate.py data_agent/test_traditional_livability_s1*.py`

Expected: PASS.

- [ ] **Step 5: Commit demand gating**

Run: `git add data_agent/uwm/traditional_livability_s7_demand_gate.py data_agent/test_traditional_livability_s7_demand_gate.py && git commit -m "feat: gate S7 siting on S1 need"`

### Task 3: Add the Gate-Aware S7 Orchestrator

**Files:**
- Create: `data_agent/uwm/traditional_livability_s7_gated.py`
- Create: `data_agent/test_traditional_livability_s7_gated.py`
- Modify: `data_agent/uwm/traditional_livability_s7.py`
- Modify: `data_agent/test_traditional_livability_s7.py`

- [ ] **Step 1: Write failing mode tests**

Cover authoritative recommendation, count-gap site cap, no-siting state, conditional acknowledgement requirement, candidate flags, prohibited wording fields, area/capacity closure limits, input detachment and unchanged scoring order.

```python
def test_unresolved_need_allows_only_acknowledged_conditional_ranking():
    with pytest.raises(ValueError, match="conditional_not_a_recommendation_ack_required"):
        run_gated_s7(mode="conditional", acknowledgement=False, **inputs(unresolved_gate()))
    result = run_gated_s7(mode="conditional", acknowledgement=True, **inputs(unresolved_gate()))
    assert result["recommendation_status"] == "conditional_candidate_ranking_available"
    assert all(row["not_a_site_recommendation"] for row in result["ranked_candidates"])


def test_positive_count_gap_caps_selected_sites():
    result = run_gated_s7(mode="authoritative", **inputs(confirmed_gate(required_site_count=2)))
    assert len(result["selected_sites"]) <= 2
```

- [ ] **Step 2: Run orchestrator tests to verify RED**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s7_gated.py`

Expected: FAIL because the orchestrator is absent.

- [ ] **Step 3: Implement mode orchestration over the existing S7 engine**

Do not duplicate geometry scoring. Call `allocate_facility_sites` only after gate validation. Preserve legacy engine ordering. Relabel all outputs by mode, attach gate evidence and cap `max_sites` for authoritative count gaps.

- [ ] **Step 4: Run S7 engine and orchestrator regressions**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s7.py data_agent/test_traditional_livability_s7_gated.py`

Expected: PASS.

- [ ] **Step 5: Commit the gated orchestrator**

Run: `git add data_agent/uwm/traditional_livability_s7.py data_agent/uwm/traditional_livability_s7_gated.py data_agent/test_traditional_livability_s7.py data_agent/test_traditional_livability_s7_gated.py && git commit -m "feat: separate S7 recommendations from conditional rankings"`

### Task 4: Build the Real Fulu Gated S7 Product

**Files:**
- Create: `data_agent/uwm/traditional_livability_s7_gated_product.py`
- Create: `scripts/build_traditional_livability_s7_gated_fulu.py`
- Create: `scripts/verify_traditional_livability_s7_gated_fulu.py`
- Create: `data_agent/test_build_traditional_livability_s7_gated_fulu.py`
- Create: `data_agent/test_verify_traditional_livability_s7_gated_fulu.py`
- Create: `docs/reports/traditional_livability_s7_gated_fulu_verification_2026-07-11.md`

- [ ] **Step 1: Write failing real-product contract tests**

Require one bundle ID, two planning areas, S1/facility/S7 source references, unresolved gate, conditional ranking status, `not_a_site_recommendation=true` on all rows, current blockers and zero fabricated values.

- [ ] **Step 2: Run product tests to verify RED**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_build_traditional_livability_s7_gated_fulu.py data_agent/test_verify_traditional_livability_s7_gated_fulu.py`

Expected: FAIL because the gated product is absent.

- [ ] **Step 3: Implement real product build and verification**

Use the existing real S7 product and S1/facility products. Create an explicit Bishan-to-Heping/Banzhu crosswalk from source geography identifiers only. Do not infer school need. Build the unresolved gate and conditional run with all blockers.

- [ ] **Step 4: Run real build and verifier**

Build into `/private/tmp/traditional_livability_s7_gated_fulu_real`. Record actual candidate counts, selected conditional rows, source digests and blockers.

- [ ] **Step 5: Commit product and report**

Run: `git add data_agent/uwm/traditional_livability_s7_gated_product.py scripts/build_traditional_livability_s7_gated_fulu.py scripts/verify_traditional_livability_s7_gated_fulu.py data_agent/test_build_traditional_livability_s7_gated_fulu.py data_agent/test_verify_traditional_livability_s7_gated_fulu.py docs/reports/traditional_livability_s7_gated_fulu_verification_2026-07-11.md && git commit -m "test: verify S1-gated Fulu S7 siting"`

### Task 5: Add Gated S7 Service and API

**Files:**
- Create: `data_agent/uwm/traditional_livability_s7_gated_service.py`
- Modify: `data_agent/api/uwm_traditional_livability_routes.py`
- Modify: `data_agent/test_uwm_traditional_livability_routes.py`
- Create: `data_agent/test_traditional_livability_s7_gated_service.py`

- [ ] **Step 1: Write failing service and route tests**

Cover product loading, demand-gate retrieval, authoritative HTTP 409, conditional acknowledgement HTTP 400, successful conditional run and compatibility GET route wording.

- [ ] **Step 2: Run tests to verify RED**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s7_gated_service.py data_agent/test_uwm_traditional_livability_routes.py -k "s7"`

Expected: FAIL because the new service/routes are absent.

- [ ] **Step 3: Implement product-backed service and endpoints**

Add:

- `GET /api/uwm/traditional-livability/s7/demand-gate`
- `POST /api/uwm/traditional-livability/s7/run`

Load through `UWM_TRADITIONAL_LIVABILITY_S7_GATED_PATH`. Preserve existing GET route but serve gate-aware output.

- [ ] **Step 4: Run route and adjacent S1/S6 regressions**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_livability_s7_gated_service.py data_agent/test_uwm_traditional_livability_routes.py data_agent/test_traditional_livability_s6_s1_service.py`

Expected: PASS.

- [ ] **Step 5: Commit service and routes**

Run: `git add data_agent/uwm/traditional_livability_s7_gated_service.py data_agent/api/uwm_traditional_livability_routes.py data_agent/test_traditional_livability_s7_gated_service.py data_agent/test_uwm_traditional_livability_routes.py && git commit -m "feat: expose S1-gated S7 APIs"`

### Task 6: Update the S7 Panel for Separate Modes

**Files:**
- Modify: `frontend/src/components/datapanel/TraditionalLivabilityS7Panel.tsx`
- Modify: `data_agent/test_uwm_traditional_livability_frontend_contract.py`

- [ ] **Step 1: Write failing frontend contract tests**

Require demand-gate state, S1 FP/FPP evidence, blockers, authoritative and conditional controls, explicit acknowledgement, current Fulu warning and absence of primary/backup recommendation wording in unresolved mode.

- [ ] **Step 2: Run frontend test to verify RED**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_uwm_traditional_livability_frontend_contract.py -k "s7"`

Expected: FAIL because the gate UI is absent.

- [ ] **Step 3: Implement demand evidence and mode UI**

Fetch the demand gate separately, disable authoritative action unless confirmed, require a checkbox acknowledgement for conditional mode and render candidates without recommendation terminology. Consume backend map evidence unchanged.

- [ ] **Step 4: Run frontend contracts and production build**

Run: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_uwm_traditional_livability_frontend_contract.py data_agent/test_uwm_traditional_livability_routes.py`

Run: `npm run build` from `frontend/`.

Expected: tests PASS and production build succeeds.

- [ ] **Step 5: Commit the panel update**

Run: `git add frontend/src/components/datapanel/TraditionalLivabilityS7Panel.tsx data_agent/test_uwm_traditional_livability_frontend_contract.py && git commit -m "feat: show S1-gated S7 siting modes"`

### Task 7: Final Regression and Evidence Audit

**Files:**
- Modify only feature-owned files required by verified failures.

- [ ] **Step 1: Audit prohibited conditional wording**

Run:

```bash
rg -n "主选|备选|建成后达标|消除缺口|推荐建设" \
  frontend/src/components/datapanel/TraditionalLivabilityS7Panel.tsx \
  data_agent/uwm/traditional_livability_s7_gated.py \
  docs/reports/traditional_livability_s7_gated_fulu_verification_2026-07-11.md
```

Expected: wording appears only in explicit authoritative-mode explanations or prohibited-wording documentation, never current conditional result labels.

- [ ] **Step 2: Run focused backend regression**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_traditional_livability_s1*.py \
  data_agent/test_traditional_livability_s7*.py \
  data_agent/test_build_traditional_livability_s7_gated_fulu.py \
  data_agent/test_verify_traditional_livability_s7_gated_fulu.py \
  data_agent/test_uwm_traditional_livability_routes.py \
  data_agent/test_uwm_traditional_livability_frontend_contract.py
```

Expected: PASS.

- [ ] **Step 3: Run frontend production build**

Run: `npm run build` from `frontend/`.

Expected: build succeeds with only existing warnings.

- [ ] **Step 4: Verify real Fulu evidence boundary**

Confirm the verification report records unresolved need, conditional ranking only, all current blockers and zero fabricated population, capacity, gap or service-radius values.

- [ ] **Step 5: Commit only necessary hardening corrections**

If corrections were required, commit feature-owned files with `fix: harden S1-gated S7 boundaries`. Do not create an empty commit.
