"""Tensor contracts for the DAM-GK research model."""

from __future__ import annotations

from dataclasses import dataclass

import torch


@dataclass(frozen=True)
class DAMGKConfig:
    node_state_dim: int
    action_dim: int
    edge_feature_dim: int
    relation_type_count: int
    context_dim: int = 0
    region_context_dim: int = 0
    hidden_dim: int = 64
    horizon: int = 3
    state_output_dim: int | None = None
    minimum_scale: float = 1e-4
    use_action_conditioning: bool = True
    use_relation_types: bool = True
    use_topology_rewrite: bool = True
    use_lag_structure: bool = True
    normalize_propagation_mass: bool = False
    use_relation_channel_fusion: bool = False
    use_region_conditioning: bool = False
    use_edge_geometry: bool = True
    edge_geometry_start_index: int | None = None
    use_multiscale_consistency: bool = True
    mutable_state_dim: int | None = None
    state_writeback_mode: str = "auto_additive"

    def output_dim(self) -> int:
        return self.state_output_dim or self.node_state_dim

    def transition_latent_dim(self) -> int:
        return self.hidden_dim * (4 if self.use_region_conditioning else 3)

    def validate(self) -> None:
        if self.horizon <= 0:
            raise ValueError("horizon_must_be_positive")
        if self.mutable_state_dim is not None and not (
            0 < self.mutable_state_dim <= self.node_state_dim
        ):
            raise ValueError("mutable_state_dim_out_of_range")
        if self.state_writeback_mode not in {
            "auto_additive",
            "additive",
            "simplex_additive",
            "none",
            "teacher_forced",
            "categorical_mixture",
            "categorical_no_writeback",
            "categorical_teacher_forced",
        }:
            raise ValueError("unsupported_state_writeback_mode")
        if self.state_writeback_mode in {
            "additive",
            "simplex_additive",
            "categorical_mixture",
            "categorical_no_writeback",
            "categorical_teacher_forced",
        }:
            mutable_dim = self.mutable_state_dim or self.node_state_dim
            if self.output_dim() != mutable_dim:
                raise ValueError("state_output_dim_must_match_mutable_state_dim")


@dataclass(frozen=True)
class DAMGKBatch:
    node_state: torch.Tensor
    node_action: torch.Tensor
    edge_index: torch.Tensor
    edge_features: torch.Tensor
    edge_types: torch.Tensor
    node_context: torch.Tensor | None = None
    node_context_by_step: torch.Tensor | None = None
    teacher_state_by_step: torch.Tensor | None = None
    region_context: torch.Tensor | None = None
    edge_valid_mask: torch.Tensor | None = None

    def validate(self, config: DAMGKConfig) -> None:
        config.validate()
        node_count = self.node_state.shape[0]
        edge_count = self.edge_index.shape[1]
        if self.node_state.ndim != 2 or self.node_state.shape[1] != config.node_state_dim:
            raise ValueError("node_state_shape_mismatch")
        if self.node_action.shape != (node_count, config.action_dim):
            raise ValueError("node_action_shape_mismatch")
        if self.edge_index.shape[0] != 2 or self.edge_index.dtype != torch.long:
            raise ValueError("edge_index_must_be_long_2_by_e")
        if self.edge_features.shape != (edge_count, config.edge_feature_dim):
            raise ValueError("edge_features_shape_mismatch")
        if config.edge_geometry_start_index is not None and not (
            0 <= config.edge_geometry_start_index < config.edge_feature_dim
        ):
            raise ValueError("edge_geometry_start_index_out_of_range")
        if self.edge_types.shape != (edge_count,) or self.edge_types.dtype != torch.long:
            raise ValueError("edge_types_shape_mismatch")
        if edge_count and (self.edge_types.min() < 0 or self.edge_types.max() >= config.relation_type_count):
            raise ValueError("edge_type_out_of_range")
        if self.node_context is not None and self.node_context.shape != (node_count, config.context_dim):
            raise ValueError("node_context_shape_mismatch")
        if config.context_dim and self.node_context is None:
            raise ValueError("node_context_required")
        if self.node_context_by_step is not None and self.node_context_by_step.shape != (
            node_count,
            config.horizon,
            config.context_dim,
        ):
            raise ValueError("node_context_by_step_shape_mismatch")
        if self.teacher_state_by_step is not None and self.teacher_state_by_step.shape != (
            node_count,
            config.horizon,
            config.node_state_dim,
        ):
            raise ValueError("teacher_state_by_step_shape_mismatch")
        if config.state_writeback_mode in {
            "teacher_forced",
            "categorical_teacher_forced",
        } and self.teacher_state_by_step is None:
            raise ValueError("teacher_state_by_step_required")
        if self.region_context is not None and self.region_context.shape != (
            node_count,
            config.region_context_dim,
        ):
            raise ValueError("region_context_shape_mismatch")
        if config.use_region_conditioning and config.region_context_dim <= 0:
            raise ValueError("region_context_dim_required")
        if config.use_region_conditioning and self.region_context is None:
            raise ValueError("region_context_required")
        if self.edge_valid_mask is not None and self.edge_valid_mask.shape != (edge_count,):
            raise ValueError("edge_valid_mask_shape_mismatch")
        if edge_count and (self.edge_index.min() < 0 or self.edge_index.max() >= node_count):
            raise ValueError("edge_index_out_of_range")


@dataclass(frozen=True)
class DAMGKOutput:
    state_delta_mean: torch.Tensor
    state_delta_scale: torch.Tensor
    effective_edge_gate: torch.Tensor
    lag_distribution: torch.Tensor
    topology_rewrite_probability: torch.Tensor
    propagated_state: torch.Tensor
    transition_latent: torch.Tensor
    relation_channel_weights: torch.Tensor
    rolled_state: torch.Tensor
    predicted_state: torch.Tensor
    edge_gate_by_step: torch.Tensor
    topology_probability_by_step: torch.Tensor
    transition_change_logit: torch.Tensor
    transition_destination_logits: torch.Tensor
