"""Land-transition task head over DAM-GK geographic dynamics representations."""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn

from .contracts import DAMGKBatch, DAMGKConfig, DAMGKOutput
from .model import DynamicActionConditionedMultiscaleKernel


@dataclass(frozen=True)
class TWMLandTransitionOutput:
    kernel_output: DAMGKOutput
    change_logit: torch.Tensor
    destination_logits: torch.Tensor
    coarse_state_logits: torch.Tensor
    use_multiscale_consistency: bool


class TWMLandTransitionModel(nn.Module):
    """Predict whether land changes, then its destination class if it does."""

    def __init__(self, config: DAMGKConfig, class_count: int = 9) -> None:
        super().__init__()
        self.kernel = DynamicActionConditionedMultiscaleKernel(config)
        transition_dim = config.transition_latent_dim()
        self.change_head = nn.Sequential(
            nn.Linear(transition_dim, config.hidden_dim),
            nn.SiLU(),
            nn.Linear(config.hidden_dim, 1),
        )
        self.destination_head = nn.Sequential(
            nn.Linear(transition_dim, config.hidden_dim),
            nn.SiLU(),
            nn.Linear(config.hidden_dim, class_count),
        )
        self.coarse_state_head = nn.Sequential(
            nn.Linear(transition_dim, config.hidden_dim),
            nn.SiLU(),
            nn.Linear(config.hidden_dim, class_count),
        )

    def forward(self, batch: DAMGKBatch) -> TWMLandTransitionOutput:
        kernel_output = self.kernel(batch)
        transition_latent = kernel_output.transition_latent
        if self.kernel.config.state_writeback_mode.startswith("categorical_"):
            change_logit = kernel_output.transition_change_logit
        else:
            change_logit = self.change_head(transition_latent).squeeze(-1)
        if self.kernel.config.state_writeback_mode.startswith("categorical_"):
            destination_logits = kernel_output.transition_destination_logits
        else:
            destination_logits = torch.log(
                kernel_output.predicted_state[
                    :, :, : self.destination_head[-1].out_features
                ].clamp_min(1e-8)
            )
        coarse_state_logits = self.coarse_state_head(transition_latent)
        if self.kernel.config.horizon == 1:
            change_logit = change_logit[:, 0]
            destination_logits = destination_logits[:, 0]
            coarse_state_logits = coarse_state_logits[:, 0]
        return TWMLandTransitionOutput(
            kernel_output=kernel_output,
            change_logit=change_logit,
            destination_logits=destination_logits,
            coarse_state_logits=coarse_state_logits,
            use_multiscale_consistency=self.kernel.config.use_multiscale_consistency,
        )
