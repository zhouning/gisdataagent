# Dependency-Aware Roadmap Demand 25 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an immutable implementation-roadmap product that converts the verified demand-24 bundle into an acyclic, evidence-gated task plan without fabricating projects, budgets, dates, organizations or policy effects.

**Architecture:** A deterministic roadmap engine maps demand-24 source products, closed UWM gates and dependency graph into shared and domain-specific tasks. Status calculation is fail-closed, priority derives from descendant unlocks and shared-domain value, and independent verification enforces DAG, lineage and recommendation boundaries.

**Tech Stack:** Python, pytest, JSON contracts, Starlette, React/TypeScript, Vite.

**Design:** `docs/superpowers/specs/2026-07-12-dependency-roadmap-demand25-design.md`

---

## Task 1: Define Task and Status Contracts
**Files:** Create `data_agent/uwm/dependency_roadmap.py`; test `data_agent/test_dependency_roadmap.py`.
- [ ] Test schema, task fields, allowed statuses, null forbidden recommendations and claim boundaries.
- [ ] Implement contracts and commit.

## Task 2: Build Acyclic Dependency Graph
**Files:** Modify module; add graph tests.
- [ ] Test shared foundations, domain chains, stable IDs, missing-reference rejection, self-dependency rejection and cycle detection.
- [ ] Implement deterministic DAG and commit.

## Task 3: Implement Fail-Closed Status and Priority
**Files:** Modify module; add status/priority tests.
- [ ] Test verified phase-0 capabilities, ready phase-1 roots, blocked calibration/verification/release tasks and no automatic in-progress status.
- [ ] Test descendant/shared-domain priority and stable ties.
- [ ] Implement status and priority calculation; commit.

## Task 4: Build and Verify Real Roadmap Bundle
**Files:** Create builder/verifier scripts, six product files and report.
- [ ] Build from the verified demand-24 six-file bundle only.
- [ ] Verify lineage, statuses, DAG, forbidden recommendations and zero fabricated values.
- [ ] Record task counts, phase counts, gate counts and digest; commit.

## Task 5: Add Service and API
**Files:** Create service/routes; modify frontend API; add tests.
- [ ] Test defensive copies, filters, auth, bundle consistency and unavailable behavior.
- [ ] Implement six read-only endpoints and commit.

## Task 6: Add Independent Roadmap Tab
**Files:** Create `ImplementationRoadmapTab.tsx`; modify `DataPanel.tsx`; add frontend contract test.
- [ ] Display verified capabilities, ready/blocked tasks, shared dependencies, domain chains, Kernel gates and recommendation boundary.
- [ ] Run production build and commit.

## Task 7: Update Ledger and Merge
**Files:** Modify ledger and tests.
- [ ] Set demand 25 to evidence-bounded with the approved maximum claim.
- [ ] Run focused tests, verifier and frontend build.
- [ ] Check protected overlap, merge and repeat verification in main.
