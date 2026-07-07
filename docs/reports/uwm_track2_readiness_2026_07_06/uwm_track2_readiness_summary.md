# UWM Track 2 Readiness Summary

- Current date: `16` days to initial review deadline
- Ready for initial submission: `False`
- System-level superiority summary: `bounded_final_endpoint_and_endpoint_aligned_planner_advantage_without_policy_outcome_superiority`
- Overall claim ceiling: `bounded_support`
- Traditional method comparison ready: `True`
- Bounded final system superiority ready: `True`
- Policy outcome superiority ready: `False`
- Empirical superiority claim: `False`

## Observed Validation

- Temporal state suite ready: `True`
- Temporal negative control passed: `True`
- Policy outcome superiority ready: `False`

## Renderer Evidence

- Multisource livability scene ready: `True`
- OSM admin mobility crosswalk projected in scene: `True`
- OSM assigned road segments in scene: `45449`
- OSM service accessibility MAE reduction: `1.140949`
- Building floor 2.5D morphology ready: `True`
- Building floor assigned buildings: `44887`
- Building floor total floors: `322665`
- Building floor max floor: `66`
- Building floor true 3D claim: `False`

## Final Endpoint Evidence

- Final livability endpoint suite ready: `True`
- Final endpoint count: `3`
- Final endpoint ready count: `3`
- Final endpoint mean relative MAE reduction: `0.115337`

## Final Decision Evidence

- Final livability decision package ready: `True`
- Final decision action count: `2`
- Final decision target unit count: `2`
- Final decision endpoint advantage: `0.0007457`
- Final decision best single-action advantage: `0.003837146`
- Final decision single-action win rate: `1.0`
- Final decision single-action empirical p-value: `0.002809`
- Final decision endpoint weight sensitivity min advantage: `0.0007457`
- Final decision risk-adjusted advantage: `0.012777213`
- Final decision neighbor delta advantage: `0.272680076`
- Final decision GraphDQN ready: `True`
- Final decision GraphDQN advantage: `0.005131954`

## GraphDQN Training Evidence

- GraphDQN training ready: `True`
- GraphDQN algorithm: `graph_dqn_fitted_q_model_based_rl`
- GraphDQN is deep RL: `True`
- GraphDQN uses graph message passing: `True`
- GraphDQN value network trained: `True`
- GraphDQN training samples: `3600`
- GraphDQN holdout q-return MAE: `0.000109541`
- GraphDQN train-mean return MAE: `0.000741536`
- GraphDQN advantage over static: `0.005131954`

## Planner Evidence

- Risk-calibrated planner replay ready: `True`
- Endpoint-aligned planner evaluator ready: `True`
- Endpoint-aligned planner advantage: `0.0007457`
- Endpoint-aligned planner advantage ratio: `2.127273`
- Spatial spillover planner evaluator ready: `True`
- Spatial neighbor benefited units: `11` vs static `5`
- Spatial neighbor livability delta advantage: `0.272680076`

## Claim Ladder

