"""Dynamic action-conditioned multi-scale geospatial kernel research package."""

from .contracts import DAMGKBatch, DAMGKConfig, DAMGKOutput
from .chongqing_adapter import (
    CHONGQING_DAM_GK_ADAPTER_SCHEMA,
    EDGE_FEATURE_NAMES,
    RELATION_TYPES,
    STATE_FEATURE_NAMES,
    ChongqingDAMGKGraph,
    build_chongqing_dam_gk_graph,
)
from .controlled_benchmark import (
    CONTROLLED_BENCHMARK_SCHEMA,
    generate_controlled_sample,
    run_controlled_benchmark,
    stack_controlled_samples,
)
from .experiment_contract import (
    DAM_GK_EXPERIMENT_SCHEMA,
    build_dam_gk_experiment_contract,
    validate_dam_gk_experiment_contract,
)
from .losses import dam_gk_objective, multiscale_consistency_loss
from .model import DynamicActionConditionedMultiscaleKernel
from .negative_controls import (
    permute_edge_geometry,
    permute_coordinate_context,
    rewire_edge_targets,
    shuffle_action_assignments,
    shuffle_relation_types,
)
from .twm_adapter import (
    TWM_DAM_GK_ADAPTER_SCHEMA,
    TWM_RELATION_TYPES,
    TWMDAMGKTransition,
    build_twm_dynamic_world_transition,
)
from .twm_transition_head import TWMLandTransitionModel, TWMLandTransitionOutput
from .twm_sequence_adapter import (
    TWM_SEQUENCE_ADAPTER_SCHEMA,
    TWM_SEQUENCE_CONTEXT_DIM,
    TWM_TEMPORAL_CONTEXT_FEATURES,
    TWMDAMGKSequence,
    build_twm_dynamic_world_sequence,
)

__all__ = [
    "DAMGKBatch",
    "DAMGKConfig",
    "DAMGKOutput",
    "CHONGQING_DAM_GK_ADAPTER_SCHEMA",
    "ChongqingDAMGKGraph",
    "EDGE_FEATURE_NAMES",
    "RELATION_TYPES",
    "STATE_FEATURE_NAMES",
    "TWM_DAM_GK_ADAPTER_SCHEMA",
    "TWM_RELATION_TYPES",
    "TWMDAMGKTransition",
    "TWMLandTransitionModel",
    "TWMLandTransitionOutput",
    "TWM_SEQUENCE_ADAPTER_SCHEMA",
    "TWM_SEQUENCE_CONTEXT_DIM",
    "TWM_TEMPORAL_CONTEXT_FEATURES",
    "TWMDAMGKSequence",
    "DAM_GK_EXPERIMENT_SCHEMA",
    "CONTROLLED_BENCHMARK_SCHEMA",
    "DynamicActionConditionedMultiscaleKernel",
    "build_dam_gk_experiment_contract",
    "build_chongqing_dam_gk_graph",
    "build_twm_dynamic_world_transition",
    "build_twm_dynamic_world_sequence",
    "dam_gk_objective",
    "generate_controlled_sample",
    "multiscale_consistency_loss",
    "permute_coordinate_context",
    "permute_edge_geometry",
    "rewire_edge_targets",
    "shuffle_action_assignments",
    "shuffle_relation_types",
    "run_controlled_benchmark",
    "stack_controlled_samples",
    "validate_dam_gk_experiment_contract",
]
