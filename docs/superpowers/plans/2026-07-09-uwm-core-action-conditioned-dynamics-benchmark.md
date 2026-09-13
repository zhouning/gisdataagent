# UWM Core Action-Conditioned Dynamics Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a full-admin UWM benchmark that tests the world-model core directly: whether action-conditioned dynamics over the 6817-transition real full-admin replay beats static, no-action-signal, and shuffled-action-signal baselines.

**Architecture:** Add a focused benchmark module that reuses `offline_world_model_policy` feature construction and ridge fitting, evaluates multiple feature variants on the same holdout split, and emits a claim-safe artifact. A builder script regenerates the ignored JSON artifact from the real full-admin planner replay.

**Tech Stack:** Python, NumPy, pytest, existing full-admin replay JSON under `data/uwm_public_proxy/chongqing_central`, `/Users/zhouning/gisdataagent/.venv/bin/pytest`.

---

## File Map

- Create `data_agent/uwm/core_action_conditioned_dynamics_benchmark.py`
  - Builds and validates the benchmark.
  - Reuses full-admin transition features from `offline_world_model_policy`.
  - Implements train-mean, no-action-signal, shuffled-action-signal and no-graph-degree variants.

- Create `data_agent/test_uwm_core_action_conditioned_dynamics_benchmark.py`
  - Tests the builder on the real full-admin replay.
  - Tests smoke/corrupt transition count downgrade.
  - Tests the generated artifact.

- Create `scripts/build_uwm_core_action_conditioned_dynamics_benchmark.py`
  - Reads the full-admin model-based graph-search replay.
  - Writes benchmark JSON and snapshot manifest under ignored `data/`.

---

### Task 1: Failing Benchmark Tests

**Files:**
- Create: `data_agent/test_uwm_core_action_conditioned_dynamics_benchmark.py`

- [ ] **Step 1: Write tests**

Write tests that import:

```python
from data_agent.uwm.core_action_conditioned_dynamics_benchmark import (
    UWM_CORE_ACTION_CONDITIONED_DYNAMICS_BENCHMARK_SCHEMA,
    build_uwm_core_action_conditioned_dynamics_benchmark,
    validate_uwm_core_action_conditioned_dynamics_benchmark,
)
```

Test expectations:

```python
benchmark["schema"] == UWM_CORE_ACTION_CONDITIONED_DYNAMICS_BENCHMARK_SCHEMA
benchmark["full_admin_scope_guard"]["passed"] is True
benchmark["full_admin_scope_guard"]["graph_node_count"] == 1017
benchmark["full_admin_scope_guard"]["graph_edge_count"] == 7932
benchmark["full_admin_scope_guard"]["available_action_count"] == 1137
benchmark["full_admin_scope_guard"]["transition_count"] == 6817
benchmark["holdout_summary"]["holdout_count"] == 973
benchmark["action_conditioning_gate"]["passed"] is True
benchmark["supported_claim"] == "core_action_conditioned_dynamics_beats_static_and_no_action_baselines"
benchmark["claim_boundary"]["max_claim_level"] == "bounded_support"
benchmark["observed_policy_outcome_superiority_claim"] is False
benchmark["empirical_superiority_claim"] is False
```

For each target in `reward`, `heat_risk_delta`, `air_pollution_exposure_delta`,
`service_accessibility_delta`, `equity_delta`, and `livability_delta`, assert:

```python
full_mae < train_mean_static_mae
full_mae < no_action_signal_mae
full_mae < shuffled_action_signal_mae
```

Also test corrupting `trajectory_dataset.transition_count` to `36` downgrades:

```python
supported_claim == "no_core_action_conditioned_dynamics_claim_supported"
claim_boundary.max_claim_level == "not_for_claim"
"full_admin_scope_guard_failed" in remaining_gates
```

- [ ] **Step 2: Verify RED**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/pytest data_agent/test_uwm_core_action_conditioned_dynamics_benchmark.py -q
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Commit tests**

```bash
git add data_agent/test_uwm_core_action_conditioned_dynamics_benchmark.py
git commit -m "test: define UWM core dynamics benchmark contract"
```

---

### Task 2: Benchmark Module

