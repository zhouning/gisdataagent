# Traditional Housing Community Demand 13 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a verified traditional-GIS evidence product for demand 13 that exposes building morphology, population context and housing evidence readiness without inventing housing stock, affordability, tenure, household composition or shortage conclusions.

**Architecture:** A focused Python product module reads building morphology, district population and downscaled population artifacts, accepts only exact administrative identifiers or documented parent administrative codes, and publishes three independent views in an immutable five-file bundle. A real-data builder, independent verifier, read-only service, Starlette API, React panel and implementation-ledger entry expose the bounded product while keeping all unsupported housing channels explicitly unavailable.

**Tech Stack:** Python, pytest, JSON contracts, Starlette, React/TypeScript, Vite.

**Design:** `docs/superpowers/specs/2026-07-12-traditional-housing-community-demand13-design.md`

---

## Task 1: Define Product and Readiness Contracts
**Files:** Create `data_agent/uwm/traditional_housing_community.py`; test `data_agent/test_traditional_housing_community.py`.
- [ ] Write failing tests asserting schema `traditional_livability.housing_community_evidence.v1`, the three independent views, complete channel readiness, mandatory interpretation flags, null unavailable values, forbidden-field absence and zero fabricated values.
- [ ] Run `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_housing_community.py` and confirm RED because the module is absent.
- [ ] Implement constants, normalized source contracts, channel-readiness rows and claim boundaries with no housing-unit or affordability derivation.
- [ ] Re-run the focused test and confirm PASS.
- [ ] Commit `feat: define housing community evidence contracts`.

## Task 2: Enforce Exact Administrative Joins
**Files:** Modify `data_agent/uwm/traditional_housing_community.py`; create `data_agent/test_traditional_housing_community_joins.py`.
- [ ] Write failing tests proving morphology and downscaled population join only on identical `admin_unit_id`, district statistics attach only through explicit `admin_code` or documented parent code, and name/centroid/row-order/proximity matches remain `incompatible` or `reference_only`.
- [ ] Assert unmatched evidence stays separate and every missing numeric field remains `None`, never zero.
- [ ] Run the join test and confirm RED.
- [ ] Implement exact-ID indexes, explicit parent-code lookup, join-status records and source trace.
- [ ] Re-run both focused tests and commit `feat: enforce housing evidence join gates`.

## Task 3: Rank Relative Evidence Gaps
**Files:** Modify `data_agent/uwm/traditional_housing_community.py`; create `data_agent/test_traditional_housing_community_ranking.py`.
- [ ] Write failing tests for deterministic ranking by missing morphology, missing population proxy, missing district context, missing service-neighbourhood context, weaker source coverage and stable `admin_unit_id` tie-breaking.
- [ ] Assert the rank is named `relative_housing_community_evidence_gap_rank` and never becomes a housing shortage, crowding, affordability or family-suitability score.
- [ ] Run RED, implement evidence-gap reasons and field-collection priorities, then run PASS.
- [ ] Commit `feat: rank housing community evidence gaps`.

## Task 4: Build and Independently Verify Chongqing Product
**Files:** Create `scripts/build_traditional_housing_community_chongqing.py`, `scripts/verify_traditional_housing_community_chongqing.py`, fixture tests and `docs/reports/traditional_housing_community_chongqing_verification_2026-07-12.md`.
- [ ] Write failing builder tests covering all three verified artifacts, five atomic files, exact join counts, unmatched counts, null preservation and direct CLI execution.
- [ ] Implement the builder and publish `data/uwm_public_proxy/chongqing_central/traditional_housing_community_chongqing/{overview,admin_units,channel_readiness,evidence_sources,map}.json`.
- [ ] Write failing independent-verifier tests rejecting forbidden fields, inferred joins, missing flags, non-null unavailable channels, fabricated counts and bundle-ID mismatch.
- [ ] Implement the verifier, verify the real Chongqing bundle, and record source counts, join coverage, limitations and SHA-256 digest in the report.
- [ ] Commit `feat: publish verified housing community product`.

## Task 5: Add Read-Only Service and API
**Files:** Create `data_agent/uwm/traditional_housing_community_service.py`, `data_agent/api/uwm_traditional_housing_community_routes.py`; modify `data_agent/frontend_api.py`; add service and API tests.
- [ ] Write failing tests for defensive deep copies, view filtering, admin lookup, map payload, bundle consistency, authentication, route registration, invalid-view 400, missing-admin 404 and unavailable-product 503.
- [ ] Run RED, implement a five-file read-only service and five GET endpoints under `/api/uwm/traditional-livability/housing-community`.
- [ ] Re-run focused backend tests and commit `feat: expose housing community evidence api`.

## Task 6: Add Traditional-Livability Panel
**Files:** Create `frontend/src/components/datapanel/TraditionalLivabilityHousingCommunityPanel.tsx`; modify `frontend/src/components/datapanel/TraditionalLivabilityTab.tsx`; create `frontend/src/components/datapanel/TraditionalLivabilityHousingCommunityPanel.contract.test.ts`.
- [ ] Write a failing source-contract test for the three views, morphology/population cards, exact-join coverage, relative evidence-gap ranking, unavailable housing channels, limitations and separate map layers.
- [ ] Implement the panel and register it only in the traditional livability tab; do not add a UWM duplicate.
- [ ] Run the frontend contract test and `npm run build`; commit `feat: add housing community evidence panel`.

## Task 7: Update Ledger and Perform Final Verification
**Files:** Modify `data_agent/uwm/ai_demand_implementation_ledger.py` and its tests.
- [ ] Write a failing ledger test expecting demand 13 status `implemented_evidence_bounded`, route/product references, and maximum claim `building_morphology_population_context_and_housing_evidence_readiness`.
- [ ] Implement the ledger update and run all demand-13 focused backend tests.
- [ ] Run the independent verifier against the published bundle and run the frontend production build.
- [ ] Confirm no protected main-worktree files overlap, commit `docs: finalize housing community demand 13`, merge with `git merge --no-ff`, and repeat focused verification on `feat/v12-extensible-platform`.
