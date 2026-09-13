# TWM Topology-Stability Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a train-only topology-stability TWM candidate that keeps the current change-FoM advantage versus FLUS while reducing fragmented false changes that hurt OA, Kappa and Macro-F1.

**Architecture:** Implement one bounded score-adjustment helper in `scripts/build_twm_public_landcover_benchmark.py`, then wire one new forecast-demand candidate into the existing `build_candidates()` path. The helper uses only `train_start`, `train_end`, `initial`, `valid` and class neighborhoods, preserving current metadata, invalid-cell masking and demand-allocation conventions.

**Tech Stack:** Python, NumPy, pytest, existing Dynamic World / GeoSOS-FLUS benchmark scripts.

---

## Files

- Modify: `scripts/build_twm_public_landcover_benchmark.py`
  - Add `apply_train_topology_stability_to_score()`.
  - Call it from `build_candidates()`.
  - Add `twm_topology_stability_guarded_persistence_forecast_demand` to predictions and metadata.
- Modify: `data_agent/test_twm_dynamic_world_flus_comparison.py`
  - Add a focused unit test for topology-stability score behavior.
  - Add a candidate-registration assertion in the existing train-only candidate test.
- Verify using:
  - `data_agent/test_twm_dynamic_world_flus_comparison.py`
  - `data_agent/test_twm_flus_v24_simulation_optimization.py`
  - `data_agent/test_twm_dynamic_world_flus_seed_summary.py`
  - `data_agent/test_twm_dongguan_geosos_validation.py`

---

### Task 1: Failing Test For Topology-Stability Score Guard

**Files:**
- Modify: `data_agent/test_twm_dynamic_world_flus_comparison.py`

- [ ] **Step 1: Add the failing unit test**

Append this test after `test_target_transition_neighborhood_boosts_target_specific_recent_expansion()`:

```python
def test_topology_stability_guard_penalizes_stable_interiors_but_preserves_frontiers():
    from scripts import build_twm_public_landcover_benchmark as benchmark

    classes = [0, 1]
    train_start = np.array(
        [
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 1, 1],
            [0, 0, 0, 1, 1],
        ],
        dtype=np.int16,
    )
    train_end = train_start.copy()
    train_end[2, 3] = 1
    initial = train_end.copy()
    valid = np.ones(initial.shape, dtype=bool)
    base_score = np.zeros((len(classes), *initial.shape), dtype=np.float32)

    adjusted, diagnostics = benchmark.apply_train_topology_stability_to_score(
        {
            "train_start": train_start,
            "train_end": train_end,
            "initial": initial,
            "valid": valid,
            "classes": classes,
        },
        base_score,
        stable_interior_density_floor=0.65,
        stable_interior_penalty=0.20,
        frontier_support_weight=0.10,
        target_neighborhood_support_weight=0.08,
    )

    target_one = classes.index(1)
    stable_interior_cell = (1, 1)
    frontier_supported_cell = (2, 2)

    assert adjusted[target_one, stable_interior_cell[0], stable_interior_cell[1]] < base_score[
        target_one, stable_interior_cell[0], stable_interior_cell[1]
    ]
    assert adjusted[target_one, frontier_supported_cell[0], frontier_supported_cell[1]] > adjusted[
        target_one, stable_interior_cell[0], stable_interior_cell[1]
    ]
    assert adjusted[classes.index(0), stable_interior_cell[0], stable_interior_cell[1]] == base_score[
        classes.index(0), stable_interior_cell[0], stable_interior_cell[1]
    ]
    assert diagnostics["schema"] == "territory_world_model.train_topology_stability_score_guard.v1"
    assert diagnostics["selection_metric"] == "train_stable_interior_frontier_target_neighborhood_support"
    assert diagnostics["uses_holdout_labels_for_training"] is False
    assert diagnostics["stable_interior_cell_count"] > 0
    assert diagnostics["frontier_cell_count"] > 0
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
./.venv/bin/python -m pytest -q \
  data_agent/test_twm_dynamic_world_flus_comparison.py::test_topology_stability_guard_penalizes_stable_interiors_but_preserves_frontiers
```

