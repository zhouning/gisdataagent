# UWM Core Action-Conditioned Dynamics Benchmark Design

Date: 2026-07-09

## Objective

Move UWM development back to the world-model core: prove, on the real full-admin
transition dataset, that the learned UWM dynamics model needs action-conditioned
signals and beats traditional non-action baselines on future-state prediction.

This is not another reporting layer. It is a model benchmark over the full
Graph-MDP replay dataset:

```text
S_t, A_t, graph context -> reward and future-state deltas
```

## Core Problem

The current full-admin learned rollout already trains an action-conditioned
ridge dynamics model over 6817 transitions, but the evidence is embedded in a
planner report. The system does not yet expose a dedicated benchmark that asks:

1. Does the model beat static/train-mean dynamics baselines?
2. Does action-conditioning matter after controlling for state?
3. Does a deterministic action-signal shuffle degrade prediction?
4. Are all results computed over the full 1017-node, 1137-action, 6817-transition
   dataset rather than a smoke subset?

An initial local probe showed an important modelling detail: removing only
action one-hot and intensity is insufficient because `mask_reason` also carries
action signal. The action ablation must remove action type, intensity and
mask-reason columns together.

## Scope

Add a core dynamics benchmark artifact:

```text
data/uwm_public_proxy/chongqing_central/core_action_conditioned_dynamics_benchmark_2026_07_09/uwm_core_action_conditioned_dynamics_benchmark.json
```

In scope:

- Reuse the full-admin planner replay transition dataset.
- Reuse the existing `offline_world_model_policy` feature construction and
  ridge fitting logic.
- Evaluate full action-state-graph dynamics against:
  - train-mean static baseline;
  - no-action-signal ablation;
  - deterministic shuffled-action-signal negative control.
- Report graph-degree ablation as a diagnostic, not a required superiority gate.
- Require exact full-admin scope counts.
- Preserve observed policy and empirical superiority claim boundaries.

Out of scope:

- No observed policy-outcome superiority claim.
- No fabricated policy intervention log.
- No frontend work.
- No new neural architecture in this slice.

## Benchmark Contract

The supported claim is:

```text
core_action_conditioned_dynamics_beats_static_and_no_action_baselines
```

The claim is allowed only if:

- `graph_node_count == 1017`;
- `graph_edge_count == 7932`;
- `available_action_count == 1137`;
- `transition_count == 6817`;
- `holdout_count > 900`;
- full model reward MAE is below train-mean reward MAE;
- full model reward MAE is below no-action-signal reward MAE;
- full model reward MAE is below shuffled-action-signal reward MAE;
- full model beats train mean, no-action signal and shuffled-action signal on
  every target in:
  - reward;
  - heat risk delta;
  - air pollution exposure delta;
  - service accessibility delta;
  - equity delta;
  - livability delta.

## Architecture

Create:

```text
data_agent/uwm/core_action_conditioned_dynamics_benchmark.py
```

The module exports:

```python
UWM_CORE_ACTION_CONDITIONED_DYNAMICS_BENCHMARK_SCHEMA
build_uwm_core_action_conditioned_dynamics_benchmark(...)
validate_uwm_core_action_conditioned_dynamics_benchmark(...)
```

The builder consumes the full-admin planner replay report and returns a
deterministic JSON-serializable benchmark.

Create:

```text
scripts/build_uwm_core_action_conditioned_dynamics_benchmark.py
```

The script reads:

```text
data/uwm_public_proxy/chongqing_central/data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json
```

and writes the benchmark JSON plus a snapshot manifest.

## Feature Variants

Use the existing `offline_world_model_policy.FEATURE_NAMES` order.

Required variants:

- `full_action_state_graph`: all features.
- `train_mean_static`: train-set target means.
- `no_action_signal`: zero these columns:
  - `action_increase_green_infrastructure`;
  - `action_traffic_emission_control`;
  - `action_add_community_service`;
  - `action_other`;
  - `intensity`;
  - `mask_heat_risk`;
  - `mask_air_pollution`;
  - `mask_service_gap`.
- `shuffled_action_signal`: deterministic row rotation of the same action-signal
  columns with a fixed offset of 137.
- `no_graph_degree`: zero `target_degree_norm`; diagnostic only.

## Testing

Add:

```text
data_agent/test_uwm_core_action_conditioned_dynamics_benchmark.py
```

Tests must assert:

1. Builder output uses the expected schema.
2. Full-admin guard passes with 1017 nodes, 7932 edges, 1137 actions and 6817
   transitions.
3. Holdout count is 973 with holdout stride 7.
4. Full model beats train mean, no-action signal and shuffled-action signal on
   every target.
5. No-action signal and shuffled-action signal are reported as failed
   falsification controls.
6. Corrupting the transition count downgrades the claim to `not_for_claim`.
7. Generated artifact is full scope and claim safe.
8. Observed policy and empirical superiority claims are false.

## Acceptance Criteria

- Focused benchmark tests pass.
- Full UWM suite passes.
- Artifact is generated from the real full-admin replay.
- No smoke-sized replay can pass.
- The result strengthens core dynamics evidence without claiming observed policy
  outcome superiority.
