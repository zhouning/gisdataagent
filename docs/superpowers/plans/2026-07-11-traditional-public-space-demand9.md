# Traditional Public Space Demand 9 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a real, evidence-bounded traditional GIS product for customer demand 9 using strictly classified Chongqing public-space evidence while keeping quality, vitality, shade, seating, waterfront access and intervention effects explicitly unavailable.

**Architecture:** A focused public-space module applies an allow-list to the verified S1/S6 facility product, records all exclusion reasons, aggregates eligible spaces at evidence-supported county/district level and produces deterministic relative evidence-gap rankings. A real-product builder writes an immutable five-file bundle, an independent verifier prevents classification contamination and fabricated values, and a read-only service, API and traditional-livability panel expose the product without recomputation.

**Tech Stack:** Python, pytest, JSON product contracts, Starlette routes, React/TypeScript, Vite.

**Design:** `docs/superpowers/specs/2026-07-11-traditional-public-space-demand9-design.md`

---

## Task 1: Define Product and Channel Contracts

**Files:**
- Create: `data_agent/uwm/traditional_public_space.py`
- Test: `data_agent/test_traditional_public_space.py`

+- [ ] Write failing tests defining schema `traditional_livability.public_space_opportunity.v1`, all implemented/proxy/unavailable demand-9 channels, canonical space fields, null-only unavailable observations, deterministic ordering and claim boundaries.
+- [ ] Run `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_traditional_public_space.py` and confirm collection fails because the module is absent.
+- [ ] Implement constants, canonical source validation, channel readiness and product assembly with no ranking logic beyond empty placeholders.
+- [ ] Run the focused test and confirm PASS.
+- [ ] Commit with `feat: define public space product contracts`.
+
+## Task 2: Implement Strict Classification
+
+**Files:**
+- Modify: `data_agent/uwm/traditional_public_space.py`
+- Test: `data_agent/test_traditional_public_space_classification.py`
+
+- [ ] Write failing tests that include park, urban plaza, botanical garden, zoo, library, museum, science museum and explicit public sports venues.
+- [ ] Add failing negative tests for internet café, KTV, resort, cinema, private entertainment, generic leisure and commercial wellness labels.
+- [ ] Require every included and excluded row to expose `classification_decision` and `classification_reason`.
+- [ ] Run the focused test and confirm RED for missing classifier behaviour.
+- [ ] Implement exact normalized allow-list and deny-list rules; ambiguous records return `excluded_ambiguous`, never an eligible category.
+- [ ] Run Tasks 1–2 tests and confirm PASS.
+- [ ] Commit with `feat: classify evidence-bounded public spaces`.
+
+## Task 3: Build Deterministic Administrative Rankings
+
+**Files:**
+- Modify: `data_agent/uwm/traditional_public_space.py`
+- Test: `data_agent/test_traditional_public_space_ranking.py`
+
+- [ ] Write failing tests for zero core open space, zero total eligible space, lower category diversity, lower core count, lower total count and stable administrative identifier tie-breaking.
+- [ ] Assert missing lower-level accessibility is a blocker/reason and never a zero score.
+- [ ] Assert the rank field is `relative_public_space_evidence_gap_rank` and `authoritative_public_space_shortage` remains null.
+- [ ] Run RED.
+- [ ] Implement transparent lexicographic ranking and reason generation without quality or investment scores.
+- [ ] Run Tasks 1–3 tests and confirm PASS.
+- [ ] Commit with `feat: rank public space evidence gaps`.
+
+## Task 4: Build the Real Chongqing Product
+
+**Files:**
+- Create: `scripts/build_traditional_public_space_chongqing.py`
+- Test: `data_agent/test_build_traditional_public_space_chongqing.py`
+
+- [ ] Write failing fixture tests using an upstream `uwm.traditional_livability.facility_product.v1` payload with eligible, excluded and ambiguous records.
+- [ ] Require atomic `overview.json`, `spaces.json`, `admin_units.json`, `channel_readiness.json` and `map.json` with one deterministic bundle ID.
+- [ ] Require output summaries for source rows, eligible rows, excluded rows, exclusion reasons, category counts, administrative counts and fabricated value count.
+- [ ] Require direct CLI execution using explicit `--facility-product` and `--output-dir` arguments.
+- [ ] Run RED.
+- [ ] Implement source adaptation, population-unit district/county crosswalk, strict classification, deterministic bundle assembly and atomic writes.
+- [ ] Build `/private/tmp/traditional_public_space_chongqing_real` from `/private/tmp/traditional_livability_s6_s1_fulu_real/uwm_traditional_livability_s6_s1_facility_product.json`.
+- [ ] Record actual counts from execution rather than hard-coding the expected 317/57/241 source-class observations.
+- [ ] Run focused tests and confirm PASS.
+- [ ] Commit with `feat: build real Chongqing public space product`.
+
+## Task 5: Independently Verify the Real Product
+
+**Files:**
+- Create: `scripts/verify_traditional_public_space_chongqing.py`
+- Test: `data_agent/test_verify_traditional_public_space_chongqing.py`
+- Create after execution: `docs/reports/traditional_public_space_chongqing_verification_2026-07-11.md`
+
+- [ ] Write failing verifier tests for bundle mismatch, duplicate space IDs, missing source trace, deny-listed eligible records, unavailable numeric values, ranking instability and fabricated-value count.
+- [ ] Run RED.
+- [ ] Implement verifier logic independent from builder classification functions, with its own prohibited-label assertions.
+- [ ] Verify `/private/tmp/traditional_public_space_chongqing_real` and capture bundle ID, real category counts, exclusion counts, blockers and verification digest.
+- [ ] Write the report with explicit statements that the inventory is sampled and quality/use/comfort are unavailable.
+- [ ] Run verifier tests and confirm PASS.
+- [ ] Commit with `test: verify Chongqing public space product`.
+
+## Task 6: Add Read-Only Service and API
+
+**Files:**
+- Create: `data_agent/uwm/traditional_public_space_service.py`
+- Create: `data_agent/api/uwm_traditional_public_space_routes.py`
+- Modify: `data_agent/frontend_api.py`
+- Test: `data_agent/test_traditional_public_space_service.py`
+- Test: `data_agent/test_uwm_traditional_public_space_routes.py`
+
+- [ ] Write failing tests for deep copies, bundle consistency, category filtering, administrative lookup, missing records, authentication, route registration and missing-product 503 responses.
+- [ ] Run RED.
+- [ ] Implement loading from `UWM_TRADITIONAL_PUBLIC_SPACE_PATH`, defaulting to `data/uwm_public_proxy/chongqing_central/traditional_public_space_chongqing`.
+- [ ] Register overview, spaces, admin list/detail and map GET endpoints under `/api/uwm/traditional-livability/public-space`.
+- [ ] Run service/API tests and confirm PASS.
+- [ ] Commit with `feat: expose traditional public space APIs`.
+
+## Task 7: Add Traditional-Livability Frontend Panel
+
+**Files:**
+- Create: `frontend/src/components/datapanel/TraditionalLivabilityPublicSpacePanel.tsx`
+- Modify: `frontend/src/components/datapanel/TraditionalLivabilityTab.tsx`
+- Test: `data_agent/test_traditional_public_space_frontend_contract.py`
+
+- [ ] Write failing contract tests for all five API paths, `公共空间与场所营造（需求9）`, category composition, exclusion statistics, relative gap ranking, manual review candidates, `数据未就绪`, fabricated-value display and map handoff.
+- [ ] Add forbidden-text assertions for authoritative shortage, observed quality, observed vitality and verified policy effect claims.
+- [ ] Run RED.
+- [ ] Implement the panel with inventory KPIs, category/exclusion evidence, ranking table, blockers and source-backed map action.
+- [ ] Register the panel only in `TraditionalLivabilityTab.tsx`; do not modify protected `MapPanel.tsx` or `WorldModelV11Tab.tsx`.
+- [ ] Run the frontend contract test and `npm run build`.
+- [ ] Commit with `feat: add traditional public space panel`.
+
+## Task 8: Publish Product and Update Ledger
+
+**Files:**
+- Create: `data/uwm_public_proxy/chongqing_central/traditional_public_space_chongqing/overview.json`
+- Create: `data/uwm_public_proxy/chongqing_central/traditional_public_space_chongqing/spaces.json`
+- Create: `data/uwm_public_proxy/chongqing_central/traditional_public_space_chongqing/admin_units.json`
+- Create: `data/uwm_public_proxy/chongqing_central/traditional_public_space_chongqing/channel_readiness.json`
+- Create: `data/uwm_public_proxy/chongqing_central/traditional_public_space_chongqing/map.json`
+- Modify: `data_agent/uwm/ai_demand_implementation_ledger.py`
+- Modify: `data_agent/test_uwm_ai_demand_implementation_ledger.py`
+
+- [ ] Copy only the independently verified deterministic bundle into the repository product path.
+- [ ] Write a failing ledger test requiring demand 9 status `implemented_evidence_bounded`, output `traditional_public_space_product`, maximum claim `public_space_inventory_distribution_and_relative_evidence_gap` and real artifact checks.
+- [ ] Preserve blockers for public access, quality, vitality, shade, seating, waterfront access, safety, accessibility and intervention effects.
+- [ ] Run ledger tests and confirm PASS.
+- [ ] Commit with `feat: register verified public space demand`.
+
+## Task 9: Final Verification and Safe Merge
+
+**Files:**
+- Modify only if evidence requires: `docs/reports/traditional_public_space_chongqing_verification_2026-07-11.md`
+
+- [ ] Run all demand-9 Python tests and affected traditional-livability frontend/API tests.
+- [ ] Run the independent verifier against the repository-published bundle.
+- [ ] Run `npm run build` in `frontend`, using an isolated npm cache if dependencies are not installed.
+- [ ] Run `git diff --check` and inspect `git diff --name-only feat/v12-extensible-platform..HEAD`.
+- [ ] Confirm `data_agent/api/world_model_v11_routes.py`, `frontend/src/components/MapPanel.tsx`, `frontend/src/components/datapanel/WorldModelV11Tab.tsx`, `data_agent/paper58_runtime/` and `data_agent/paper58_visualization.py` are untouched.
+- [ ] Merge with `git merge --no-ff feat/traditional-public-space-demand9` from `/Users/zhouning/gisdataagent`; do not reset, clean or stash the main worktree.
+- [ ] Re-run focused tests and the independent verifier in the merged main worktree.
+
