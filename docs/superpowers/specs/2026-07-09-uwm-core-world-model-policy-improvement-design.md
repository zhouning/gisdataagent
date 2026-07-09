# UWM Core World-Model Policy Improvement Design

Date: 2026-07-09

## Objective

Add the next UWM core layer after action-conditioned dynamics training:
model-based policy improvement over a learned world model.

The previous core benchmark proved that the trained dynamics model needs action
conditioning:

```text
S_t, A_t, graph context -> reward and future-state deltas
```

This design tests the next question:

```text
Can UWM use that learned dynamics model to improve a policy over the real
full-admin action space, and can it beat static, one-step and action-ablation
policy baselines under the same imagined-world evaluation?
```

## Core Distinction

The dynamics benchmark is supervised system identification. It trains
`f(s, a, graph) -> r, delta_s`.

This feature adds RL-style policy improvement. It uses the trained dynamics
model as a learned simulator and performs multi-step value backup:

```text
Q_k(s, a) = r_model(s, a) + gamma * V_{k-1}(f_model(s, a))
V_k(s) = max_a Q_k(s, a)
pi_k(s) = argmax_a Q_k(s, a)
```

The implementation remains offline and same-scene. It does not use observed
city intervention outcomes, and it does not claim empirical policy superiority.

## Scope

Create a dedicated benchmark artifact:

```text
data/uwm_public_proxy/chongqing_central/core_world_model_policy_improvement_benchmark_2026_07_09/uwm_core_world_model_policy_improvement_benchmark.json
```

In scope:

- Train the same full action-conditioned ridge dynamics model used by the core
  dynamics benchmark.
- Build policy-improvement evaluators over the full-admin action inventory from
  the real 1017-node graph.
- Use imagined rollout and value backup over learned latent state features.
- Compare full action-conditioned policy improvement with static, one-step,
  beam-search, no-action-signal and shuffled-action-signal policy baselines.
- Require exact full-admin scope counts.
- Emit a claim-safe JSON artifact and snapshot manifest.

Out of scope:

- No online RL against a real city environment.
- No observed intervention log or causal policy effect estimate.
- No frontend work.
- No new neural architecture in this slice.
- No claim that an implemented policy improved observed city outcomes.

## Supported Claim

The supported claim is:

```text
core_world_model_policy_improvement_beats_static_and_action_ablation_baselines
```

The no-claim fallback is:

```text
no_core_world_model_policy_improvement_claim_supported
```

The claim boundary must remain:

```text
bounded_support
```

when the gate passes, and:

```text
not_for_claim
```

when any required gate fails.

These flags must always remain false:

```text
observed_policy_outcome_superiority_claim = False
empirical_superiority_claim = False
```

## Full-Admin Scope Guard

The benchmark can support a claim only if the source replay has:

- `graph_node_count == 1017`
- `graph_edge_count == 7932`
- `available_action_count == 1137`
- `transition_count == 6817`
- `transition_row_count == 6817`
- `experiment_scope == "full_admin_graph"`

The benchmark must downgrade to no-claim if a smoke-sized or metadata-corrupted
replay is passed in, even if the model can still compute numbers.

## Architecture

Create:

```text
data_agent/uwm/core_world_model_policy_improvement_benchmark.py
```

The module exports:

```python
UWM_CORE_WORLD_MODEL_POLICY_IMPROVEMENT_BENCHMARK_SCHEMA
build_uwm_core_world_model_policy_improvement_benchmark(...)
validate_uwm_core_world_model_policy_improvement_benchmark(...)
```

The builder consumes the full-admin graph planner replay and returns a
deterministic JSON-serializable benchmark.

Create:

```text
scripts/build_uwm_core_world_model_policy_improvement_benchmark.py
```

The script reads:

```text
data/uwm_public_proxy/chongqing_central/data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json
```

and writes the benchmark JSON plus a snapshot manifest.

## Reuse

Reuse the existing dynamics feature definitions and training helpers from:

```text
data_agent/uwm/offline_world_model_policy.py
```

Required reused concepts:

- `FEATURE_NAMES`
- `TARGET_NAMES`
- `_node_features_by_unit`
- `_degree_by_unit`
- `_training_row`
- `_holdout_indices`
- `_fit_ridge_multi_output`
- `_mae_by_target`

The new module may copy the state-update mechanics already used for imagined
rollouts if the existing helpers are private and not cleanly reusable.

## Model Variants

Required learned dynamics variants:

- `full_action_state_graph`
- `no_action_signal`
- `shuffled_action_signal`

The action-signal columns are:

- every feature name beginning with `action_`
- `intensity`
- `mask_heat_risk`
- `mask_air_pollution`
- `mask_service_gap`

The shuffled variant uses deterministic roll offset `137`.

## Policy Variants

The benchmark must evaluate at least these policy variants:

- `world_model_policy_improvement`
  - Uses the full action-conditioned dynamics model.
  - Performs finite-horizon value backup over imagined latent state transitions.
  - Selects an action sequence using the improved Q estimate.

- `static_single_step_baseline`
  - Uses the source report static action when available.
  - Evaluated under the same full learned dynamics model for a fair imagined
    return comparison.

- `one_step_world_model_greedy`
  - Selects by immediate predicted conservative reward only.
  - Tests whether policy improvement adds value beyond one-step scoring.

