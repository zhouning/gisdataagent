"""Trainable DAM-GK core without a dependency on a graph framework."""

from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as functional

from .contracts import DAMGKBatch, DAMGKConfig, DAMGKOutput


class DynamicActionConditionedMultiscaleKernel(nn.Module):
    """Learn effective relations, delayed propagation and soft topology rewrites."""

    def __init__(self, config: DAMGKConfig) -> None:
        super().__init__()
        config.validate()
        self.config = config
        hidden = config.hidden_dim
        self.node_encoder = nn.Sequential(
            nn.Linear(config.node_state_dim + config.context_dim, hidden),
            nn.SiLU(),
            nn.Linear(hidden, hidden),
        )
        self.action_encoder = nn.Sequential(
            nn.Linear(config.action_dim, hidden),
            nn.SiLU(),
            nn.Linear(hidden, hidden),
        )
        self.region_encoder = nn.Sequential(
            nn.Linear(max(1, config.region_context_dim), hidden),
            nn.SiLU(),
            nn.Linear(hidden, hidden),
        )
        self.relation_embedding = nn.Embedding(config.relation_type_count, hidden)
        edge_input_dim = hidden * (
            5 if config.use_region_conditioning else 4
        ) + config.edge_feature_dim
        self.relation_gate = nn.Sequential(
            nn.Linear(edge_input_dim, hidden),
            nn.SiLU(),
            nn.Linear(hidden, 1),
        )
        self.lag_head = nn.Sequential(
            nn.Linear(edge_input_dim, hidden),
            nn.SiLU(),
            nn.Linear(hidden, config.horizon),
        )
        self.message_encoder = nn.Sequential(
            nn.Linear(edge_input_dim, hidden),
            nn.SiLU(),
            nn.Linear(hidden, hidden),
        )
        self.topology_rewrite_head = nn.Sequential(
            nn.Linear(edge_input_dim, hidden),
            nn.SiLU(),
            nn.Linear(hidden, 1),
        )
        self.relation_channel_fusion = nn.Sequential(
            nn.Linear(hidden * 2, hidden),
            nn.SiLU(),
            nn.Linear(hidden, config.relation_type_count),
        )
        self.relation_channel_projection = nn.Sequential(
            nn.Linear(hidden * config.relation_type_count, hidden),
            nn.SiLU(),
            nn.Linear(hidden, hidden),
        )
        self.relation_channel_residual_gate = nn.Sequential(
            nn.Linear(hidden * 2, hidden),
            nn.SiLU(),
            nn.Linear(hidden, 1),
        )
        transition_input_dim = config.transition_latent_dim()
        self.transition_mean = nn.Sequential(
            nn.Linear(transition_input_dim, hidden),
            nn.SiLU(),
            nn.Linear(hidden, config.output_dim()),
        )
        self.transition_scale = nn.Sequential(
            nn.Linear(transition_input_dim, hidden),
            nn.SiLU(),
            nn.Linear(hidden, config.output_dim()),
        )
        self.transition_change = nn.Sequential(
            nn.Linear(transition_input_dim, hidden),
            nn.SiLU(),
            nn.Linear(hidden, 1),
        )

    def forward(self, batch: DAMGKBatch) -> DAMGKOutput:
        batch.validate(self.config)
        base_context = batch.node_context
        if base_context is None:
            base_context = batch.node_state.new_zeros((batch.node_state.shape[0], 0))
        action_latent = self.action_encoder(batch.node_action)
        if not self.config.use_action_conditioning:
            action_latent = torch.zeros_like(action_latent)
        if self.config.use_region_conditioning:
            region_latent = self.region_encoder(batch.region_context)
        else:
            region_latent = action_latent.new_zeros(action_latent.shape)
        source, target = batch.edge_index
        edge_features = batch.edge_features
        if (
            not self.config.use_edge_geometry
            and self.config.edge_geometry_start_index is not None
        ):
            edge_features = edge_features.clone()
            edge_features[:, self.config.edge_geometry_start_index :] = 0.0
        relation_latent = self.relation_embedding(batch.edge_types)
        if not self.config.use_relation_types:
            relation_latent = torch.zeros_like(relation_latent)
        current_state = batch.node_state
        rolled_states = []
        predicted_states = []
        delta_means = []
        delta_scales = []
        propagated_steps = []
        transition_latent_steps = []
        gate_steps = []
        topology_steps = []
        transition_change_steps = []
        transition_destination_steps = []
        relation_channel_weight_steps = []
        lag_distribution = None
        initial_gate = None
        initial_topology = None
        node_count = batch.node_state.shape[0]
        for step_index in range(self.config.horizon):
            context = (
                batch.node_context_by_step[:, step_index]
                if batch.node_context_by_step is not None
                else base_context
            )
            node_latent = self.node_encoder(torch.cat([current_state, context], dim=-1))
            edge_parts = [
                node_latent[source],
                node_latent[target],
                action_latent[source],
                relation_latent,
            ]
            if self.config.use_region_conditioning:
                edge_parts.append(region_latent[source])
            edge_parts.append(edge_features)
            edge_inputs = torch.cat(edge_parts, dim=-1)
            effective_gate = torch.sigmoid(self.relation_gate(edge_inputs)).squeeze(-1)
            topology_rewrite = torch.sigmoid(self.topology_rewrite_head(edge_inputs)).squeeze(-1)
            if not self.config.use_topology_rewrite:
                topology_rewrite = torch.ones_like(topology_rewrite)
            if batch.edge_valid_mask is not None:
                valid = batch.edge_valid_mask.to(dtype=effective_gate.dtype)
                effective_gate = effective_gate * valid
                topology_rewrite = topology_rewrite * valid
            current_lag_distribution = torch.softmax(self.lag_head(edge_inputs), dim=-1)
            if not self.config.use_lag_structure:
                current_lag_distribution = torch.full_like(
                    current_lag_distribution, 1.0 / float(self.config.horizon)
                )
            messages = self.message_encoder(edge_inputs)
            lag_weight = current_lag_distribution[:, step_index]
            weighted = messages * (
                effective_gate * topology_rewrite * lag_weight
            ).unsqueeze(-1)
            base_aggregated = messages.new_zeros(
                (node_count, self.config.hidden_dim)
            )
            base_aggregated.index_add_(0, target, weighted)
            if self.config.normalize_propagation_mass:
                base_mass = effective_gate.new_zeros((node_count, 1))
                base_mass.index_add_(
                    0,
                    target,
                    (
                        effective_gate
                        * topology_rewrite
                        * lag_weight
                    ).unsqueeze(-1),
                )
                base_aggregated = base_aggregated / base_mass.clamp_min(1.0)
            if self.config.use_relation_channel_fusion:
                channel_index = (
                    batch.edge_types
                    if self.config.use_relation_types
                    else torch.zeros_like(batch.edge_types)
                )
                relation_channels = messages.new_zeros(
                    (
                        node_count,
                        self.config.relation_type_count,
                        self.config.hidden_dim,
                    )
                )
                flat_channel_target = (
                    target * self.config.relation_type_count + channel_index
                )
                relation_channels.view(-1, self.config.hidden_dim).index_add_(
                    0, flat_channel_target, weighted
                )
                if self.config.normalize_propagation_mass:
                    channel_mass = effective_gate.new_zeros(
                        (node_count, self.config.relation_type_count, 1)
                    )
                    channel_mass.view(-1, 1).index_add_(
                        0,
                        flat_channel_target,
                        (
                            effective_gate
                            * topology_rewrite
                            * lag_weight
                        ).unsqueeze(-1),
                    )
                    relation_channels = relation_channels / channel_mass.clamp_min(1.0)
                relation_channel_weights = torch.softmax(
                    self.relation_channel_fusion(
                        torch.cat([node_latent, action_latent], dim=-1)
                    ),
                    dim=-1,
                )
                if not self.config.use_relation_types:
                    relation_channel_weights = torch.zeros_like(
                        relation_channel_weights
                    )
                    relation_channel_weights[:, 0] = 1.0
                weighted_relation_channels = torch.sum(
                    relation_channels * relation_channel_weights.unsqueeze(-1),
                    dim=1,
                )
                projected_relation_channels = self.relation_channel_projection(
                    relation_channels.flatten(start_dim=1)
                )
                residual_gate = torch.sigmoid(
                    self.relation_channel_residual_gate(
                        torch.cat([node_latent, action_latent], dim=-1)
                    )
                )
                relation_residual = (
                    0.5 * weighted_relation_channels
                    + 0.5 * projected_relation_channels
                )
                aggregated = base_aggregated + residual_gate * relation_residual
            else:
                aggregated = base_aggregated
                relation_channel_weights = effective_gate.new_zeros(
                    (node_count, self.config.relation_type_count)
                )
            transition_parts = [node_latent, action_latent, aggregated]
            if self.config.use_region_conditioning:
                transition_parts.append(region_latent)
            transition_inputs = torch.cat(transition_parts, dim=-1)
            raw_transition = self.transition_mean(transition_inputs)
            transition_change_logit = self.transition_change(
                transition_inputs
            ).squeeze(-1)
            delta_mean = raw_transition
            delta_scale = functional.softplus(self.transition_scale(transition_inputs))
            delta_scale = delta_scale + self.config.minimum_scale
            if self.config.state_writeback_mode.startswith("categorical_"):
                mutable_dim = self.config.mutable_state_dim or current_state.shape[-1]
                current_mutable = current_state[:, :mutable_dim]
                destination_state = torch.softmax(raw_transition, dim=-1)
                change_probability = torch.sigmoid(
                    transition_change_logit
                ).unsqueeze(-1)
                predicted_mutable = (
                    (1.0 - change_probability) * current_mutable
                    + change_probability * destination_state
                )
                delta_mean = predicted_mutable - current_mutable
                predicted_state = self._replace_mutable_state(
                    current_state, predicted_mutable
                )
                if self.config.state_writeback_mode == "categorical_no_writeback":
                    current_state = current_state
                elif self.config.state_writeback_mode == "categorical_teacher_forced":
                    current_state = batch.teacher_state_by_step[:, step_index]
                else:
                    current_state = predicted_state
            else:
                predicted_state = self._write_back_state(
                    current_state,
                    delta_mean,
                    teacher_state=None,
                )
                if self.config.state_writeback_mode == "teacher_forced":
                    predicted_state = self._write_back_state(
                        current_state,
                        delta_mean,
                        teacher_state=None,
                        mode_override="simplex_additive",
                    )
                    current_state = batch.teacher_state_by_step[:, step_index]
                else:
                    current_state = predicted_state
            delta_means.append(delta_mean)
            delta_scales.append(delta_scale)
            propagated_steps.append(aggregated)
            transition_latent_steps.append(transition_inputs)
            gate_steps.append(effective_gate)
            topology_steps.append(topology_rewrite)
            transition_change_steps.append(transition_change_logit)
            transition_destination_steps.append(raw_transition)
            relation_channel_weight_steps.append(relation_channel_weights)
            predicted_states.append(predicted_state)
            rolled_states.append(current_state)
            if initial_gate is None:
                initial_gate = effective_gate
                initial_topology = topology_rewrite
                lag_distribution = current_lag_distribution
        state_delta_mean = torch.stack(delta_means, dim=1)
        state_delta_scale = torch.stack(delta_scales, dim=1)
        propagated_state = torch.stack(propagated_steps, dim=1)
        return DAMGKOutput(
            state_delta_mean=state_delta_mean,
            state_delta_scale=state_delta_scale,
            effective_edge_gate=initial_gate,
            lag_distribution=lag_distribution,
            topology_rewrite_probability=initial_topology,
            propagated_state=propagated_state,
            transition_latent=torch.stack(transition_latent_steps, dim=1),
            relation_channel_weights=torch.stack(
                relation_channel_weight_steps, dim=1
            ),
            rolled_state=torch.stack(rolled_states, dim=1),
            predicted_state=torch.stack(predicted_states, dim=1),
            edge_gate_by_step=torch.stack(gate_steps, dim=1),
            topology_probability_by_step=torch.stack(topology_steps, dim=1),
            transition_change_logit=torch.stack(
                transition_change_steps, dim=1
            ),
            transition_destination_logits=torch.stack(
                transition_destination_steps, dim=1
            ),
        )

    @staticmethod
    def _replace_mutable_state(
        current_state: torch.Tensor, mutable_state: torch.Tensor
    ) -> torch.Tensor:
        if mutable_state.shape[-1] == current_state.shape[-1]:
            return mutable_state
        return torch.cat(
            [mutable_state, current_state[:, mutable_state.shape[-1] :]], dim=-1
        )

    def _write_back_state(
        self,
        current_state: torch.Tensor,
        delta_mean: torch.Tensor,
        *,
        teacher_state: torch.Tensor | None,
        mode_override: str | None = None,
    ) -> torch.Tensor:
        mode = mode_override or self.config.state_writeback_mode
        if mode == "teacher_forced":
            if teacher_state is None:
                return current_state
            return teacher_state
        if mode == "none":
            return current_state
        if mode == "auto_additive":
            if delta_mean.shape[-1] != current_state.shape[-1]:
                return current_state
            return current_state + delta_mean

        mutable_dim = self.config.mutable_state_dim or current_state.shape[-1]
        mutable_state = current_state[:, :mutable_dim] + delta_mean
        if mode == "simplex_additive":
            nonnegative_state = mutable_state.clamp_min(0.0)
            mass = nonnegative_state.sum(dim=-1, keepdim=True)
            normalized_state = nonnegative_state / mass.clamp_min(1e-8)
            fallback_state = torch.softmax(mutable_state, dim=-1)
            mutable_state = torch.where(
                mass > 1e-8, normalized_state, fallback_state
            )
        return self._replace_mutable_state(current_state, mutable_state)
