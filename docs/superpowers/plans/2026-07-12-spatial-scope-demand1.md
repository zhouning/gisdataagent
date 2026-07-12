# Spatial Scope Demand 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a verified but explicitly fragile spatial-scope and administrative-unit registry for shared traditional GIS and UWM use.

**Architecture:** A deterministic GIS builder extracts hierarchy, identity, geometry metadata and diagnostics from the existing GeoJSON and manifest. UWM consumes the resulting immutable identities and geometry references while topology and legal-boundary claims remain gated.

**Tech Stack:** Python, pytest, GeoJSON/JSON contracts, Starlette, React/TypeScript, Vite.

---

### Task 1: Define Spatial Registry
- [ ] Write failing tests for stable identities, hierarchy, extent and fragile claim boundaries.
- [ ] Implement the core spatial-scope registry.

### Task 2: Build Real Product
- [ ] Parse the 1,017-feature GeoJSON and manifest with diagnostics.
- [ ] Publish six files and independently verify counts and non-legal boundary claims.

### Task 3: Add Service API UI
- [ ] Add bundle service and six authenticated endpoints.
- [ ] Add a spatial-scope registry tab and pass frontend build.

### Task 4: Update Ledger Merge
- [ ] Promote demand 1 to evidence-bounded fragile registry.
- [ ] Verify, review protected overlap, commit and merge with `--no-ff`.