**Files:**
- Create: `data_agent/uwm/core_action_conditioned_dynamics_benchmark.py`

- [ ] **Step 1: Implement builder**

Implementation requirements:

- Import `numpy as np`.
- Reuse these package-local helpers from `offline_world_model_policy`:
  - `FEATURE_NAMES`
  - `TARGET_NAMES`
  - `_degree_by_unit`
  - `_fit_ridge_multi_output`
  - `_holdout_indices`
  - `_mae_by_target`
  - `_node_features_by_unit`
  - `_training_row`
- Build `X` and `Y` from `trajectory_dataset.transitions`.
- Use `holdout_stride=7` by default.
- Fit ridge with `ridge=0.001` by default.
- Variant columns:
  - action signal: feature names beginning with `action_`, plus `intensity`, `mask_heat_risk`, `mask_air_pollution`, `mask_service_gap`.
  - graph degree: `target_degree_norm`.
- Use deterministic shuffle offset `137` for action-signal columns.

Top-level output must include:

```python
schema
benchmark_id
created_at
experiment_scope
feature_names
target_names
full_admin_scope_guard
holdout_summary
variant_metrics
action_conditioning_gate
supported_claim
claim_boundary
remaining_gates
observed_policy_outcome_superiority_claim
empirical_superiority_claim
```

- [ ] **Step 2: Verify GREEN for builder tests**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/pytest data_agent/test_uwm_core_action_conditioned_dynamics_benchmark.py::test_core_action_conditioned_dynamics_benchmark_uses_full_admin_holdout_and_beats_ablation_baselines data_agent/test_uwm_core_action_conditioned_dynamics_benchmark.py::test_core_action_conditioned_dynamics_benchmark_rejects_smoke_sized_transition_scope -q
```

Expected: PASS for object-level tests.

- [ ] **Step 3: Commit module**

```bash
git add data_agent/uwm/core_action_conditioned_dynamics_benchmark.py
git commit -m "feat: benchmark UWM action-conditioned dynamics core"
```

---

### Task 3: Artifact Builder

**Files:**
- Create: `scripts/build_uwm_core_action_conditioned_dynamics_benchmark.py`

- [ ] **Step 1: Implement script**

Script reads:

```text
data/uwm_public_proxy/chongqing_central/data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json
```

Script writes:

```text
data/uwm_public_proxy/chongqing_central/core_action_conditioned_dynamics_benchmark_2026_07_09/uwm_core_action_conditioned_dynamics_benchmark.json
data/uwm_public_proxy/chongqing_central/core_action_conditioned_dynamics_benchmark_2026_07_09/snapshot_manifest.json
```

- [ ] **Step 2: Generate artifact**

Run:

```bash
env PYTHONPATH=. /Users/zhouning/gisdataagent/.venv/bin/python scripts/build_uwm_core_action_conditioned_dynamics_benchmark.py
```

Expected output includes:

```text
"graph_node_count": 1017
"transition_count": 6817
"holdout_count": 973
"supported_claim": "core_action_conditioned_dynamics_beats_static_and_no_action_baselines"
```

- [ ] **Step 3: Run focused tests**

```bash
/Users/zhouning/gisdataagent/.venv/bin/pytest data_agent/test_uwm_core_action_conditioned_dynamics_benchmark.py -q
```

Expected: all focused tests pass.

- [ ] **Step 4: Commit script**

```bash
git add scripts/build_uwm_core_action_conditioned_dynamics_benchmark.py
git commit -m "feat: regenerate UWM core dynamics benchmark"
```

Do not force-add ignored `data/` artifacts unless explicitly requested.

---

### Task 4: Full Verification

**Files:**
- No new source files expected.

- [ ] **Step 1: Run full UWM suite**

```bash
/Users/zhouning/gisdataagent/.venv/bin/pytest data_agent/test_uwm_*.py -q
```

Expected: all UWM tests pass.

- [ ] **Step 2: Report exact evidence**

Report:

- focused benchmark test count;
- full UWM suite count;
- full-admin counts;
- full model MAE versus train mean, no-action signal and shuffled-action signal;
- claim boundary remains bounded support only;
- observed policy and empirical superiority remain false.
