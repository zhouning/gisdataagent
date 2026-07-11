# Traditional Social Infrastructure and Public Service Demands 12/21 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans and implement each task with TDD.

**Goal:** Build one real, evidence-bounded traditional GIS facility/service product with separate demand-12 and demand-21 views, without fabricating capacity, lifecycle, service standards, future demand or policy effects.

**Architecture:** A shared product builder consumes existing S1/S6 facility evidence and demand-8 accessibility artifacts, normalizes source-backed facilities, creates deterministic administrative view metrics and relative-gap rankings, and writes an immutable five-file bundle. A verifier, read-only service, Starlette routes and a two-view traditional-livability panel expose the verified product. The AI demand ledger is upgraded only after real artifact verification.

**Tech Stack:** Python, pytest, existing JSON product contracts, Starlette routes, React/TypeScript, Vite.

**Design:** `docs/superpowers/specs/2026-07-11-traditional-social-public-service-demands12-21-design.md`

---

## Task 1: Define Shared Product Contracts

**Files:**
- Create: `data_agent/uwm/traditional_social_public_service.py`
- Test: `data_agent/test_traditional_social_public_service.py`

- [ ] Write failing tests for schemas, both view definitions, complete channel readiness, null-only unavailable values, canonical ordering and deterministic identifiers.
- [ ] Run RED and confirm the module is absent.
- [ ] Implement constants, source validation, canonical facility rows and claim boundaries.
- [ ] Run focused tests and commit.

## Task 2: Build View Classification and Rankings

**Files:**
- Modify: `data_agent/uwm/traditional_social_public_service.py`
- Test: `data_agent/test_traditional_social_public_service_ranking.py`

- [ ] Write failing tests for demand-12 and demand-21 membership, unmapped categories, category diversity, zero-facility priority, missing-accessibility handling, stable ties and reason traces.
- [ ] Run RED.
- [ ] Implement deterministic view aggregation and relative evidence-gap rankings without capacity or statutory deficit claims.
- [ ] Run Tasks 1–2 tests and commit.

## Task 3: Build Real Chongqing Bundle

**Files:**
- Create: `scripts/build_traditional_social_public_service_chongqing.py`
- Test: `data_agent/test_build_traditional_social_public_service_chongqing.py`

- [ ] Write failing tests for explicit source-root discovery, reuse of S1/S6/demand-8 artifacts, five atomic files, shared bundle ID, unique facilities and zero fabricated unavailable values.
- [ ] Run RED.
- [ ] Implement artifact loading, canonical normalization, administrative joins, deterministic bundle assembly and atomic writes.
- [ ] Build a real product under `/private/tmp/traditional_social_public_service_chongqing_real`.
- [ ] Record actual input and output counts without hard-coded expected Chongqing values.
- [ ] Run focused tests and commit.

## Task 4: Independently Verify Product

**Files:**
- Create: `scripts/verify_traditional_social_public_service_chongqing.py`
- Test: `data_agent/test_verify_traditional_social_public_service_chongqing.py`
- Create after execution: `docs/reports/traditional_social_public_service_chongqing_verification_2026-07-11.md`

- [ ] Write failing tests for bundle mismatch, duplicate IDs, missing source trace, illegal unavailable numeric values, ranking instability and forbidden authoritative claims.
- [ ] Run RED.
- [ ] Implement a verifier independent from builder internals.
- [ ] Verify the real bundle and write counts, blockers, bundle ID and verification digest to the report.
- [ ] Run focused tests and commit.

## Task 5: Add Read-Only Service and API

**Files:**
- Create: `data_agent/uwm/traditional_social_public_service_service.py`
- Create: `data_agent/api/uwm_traditional_social_public_service_routes.py`
- Modify: `data_agent/frontend_api.py`
- Test: `data_agent/test_traditional_social_public_service_service.py`
- Test: `data_agent/test_uwm_traditional_social_public_service_routes.py`

- [ ] Write failing tests for deep-copy responses, bundle consistency, view filtering, admin lookup, authentication, route registration and product-unavailable responses.
- [ ] Run RED.
- [ ] Implement loading from `UWM_TRADITIONAL_SOCIAL_PUBLIC_SERVICE_PATH` with a verified default product path.
- [ ] Register overview, facilities, admin list/detail and map endpoints.
- [ ] Run service/API tests and commit.

## Task 6: Add Two-View Traditional Panel

**Files:**
- Create: `frontend/src/components/datapanel/TraditionalLivabilitySocialPublicServicePanel.tsx`
- Modify: `frontend/src/components/datapanel/TraditionalLivabilityTab.tsx`
- Test: `data_agent/test_traditional_social_public_service_frontend_contract.py`

- [ ] Write failing contract tests for both view selectors, API paths, readiness, blockers, relative-gap wording and no capacity/overload claims.
- [ ] Run RED.
- [ ] Implement inventory, category, administrative ranking, map handoff and unavailable-channel rendering.
- [ ] Run contract tests and frontend build, then commit.

## Task 7: Publish Product and Update Ledger

**Files:**
- Create: `data/uwm_public_proxy/chongqing_central/traditional_social_public_service_chongqing/overview.json`
- Create: `data/uwm_public_proxy/chongqing_central/traditional_social_public_service_chongqing/facilities.json`
- Create: `data/uwm_public_proxy/chongqing_central/traditional_social_public_service_chongqing/admin_units.json`
- Create: `data/uwm_public_proxy/chongqing_central/traditional_social_public_service_chongqing/channel_readiness.json`
- Create: `data/uwm_public_proxy/chongqing_central/traditional_social_public_service_chongqing/map.json`
- Modify: `data_agent/uwm/ai_demand_implementation_ledger.py`
- Test: `data_agent/test_ai_demand_implementation_ledger.py`

- [ ] Copy only the independently verified deterministic bundle into the repository product path.
- [ ] Write failing ledger tests requiring real artifacts for demands 12 and 21 and preserving all evidence blockers.
- [ ] Upgrade both demands to `implemented_evidence_bounded` with exact artifact references.
- [ ] Run ledger tests and commit.

## Task 8: Final Verification and Safe Merge

**Files:**
- Modify only if evidence requires: `docs/reports/traditional_social_public_service_chongqing_verification_2026-07-11.md`

- [ ] Run all new Python tests.
- [ ] Run affected traditional-livability route and frontend contract tests.
- [ ] Run the independent verifier against the published bundle.
- [ ] Run `npm run build` in `frontend`.
- [ ] Inspect git diff and confirm protected Paper58/TWM files are untouched.
- [ ] Merge the feature branch into `feat/v12-extensible-platform` without reset, clean or stash.

