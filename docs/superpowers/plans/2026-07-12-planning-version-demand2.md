# Planning Version Demand 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a verified planning/parcel asset inventory and fail-closed version-lineage readiness product.

**Architecture:** The builder extracts selected real audit profiles into normalized version assets. Missing approval, effective-period and successor evidence keeps all temporal and UWM baseline mechanisms closed.

**Tech Stack:** Python, pytest, JSON contracts, Starlette, React/TypeScript, Vite.

---

### Task 1: Define Version Contracts
- [ ] Write failing tests for asset classes, unavailable version channels and closed temporal/UWM gates.
- [ ] Implement the core planning-version product.

### Task 2: Build Audit Product
- [ ] Parse selected real planning ZIP audit profiles.
- [ ] Publish six files and independently verify no false current-version claim.

### Task 3: Add Service API UI
- [ ] Add bundle service and six authenticated endpoints.
- [ ] Add planning-version tab and pass frontend build.

### Task 4: Update Ledger Merge
- [ ] Promote demand 2 to evidence-bounded asset/version readiness.
- [ ] Verify, review protected overlap, commit and merge with `--no-ff`.
