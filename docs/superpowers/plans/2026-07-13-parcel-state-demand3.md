# Parcel State Demand 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a verified land-use schema audit and fail-closed parcel/UWM state readiness product.

**Architecture:** Audit-backed source assets and field capabilities are separated from unavailable feature observations. Traditional GIS and UWM gates remain closed until source features and authoritative version metadata are materialized.

**Tech Stack:** Python, pytest, JSON contracts, Starlette, React/TypeScript, Vite.

---

### Task 1: Define Parcel State Contract
- [ ] Write failing tests for unavailable state channels and closed traditional/UWM mechanisms.
- [ ] Implement the core parcel-state readiness product.

### Task 2: Build Audit Product
- [ ] Extract DLTB and supporting ledger/planning audit evidence.
- [ ] Publish six files and independently verify zero fabricated state statistics.

### Task 3: Add Service API UI
- [ ] Add service and six authenticated endpoints.
- [ ] Add parcel-state tab and pass frontend build.

### Task 4: Update Ledger Merge
- [ ] Promote demand 3 to evidence-bounded state readiness.
- [ ] Verify, review protected overlap, commit and merge with `--no-ff`.
