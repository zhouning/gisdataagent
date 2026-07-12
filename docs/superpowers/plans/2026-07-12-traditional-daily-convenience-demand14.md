# Traditional Daily Convenience Demand 14 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a verified traditional GIS product for demand 14 that diagnoses daily-service inventory and accessibility context while keeping business operation, employment, revenue, demand and entrepreneurship outcomes closed.

**Architecture:** A focused module applies strict daily-convenience and business-activity classifiers to the verified facility product, keeps bank/ATM and convenience/business views distinct, reuses demand-8 accessibility only by exact administrative ID, and ranks relative evidence gaps. A real builder, independent verifier, read-only service, API, traditional-livability panel and ledger integration expose one immutable five-file bundle.

**Tech Stack:** Python, pytest, JSON contracts, Starlette, React/TypeScript, Vite.

**Design:** `docs/superpowers/specs/2026-07-12-traditional-daily-convenience-demand14-design.md`

---

## Task 1: Define Product and Channel Contracts
**Files:** Create `data_agent/uwm/traditional_daily_convenience.py`; test `data_agent/test_traditional_daily_convenience.py`.
- [ ] Write failing tests for schema, two views, complete channel readiness, canonical place fields, null economic fields, non-outcome flags and claim boundaries.
- [ ] Run RED, implement minimal contracts, run PASS, commit `feat: define daily convenience evidence contracts`.

## Task 2: Implement Strict Classification
**Files:** Modify product module; test `data_agent/test_traditional_daily_convenience_classification.py`.
- [ ] Write failing allow-list tests for convenience stores, supermarkets, markets, pharmacies, cafés, fast food, post, laundry, repair, telecom outlets, bank branches and ATMs.
- [ ] Write failing exclusion tests for construction materials, automobiles, KTV, internet cafés, resorts, hotels, funeral, massage, generic services, null/other and residential misclassification.
- [ ] Assert ATM is `atm_access_point`, bank is `bank_branch`, and company POIs belong only to `business_activity_evidence`.
- [ ] Implement exact normalized rules, run PASS, commit `feat: classify daily convenience and business evidence`.

## Task 3: Aggregate and Rank Evidence Gaps
**Files:** Modify product module; test `data_agent/test_traditional_daily_convenience_ranking.py`.
- [ ] Write failing tests for zero essential categories, missing store/supermarket/market/pharmacy evidence, lower diversity, lower count, missing exact accessibility and stable ties.
- [ ] Assert no economic-vitality, demand, employment or investment score exists.
- [ ] Implement exact-ID accessibility reuse, deterministic ranking and evidence-acquisition priorities; run PASS and commit.

## Task 4: Build and Independently Verify Chongqing Product
**Files:** Create builder/verifier scripts and their tests; create `docs/reports/traditional_daily_convenience_chongqing_verification_2026-07-12.md`.
- [ ] Write failing fixture tests for sampled facility input, demand-8 accessibility input, five atomic files, classification/exclusion statistics, exact-ID match count and direct CLI.
- [ ] Build `/private/tmp/traditional_daily_convenience_chongqing_real` from verified products.
- [ ] Write independent-verifier tests rejecting deny-listed convenience rows, ATM-as-bank, company-as-employment, unavailable economic values, inferred joins and bundle mismatch.
- [ ] Verify the real product, record real counts/digest and commit.

## Task 5: Add Read-Only Service and API
**Files:** Create service/routes; modify `data_agent/frontend_api.py`; add service/API tests.
- [ ] Write RED tests for deep copies, view/category filtering, admin lookup, bundle consistency, auth, registration and missing-product 503.
- [ ] Implement five GET endpoints under `/api/uwm/traditional-livability/daily-convenience`; run PASS and commit.

## Task 6: Add Traditional-Livability Panel
**Files:** Create `TraditionalLivabilityDailyConveniencePanel.tsx`; modify `TraditionalLivabilityTab.tsx`; add frontend contract test.
- [ ] Write RED contract for two views, category/exclusion counts, bank/ATM distinction, accessibility match coverage, relative gap, unavailable channels and separate map layers.
- [ ] Require visible statements `POI存在不代表实际营业`, `企业POI不代表就业岗位`, `相对缺口不代表权威市场短缺`.
- [ ] Forbid economic-vitality, employment, profitability and activation-effect claims.
- [ ] Implement panel, run contract and production build, commit.

## Task 7: Publish, Update Ledger and Merge
**Files:** Publish five JSON files; modify ledger and ledger test.
- [ ] Publish only independently verified files.
- [ ] Require demand 14 `implemented_evidence_bounded`, output `traditional_daily_convenience_business_evidence_product`, and maximum claim `daily_service_inventory_accessibility_context_and_business_activity_evidence`.
- [ ] Preserve operation, licence, employment, revenue, demand, entrepreneurship and causal-effect blockers.
- [ ] Run all tests, verifier, frontend build and protected-file diff check.
- [ ] Merge `--no-ff` into `feat/v12-extensible-platform` without reset, clean or stash; re-run focused verification.
