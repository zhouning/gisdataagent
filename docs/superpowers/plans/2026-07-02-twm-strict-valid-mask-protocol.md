# TWM Strict Valid Mask Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate prediction-time and evaluation-time valid masks in the TWM Dynamic World / public land-cover FLUS benchmark.

**Architecture:** Keep `case.valid` as the prediction-time mask for compatibility, add evaluation-mask helpers, and route metrics/report counts through evaluation masks. Public benchmark cases use local `prediction_valid` and `evaluation_valid` variables with explicit counts in reports.

**Tech Stack:** Python, NumPy, pytest, rasterio fixtures, existing TWM benchmark scripts.

---

### Task 1: Dynamic World / FLUS Case Mask Split

**Files:**
- Modify: `data_agent/test_twm_dynamic_world_flus_comparison.py`
- Modify: `scripts/run_twm_dynamic_world_flus_comparison.py`

- [x] **Step 1: Write failing test**

Add a synthetic region where the holdout frame has one nodata cell but train
start/end remain valid there. Assert `case.valid` still covers the train-valid
prediction domain, while `case_evaluation_valid(case)` excludes the holdout
nodata cell.

- [x] **Step 2: Verify RED**

Run:

```bash
./.venv/bin/python -m pytest -q data_agent/test_twm_dynamic_world_flus_comparison.py::test_select_cases_separates_prediction_and_evaluation_masks
```

Expected: fail before helper/field implementation.

Actual RED 2026-07-02:

```text
AssertionError: assert 3 == 4
```

- [x] **Step 3: Implement minimal runner changes**

Add optional `evaluation_valid` and `evaluation_target_counts` fields to
`FlusComparisonCase`, add helper accessors, build `case.valid` from
`transition_pair_valid_mask`, and route metrics through the evaluation mask.

- [x] **Step 4: Verify GREEN**

Run the same test and expect one pass.

Actual GREEN 2026-07-02:

```text
1 passed in 1.21s
```

### Task 2: Public Benchmark Runner Mask Split

**Files:**
- Modify: `data_agent/test_twm_dynamic_world_flus_comparison.py`
- Modify: `scripts/build_twm_public_landcover_benchmark.py`

- [x] **Step 1: Write failing test**

Create a three-frame public benchmark region with one holdout nodata cell and
assert report counts expose prediction/evaluation mask separation.

- [x] **Step 2: Verify RED**

Run:

```bash
./.venv/bin/python -m pytest -q data_agent/test_twm_dynamic_world_flus_comparison.py::test_public_benchmark_reports_prediction_and_evaluation_valid_masks
```

Expected: fail before report count implementation.

Actual RED 2026-07-02:

```text
KeyError: 'prediction_valid_cell_count'
```

- [x] **Step 3: Implement minimal public benchmark changes**

Use `transition_pair_valid_mask` for prediction/model inputs and `valid_mask`
for evaluation metrics/report counts. Add `prediction_valid_cell_count` and
`evaluation_valid_cell_count` to case reports.

- [x] **Step 4: Verify GREEN**

Run the same test and expect one pass.

Actual GREEN 2026-07-02:

```text
1 passed in 1.21s
```

### Task 3: Regression And Protocol Check

**Files:**
- No additional source changes.

- [x] **Step 1: Run focused tests**

```bash
./.venv/bin/python -m pytest -q data_agent/test_twm_dynamic_world_flus_comparison.py
```

Actual 2026-07-02:

```text
37 passed in 2.20s
```

- [x] **Step 2: Run FLUS/GeoSOS focused suite**

```bash
./.venv/bin/python -m pytest -q \
  data_agent/test_twm_flus_v24_simulation_optimization.py \
  data_agent/test_twm_dynamic_world_flus_comparison.py \
  data_agent/test_twm_dynamic_world_flus_seed_summary.py \
  data_agent/test_twm_dongguan_geosos_validation.py
```

Actual 2026-07-02:

```text
41 passed in 4.74s
```

- [x] **Step 3: Check current manifest mask deltas**

Run a manifest scan and confirm whether the current 100-case prediction and
evaluation masks differ. If they do not differ, previous 100-case scores remain
algorithmically comparable after protocol hardening.

Actual 2026-07-02:

```text
case_count: 100
diff_cases: 0
total_prediction_valid: 3182460
total_evaluation_valid: 3182460
total_pred_not_eval: 0
```

- [x] **Step 4: Recompute strict-mask 100-case reused-FLUS report**

Actual 2026-07-02:

```text
status: pass
case_count: 100
candidate_id: twm_topology_stability_guarded_persistence_forecast_demand
mean_change_fom: 0.205632
mean_change_f1: 0.338643
mean_overall_accuracy: 0.897029
mean_kappa: 0.761089
mean_macro_f1: 0.472769
mean_change_fom_delta_vs_flus: +0.054676
output: /private/tmp/twm_dynamic_world_flus_topology_strict_mask_verify_2026-07-02.json
```
