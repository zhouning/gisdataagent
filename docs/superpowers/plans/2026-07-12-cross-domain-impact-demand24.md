# Cross-Domain Impact Demand 24 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a verified cross-domain evidence orchestration product that registers traditional GIS and UWM outputs, enforces spatial/semantic comparability, ranks evidence-orchestration priorities and exposes dependencies without creating a universal impact score.

**Architecture:** Domain adapters normalize only metadata, native evidence-gap facts and exact district identifiers from verified source bundles. A comparability engine prohibits inferred joins and cross-grain score aggregation, while a UWM registry distinguishes calibrated environmental dynamics from closed housing, culture, economy and resilience gates.

**Tech Stack:** Python, pytest, JSON contracts, Starlette, React/TypeScript, Vite.

**Design:** `docs/superpowers/specs/2026-07-12-cross-domain-impact-demand24-design.md`

---

## Task 1: Define Source Registry Contracts
**Files:** Create `data_agent/uwm/cross_domain_impact.py`; test `data_agent/test_cross_domain_impact.py`.
- [ ] Write failing tests for source metadata, technology routes, spatial grains, identifier contracts, claim boundaries and zero fabricated values.
- [ ] Implement product constants and source registration; run PASS and commit.

## Task 2: Implement Comparability Gates
**Files:** Modify product module; create `data_agent/test_cross_domain_impact_comparability.py`.
- [ ] Write failing pairwise tests for exact district comparability, aggregate reference-only, incompatible grains, temporal incompatibility and semantic incompatibility.
- [ ] Assert names, centroids, proximity and row order cannot create exact joins.
- [ ] Implement the deterministic matrix and commit.

## Task 3: Build District Evidence Priority
**Files:** Modify product module; create `data_agent/test_cross_domain_impact_priority.py`.
- [ ] Write failing tests for exact district-code assembly, null preservation, native-rank trace, blocker/dependency counts and stable priority ranking.
- [ ] Assert no weighted composite or outcome-severity field exists.
- [ ] Implement the district matrix and commit.

## Task 4: Register UWM Dynamic and Closed Channels
**Files:** Modify product module and tests.
- [ ] Write failing tests distinguishing `uwm_calibrated_dynamic` environmental evidence from closed housing, culture, economy and resilience gates.
- [ ] Implement dynamic evidence trace, calibration scope and closed-gate blockers; commit.

## Task 5: Build and Independently Verify Product
**Files:** Create builder/verifier scripts, real bundle and verification report.
- [ ] Write builder tests for verified source products, six immutable files, source traces and direct CLI.
- [ ] Build the Chongqing cross-domain product.
- [ ] Write verifier tests rejecting inferred joins, composite scores, false dynamic channels, missing dependency traces and bundle mismatch.
- [ ] Verify real counts/digest and commit.

## Task 6: Add Read-Only API
**Files:** Create service/routes; modify `data_agent/frontend_api.py`; add tests.
- [ ] Test defensive copies, filters, bundle consistency, auth and 400/404/503 behavior.
- [ ] Implement six GET endpoints under `/api/uwm/cross-domain-impact`; run PASS and commit.

## Task 7: Add Independent UI Tab
**Files:** Create `CrossDomainImpactTab.tsx`; modify `DataPanel.tsx`; add frontend contract test.
- [ ] Test route status, comparability matrix, priority units, UWM channels, dependencies, claim warnings and map dispatch.
- [ ] Implement `跨领域影响与优先级` tab and run production build.

## Task 8: Update Ledger and Merge
**Files:** Modify implementation ledger and tests.
- [ ] Test demand 24 status and maximum claim.
- [ ] Run focused backend tests, independent verifier and frontend build.
- [ ] Check protected-file overlap, merge with `--no-ff`, and repeat verification in the main worktree.
