"""Urban World Model foundation contracts and first rollout gates.

The UWM package keeps renderer, simulator, baseline and evaluation boundaries
explicit. The current simulator is a transparent mechanism backend for
action-conditioned rollout tests, not an empirical predictive superiority claim.
"""

from .contracts import (
    UWM_OBSERVATION_SCHEMA,
    UWM_PLAN_PACKAGE_SCHEMA,
    UWM_ROLLOUT_TRACE_SCHEMA,
)
from .causal_policy_evidence import (
    UWM_CAUSAL_POLICY_EVIDENCE_GATE_SCHEMA,
    build_uwm_causal_policy_evidence_gate,
    validate_uwm_causal_policy_evidence_gate,
)
from .building_floor_morphology import (
    UWM_BUILDING_FLOOR_MORPHOLOGY_SCHEMA,
    build_uwm_building_floor_morphology,
)
from .data_calibrated_mechanism_table import (
    UWM_DATA_CALIBRATED_MECHANISM_TABLE_SCHEMA,
    build_uwm_data_calibrated_mechanism_table,
    validate_uwm_data_calibrated_mechanism_table,
)
from .data_acquisition import build_uwm_public_data_acquisition_plan, summarize_acquisition_blockers
from .data_foundation import audit_uwm_data_foundation_manifest, audit_uwm_data_foundation_roles
from .evaluation import UWM_DYNAMIC_ADVANTAGE_EVALUATION_SCHEMA, UWM_PLANNER_ADVANTAGE_EVALUATION_SCHEMA
from .external_observed_holdout import (
    UWM_EXTERNAL_OBSERVED_HOLDOUT_SUITE_SCHEMA,
    build_uwm_external_observed_holdout_suite,
    validate_uwm_external_observed_holdout_suite,
)
from .endpoint_aligned_planner_evaluator import (
    UWM_ENDPOINT_ALIGNED_PLANNER_EVALUATOR_SCHEMA,
    build_uwm_endpoint_aligned_planner_evaluator,
)
from .ghsl_alignment import (
    GHSL_ADMIN_ALIGNMENT_SCHEMA,
    align_ghsl_tiles_to_admin_units,
    build_mmfe_state_input_from_ghsl_admin_alignment,
    validate_ghsl_admin_alignment,
)
from .mmfe_state_input import MMFE_UWM_STATE_INPUT_SCHEMA
from .multisource_livability_scene import (
    UWM_MULTISOURCE_LIVABILITY_SCENE_SCHEMA,
    build_uwm_multisource_livability_scene,
)
from .livability_endpoint_suite import (
    UWM_LIVABILITY_ENDPOINT_SUITE_SCHEMA,
    build_uwm_livability_endpoint_suite,
)
from .livability_decision_package import (
    UWM_LIVABILITY_DECISION_PACKAGE_SCHEMA,
    build_uwm_livability_decision_package,
)
from .full_admin_livability_decision_package import (
    UWM_FULL_ADMIN_LIVABILITY_DECISION_PACKAGE_SCHEMA,
    build_uwm_full_admin_livability_decision_package,
)
from .full_admin_mobility_graph import (
    UWM_FULL_ADMIN_MOBILITY_GRAPH_SCHEMA,
    build_full_admin_mobility_graph,
    validate_full_admin_mobility_graph,
    write_full_admin_mobility_graph_snapshot,
)
from .livability_requirement_registry import (
    CUSTOMER_DEMAND_PRIMARY_ROUTES,
    LIVABILITY_SCENARIO_PRIMARY_ROUTES,
    PRIMARY_ROUTES,
    UWM_LIVABILITY_REQUIREMENT_REGISTRY_SCHEMA,
    build_livability_requirement_registry,
    requirement_coverage_for_route,
    validate_livability_requirement_registry,
)
from .livability_graph_mdp_env import (
    LIVABILITY_GRAPH_MDP_ENV_SCHEMA,
    build_livability_graph_mdp_env,
)
from .livability_rl_training import (
    UWM_LIVABILITY_RL_TRAINING_REPORT_SCHEMA,
    train_livability_model_based_q_agent,
)
from .livability_graph_drl import (
    UWM_LIVABILITY_GRAPH_DRL_TRAINING_REPORT_SCHEMA,
    train_livability_graph_dqn_agent,
)
from .energy_regularized_planner import (
    UWM_ENERGY_REGULARIZED_ACTION_SEQUENCE_PLANNER_SCHEMA,
    plan_with_energy_regularized_action_sequences,
)
from .full_admin_energy_regularized_planner import (
    UWM_FULL_ADMIN_ENERGY_REGULARIZED_ACTION_SEQUENCE_PLANNER_SCHEMA,
    plan_full_admin_energy_regularized_action_sequences,
)
from .full_admin_action_inventory import (
    UWM_FULL_ADMIN_ACTION_INVENTORY_SCHEMA,
    build_full_admin_action_inventory,
)
from .production_state_action_space import (
    UWM_PRODUCTION_STATE_ACTION_SPACE_ASSESSMENT_SCHEMA,
    build_uwm_production_state_action_space_assessment,
)
from .openmeteo_history import (
    OPENMETEO_HISTORICAL_PROXY_SCHEMA,
    build_mmfe_state_input_from_openmeteo_historical_proxy,
    build_openmeteo_historical_environmental_proxy,
    build_openmeteo_historical_urls,
    write_openmeteo_historical_snapshot,
)
from .openmeteo_proxy import OPENMETEO_ENVIRONMENTAL_PROXY_SCHEMA, build_openmeteo_environmental_proxy
from .osm_admin_mobility_crosswalk import (
    UWM_OSM_ADMIN_MOBILITY_CROSSWALK_SCHEMA,
    build_uwm_osm_admin_mobility_crosswalk,
)
from .planner import DEFAULT_PLANNER_BACKEND, build_evidence_gated_plan
from .scene_state import (
    UWM_SCENE_STATE_SCHEMA,
    build_scene_state_from_proxy_artifacts,
    derive_simulator_scenario_from_scene_state,
    validate_scene_state,
)
from .simulator import DEFAULT_SIMULATOR_BACKEND, simulate_livability_rollout
from .scene_aligned_gridded_air_quality_holdout import (
    UWM_SCENE_ALIGNED_GRIDDED_AIR_QUALITY_HOLDOUT_SCHEMA,
    build_uwm_scene_aligned_gridded_air_quality_holdout,
    validate_uwm_scene_aligned_gridded_air_quality_holdout,
)
from .station_aligned_air_quality_holdout import (
    UWM_STATION_ALIGNED_AIR_QUALITY_HOLDOUT_SCHEMA,
    build_uwm_station_aligned_air_quality_holdout,
    validate_uwm_station_aligned_air_quality_holdout,
)
from .spatial_spillover_planner_evaluator import (
    UWM_SPATIAL_SPILLOVER_PLANNER_EVALUATOR_SCHEMA,
    build_uwm_spatial_spillover_planner_evaluator,
)
from .spatial_causal_question_registry import (
    UWM_SPATIAL_CAUSAL_QUESTION_REGISTRY_SCHEMA,
    build_uwm_spatial_causal_question_registry,
    validate_uwm_spatial_causal_question_registry,
)
from .track2_submission import (
    build_track2_readiness_matrix,
    build_uwm_default_artifact_inventory,
    build_uwm_default_track2_readiness_matrix,
)
from .traditional_livability_baseline import (
    UWM_TRADITIONAL_LIVABILITY_BASELINE_SCHEMA,
    build_traditional_livability_baseline,
)
from .traditional_vs_world_model_demo import (
    UWM_TRADITIONAL_VS_WORLD_MODEL_DEMO_SCHEMA,
    build_traditional_vs_world_model_demo,
)
from .world_model_evidence_readiness import (
    UWM_WORLD_MODEL_EVIDENCE_READINESS_SCHEMA,
    build_world_model_evidence_readiness,
)

