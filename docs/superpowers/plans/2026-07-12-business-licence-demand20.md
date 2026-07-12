# Business Licence Demand 20 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a verified business-POI and authoritative-licence readiness product without inferring legal entity, active operation, employment or economic performance.

**Architecture:** A demand-14 adapter reuses only business-activity POI records and district IDs. Separate licence/lifecycle contracts remain unavailable, and a fail-closed UWM gate blocks entity lifecycle and policy-response predictions.

**Tech Stack:** Python, pytest, JSON contracts, Starlette, React/TypeScript, Vite.

**Design:** `docs/superpowers/specs/2026-07-12-business-licence-demand20-design.md`

---

## Task 1: Define Product and Boundary Contracts
- [ ] Test POI-only fields, unavailable licence channels, closed lifecycle mechanisms and forbidden economic fields.
- [ ] Implement product module and commit.

## Task 2: Build Real Demand-14 Adapter
- [ ] Publish seven files from verified business-activity evidence and independently verify counts and boundaries.

## Task 3: Add Service, API and UI
- [ ] Implement seven endpoints, focused tests and independent tab.
- [ ] Run frontend build.

## Task 4: Update Ledger and Merge
- [ ] Update demand 20 status and claim with tests.
- [ ] Verify, merge and repeat main validation.
