# TWM Topology-Stability Guard Design

Date: 2026-07-02
Project: GIS Data Agent / Territory World Model
Scope: Dynamic World / GeoSOS-FLUS benchmark candidate improvement

## Objective

The current TWM benchmark evidence shows a real but metric-specific advantage:
TWM beats FLUS on change-focused metrics, while FLUS still leads on overall map
agreement metrics such as OA, Kappa and Macro-F1. The next algorithm increment
should therefore keep the change FoM advantage while reducing fragmented false
changes that hurt map-level accuracy.

This design adds a train-only topology-stability guard to the current best
TWM candidate family. The goal is not to claim blanket superiority over FLUS.
The goal is to make TWM a stronger geospatial world model by using spatial
topology, stable interiors and transition-frontier support as first-class
signals.

## Candidate

Add one forecast-demand candidate:

```text
twm_topology_stability_guarded_persistence_forecast_demand
```

The candidate should build on the existing strongest path:

```text
temporal activity
  + target-neighborhood support
  + strict train replay precision guard
  + overprediction guard
  + transition-pair false-alarm pressure
  + persistence demand projection
  + adaptive change budget
```

The new guard is inserted into the score path before allocation. It should not
use holdout labels.

## Algorithm

Create a helper with this responsibility:

```text
apply_train_topology_stability_to_score(
  model_inputs,
  score,
  stable_interior_density_floor,
  stable_interior_penalty,
  frontier_support_weight,
  target_neighborhood_support_weight
)
```

The helper computes three train-only spatial signals.

1. Stable interior

Cells where `train_start == train_end == initial` and the current same-class
neighborhood density is high are treated as stable interiors. Non-persistence
targets for these cells receive a score penalty. This should reduce isolated
or fragmented changes that inflate false alarms and lower OA/Macro-F1.

2. Transition frontier

Cells that changed in the training interval, or are adjacent to training
changes, are treated as transition frontier. Non-persistence targets in these
areas should not receive the full stable-interior penalty.

3. Target neighborhood support

For each target class, cells near existing target-class neighborhoods receive
support for that target. This preserves spatially plausible expansion and
avoids suppressing all true changes.

The score adjustment should be additive and bounded:

```text
adjusted_score[target, cell]
  = score[target, cell]
  - stable_interior_penalty * stable_interior_strength
  + frontier_support_weight * frontier_strength
  + target_neighborhood_support_weight * target_neighbor_density
```

The adjustment applies only to non-persistence targets. Valid masks must be
preserved with the same `-1e9` invalid-cell convention used by the existing
score helpers.

## Metadata Contract

The candidate metadata must include:

```text
backend = train_topology_stability_guarded_persistence_demand_score_allocation
demand_mode = forecast_demand
uses_holdout_labels_for_training = false
component_flags.topology_stability_guard = true
component_flags.persistence_demand_projection = true
component_flags.train_replay_transition_false_alarm_guard = true
```

The topology diagnostics must include:

```text
schema = territory_world_model.train_topology_stability_score_guard.v1
selection_metric = train_stable_interior_frontier_target_neighborhood_support
stable_interior_cell_count
frontier_cell_count
mean_same_class_neighbor_density
stable_interior_penalty
frontier_support_weight
target_neighborhood_support_weight
uses_holdout_labels_for_training = false
```

## Testing

Use TDD.

1. Add a focused unit test for `apply_train_topology_stability_to_score`.
   The test should prove that a stable interior non-persistence change is
   penalized more than a frontier-supported change.

2. Add a candidate-registration test in
   `data_agent/test_twm_dynamic_world_flus_comparison.py`.
   The test should assert:

```text
candidate exists in metrics
metadata backend matches the new topology-stability candidate
component_flags.topology_stability_guard is true
uses_holdout_labels_for_training is false
target_total_demand_abs_error == 0
```

3. Run the existing focused benchmark regression suite:

```text
./.venv/bin/python -m pytest -q \
  data_agent/test_twm_dynamic_world_flus_comparison.py \
  data_agent/test_twm_flus_v24_simulation_optimization.py \
  data_agent/test_twm_dynamic_world_flus_seed_summary.py \
  data_agent/test_twm_dongguan_geosos_validation.py
```

4. Recompute the 100-case Dynamic World / FLUS reused-baseline report with
current code. The new candidate can be promoted only if it keeps a positive
mean change FoM delta versus FLUS and reduces at least one of the map-metric
gaps versus the current top candidate.

## Claim Boundary

Passing the tests does not prove that TWM generally beats GeoSOS-FLUS. It
supports a narrower claim:

```text
On the evaluated Dynamic World / FLUS benchmark slice, the topology-stability
guard improves the TWM change-focused simulator path while preserving explicit
train-only provenance and demand/constraint discipline.
```

If the 100-case recompute does not improve OA, Kappa or Macro-F1 gap, the
candidate remains diagnostic and must not be used in superiority language.