Expected failure:

```text
AttributeError: module 'scripts.build_twm_public_landcover_benchmark' has no attribute 'apply_train_topology_stability_to_score'
```

---

### Task 2: Implement Topology-Stability Score Helper

**Files:**
- Modify: `scripts/build_twm_public_landcover_benchmark.py`

- [ ] **Step 1: Add the helper**

Insert this function after `apply_train_target_transition_neighborhood_to_score()`:

```python
def apply_train_topology_stability_to_score(
    model_inputs: dict[str, Any],
    score: np.ndarray,
    *,
    stable_interior_density_floor: float = 0.65,
    stable_interior_penalty: float = 0.18,
    frontier_support_weight: float = 0.08,
    target_neighborhood_support_weight: float = 0.06,
) -> tuple[np.ndarray, dict[str, Any]]:
    train_start = model_inputs["train_start"]
    train_end = model_inputs["train_end"]
    initial = model_inputs["initial"]
    valid = model_inputs["valid"]
    classes = list(model_inputs["classes"])
    adjusted = score.copy()

    density_floor = max(0.0, min(1.0, float(stable_interior_density_floor)))
    penalty = max(0.0, float(stable_interior_penalty))
    frontier_weight = max(0.0, float(frontier_support_weight))
    target_weight = max(0.0, float(target_neighborhood_support_weight))
    train_change = valid & (train_start != train_end)
    frontier_strength = np.maximum(train_change.astype(np.float32), neighborhood_mean(train_change, valid))

    stable_interior_any = np.zeros(initial.shape, dtype=bool)
    same_class_density_values: list[np.ndarray] = []
    stable_interior_by_class: dict[int, np.ndarray] = {}
    for source in classes:
        same_class_density = neighbor_density(initial, int(source), valid)
        stable_interior = (
            valid
            & (train_start == int(source))
            & (train_end == int(source))
            & (initial == int(source))
            & (same_class_density >= density_floor)
        )
        stable_interior_by_class[int(source)] = stable_interior
        stable_interior_any |= stable_interior
        if int((valid & (initial == int(source))).sum()) > 0:
            same_class_density_values.append(same_class_density[valid & (initial == int(source))])

    for target_idx, target in enumerate(classes):
        target_density = neighbor_density(initial, int(target), valid)
        non_persistence = valid & (initial != int(target))
        if int(non_persistence.sum()) == 0:
            continue
        source_stable = stable_interior_any & non_persistence
        if int(source_stable.sum()) > 0 and penalty > 0.0:
            stable_penalty = penalty * (1.0 - np.clip(frontier_strength[source_stable], 0.0, 1.0))
            adjusted[target_idx, source_stable] = adjusted[target_idx, source_stable] - stable_penalty.astype(np.float32)
        if frontier_weight > 0.0:
            adjusted[target_idx, non_persistence] = adjusted[target_idx, non_persistence] + (
                np.float32(frontier_weight) * frontier_strength[non_persistence]
            )
        if target_weight > 0.0:
            adjusted[target_idx, non_persistence] = adjusted[target_idx, non_persistence] + (
                np.float32(target_weight) * target_density[non_persistence]
            )

    adjusted[:, ~valid] = -1e9
    mean_same_density = (
        float(np.mean(np.concatenate(same_class_density_values)))
        if same_class_density_values
        else 0.0
    )
    return adjusted.astype(np.float32), {
        "schema": "territory_world_model.train_topology_stability_score_guard.v1",
        "selection_metric": "train_stable_interior_frontier_target_neighborhood_support",
        "uses_holdout_labels_for_training": False,
        "stable_interior_density_floor": round(float(density_floor), 6),
        "stable_interior_penalty": round(float(penalty), 6),
        "frontier_support_weight": round(float(frontier_weight), 6),
        "target_neighborhood_support_weight": round(float(target_weight), 6),
        "stable_interior_cell_count": int(stable_interior_any.sum()),
        "frontier_cell_count": int((valid & (frontier_strength > 0.0)).sum()),
        "train_change_cell_count": int(train_change.sum()),
        "mean_same_class_neighbor_density": round(mean_same_density, 6),
        "stable_interior_by_class": {
            str(cls): int(mask.sum())
            for cls, mask in sorted(stable_interior_by_class.items())
        },
    }
```

