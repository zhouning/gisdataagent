# UWM Environmental Dynamics Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-evidence UWM environmental dynamics capability that evolves a real Chongqing environmental state through time, applies controlled green-infrastructure proxy actions, propagates supported spatial effects, and exposes counterfactual trajectories without claiming unsupported causal benefits.

**Architecture:** Add a focused `environmental_kernel` package that composes existing TAP temporal dynamics, environmental evidence bundles, canonical state/action contracts and channel-isolated spillover logic. A Chongqing product builder binds real artifacts and fails closed where action-response evidence is missing; a service/API/frontend layer exposes the same immutable bundle and its claim boundary without recomputing the kernel.

**Tech Stack:** Python 3.11+, pytest, existing UWM JSON contracts, Shapely/GeoPandas where geometry is already available, FastAPI-style Flask route patterns used in `data_agent/api`, React/TypeScript, Vite.

**Design:** `docs/superpowers/specs/2026-07-11-uwm-environmental-dynamics-kernel-design.md`

---

## File Structure

- `data_agent/uwm/environmental_kernel/contracts.py`: schema constants, support levels and fail-closed validators.
- `data_agent/uwm/environmental_kernel/state.py`: canonical environmental state graph and stable digests.
- `data_agent/uwm/environmental_kernel/actions.py`: actor-bound green-infrastructure proxy actions and S2 binding.
- `data_agent/uwm/environmental_kernel/evidence_gate.py`: independent readiness gates per transition mechanism.
- `data_agent/uwm/environmental_kernel/dynamics.py`: temporal, direct-action and spatial channel composition.
- `data_agent/uwm/environmental_kernel/rollout.py`: paired baseline/intervention trajectories and invariants.
- `data_agent/uwm/environmental_kernel/product.py`: immutable real-scene product assembly and verification summary.
- `data_agent/uwm/environmental_kernel/service.py`: product loading, actor isolation and rollout execution.
- `scripts/build_uwm_environmental_kernel_chongqing.py`: build the real Chongqing product.
- `scripts/verify_uwm_environmental_kernel_chongqing.py`: independently verify fabricated-value count, digests and claim boundaries.
- `data_agent/api/uwm_livability_routes.py`: expose scene, gate, rollout and map endpoints using the existing livability blueprint; if the repository uses a different registered route file at implementation time, modify that registered file and update its existing route tests.
- `frontend/src/components/datapanel/UwmLivabilityEnvironmentalKernelPanel.tsx`: environmental dynamics UI.
- Existing UWM livability tab file discovered by `rg "UWM.*宜居|livability" frontend/src/components/datapanel`: register the new panel without changing unrelated Paper58/TWM files.

## Task 1: Define Environmental Kernel Contracts

**Files:**
- Create: `data_agent/uwm/environmental_kernel/__init__.py`
- Create: `data_agent/uwm/environmental_kernel/contracts.py`
- Test: `data_agent/test_uwm_environmental_kernel_contracts.py`

- [ ] **Step 1: Write failing schema and validation tests**

Create tests that import `validate_environmental_state`, `validate_environmental_action`, `validate_rollout_result`, and constants for `observed_calibrated`, `observed_context`, `bounded_proxy`, and `unavailable`. Assert rejection of missing evidence bundle IDs, guessed zero values carrying `unavailable`, unknown support levels, causal-effect claims, and rollout results lacking `not_a_causal_effect_estimate=True`.

