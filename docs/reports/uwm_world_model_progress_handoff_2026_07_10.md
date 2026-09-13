# UWM Geospatial World Model Progress Handoff - 2026-07-10

## Current Objective

Continue UWM (urban livability analysis) as a real geospatial world model, not a demo, mock, smoke test, or pure scoring pipeline. The current implementation uses full-admin Chongqing prepared data and keeps a strict claim boundary:

- Supported: bounded full-admin research world-model evidence.
- Not supported: observed policy-outcome superiority, empirical intervention superiority, observed OD flow, or observed trip-time claims.

## Completed In This Checkpoint

1. Full-admin mobility graph foundation
   - Added `data_agent/uwm/full_admin_mobility_graph.py`.
   - Added `scripts/build_uwm_full_admin_mobility_graph.py`.
   - Added `data_agent/test_uwm_full_admin_mobility_graph.py`.
   - Generated `data/uwm_public_proxy/chongqing_central/full_admin_mobility_graph_2026_07_10/full_admin_mobility_graph.json`.
   - Result: 1017 nodes, 5085 mobility-accessibility similarity edges.
   - Context evidence: Unicom directed edges 1067, OSM highway edges 45468, OSM crosswalk assigned road segments 45449.

2. Mobility-aware world-model state encoding
   - `model_based_rl.py` graph nodes now carry `uwm.graph_node_features.mobility_accessibility.v1`.
   - Node features include heat, air, service, equity, livability, travel time, road count, road length, speed, capacity, essential service, inverse travel-time, service gap, and degree.

3. GraphDQN training now consumes world-state mobility features
   - `livability_graph_drl.py` exports `GRAPH_NODE_FEATURE_NAMES`.
   - GraphDQN node tensors now include 14 features, including mobility/accessibility variables.
   - Action features now include target and previous selected node mobility-aware feature rows.
   - Full-admin GraphDQN artifact regenerated:
     - `q_return_mae=0.000053133`
     - `train_mean_return_mae=0.000994236`
     - `advantage_over_traditional_static=0.000773039`

4. Offline action-conditioned world model now consumes mobility features
   - `offline_world_model_policy.py` expands to 23 features.
   - New action-state features include:
     - `target_travel_time_min_norm`
     - `target_road_segment_count_norm`
     - `target_road_length_km_norm`
     - `target_mean_road_speed_kmh_norm`
     - `target_capacity_norm`
     - `target_essential_norm`
     - `target_travel_time_inverse_norm`
   - Learned rollout artifact regenerated:
     - `reward_mae=0.000032363`
     - `train_mean_reward_mae=0.00222562`
     - `imagined_advantage_over_static=0.001192103`
     - `imagined_advantage_over_one_step=0.00089763`

5. Core benchmarks regenerated
   - Core action-conditioned dynamics benchmark:
     - supported claim: `core_action_conditioned_dynamics_beats_static_and_no_action_baselines`
     - holdout count: 973
   - Core world-model policy-improvement benchmark:
     - supported claim: `core_world_model_policy_improvement_beats_static_and_action_ablation_baselines`
     - policy gate passed: true
     - holdout count: 973

6. Evidence packaging updated
   - Full-admin decision package now exposes GraphDQN node feature names and learned rollout world-model feature names.
   - Superiority dossier now exposes the same feature schema evidence.
   - Data foundation evidence gate distinguishes:
     - `bounded_mobility_projection_graph_ready=true`
     - `observed_mobility_or_travel_time_graph_ready=false`

## Regenerated Full-Admin Artifacts

- `data/uwm_public_proxy/chongqing_central/data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json`
- `data/uwm_public_proxy/chongqing_central/livability_graph_drl_training_full_admin_graph_2026_07_08/uwm_full_admin_graph_livability_graph_drl_training_report.json`
- `data/uwm_public_proxy/chongqing_central/learned_world_model_rollout_full_admin_graph_2026_07_08/uwm_full_admin_graph_learned_world_model_rollout.json`
- `data/uwm_public_proxy/chongqing_central/core_action_conditioned_dynamics_benchmark_2026_07_09/uwm_core_action_conditioned_dynamics_benchmark.json`
- `data/uwm_public_proxy/chongqing_central/core_world_model_policy_improvement_benchmark_2026_07_09/uwm_core_world_model_policy_improvement_benchmark.json`
- `data/uwm_public_proxy/chongqing_central/full_admin_livability_decision_package_2026_07_08/uwm_full_admin_livability_decision_package.json`
- `data/uwm_public_proxy/chongqing_central/energy_regularized_planner_full_admin_graph_2026_07_08/uwm_full_admin_graph_energy_regularized_planner_report.json`
- `data/uwm_public_proxy/chongqing_central/full_admin_world_model_superiority_dossier_2026_07_09/uwm_full_admin_world_model_superiority_dossier.json`
- `data/uwm_public_proxy/chongqing_central/data_foundation_evidence_gate_2026_07_05/uwm_data_foundation_evidence_gate.json`

## Verification

Latest targeted verification command:

```bash
PYTHONPATH=. /Users/zhouning/gisdataagent/.venv/bin/pytest \
  data_agent/test_uwm_model_based_rl.py::test_graph_mdp_state_encodes_mobility_accessibility_features \
  data_agent/test_uwm_livability_graph_drl_training.py \
  data_agent/test_uwm_offline_world_model_policy.py \
  data_agent/test_uwm_full_admin_graph_planner_replay.py \
  data_agent/test_uwm_full_admin_graph_drl_training.py \
  data_agent/test_uwm_full_admin_learned_world_model_rollout.py \
  data_agent/test_uwm_core_action_conditioned_dynamics_benchmark.py \
  data_agent/test_uwm_core_world_model_policy_improvement_benchmark.py \
  data_agent/test_uwm_full_admin_livability_decision_package.py::test_full_admin_livability_decision_package_collects_real_full_scope_evidence \
  data_agent/test_uwm_full_admin_livability_decision_package.py::test_full_admin_livability_decision_package_artifact_is_full_scope_and_claim_safe \
  data_agent/test_uwm_full_admin_livability_decision_package.py::test_evidence_gate_tracks_full_admin_livability_decision_package \
  data_agent/test_uwm_full_admin_world_model_superiority_dossier.py \
  data_agent/test_uwm_data_foundation_evidence_gate.py::test_data_foundation_evidence_gate_uses_prepared_artifacts_without_smoke_claims \
  data_agent/test_uwm_world_model_evidence_readiness.py::test_world_model_evidence_readiness_distinguishes_bounded_mobility_projection_from_observed_trip_time \
  data_agent/test_uwm_full_admin_energy_regularized_planner.py \
  -q
```

Result: `32 passed in 78.03s`.

## Current Claim Boundary

The current evidence supports bounded same-scene, full-admin world-model advantages over traditional baselines. It still does not support production deployment or observed policy outcome superiority.

Current production blockers:

- observed mobility or travel-time graph is still missing;
- scene-aligned station-calibrated air-quality holdout is still missing;
- observed policy outcome holdout is still missing;
- planner governance binding is still missing.

## Recommended Next Development Step

Do not add more scoring layers. Continue with production-grade world-model gaps:

1. Replace bounded mobility projection with observed or institutionally sourced OD/trip-time/mobility graph.
2. Bind action candidates to authoritative governance/project/action-cost tables.
3. Add observed before-after or quasi-experimental policy outcome validation panel.
4. Expand cross-time/cross-city holdout tests so superiority claims can move beyond same-scene bounded support.
