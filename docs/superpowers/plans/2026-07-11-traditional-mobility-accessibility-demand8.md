# Traditional Mobility and Accessibility Demand 8 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a real, evidence-bounded traditional GIS product for customer demand 8 using the existing Chongqing service-accessibility and road-network foundation, while keeping transit, safety, shade, cycling, parking and universal-accessibility channels explicitly unavailable.

**Architecture:** A focused mobility product module validates existing accessibility, mobility-graph and quality-audit artifacts, creates deterministic administrative gap rankings and a complete channel-readiness matrix, then writes an immutable four-file product. A read-only service, Starlette routes and a traditional-livability frontend panel expose the product without recomputing or upgrading claims.

**Tech Stack:** Python, pytest, existing JSON product contracts, Starlette routes, React/TypeScript, Vite.

**Design:** `docs/superpowers/specs/2026-07-11-traditional-mobility-accessibility-demand8-design.md`

---

## Task 1: Define Demand-8 Product and Channel Contracts

**Files:**
- Create: `data_agent/uwm/traditional_mobility_accessibility.py`
- Test: `data_agent/test_traditional_mobility_accessibility.py`

- [ ] Write failing tests for `implemented`, `proxy_only`, `unavailable`, all required demand-8 channels, null-only unavailable values, proxy travel-time labels, canonical row ordering and deterministic bundle inputs.
- [ ] Run the test and confirm failure because the module is missing.
- [ ] Implement schema constants, channel definitions, source validation and canonical administrative row construction.
- [ ] Run the focused test and commit with `feat: define mobility accessibility product contracts`.

## Task 2: Build Transparent Gap Rankings

**Files:**
- Modify: `data_agent/uwm/traditional_mobility_accessibility.py`
- Test: `data_agent/test_traditional_mobility_accessibility_ranking.py`

- [ ] Write failing tests for score exclusions, ascending accessibility-gap ordering, nearest-service tie breakers, zero-service reasons, missing-evidence review priority and absence of authoritative thresholds.
- [ ] Run RED.
- [ ] Implement deterministic relative ranking and review-priority reasons without a composite walkability score.
- [ ] Run Tasks 1–2 tests and commit with `feat: rank evidence-bounded accessibility gaps`.

## Task 3: Build and Independently Verify the Real Chongqing Product

**Files:**
- Create: `scripts/build_traditional_mobility_accessibility_chongqing.py`
- Create: `scripts/verify_traditional_mobility_accessibility_chongqing.py`
- Test: `data_agent/test_build_traditional_mobility_accessibility_chongqing.py`
- Test: `data_agent/test_verify_traditional_mobility_accessibility_chongqing.py`
- Create after execution: `docs/reports/traditional_mobility_accessibility_chongqing_verification_2026-07-11.md`

- [ ] Write failing tests for atomic `overview.json`, `admin_units.json`, `channel_readiness.json`, `map.json`, shared bundle ID, real counts, direct CLI execution, zero fabricated values and unavailable-channel numeric-value rejection.
- [ ] Run RED.
- [ ] Implement artifact discovery under an explicit source root, deterministic bundle assembly and atomic writes.
- [ ] Build `/private/tmp/traditional_mobility_accessibility_chongqing_real` using `/Users/zhouning/gisdataagent` as source root.
- [ ] Run the independent verifier and record actual bundle, counts, blockers and verification digest in the report.
- [ ] Run product tests and commit with `feat: build real Chongqing mobility accessibility product`.

## Task 4: Add Read-Only Service and API

**Files:**
- Create: `data_agent/uwm/traditional_mobility_accessibility_service.py`
- Create: `data_agent/api/uwm_traditional_mobility_routes.py`
- Modify: `data_agent/frontend_api.py`
- Test: `data_agent/test_traditional_mobility_accessibility_service.py`
- Test: `data_agent/test_uwm_traditional_mobility_routes.py`

- [ ] Write failing tests for deep copies, bundle mismatch, admin lookup, missing admin, authentication, route registration and product-unavailable responses.
- [ ] Run RED.
- [ ] Implement product-backed service loading from `UWM_TRADITIONAL_MOBILITY_PATH`.
- [ ] Register overview, admin list, admin detail and map GET endpoints.
- [ ] Run service/API tests and commit with `feat: expose traditional mobility accessibility APIs`.

## Task 5: Add the Traditional-Livability Mobility Panel

**Files:**
- Create: `frontend/src/components/datapanel/TraditionalLivabilityMobilityPanel.tsx`
- Modify: `frontend/src/components/datapanel/TraditionalLivabilityTab.tsx`
- Test: `data_agent/test_traditional_mobility_accessibility_frontend_contract.py`
- Modify if needed: `data_agent/test_uwm_traditional_livability_frontend_contract.py`

- [ ] Write failing contract tests for all four API paths, channel readiness, proxy warning, unavailable transit/safety/shade/accessibility fields, ranking, review candidates and `__handleMapUpdate`.
- [ ] Forbid observed-walk-time, safe-route, transit-coverage and authoritative investment claims.
- [ ] Run RED.
- [ ] Implement the panel and register it in the existing traditional-livability tab.
- [ ] Run frontend tests and `npm run build`; commit with `feat: add traditional mobility accessibility panel`.

## Task 6: Update the AI Demand Implementation Ledger

**Files:**
- Modify: `data_agent/uwm/ai_demand_implementation_ledger.py`
- Modify: `data_agent/test_uwm_ai_demand_implementation_ledger.py`

- [ ] Write a failing test requiring demand 8 to become `implemented_evidence_bounded`, reference the verified mobility product and retain blockers for transit, safety, shade, accessibility, cycling and parking.
- [ ] Run RED.
- [ ] Update only demand 8’s overlay and maximum supported claim.
- [ ] Run ledger/API/frontend readiness tests and commit with `feat: register verified demand 8 mobility product`.

## Task 7: Integrated Verification and Safe Merge

- [ ] Rebuild and verify the real product from scratch.
- [ ] Run all new mobility tests plus existing traditional-livability and AI-demand-readiness regressions.
- [ ] Run the frontend production build.
- [ ] Record main-worktree Paper58/TWM modifications and confirm no overlapping uncommitted files.
- [ ] Merge with `--no-ff`, rerun tests/build on main and confirm protected edits remain.
- [ ] Remove only the feature worktree and merged branch.