- [ ] **Step 2: Run the RED test**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_uwm_environmental_kernel_contracts.py
```

Expected: FAIL because `data_agent.uwm.environmental_kernel` does not exist.

- [ ] **Step 3: Implement minimal immutable contracts**

Define schemas `uwm.environmental_state.v1`, `uwm.environmental_action.v1`, `uwm.environmental_evidence_gate.v1`, and `uwm.environmental_rollout.v1`. Validators return `{"valid": bool, "errors": list[str]}` and explicitly reject `causal_effect_estimate=True`, absent per-field support, and unavailable effects represented numerically.

- [ ] **Step 4: Run GREEN**

Run the Task 1 test and expect all tests to pass.

- [ ] **Step 5: Commit**

```bash
git add data_agent/uwm/environmental_kernel data_agent/test_uwm_environmental_kernel_contracts.py
git commit -m "feat: define environmental kernel contracts"
```

## Task 2: Build Canonical Environmental State Graphs

**Files:**
- Create: `data_agent/uwm/environmental_kernel/state.py`
- Test: `data_agent/test_uwm_environmental_kernel_state.py`

- [ ] **Step 1: Write failing deterministic-state tests**

Use a three-node fixture with `grid_adjacent_grid` and `grid_within_admin` edges. Assert canonical ordering, stable SHA-256 digest under input reordering, null preservation for unavailable PM2.5 or temperature, per-field support levels, rejection of duplicate nodes, dangling edges, invalid fractions, and name-based geography crosswalk fields.

- [ ] **Step 2: Run RED**

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_uwm_environmental_kernel_state.py
```

Expected: FAIL on missing state builder.

- [ ] **Step 3: Implement `build_environmental_state`**

Return a canonical deep-copied state with sorted nodes/edges, `snapshot_digest`, `missing_fields`, source dataset IDs and claim boundary. Accept only `grid_adjacent_grid`, `grid_within_admin`, verified `admin_adjacent_admin`, and separately labelled geographic-similarity edges.

- [ ] **Step 4: Run GREEN and contract regression**

Run Task 1 and Task 2 tests together; expect all pass.

- [ ] **Step 5: Commit**

```bash
git add data_agent/uwm/environmental_kernel/state.py data_agent/test_uwm_environmental_kernel_state.py
git commit -m "feat: build canonical environmental states"
```

## Task 3: Implement Controlled Environmental Actions

**Files:**
- Create: `data_agent/uwm/environmental_kernel/actions.py`
- Test: `data_agent/test_uwm_environmental_kernel_actions.py`

- [ ] **Step 1: Write failing action tests**

Cover `no_intervention` and `green_infrastructure_change`. Assert server actor binding, stable action digest, stale state rejection, unknown target rejection, declared-area-over-geometry rejection, vegetation fraction outside `[0,1]` rejection, unsupported action type rejection, and mandatory valid S2 transition digest for `convert_declared_parcel_to_green_proxy`.

- [ ] **Step 2: Run RED**

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_uwm_environmental_kernel_actions.py
```

Expected: FAIL because action functions are absent.

- [ ] **Step 3: Implement actor-bound action creation**

Implement `bind_environmental_action(request, state, actor, s2_artifact=None)` and return an immutable action. Ignore any client-supplied trusted actor field and use only the service actor. Include state, geometry, evidence and optional S2 digests in the action digest.

- [ ] **Step 4: Run GREEN and regression**

Run Tasks 1–3 tests; expect all pass.

- [ ] **Step 5: Commit**

```bash
git add data_agent/uwm/environmental_kernel/actions.py data_agent/test_uwm_environmental_kernel_actions.py
git commit -m "feat: validate environmental intervention actions"
```

## Task 4: Add Independent Evidence Gates

**Files:**
- Create: `data_agent/uwm/environmental_kernel/evidence_gate.py`
- Test: `data_agent/test_uwm_environmental_kernel_evidence_gate.py`

- [ ] **Step 1: Write failing mechanism-gate tests**

Build fixtures where PM2.5 temporal holdout passes but green-action PM2.5 calibration is absent. Assert temporal readiness becomes `observed_calibrated` while direct action response remains `unavailable`; temperature and vegetation channels are evaluated independently; observed context never promotes itself to action calibration; blockers and maximum claim level are deterministic.

- [ ] **Step 2: Run RED**

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_uwm_environmental_kernel_evidence_gate.py
```