- [ ] **Step 2: Run the focused test and verify it passes**

Run:

```bash
./.venv/bin/python -m pytest -q \
  data_agent/test_twm_dynamic_world_flus_comparison.py::test_topology_stability_guard_penalizes_stable_interiors_but_preserves_frontiers
```

Expected:

```text
1 passed
```

---

### Task 3: Failing Candidate Registration Test

**Files:**
- Modify: `data_agent/test_twm_dynamic_world_flus_comparison.py`

- [ ] **Step 1: Extend the existing candidate test**

Inside `test_transition_reliability_change_budget_candidate_is_train_only()`, after the `pair_guard_candidate` assertions, add:

```python
    topology_candidate = "twm_topology_stability_guarded_persistence_forecast_demand"
    assert topology_candidate in metrics
    assert metadata[topology_candidate]["backend"] == "train_topology_stability_guarded_persistence_demand_score_allocation"
    assert metadata[topology_candidate]["uses_holdout_labels_for_training"] is False
    assert metadata[topology_candidate]["component_flags"]["topology_stability_guard"] is True
    assert metadata[topology_candidate]["component_flags"]["train_replay_transition_false_alarm_guard"] is True
    assert metadata[topology_candidate]["component_flags"]["persistence_demand_projection"] is True
    assert metadata[topology_candidate]["training_topology_stability"]["uses_holdout_labels_for_training"] is False
    assert metadata[topology_candidate]["target_counts"] == module.class_counts(
        case.train_end.array,
        case.valid,
        list(case.classes),
    )
    assert metrics[topology_candidate]["target_total_demand_abs_error"] == 0
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
./.venv/bin/python -m pytest -q \
  data_agent/test_twm_dynamic_world_flus_comparison.py::test_transition_reliability_change_budget_candidate_is_train_only
```

Expected failure:

```text
AssertionError: assert 'twm_topology_stability_guarded_persistence_forecast_demand' in metrics
```

---

### Task 4: Wire New Candidate Into Existing Builder

**Files:**
- Modify: `scripts/build_twm_public_landcover_benchmark.py`

- [ ] **Step 1: Build the topology-adjusted score in `build_candidates()`**

After the call that assigns `activity_target_neighborhood_strict_replay_precision_overprediction_false_alarm_score`
and `activity_target_neighborhood_strict_replay_precision_overprediction_false_alarm_diagnostics`, add:

```python
    (
        topology_stability_guarded_score,
        topology_stability_guarded_diagnostics,
    ) = apply_train_topology_stability_to_score(
        model_inputs,
        activity_target_neighborhood_strict_replay_precision_overprediction_false_alarm_score,
        stable_interior_density_floor=0.65,
        stable_interior_penalty=0.18,
        frontier_support_weight=0.08,
        target_neighborhood_support_weight=0.06,
    )
```

- [ ] **Step 2: Allocate the new prediction**

After `pair_false_alarm_guarded_persistence_prediction` is created, add:

```python
    (
        topology_stability_guarded_persistence_prediction,
        topology_stability_guarded_persistence_diagnostics,
    ) = allocate_score_projection_with_adaptive_change_budget_scale(
        model_inputs,
        persistence_forecast_counts,
        topology_stability_guarded_score,
        churn_fraction=0.9,
    )
```

- [ ] **Step 3: Register the new prediction**

In the `predictions` dictionary, after `twm_pair_false_alarm_guarded_persistence_forecast_demand`, add:

```python
        "twm_topology_stability_guarded_persistence_forecast_demand": topology_stability_guarded_persistence_prediction,
```

- [ ] **Step 4: Register metadata**

