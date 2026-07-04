# TWM Runtime Benchmark v1

- Status: `fail`
- Dataset manifest hash: `2278ac2b8aa383c17ab3ebeacc24352f9ac20c1b12004eb307e391b7401840b5`
- Failed gates: `simulator_gate, planner_gate, negative_control_gate`

## Gates

- `dataset_integrity_gate`: `pass`; missing/review: none
- `renderer_gate`: `pass`; missing/review: none
- `simulator_gate`: `fail`; missing/review: simulator_trace, dataset_snapshot_hash, model_family, split, prediction_id, action_mask_probability, holdout_metrics
- `planner_gate`: `fail`; missing/review: planner_consumes_simulator_trace, simulator_trace_bound_to_each_candidate, planner_regret_against_human_oracle
- `evidence_claim_gate`: `pass`; missing/review: none
- `negative_control_gate`: `fail`; missing/review: negative_control_runtime_results, shuffled_action_control, shuffled_label_control
- `leakage_guard_gate`: `pass`; missing/review: none

## Claim Boundary

- Runtime benchmark: `fail`
- Production accuracy: `not_supported`
- Production decision: `blocked_without_real_observed_history`
- FLUS superiority: `not_evaluated_by_this_benchmark`

## Recommendations

- Implement a traceable simulator backend that emits simulator_trace for every forecast and rollout.
- Force planner ranking to consume simulator_trace and action-mask outputs for each candidate.
- Execute impossible-action, support-missing, policy-conflict and shuffled-control tests in the benchmark loop.