Expected: FAIL on missing gate builder.

- [ ] **Step 3: Implement `build_environmental_evidence_gate`**

Return readiness for state observation, temporal calibration, direct action response, spatial propagation, forcing alignment and counterfactual comparison. Require explicit coefficient source and calibration artifact for `observed_calibrated`; otherwise use `bounded_proxy` only when a declared bound exists, else `unavailable`.

- [ ] **Step 4: Run GREEN and regression**

Run Tasks 1–4 tests; expect all pass.

- [ ] **Step 5: Commit**

```bash
git add data_agent/uwm/environmental_kernel/evidence_gate.py data_agent/test_uwm_environmental_kernel_evidence_gate.py
git commit -m "feat: gate environmental transition evidence"
```

## Task 5: Compose Temporal, Direct and Spatial Dynamics

**Files:**
- Create: `data_agent/uwm/environmental_kernel/dynamics.py`
- Test: `data_agent/test_uwm_environmental_kernel_dynamics.py`

- [ ] **Step 1: Write failing dynamics tests**

Assert `step_environmental_state` returns three separate contributions: `temporal`, `direct_action`, and `spatial_propagation`. Verify TAP temporal output can change PM2.5 without creating an action benefit; deterministic vegetation edit affects only target nodes; unavailable temperature or PM2.5 action response remains null; pollution, thermal and vegetation propagation channels use distinct coefficient sources; a disabled channel emits no numeric delta.

- [ ] **Step 2: Run RED**

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_uwm_environmental_kernel_dynamics.py
```

Expected: FAIL on missing dynamics composer.

- [ ] **Step 3: Implement hybrid step composition**

Reuse the callable contract in `data_agent/uwm/tap_external_dynamics.py` for temporal PM2.5 when its gate passes. Adapt the message shape from `data_agent/uwm/spatial_spillover_kernel.py`, but keep coefficients and messages isolated by effect channel. Do not add unavailable values to state and never substitute zero.

- [ ] **Step 4: Run GREEN plus existing kernel regressions**

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_uwm_environmental_kernel_dynamics.py \
  data_agent/test_uwm_tap_external_dynamics.py \
  data_agent/test_uwm_data_calibrated_spatial_spillover_kernel.py
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add data_agent/uwm/environmental_kernel/dynamics.py data_agent/test_uwm_environmental_kernel_dynamics.py
git commit -m "feat: compose environmental hybrid dynamics"
```

## Task 6: Execute Paired Counterfactual Rollouts

**Files:**
- Create: `data_agent/uwm/environmental_kernel/rollout.py`
- Test: `data_agent/test_uwm_environmental_kernel_rollout.py`

- [ ] **Step 1: Write failing rollout-invariant tests**

Assert baseline and intervention share initial digest, graph version, horizon, forcing digest and random seed. Verify per-step mechanism contributions, immutable actions, counterfactual deltas only for jointly available values, uncertainty envelopes, mismatch rejection, and `not_a_causal_effect_estimate=True`.

