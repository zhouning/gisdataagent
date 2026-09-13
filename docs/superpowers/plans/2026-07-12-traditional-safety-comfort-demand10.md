# Traditional Safety and Comfort Evidence Demand 10 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a verified traditional GIS evidence-diagnostic product for demand 10 that exposes mobility and environmental context without claiming safety outcomes, thermal comfort, safe routes or intervention effects.

**Architecture:** A focused product module validates independent mobility, meteorology, air-quality and public-safety-facility evidence sources, applies explicit spatial-grain join gates and ranks evidence incompleteness rather than danger. A real builder writes an immutable five-file bundle; an independent verifier, read-only service, API, traditional-livability panel and ledger integration expose the bounded product.

**Tech Stack:** Python, pytest, JSON product contracts, Starlette, React/TypeScript, Vite.

**Design:** `docs/superpowers/specs/2026-07-12-traditional-safety-comfort-demand10-design.md`

---

## Task 1: Define Product and Readiness Contracts

**Files:**
- Create: `data_agent/uwm/traditional_safety_comfort.py`
- Test: `data_agent/test_traditional_safety_comfort.py`

- [ ] Write failing tests for schema `traditional_livability.safety_comfort_evidence.v1`, all demand-10 channels, five source/join statuses, forbidden score fields, unavailable null values and claim boundaries.
- [ ] Run the focused test and confirm `ModuleNotFoundError`.
- [ ] Implement channel constants, source contracts, canonical rows and claim boundaries without source fusion.
- [ ] Run the focused test and confirm PASS.
- [ ] Commit with `feat: define safety comfort evidence contracts`.

## Task 2: Implement Spatial-Grain and Claim Gates

**Files:**
- Modify: `data_agent/uwm/traditional_safety_comfort.py`
- Test: `data_agent/test_traditional_safety_comfort_join_gates.py`

- [ ] Write failing tests for `exact_supported`, `aggregate_supported`, `reference_only` and `incompatible` joins using explicit identifiers and parent-child crosswalks.
- [ ] Assert names, centroids and row order never create a supported join.
- [ ] Assert mobility rows carry `network_context_not_road_safety=true`; meteorology rows carry `temperature_context_not_thermal_comfort=true`.
- [ ] Run RED.
- [ ] Implement deterministic join decisions and reject unsupported inferred joins.
- [ ] Run Tasks 1–2 tests and confirm PASS.
- [ ] Commit with `feat: gate safety comfort evidence joins`.

## Task 3: Rank Evidence Gaps and Collection Priorities

**Files:**
- Modify: `data_agent/uwm/traditional_safety_comfort.py`
- Test: `data_agent/test_traditional_safety_comfort_ranking.py`

- [ ] Write failing tests for unavailable critical-channel count, absent mobility, absent meteorology, absent air quality, incompatible joins and stable ID tie-breaking.
- [ ] Assert rank field is `relative_safety_comfort_evidence_gap_rank` and no safety, crime, risk, thermal-comfort or investment score exists.
- [ ] Assert field priorities identify crashes, lighting, crossings, shade, accessibility and comfort measurements as data collection.
- [ ] Run RED, implement transparent ranking/reason logic, then run PASS.
- [ ] Commit with `feat: rank safety comfort evidence gaps`.

## Task 4: Build and Verify Real Chongqing Product

**Files:**
- Create: `scripts/build_traditional_safety_comfort_chongqing.py`
- Create: `scripts/verify_traditional_safety_comfort_chongqing.py`
- Test: `data_agent/test_build_traditional_safety_comfort_chongqing.py`
- Test: `data_agent/test_verify_traditional_safety_comfort_chongqing.py`
- Create after execution: `docs/reports/traditional_safety_comfort_chongqing_verification_2026-07-12.md`

- [ ] Write failing builder tests using mobility, environmental and facility fixtures with mismatched grains.
- [ ] Require `overview.json`, `admin_units.json`, `channel_readiness.json`, `evidence_sources.json` and `map.json` to share one bundle ID.
- [ ] Require source counts, grains, time ranges, join statuses, missingness, fabricated-value count and production blockers.
- [ ] Implement explicit CLI inputs and atomic deterministic output.
- [ ] Build `/private/tmp/traditional_safety_comfort_chongqing_real` from verified repository/private-tmp products.
- [ ] Write failing independent-verifier tests for forbidden scores, temperature-as-comfort labels, network-as-safety labels, inferred joins, unavailable numeric values and bundle mismatch.
- [ ] Implement independent verification and write the real verification report.
- [ ] Commit with `feat: build verified Chongqing safety comfort evidence product`.

## Task 5: Add Read-Only Service and API

**Files:**
- Create: `data_agent/uwm/traditional_safety_comfort_service.py`
- Create: `data_agent/api/uwm_traditional_safety_comfort_routes.py`
- Modify: `data_agent/frontend_api.py`
- Test: `data_agent/test_traditional_safety_comfort_service.py`
- Test: `data_agent/test_uwm_traditional_safety_comfort_routes.py`

- [ ] Write failing tests for deep copies, bundle consistency, source-family filtering, admin lookup, authentication, route registration and missing-product 503.
- [ ] Run RED.
- [ ] Implement loading from `UWM_TRADITIONAL_SAFETY_COMFORT_PATH` and five read-only endpoints under `/api/uwm/traditional-livability/safety-comfort`.
- [ ] Run PASS and commit with `feat: expose safety comfort evidence APIs`.

## Task 6: Add Traditional-Livability Panel

**Files:**
- Create: `frontend/src/components/datapanel/TraditionalLivabilitySafetyComfortPanel.tsx`
- Modify: `frontend/src/components/datapanel/TraditionalLivabilityTab.tsx`
- Test: `data_agent/test_traditional_safety_comfort_frontend_contract.py`

- [ ] Write failing contract tests for all API paths, independent evidence families, join status, unavailable channels, evidence-gap rank, field-collection priorities and map layers.
- [ ] Require visible statements `证据缺口排名不代表危险程度`, `温度上下文不等于热舒适` and `路网上下文不等于道路安全`.
- [ ] Forbid authoritative risk, crime, safe-route, accessibility-compliance and intervention-effect wording.
- [ ] Implement the panel only inside `TraditionalLivabilityTab.tsx` and run the contract test plus `npm run build`.
- [ ] Commit with `feat: add safety comfort evidence panel`.

## Task 7: Publish, Update Ledger and Merge Safely

**Files:**
- Create: `data/uwm_public_proxy/chongqing_central/traditional_safety_comfort_chongqing/*.json`
- Modify: `data_agent/uwm/ai_demand_implementation_ledger.py`
- Modify: `data_agent/test_uwm_ai_demand_implementation_ledger.py`

- [ ] Publish only the independently verified five-file bundle.
- [ ] Write a failing ledger test requiring demand 10 `implemented_evidence_bounded`, output `traditional_safety_comfort_evidence_product` and maximum claim `mobility_environment_context_and_safety_comfort_evidence_readiness`.
- [ ] Preserve all crash, crime, lighting, crossing, shade, accessibility, thermal-comfort and intervention-effect blockers.
- [ ] Run all new tests, independent verification and frontend production build.
- [ ] Inspect changed paths and confirm protected Paper58/TWM files are untouched.
- [ ] Merge with `--no-ff` into `feat/v12-extensible-platform` without reset, clean or stash.
- [ ] Re-run focused tests and independent verification in the main worktree.