- `observed_temporal_state_prediction_advantage_over_static_baseline_suite` | scope `observed_temporal_state_prediction_not_policy_outcome` | level `bounded_support` | allowed `True`
- `tap_external_temporal_dynamics_advantage_without_spatial_claim` | scope `tap_external_temporal_transition_without_spatial_claim` | level `bounded_support` | allowed `True`
- `learned_world_model_rollout_improves_imagined_static_and_one_step_baselines` | scope `simulator_replay_learned_dynamics_not_observed_policy_outcome` | level `bounded_support` | allowed `True`
- `business_theory_aligned_learned_rollout_beats_static_proxy_baseline` | scope `business_theory_aligned_proxy_package_not_observed_policy_outcome` | level `exploratory_only` | allowed `False`
- `paper6_arcgis_sci_plus_real_artifact_causal_diagnostic_ready` | scope `algorithmic_causal_policy_effect_validation_diagnostic_not_observed_policy_outcome` | level `bounded_support` | allowed `True`
- `external_observed_state_prediction_advantage_over_static_baseline_suite` | scope `two_source_external_observed_state_holdout_not_policy_outcome` | level `bounded_support` | allowed `True`
- `historical_station_aligned_tap_pm25_beats_static_station_baselines` | scope `historical_2018_station_aligned_pm25_holdout_not_2024_scene` | level `bounded_support` | allowed `True`
- `data_calibrated_simulator_mechanism_replaces_hardcoded_coefficients` | scope `simulator_mechanism_table_calibrated_from_real_state_transition_evidence_not_policy_outcome` | level `bounded_support` | allowed `True`
- `data_calibrated_planner_replay_advantage_over_static_heuristic` | scope `data_calibrated_model_based_planner_replay_not_policy_outcome` | level `bounded_support` | allowed `True`
- `risk_calibrated_planner_replay_advantage_over_static_heuristic` | scope `scene_uncertainty_calibrated_model_based_planner_replay_not_policy_outcome` | level `bounded_support` | allowed `True`
- `scene_aligned_gridded_pm25_spatial_message_advantage_over_static_baselines` | scope `scene_aligned_gridded_air_quality_state_reconstruction_not_station_or_policy_outcome` | level `bounded_support` | allowed `True`
- `scene_aligned_gridded_pm25_conformal_uncertainty_advantage_over_static_baseline` | scope `scene_aligned_gridded_air_quality_uncertainty_calibration_not_station_or_policy_outcome` | level `bounded_support` | allowed `True`
- `multisource_livability_scene_air_quality_head_beats_single_source_baselines` | scope `multisource_admin_unit_livability_scene_with_source_gated_air_quality_holdout` | level `bounded_support` | allowed `True`
- `osm_admin_mobility_crosswalk_service_accessibility_head_beats_static_baselines` | scope `osm_road_to_admin_mobility_crosswalk_service_accessibility_not_policy_outcome` | level `bounded_support` | allowed `True`
- `building_floor_25d_morphology_service_endpoint_head_beats_2d_baselines` | scope `building_floor_25d_morphology_not_full_3d_city_model` | level `bounded_support` | allowed `True`
- `uwm_final_livability_endpoint_suite_beats_traditional_baselines` | scope `final_livability_endpoint_prediction_suite_not_policy_outcome` | level `bounded_support` | allowed `True`
- `endpoint_aligned_planner_replay_advantage_over_static_heuristic` | scope `endpoint_aligned_planner_replay_not_policy_outcome` | level `bounded_support` | allowed `True`
- `spatial_spillover_planner_replay_advantage_over_static_heuristic` | scope `spatial_spillover_planner_replay_not_policy_outcome` | level `bounded_support` | allowed `True`
- `uwm_livability_decision_package_beats_static_heuristic_on_validated_endpoints_spillover_and_risk` | scope `final_livability_decision_package_not_policy_outcome` | level `bounded_support` | allowed `True`
- `trained_model_based_q_agent_improves_same_scene_static_livability_baseline` | scope `simulator_grounded_model_based_rl_training_not_policy_outcome` | level `bounded_support` | allowed `True`
- `graph_dqn_value_network_improves_same_scene_static_livability_baseline` | scope `simulator_grounded_graph_drl_training_not_policy_outcome` | level `bounded_support` | allowed `True`
- `uwm_bounded_final_endpoint_and_planner_advantage_over_traditional_methods` | scope `bounded_final_endpoint_prediction_and_endpoint_aligned_planner_replay_not_policy_outcome` | level `bounded_support` | allowed `True`

## Forbidden Claims

- `observed_policy_outcome_superiority`
- `spatial_attribution_for_tap_external_transition`
- `overall_empirical_policy_superiority`

## Remaining Gates

- `observed_policy_outcome_required`
- `scene_aligned_station_calibrated_air_quality_holdout_required`
- `synthetic_proxy_boundary_must_remain_visible`