- [ ] **Step 2: Run RED**

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_uwm_environmental_kernel_rollout.py
```

Expected: FAIL on missing rollout function.

- [ ] **Step 3: Implement `run_environmental_counterfactual`**

Execute `no_intervention` and the bound intervention from the same state and forcing package for an explicit horizon. Return trajectories, supported deltas, mechanism contributions, propagation messages, evidence gate, blockers and stable rollout digest.

- [ ] **Step 4: Run GREEN and Tasks 1–6 regression**

Run all `data_agent/test_uwm_environmental_kernel_*.py` tests and expect all pass.

- [ ] **Step 5: Commit**

```bash
git add data_agent/uwm/environmental_kernel/rollout.py data_agent/test_uwm_environmental_kernel_rollout.py
git commit -m "feat: run environmental counterfactual trajectories"
```

## Task 7: Build and Verify the Real Chongqing Product

**Files:**
- Create: `data_agent/uwm/environmental_kernel/product.py`
- Create: `scripts/build_uwm_environmental_kernel_chongqing.py`
- Create: `scripts/verify_uwm_environmental_kernel_chongqing.py`
- Test: `data_agent/test_build_uwm_environmental_kernel_chongqing.py`
- Test: `data_agent/test_verify_uwm_environmental_kernel_chongqing.py`
- Create after execution: `docs/reports/uwm_environmental_kernel_chongqing_verification_2026-07-11.md`

- [ ] **Step 1: Write failing product-builder tests**

Use temporary real-format fixtures matching existing environmental evidence artifacts. Assert atomic files `scene.json`, `evidence_gate.json`, `current_rollout.json`, and `map.json`; matching bundle IDs; real source IDs and dates; no NaN; zero fabricated values; and fail-closed intervention outcomes when action-response evidence is absent.

- [ ] **Step 2: Run RED**

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_build_uwm_environmental_kernel_chongqing.py \
  data_agent/test_verify_uwm_environmental_kernel_chongqing.py
```

Expected: FAIL because scripts and product assembly are absent.

- [ ] **Step 3: Implement product discovery and atomic build**

Bind existing environmental fusion, TAP temporal calibration/holdout, aligned geometry and forcing artifacts discovered under the configured source root. Record every missing input as a blocker. Generate a baseline rollout and only a bounded or closed intervention rollout according to the evidence gate.

- [ ] **Step 4: Build the actual product in `/private/tmp`**

```bash
/Users/zhouning/gisdataagent/.venv/bin/python scripts/build_uwm_environmental_kernel_chongqing.py \
  --source-root /Users/zhouning/gisdataagent \
  --output-dir /private/tmp/uwm_environmental_kernel_chongqing_real
```

Expected: exit `0` for a valid product even when intervention outcomes are closed, with explicit blockers and no fabricated values.

- [ ] **Step 5: Verify and write the report**

Run the verifier against the real product. Copy its evidence summary, bundle digest, actual source dates, supported channels and blockers into `docs/reports/uwm_environmental_kernel_chongqing_verification_2026-07-11.md`.

- [ ] **Step 6: Run GREEN and commit**

```bash
git add data_agent/uwm/environmental_kernel/product.py \
  scripts/build_uwm_environmental_kernel_chongqing.py \
  scripts/verify_uwm_environmental_kernel_chongqing.py \
  data_agent/test_build_uwm_environmental_kernel_chongqing.py \
  data_agent/test_verify_uwm_environmental_kernel_chongqing.py \
  docs/reports/uwm_environmental_kernel_chongqing_verification_2026-07-11.md
git commit -m "feat: build real Chongqing environmental kernel product"
```

## Task 8: Add Product Service and API

**Files:**
- Create: `data_agent/uwm/environmental_kernel/service.py`
- Test: `data_agent/test_uwm_environmental_kernel_service.py`
- Modify: registered UWM livability route module discovered with `rg "livability" data_agent/api`
- Test: corresponding existing route test plus `data_agent/test_uwm_environmental_kernel_routes.py`

- [ ] **Step 1: Write failing service and route tests**

Assert bundle mismatch rejection, deep-copy responses, actor isolation, stale scene rejection, unsupported action rejection, and endpoints for scene, evidence gate, rollout and map. Assert POST actor comes from authenticated request context rather than body and errors preserve blockers without upgrading claims.

- [ ] **Step 2: Run RED**

Run the new service and route tests; expect missing service/endpoints.

- [ ] **Step 3: Implement product-backed service**

Load immutable product files from `UWM_ENVIRONMENTAL_KERNEL_PATH`. `run()` binds the actor, validates the request against the stored scene, executes the same kernel contracts and returns a new rollout without mutating the built product.

- [ ] **Step 4: Register API endpoints**

Add:

