# Traditional Cultural Heritage Demand 16 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a verified cultural-place and heritage-readiness product that separates explicitly classified cultural places, keyword-only candidate leads and mandatory exclusions without claiming legal heritage status or cultural value.

**Architecture:** A focused classifier consumes the verified Chongqing facility product and assigns every relevant record to one evidence tier using strict source-category allow lists and incompatible-category exclusions. Deterministic administrative aggregation, a real-data builder, independent verifier, read-only service, authenticated API, independent UI tab and demand-ledger update publish one immutable five-file product.

**Tech Stack:** Python, pytest, JSON contracts, Starlette, React/TypeScript, Vite.

**Design:** `docs/superpowers/specs/2026-07-12-traditional-cultural-heritage-demand16-design.md`

---

## Task 1: Define Product and Readiness Contracts
**Files:** Create `data_agent/uwm/traditional_cultural_heritage.py`; test `data_agent/test_traditional_cultural_heritage.py`.
- [ ] Write failing tests for schema, four evidence views, canonical categories, mandatory claim flags, null legal status, unavailable channels and forbidden-field absence.
- [ ] Run the focused test and confirm RED because the module is absent.
- [ ] Implement constants, place contracts, readiness rows and claim boundaries with `fabricated_value_count=0`.
- [ ] Re-run the focused test and commit `feat: define cultural heritage evidence contracts`.

## Task 2: Implement Strict Evidence-Tier Classification
**Files:** Modify product module; create `data_agent/test_traditional_cultural_heritage_classification.py`.
- [ ] Write failing allow-list tests for explicit museums, memorial halls, cultural relic sites, religious places, cultural centers and exhibition/gallery categories.
- [ ] Write failing candidate tests proving unsupported names such as an explicitly uncategorized heritage site become `requires_authoritative_verification` with null legal status.
- [ ] Write failing exclusion tests for villages, banks, parking, hotels, stores, companies, schools, hospitals, government offices, entrances and ordinary addresses whose names contain cultural keywords.
- [ ] Implement deterministic normalized classification and exclusion reasons; run PASS and commit.

## Task 3: Aggregate and Rank Evidence Readiness
**Files:** Modify product module; create `data_agent/test_traditional_cultural_heritage_ranking.py`.
- [ ] Write failing tests for explicit admin-code aggregation, unmatched isolation, confirmed/category/source counts, candidate imbalance, stable gap ranking and acquisition priorities.
- [ ] Assert no name, centroid, proximity or row-order join exists and missing scope is not converted to authoritative zero.
- [ ] Implement deterministic evidence-gap ranking and commit.

## Task 4: Build and Independently Verify Chongqing Product
**Files:** Create builder/verifier scripts and tests; create verification report.
- [ ] Write failing builder tests for the 76,292-record facility product, five atomic files, tier/category counts, exclusion reasons, map layers and direct CLI.
- [ ] Implement builder and publish `data/uwm_public_proxy/chongqing_central/traditional_cultural_heritage_chongqing`.
- [ ] Write verifier tests rejecting keyword promotion, incompatible-category promotion, inferred legal status, forbidden scores, non-null unavailable values and bundle mismatch.
- [ ] Verify the real bundle, record counts and digest, then commit.

## Task 5: Add Read-Only Service and API
**Files:** Create service/routes; modify `data_agent/frontend_api.py`; add tests.
- [ ] Write failing tests for defensive copies, tier/category filters, admin lookup, map filtering, authentication, route registration and 400/404/503 behavior.
- [ ] Implement five GET endpoints under `/api/uwm/traditional-livability/cultural-heritage` and run focused backend tests.
- [ ] Commit `feat: expose cultural heritage evidence api`.

## Task 6: Add Independent Cultural-Heritage Tab
**Files:** Create `TraditionalCulturalHeritageTab.tsx`; modify the data-panel tab registry; add a frontend contract test.
- [ ] Write a failing contract for four evidence views, confirmed/candidate separation, exclusion diagnostics, unavailable channels, relative evidence-gap table and map dispatch.
- [ ] Implement an independent `文化遗产与场所` tab without adding a duplicate UWM analysis.
- [ ] Run frontend contract tests and `npm run build`; commit.

## Task 7: Update Ledger and Final Verification
**Files:** Modify `data_agent/uwm/ai_demand_implementation_ledger.py` and tests.
- [ ] Write a failing ledger test for demand 16 `implemented_evidence_bounded` and maximum claim `cultural_place_inventory_candidate_leads_and_heritage_evidence_readiness`.
- [ ] Implement the ledger entry and run all demand-16 focused tests.
- [ ] Run the independent verifier and frontend production build.
- [ ] Check protected-file overlap, merge with `git merge --no-ff`, and repeat verification in the main worktree.
