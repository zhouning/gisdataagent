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
from .data_acquisition import build_uwm_public_data_acquisition_plan, summarize_acquisition_blockers
from .data_foundation import audit_uwm_data_foundation_manifest, audit_uwm_data_foundation_roles
from .evaluation import UWM_DYNAMIC_ADVANTAGE_EVALUATION_SCHEMA, UWM_PLANNER_ADVANTAGE_EVALUATION_SCHEMA
from .ghsl_alignment import (
    GHSL_ADMIN_ALIGNMENT_SCHEMA,
    align_ghsl_tiles_to_admin_units,
    build_mmfe_state_input_from_ghsl_admin_alignment,
    validate_ghsl_admin_alignment,
)
from .mmfe_state_input import MMFE_UWM_STATE_INPUT_SCHEMA
from .openmeteo_history import (
    OPENMETEO_HISTORICAL_PROXY_SCHEMA,
    build_mmfe_state_input_from_openmeteo_historical_proxy,
    build_openmeteo_historical_environmental_proxy,
    build_openmeteo_historical_urls,
    write_openmeteo_historical_snapshot,
)
from .openmeteo_proxy import OPENMETEO_ENVIRONMENTAL_PROXY_SCHEMA, build_openmeteo_environmental_proxy
from .planner import DEFAULT_PLANNER_BACKEND, build_evidence_gated_plan
from .scene_state import (
    UWM_SCENE_STATE_SCHEMA,
    build_scene_state_from_proxy_artifacts,
    derive_simulator_scenario_from_scene_state,
    validate_scene_state,
)
from .simulator import DEFAULT_SIMULATOR_BACKEND, simulate_livability_rollout
from .track2_submission import (
    build_track2_readiness_matrix,
    build_uwm_default_artifact_inventory,
    build_uwm_default_track2_readiness_matrix,
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
    "UWM_DYNAMIC_ADVANTAGE_EVALUATION_SCHEMA",
    "UWM_OBSERVATION_SCHEMA",
    "UWM_PLAN_PACKAGE_SCHEMA",
    "UWM_PLANNER_ADVANTAGE_EVALUATION_SCHEMA",
    "UWM_ROLLOUT_TRACE_SCHEMA",
    "UWM_SCENE_STATE_SCHEMA",
    "UWM_WORLD_MODEL_EVIDENCE_READINESS_SCHEMA",
    "audit_uwm_data_foundation_manifest",
    "audit_uwm_data_foundation_roles",
    "align_ghsl_tiles_to_admin_units",
    "build_evidence_gated_plan",
    "build_mmfe_state_input_from_openmeteo_historical_proxy",
    "build_mmfe_state_input_from_ghsl_admin_alignment",
    "build_track2_readiness_matrix",
    "build_uwm_default_artifact_inventory",
    "build_uwm_default_track2_readiness_matrix",
    "build_uwm_public_data_acquisition_plan",
    "build_openmeteo_environmental_proxy",
    "build_openmeteo_historical_environmental_proxy",
    "build_openmeteo_historical_urls",
    "build_scene_state_from_proxy_artifacts",
    "simulate_livability_rollout",
    "build_world_model_evidence_readiness",
    "summarize_acquisition_blockers",
    "derive_simulator_scenario_from_scene_state",
    "validate_ghsl_admin_alignment",
    "validate_scene_state",
    "write_openmeteo_historical_snapshot",
]