__all__ = [
    "DEFAULT_PLANNER_BACKEND",
    "DEFAULT_SIMULATOR_BACKEND",
    "GHSL_ADMIN_ALIGNMENT_SCHEMA",
    "MMFE_UWM_STATE_INPUT_SCHEMA",
    "OPENMETEO_ENVIRONMENTAL_PROXY_SCHEMA",
    "OPENMETEO_HISTORICAL_PROXY_SCHEMA",
    "UWM_BUILDING_FLOOR_MORPHOLOGY_SCHEMA",
    "UWM_CAUSAL_POLICY_EVIDENCE_GATE_SCHEMA",
    "UWM_DATA_CALIBRATED_MECHANISM_TABLE_SCHEMA",
    "UWM_DYNAMIC_ADVANTAGE_EVALUATION_SCHEMA",
    "UWM_ENERGY_REGULARIZED_ACTION_SEQUENCE_PLANNER_SCHEMA",
    "UWM_FULL_ADMIN_ENERGY_REGULARIZED_ACTION_SEQUENCE_PLANNER_SCHEMA",
    "UWM_FULL_ADMIN_ACTION_INVENTORY_SCHEMA",
    "UWM_FULL_ADMIN_MOBILITY_GRAPH_SCHEMA",
    "UWM_PRODUCTION_STATE_ACTION_SPACE_ASSESSMENT_SCHEMA",
    "UWM_ENDPOINT_ALIGNED_PLANNER_EVALUATOR_SCHEMA",
    "UWM_EXTERNAL_OBSERVED_HOLDOUT_SUITE_SCHEMA",
    "UWM_LIVABILITY_ENDPOINT_SUITE_SCHEMA",
    "UWM_LIVABILITY_REQUIREMENT_REGISTRY_SCHEMA",
    "UWM_LIVABILITY_DECISION_PACKAGE_SCHEMA",
    "UWM_FULL_ADMIN_LIVABILITY_DECISION_PACKAGE_SCHEMA",
    "UWM_LIVABILITY_GRAPH_DRL_TRAINING_REPORT_SCHEMA",
    "LIVABILITY_GRAPH_MDP_ENV_SCHEMA",
    "UWM_LIVABILITY_RL_TRAINING_REPORT_SCHEMA",
    "UWM_MULTISOURCE_LIVABILITY_SCENE_SCHEMA",
    "UWM_OBSERVATION_SCHEMA",
    "UWM_OSM_ADMIN_MOBILITY_CROSSWALK_SCHEMA",
    "UWM_PLAN_PACKAGE_SCHEMA",
    "UWM_PLANNER_ADVANTAGE_EVALUATION_SCHEMA",
    "UWM_ROLLOUT_TRACE_SCHEMA",
    "UWM_SCENE_ALIGNED_GRIDDED_AIR_QUALITY_HOLDOUT_SCHEMA",
    "UWM_SCENE_STATE_SCHEMA",
    "UWM_SPATIAL_CAUSAL_QUESTION_REGISTRY_SCHEMA",
    "UWM_SPATIAL_SPILLOVER_PLANNER_EVALUATOR_SCHEMA",
    "UWM_STATION_ALIGNED_AIR_QUALITY_HOLDOUT_SCHEMA",
    "UWM_TRADITIONAL_LIVABILITY_BASELINE_SCHEMA",
    "UWM_TRADITIONAL_VS_WORLD_MODEL_DEMO_SCHEMA",
    "UWM_WORLD_MODEL_EVIDENCE_READINESS_SCHEMA",
    "audit_uwm_data_foundation_manifest",
    "audit_uwm_data_foundation_roles",
    "align_ghsl_tiles_to_admin_units",
    "build_evidence_gated_plan",
    "build_mmfe_state_input_from_openmeteo_historical_proxy",
    "build_mmfe_state_input_from_ghsl_admin_alignment",
    "build_track2_readiness_matrix",
    "build_uwm_building_floor_morphology",
    "build_uwm_causal_policy_evidence_gate",
    "build_uwm_data_calibrated_mechanism_table",
    "build_uwm_endpoint_aligned_planner_evaluator",
    "build_uwm_external_observed_holdout_suite",
    "build_uwm_livability_endpoint_suite",
    "build_livability_requirement_registry",
    "build_uwm_livability_decision_package",
    "build_uwm_full_admin_livability_decision_package",
    "build_full_admin_mobility_graph",
    "build_full_admin_action_inventory",
    "build_uwm_production_state_action_space_assessment",
    "build_livability_graph_mdp_env",
    "build_uwm_multisource_livability_scene",
    "build_uwm_osm_admin_mobility_crosswalk",
    "build_uwm_scene_aligned_gridded_air_quality_holdout",
    "build_uwm_spatial_causal_question_registry",
    "build_uwm_spatial_spillover_planner_evaluator",
    "build_uwm_station_aligned_air_quality_holdout",
    "build_uwm_default_artifact_inventory",
    "build_uwm_default_track2_readiness_matrix",
    "build_uwm_public_data_acquisition_plan",
    "build_traditional_livability_baseline",
    "build_traditional_vs_world_model_demo",
    "build_openmeteo_environmental_proxy",
    "build_openmeteo_historical_environmental_proxy",
    "build_openmeteo_historical_urls",
    "build_scene_state_from_proxy_artifacts",
    "plan_with_energy_regularized_action_sequences",
    "plan_full_admin_energy_regularized_action_sequences",
    "simulate_livability_rollout",
    "train_livability_model_based_q_agent",
    "validate_full_admin_mobility_graph",
    "validate_livability_requirement_registry",
    "write_full_admin_mobility_graph_snapshot",
    "requirement_coverage_for_route",
    "CUSTOMER_DEMAND_PRIMARY_ROUTES",
    "LIVABILITY_SCENARIO_PRIMARY_ROUTES",
    "PRIMARY_ROUTES",
    "train_livability_graph_dqn_agent",
    "build_world_model_evidence_readiness",
    "summarize_acquisition_blockers",
    "derive_simulator_scenario_from_scene_state",
    "validate_ghsl_admin_alignment",
    "validate_scene_state",
    "validate_uwm_causal_policy_evidence_gate",
    "validate_uwm_data_calibrated_mechanism_table",
    "validate_uwm_external_observed_holdout_suite",
    "validate_uwm_scene_aligned_gridded_air_quality_holdout",
    "validate_uwm_spatial_causal_question_registry",
    "validate_uwm_station_aligned_air_quality_holdout",
    "write_openmeteo_historical_snapshot",
]