```text
GET  /api/uwm/livability/environmental-kernel/scene
GET  /api/uwm/livability/environmental-kernel/evidence-gate
POST /api/uwm/livability/environmental-kernel/rollout
GET  /api/uwm/livability/environmental-kernel/map
```

Return `409` for stale/conflicting evidence and `400` for invalid actions.

- [ ] **Step 5: Run GREEN and commit**

Run service, route and existing UWM livability route regressions, then commit with:

```bash
git commit -m "feat: expose environmental kernel APIs"
```

## Task 9: Add the UWM Environmental Dynamics Panel

**Files:**
- Create: `frontend/src/components/datapanel/UwmLivabilityEnvironmentalKernelPanel.tsx`
- Modify: existing UWM livability tab component discovered before editing
- Test: `data_agent/test_uwm_environmental_kernel_frontend_contract.py`

- [ ] **Step 1: Write failing frontend contract tests**

Require all four API paths, observed period, evidence gate, action acknowledgement, baseline/intervention trajectories, temporal/direct/spatial mechanism labels, blockers, map event `__handleMapUpdate`, `bounded_proxy`, `unavailable`, and `not_a_causal_effect_estimate`. Forbid `因果效果`, `权威降温收益`, `保证降低`, and static-only claims presented as rollout.

- [ ] **Step 2: Run RED**

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_uwm_environmental_kernel_frontend_contract.py
```

Expected: FAIL because panel is absent.

- [ ] **Step 3: Implement the panel**

Display scene/evidence first. Allow only supported action types and require acknowledgement that proxy deltas are not causal estimates. Plot or table baseline/intervention values only when jointly available; render unavailable channels as unavailable, not zero. Send stored map payload to `window.__handleMapUpdate`.

- [ ] **Step 4: Run frontend tests and production build**

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_uwm_environmental_kernel_frontend_contract.py \
  data_agent/test_uwm_livability_world_model_frontend_contract.py
cd frontend && npm run build
```

Expected: tests pass and Vite production build exits `0`; existing bundle-size warnings may remain documented.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/datapanel/UwmLivabilityEnvironmentalKernelPanel.tsx \
  frontend/src/components/datapanel/<discovered-uwm-livability-tab>.tsx \
  data_agent/test_uwm_environmental_kernel_frontend_contract.py
git commit -m "feat: add UWM environmental dynamics panel"
```

## Task 10: Complete Integrated Verification and Safe Merge

**Files:**
- Modify only if verification finds a task-related defect.

- [ ] **Step 1: Run focused backend suite**

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_uwm_environmental_kernel_*.py \
  data_agent/test_build_uwm_environmental_kernel_chongqing.py \
  data_agent/test_verify_uwm_environmental_kernel_chongqing.py \
  data_agent/test_uwm_tap_external_dynamics.py \
  data_agent/test_uwm_environmental_fusion.py \
  data_agent/test_uwm_data_calibrated_spatial_spillover_kernel.py
```

Expected: all pass.

- [ ] **Step 2: Run API and frontend regression**

Run the new API/frontend tests and existing UWM livability route/frontend tests. Run `npm run build` from `frontend`.

- [ ] **Step 3: Rebuild and independently verify the real product**

Delete only the `/private/tmp/uwm_environmental_kernel_chongqing_real` product directory, rebuild it, run the verifier and confirm the documented digest and fabricated-value count.

- [ ] **Step 4: Check branch cleanliness and protected main-tree edits**

Confirm the feature worktree is clean. Before merge, record `git -C /Users/zhouning/gisdataagent status --short`, especially Paper58/TWM files. Do not run `reset`, `clean`, stash or checkout over those files.

- [ ] **Step 5: Merge with a merge commit and rerun verification on main**

Merge the feature branch into `feat/v12-extensible-platform` using `git merge --no-ff`. Rerun focused pytest and `npm run build`, then confirm the pre-existing Paper58/TWM status entries remain present.

