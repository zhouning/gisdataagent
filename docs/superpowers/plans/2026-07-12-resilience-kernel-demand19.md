# Resilience Kernel Demand 19 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a verified resilience UWM foundation with observed state, provenance-backed spatial graph, seven evidence gates and a fail-closed rollout that never fabricates hazard, response or recovery dynamics.

**Architecture:** Static source adapters bind the verified administrative graph, network/facility/environment context and demand-25 dependency chain into immutable state and graph products. A resilience Kernel contract exposes disturbance/action/transition interfaces, but the production rollout remains closed until mechanism-specific evidence and held-out calibration pass.

**Tech Stack:** Python, pytest, JSON contracts, Starlette, React/TypeScript, Vite.

**Design:** `docs/superpowers/specs/2026-07-12-resilience-kernel-demand19-design.md`

---

## Task 1: Define State and Kernel Contracts
- [ ] Test schema, node contract, seven gates, closed mechanisms, mandatory flags and forbidden fields.
- [ ] Implement `data_agent/uwm/resilience_kernel.py`; run PASS and commit.

## Task 2: Enforce Graph Provenance
- [ ] Test edge provenance, null propagation parameters and rejection of inferred coefficients.
- [ ] Implement graph validation and commit.

## Task 3: Build Fail-Closed Rollout
- [ ] Test no future trajectory, loss, response effectiveness, recovery time or intervention benefit is returned.
- [ ] Implement baseline-context rollout and blocker trace; commit.

## Task 4: Build Real Chongqing Bundle
- [ ] Adapt verified administrative graph, network/facility/environment context and roadmap dependency chain.
- [ ] Publish seven immutable files and independently verify them.
- [ ] Record real node/edge/gate counts and digest; commit.

## Task 5: Add Service and API
- [ ] Implement read-only service and seven authenticated endpoints with bundle checks and tests.
- [ ] Commit.

## Task 6: Add Resilience World Model Tab
- [ ] Display state/graph coverage, gates, closed mechanisms, dependency chain and claim boundaries.
- [ ] Run frontend build and commit.

## Task 7: Update Ledger and Merge
- [ ] Update demand 19 status and maximum claim with tests.
- [ ] Run focused tests, verifier and build.
- [ ] Check protected overlap, merge and repeat main verification.
