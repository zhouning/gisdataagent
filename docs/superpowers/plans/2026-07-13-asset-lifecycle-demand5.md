# Asset Lifecycle Demand 5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a cross-product asset catalog and fail-closed lifecycle/UWM state readiness product.

**Architecture:** Existing verified products are referenced rather than copied or naively merged. Entity-resolution, lifecycle and UWM mechanisms stay closed until authoritative asset records and temporal events are available.

**Tech Stack:** Python, pytest, JSON contracts, Starlette, React/TypeScript, Vite.

---

### Task 1: Define Asset Contract
- [ ] Write failing tests for overlap-aware cataloging, unavailable lifecycle channels and closed UWM mechanisms.
- [ ] Implement the core asset lifecycle product.

### Task 2: Build Source Catalog
- [ ] Register verified source products and record-count semantics.
- [ ] Publish six files and independently verify no unique-asset or condition claims.

### Task 3: Add Service API UI
- [ ] Add service and six authenticated endpoints.
- [ ] Add asset-lifecycle tab and pass frontend build.

### Task 4: Update Ledger Merge
- [ ] Promote demand 5 to evidence-bounded readiness.
- [ ] Verify, review protected overlap, commit and merge with `--no-ff`.