In the `metadata` dictionary, after `twm_pair_false_alarm_guarded_persistence_forecast_demand`, add:

```python
        "twm_topology_stability_guarded_persistence_forecast_demand": {
            "backend": "train_topology_stability_guarded_persistence_demand_score_allocation",
            "demand_mode": "forecast_demand",
            "uses_holdout_labels_for_training": False,
            "component_flags": {
                "driver_features": True,
                "neighborhood_features": True,
                "transition_prior": True,
                "temporal_activity_calibration": True,
                "temporal_activity_neighborhood": True,
                "target_transition_neighborhood": True,
                "train_replay_transition_precision_guard": True,
                "strict_train_replay_transition_precision_guard": True,
                "train_replay_transition_overprediction_guard": True,
                "train_replay_transition_false_alarm_guard": True,
                "topology_stability_guard": True,
                "demand_projection": True,
                "persistence_demand_projection": True,
                "change_budget_calibration": True,
                "adaptive_change_budget_scale": True,
                "balanced_map_mode": True,
            },
            "training_diagnostics": training_diagnostics,
            "training_temporal_activity": activity_neighborhood_diagnostics,
            "training_target_transition_neighborhood": activity_target_neighborhood_diagnostics,
            "training_replay_transition_precision": activity_target_neighborhood_strict_replay_precision_diagnostics,
            "training_replay_transition_overprediction": (
                activity_target_neighborhood_strict_replay_precision_overprediction_diagnostics
            ),
            "training_replay_transition_false_alarm": (
                activity_target_neighborhood_strict_replay_precision_overprediction_false_alarm_diagnostics
            ),
            "training_topology_stability": topology_stability_guarded_diagnostics,
            "training_demand_projection": persistence_forecast_diagnostics,
            "training_change_budget": topology_stability_guarded_persistence_diagnostics,
            "target_counts": persistence_forecast_counts,
        },
```

- [ ] **Step 5: Run the candidate-registration test**

Run:

```bash
./.venv/bin/python -m pytest -q \
  data_agent/test_twm_dynamic_world_flus_comparison.py::test_transition_reliability_change_budget_candidate_is_train_only
```

Expected:

```text
1 passed
```

---

### Task 5: Focused Regression Suite

**Files:**
- No source changes.

- [x] **Step 1: Run the Dynamic World / FLUS test file**

Run:

```bash
./.venv/bin/python -m pytest -q data_agent/test_twm_dynamic_world_flus_comparison.py
```

Expected:

```text
all tests pass
```

Actual 2026-07-02:

```text
35 passed in 2.23s
```

- [x] **Step 2: Run the focused FLUS/GeoSOS suite**

Run:

```bash
./.venv/bin/python -m pytest -q \
  data_agent/test_twm_flus_v24_simulation_optimization.py \
  data_agent/test_twm_dynamic_world_flus_comparison.py \
  data_agent/test_twm_dynamic_world_flus_seed_summary.py \
  data_agent/test_twm_dongguan_geosos_validation.py
```

Expected:

```text
all tests pass
```

Actual 2026-07-02:

```text
39 passed in 4.66s
```

- [x] **Step 3: Run whitespace check**

Run:

```bash
git diff --check -- \
  scripts/build_twm_public_landcover_benchmark.py \
  data_agent/test_twm_dynamic_world_flus_comparison.py \
  docs/superpowers/specs/2026-07-02-twm-topology-stability-guard-design.md \
  docs/superpowers/plans/2026-07-02-twm-topology-stability-guard.md
```

Expected: no output, exit code 0.

Actual 2026-07-02: no output, exit code 0.

---

### Task 6: 100-Case Current-Code Recompute

**Files:**
- No source changes.
- Output: `/private/tmp/twm_dynamic_world_flus_topology_verify_2026-07-02.json`

- [x] **Step 1: Recompute the reused-FLUS 100-case report**

Run:

