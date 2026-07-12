# Development Control Demand 22 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a verified planning-rule catalog and DCR execution-readiness product without inventing site-specific legal parameters or approval decisions.

**Architecture:** Source-backed standards and rule modules are classified by authority and execution status. All site-specific DCR channels remain unavailable, while a fail-closed DCR+ gate blocks applicability, compliance and scheme-modification reasoning.

**Tech Stack:** Python, pytest, JSON contracts, Starlette, React/TypeScript, Vite.

**Design:** `docs/superpowers/specs/2026-07-12-development-control-demand22-design.md`

---

## Task 1: Define Rule and Gate Contracts
- [ ] Test rule classes, reference-only execution, unavailable DCR nulls, closed DCR+ mechanisms and forbidden legal fields.
- [ ] Implement module and commit.

## Task 2: Build Real Rule Asset Catalog
- [ ] Register source-backed standards and rule capabilities with authority limitations.
- [ ] Publish six files and independently verify.

## Task 3: Add Service, API and UI
- [ ] Implement six endpoints, tests and independent tab.
- [ ] Run frontend build.

## Task 4: Update Ledger and Merge
- [ ] Update demand 22 claim with tests.
- [ ] Verify, merge and repeat main validation.