- `multi_step_beam_search`
  - Uses existing learned rollout search semantics as a planning baseline.
  - Tests whether explicit value backup has evidence beyond beam ranking.

- `no_action_signal_world_model_policy`
  - Runs the same policy-improvement algorithm with a no-action-signal dynamics
    model.
  - Tests whether the policy improvement relies on action-conditioned dynamics.

- `shuffled_action_signal_world_model_policy`
  - Runs the same policy-improvement algorithm with shuffled action signals.
  - Tests whether action-state pairing matters.

## Policy Improvement Algorithm

Use deterministic finite-horizon fitted value backup over candidate actions.

Default configuration:

- `horizon = 2`
- `gamma = 0.9`
- `beam_width = 8`
- `ridge = 0.001`
- `holdout_stride = 7`
- `uncertainty_penalty = 0.5`
- `shuffle_offset = 137`

The value backup operates over a beam of imagined latent states. At each step:

1. Score candidate actions with the learned dynamics model.
2. Apply predicted dynamics to the target unit latent features.
3. Propagate cumulative discounted conservative return.
4. Keep the top `beam_width` states.

The selected policy sequence is the best cumulative discounted conservative
return after `horizon` steps.

This is not policy-gradient RL. It is model-based offline policy improvement
using a learned simulator and finite-horizon value backup.

## Evaluation Metrics

The artifact must include:

- dynamics holdout metrics for each model variant;
- train and holdout counts;
- full-admin scope counts;
- selected action sequence for each policy variant;
- imagined cumulative predicted return;
- imagined cumulative conservative return;
- advantage of `world_model_policy_improvement` over each baseline;
- per-baseline pass or fail flags;
- claim boundary and remaining gates.

The policy-improvement gate passes only if:

- full-admin scope guard passes;
- full dynamics model beats train-mean reward MAE;
- full dynamics model beats no-action and shuffled-action reward MAE;
- `world_model_policy_improvement` has higher conservative imagined return than:
  - `static_single_step_baseline`;
  - `one_step_world_model_greedy`;
  - `no_action_signal_world_model_policy`;
  - `shuffled_action_signal_world_model_policy`;
- the selected full policy sequence contains at least two actions when
  `horizon == 2`;
- observed and empirical superiority flags remain false.

The beam-search baseline is diagnostic. If it beats value backup, the artifact
must still be valid but must not support the policy-improvement claim unless the
implementation explicitly marks the beam-search comparison as a non-required
diagnostic and explains why.

## Artifact Schema

Top-level required fields:

```text
schema
benchmark_id
created_at
experiment_scope
source_report_schema
feature_names
target_names
full_admin_scope_guard
training_summary
dynamics_holdout_metrics
policy_improvement_config
policy_variant_metrics
policy_improvement_gate
supported_claim
claim_boundary
remaining_gates
audit_trace
observed_policy_outcome_superiority_claim
empirical_superiority_claim
```

`policy_variant_metrics` must be keyed by policy variant id. Each row includes:

```text
policy_variant
dynamics_variant
action_sequence
action_count
imagined_steps
imagined_cumulative_predicted_return
imagined_cumulative_conservative_return
relative_to_world_model_policy_improvement
```

## Testing

Add:

```text
data_agent/test_uwm_core_world_model_policy_improvement_benchmark.py
```

Tests must assert:

1. The builder output uses schema
   `uwm.core_world_model_policy_improvement_benchmark.v1`.
2. The full-admin scope guard passes with 1017 nodes, 7932 edges, 1137 actions
   and 6817 transitions.
3. Training summary uses 6817 rows and holdout count 973.
4. Dynamics holdout metrics show the full model beats train mean, no-action and
   shuffled-action reward baselines.
5. The policy-improvement gate passes.
6. The supported claim is
   `core_world_model_policy_improvement_beats_static_and_action_ablation_baselines`.
7. The policy-improvement conservative return beats static, one-step greedy,
   no-action and shuffled-action policy baselines.
8. Corrupting `trajectory_dataset.transition_count` to `36` downgrades the
   claim to no-claim and adds `full_admin_scope_guard_failed`.
9. The generated artifact is full scope and claim safe.
10. Observed policy and empirical superiority claims are false.

## Acceptance Criteria

- Focused policy-improvement tests pass.
- Full UWM suite passes.
- Artifact is generated from the real full-admin replay.
- No smoke-sized replay can pass the claim gate.
- The result clearly separates:
  - supervised dynamics training;
  - model-based policy improvement over the learned world model;
  - absence of observed city policy-outcome evidence.

## Risks And Controls

- Risk: calling greedy multi-step search "RL" without value backup.
  - Control: the artifact must expose value-backup configuration and policy
    improvement gate fields.

- Risk: action ablation still leaks action identity through mask features.
  - Control: action ablation must remove action one-hot, intensity and mask
    reason features together.

- Risk: policy improvement beats weak baselines only because of a different
  evaluator.
  - Control: every policy variant is evaluated under the same return convention
    and reports the exact action sequence.

- Risk: same-scene imagined returns are mistaken for observed policy outcomes.
  - Control: claim boundary remains bounded support, remaining gates stay open,
    and forbidden observed/empirical flags remain false.