```bash
./.venv/bin/python -c 'import json; from pathlib import Path; from scripts.run_twm_dynamic_world_flus_comparison import DEFAULT_MANIFEST, load_manifest_regions, select_regions, select_cases, recompute_twm_experiments_from_existing_report; existing_path=Path("docs/reports/twm_dynamic_world_admin20_flus_ann_twm_balanced_modes_all20_reused_flus_seed20260623_2026-06-24.json"); output=Path("/private/tmp/twm_dynamic_world_flus_topology_verify_2026-07-02.json"); existing=json.loads(existing_path.read_text(encoding="utf-8")); regions,_=load_manifest_regions(DEFAULT_MANIFEST); cases=select_cases(select_regions(regions, region_limit=None, region_ids=None), case_limit=None, case_limit_per_region=None); report=recompute_twm_experiments_from_existing_report(existing_report=existing, cases=cases, output_path=output); output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str)+"\n", encoding="utf-8"); f=report["formal_forecast_comparison"]; candidate="twm_topology_stability_guarded_persistence_forecast_demand"; ranking={row["candidate_id"]: row for row in f.get("ranking_by_mean_change_fom", [])}; print(json.dumps({"status": report.get("status"), "case_count": report.get("data_profile", {}).get("case_count"), "candidate": ranking.get(candidate), "delta_vs_flus": f.get("paired_deltas_vs_flus", {}).get(candidate), "output": str(output)}, ensure_ascii=False, indent=2))'
```

Expected:

```text
"status": "pass"
"case_count": 100
"candidate": object with "candidate_id": "twm_topology_stability_guarded_persistence_forecast_demand"
```

Actual 2026-07-02:

```text
status: pass
case_count: 100
candidate_id: twm_topology_stability_guarded_persistence_forecast_demand
mean_change_fom: 0.205632
mean_overall_accuracy: 0.897029
mean_kappa: 0.761089
mean_macro_f1: 0.472769
mean_change_fom_delta_vs_flus: +0.054676
output: /private/tmp/twm_dynamic_world_flus_topology_verify_2026-07-02.json
```

- [x] **Step 2: Interpret promotion boundary**

Use the printed `delta_vs_flus` and ranking row:

```text
Promote candidate language only if:
- mean_change_fom_delta > 0
- at least one of mean_overall_accuracy, mean_kappa or mean_macro_f1 improves versus the current top candidate from the pre-change verification:
  - current top: twm_pair_false_alarm_guarded_persistence_forecast_demand
  - current top mean_change_fom: 0.193984
  - current top mean_overall_accuracy: 0.895258
  - current top mean_macro_f1: 0.467125
```

If it does not improve map-metric gaps, report it as a diagnostic candidate and keep `twm_pair_false_alarm_guarded_persistence_forecast_demand` as current top.

Actual 2026-07-02:

```text
Promote as current 100-case Dynamic World change-detection leader:
- change FoM improves vs previous current top by +0.011648.
- overall accuracy improves vs previous current top by +0.001771.
- macro-F1 improves vs previous current top by +0.005644.

Keep claim boundary:
- TWM topology candidate beats FLUS on change FoM/change F1 for this evaluated slice.
- Do not claim broad superiority over FLUS because OA, kappa and macro-F1 still trail FLUS.
```

---

### Task 7: Optional Commit Step

**Files:**
- Modified implementation and tests.
- New docs:
  - `docs/superpowers/specs/2026-07-02-twm-topology-stability-guard-design.md`
  - `docs/superpowers/plans/2026-07-02-twm-topology-stability-guard.md`

- [ ] **Step 1: Commit only with explicit user approval**

If the user asks for a commit, run:

```bash
git add \
  scripts/build_twm_public_landcover_benchmark.py \
  data_agent/test_twm_dynamic_world_flus_comparison.py \
  docs/superpowers/specs/2026-07-02-twm-topology-stability-guard-design.md \
  docs/superpowers/plans/2026-07-02-twm-topology-stability-guard.md
git commit -m "feat(twm): add topology stability guarded FLUS candidate"
```

Expected:

```text
[feat/v12-extensible-platform <commit-hash>] feat(twm): add topology stability guarded FLUS candidate
```
